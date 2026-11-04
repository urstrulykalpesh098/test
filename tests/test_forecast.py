import copy
import json
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from marketsim import forecast as fcmod
from marketsim.engine import run_scenario
from marketsim.forecast import Forecast, load_series, make_forecast, statistical_forecast
from marketsim.report import write_outputs
from marketsim.scenario import Scenario, attach_forecast

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "scenarios" / "baseline.json").read_text())


def write_csv(rows, header="date,close"):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    tmp.write(header + "\n" + "\n".join(rows) + "\n")
    tmp.close()
    return tmp.name


class LoadSeriesTest(unittest.TestCase):
    def test_detects_close_column_and_skips_junk(self):
        rows = [f"2025-01-{i:02d},{100 + i}" for i in range(1, 32)] + ["2025-02-01,", "2025-02-02,n/a", "2025-02-03,\"1,200.5\""]
        values = load_series(write_csv(rows))
        self.assertEqual(values[0], 101.0)
        self.assertEqual(values[-1], 1200.5)
        self.assertEqual(len(values), 32)

    def test_explicit_column_and_errors(self):
        path = write_csv([f"{i},{50 + i}" for i in range(40)], header="t,Price")
        self.assertEqual(load_series(path, "price")[0], 50.0)
        with self.assertRaisesRegex(ValueError, "no column"):
            load_series(path, "volume")
        with self.assertRaisesRegex(ValueError, "at least 32"):
            load_series(write_csv(["2025-01-01,1", "2025-01-02,2"]))
        with self.assertRaisesRegex(ValueError, "positive"):
            load_series(write_csv([f"d{i},{i - 5}" for i in range(40)]))


class StatisticalForecastTest(unittest.TestCase):
    def test_quantiles_ordered_and_widen(self):
        hist = [100 * math.exp(0.01 * math.sin(i)) for i in range(300)]
        fc = statistical_forecast(hist, 20)
        self.assertEqual(fc.source, "statistical")
        self.assertEqual(fc.horizon, 20)
        for h in range(20):
            col = [fc.quantiles[q][h] for q in sorted(fc.quantiles)]
            self.assertEqual(col, sorted(col))
        lo, hi = fc.band()
        self.assertGreater(hi[-1] - lo[-1], hi[0] - lo[0])
        self.assertIsNotNone(fc.per_step_vol())

    def test_auto_falls_back_without_timesfm(self):
        with mock.patch.object(fcmod, "timesfm_available", return_value=False):
            self.assertEqual(make_forecast([100.0 + i for i in range(64)], 5).source, "statistical")
        with self.assertRaises(ValueError):
            make_forecast([1.0] * 64, 5, model="prophet")

    def test_relative_path_interpolates(self):
        fc = Forecast("test", [50.0], [55.0, 60.5], {})
        path = fc.relative_path(ticks=4, ticks_per_step=2)
        self.assertAlmostEqual(path[1], 1.1)
        self.assertAlmostEqual(path[3], 1.21)
        self.assertAlmostEqual(path[0], math.sqrt(1.1))
        self.assertAlmostEqual(fc.relative_path(6, 2)[-1], 1.21)  # holds the last value


class FakeOutput:
    def __init__(self, forecast, quantiles):
        self.forecast, self.quantiles = forecast, quantiles


class TimesFMAdapterTest(unittest.TestCase):
    """Exercises our adapter against the TimesFM-3 interface, with a stand-in model."""

    def test_adapter_maps_quantiles(self):
        import numpy as np

        calls = {}

        class FakeForecaster:
            config = types.SimpleNamespace(quantiles=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])

            @classmethod
            def from_pretrained(cls, name, device=None):
                calls["checkpoint"], calls["device"] = name, device
                return cls()

            def predict(self, context, horizon, return_quantiles=False, make_positive=False):
                calls["context_len"], calls["horizon"] = len(context), horizon
                base = np.full(horizon, float(context[-1]))
                q = np.stack([base * (0.9 + 0.025 * j) for j in range(9)], axis=1)
                return FakeOutput(q[:, 4], q)

        fake = types.ModuleType("timesfm3")
        fake.TimesFM3Forecaster = FakeForecaster
        fcmod._TIMESFM_CACHE.clear()
        with mock.patch.dict(sys.modules, {"timesfm3": fake}), \
                mock.patch.dict("os.environ", {"MARKETSIM_TIMESFM_CHECKPOINT": "/models/tfm3"}):
            fc = make_forecast([100.0] * 64, 7, model="timesfm")
        self.assertEqual(fc.source, "timesfm-3")
        self.assertEqual(calls, {"checkpoint": "/models/tfm3", "device": "cpu", "context_len": 64, "horizon": 7})
        self.assertEqual(fc.median, [100.0] * 7)
        self.assertAlmostEqual(fc.quantiles[0.1][0], 90.0)
        self.assertAlmostEqual(fc.quantiles[0.9][0], 110.0)

    def test_missing_timesfm_is_a_clear_error(self):
        with mock.patch.dict(sys.modules, {"timesfm3": None}):
            with self.assertRaisesRegex(RuntimeError, "requirements-timesfm.txt"):
                make_forecast([100.0] * 64, 5, model="timesfm")


class ScenarioIntegrationTest(unittest.TestCase):
    def scenario(self, ticks=200):
        data = copy.deepcopy(BASE)
        data["ticks"] = ticks
        return Scenario.from_dict(data)

    def test_fair_value_follows_forecast(self):
        sc = self.scenario()
        fc = Forecast("test", [100.0], [100.0 * 1.01 ** (h + 1) for h in range(20)], {})
        attach_forecast(sc, fc, ticks_per_step=10, vol_from_band=False)
        sc.fundamental_vol = 0.0
        run = run_scenario(sc, 0)
        self.assertAlmostEqual(run.series["fundamental"][-1], 100.0 * 1.01 ** 20, places=6)
        self.assertGreater(run.series["price"][-1], 110)

    def test_band_sets_volatility_and_report_section(self):
        sc = self.scenario(300)
        hist = [100 * math.exp(0.02 * math.sin(i / 3)) for i in range(200)]
        attach_forecast(sc, statistical_forecast(hist, 30), ticks_per_step=10)
        self.assertGreater(sc.fundamental_vol, 0)
        runs = [run_scenario(sc, s) for s in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            summary = write_outputs(runs, Path(tmp))
            self.assertIn("Scenario vs baseline forecast", (Path(tmp) / "report.html").read_text())
            self.assertEqual(summary["baseline_forecast"]["horizon_steps"], 30)

    def test_bundled_forecast_scenario_resolves_csv(self):
        sc = Scenario.load(ROOT / "scenarios" / "rate_hike_on_forecast.json")
        self.assertTrue(sc.resolve_path(sc.baseline_forecast["csv"]).exists())
        bad = copy.deepcopy(BASE)
        bad["baseline_forecast"] = {"csv": "x.csv", "horizn": 3}
        with self.assertRaisesRegex(ValueError, "horizn"):
            Scenario.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
