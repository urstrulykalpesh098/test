import copy
import json
import tempfile
import unittest
from pathlib import Path

from marketsim.analysis import event_impacts, market_stats, monte_carlo_summary, trader_stats
from marketsim.engine import Simulation, run_scenario
from marketsim.report import write_outputs
from marketsim.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "scenarios" / "baseline.json").read_text())


def small(**overrides):
    data = copy.deepcopy(BASE)
    data["ticks"] = 300
    data.update(overrides)
    return Scenario.from_dict(data)


class SimulationTest(unittest.TestCase):
    def test_deterministic_for_seed(self):
        sc = small()
        a, b, c = run_scenario(sc, 7), run_scenario(sc, 7), run_scenario(sc, 8)
        self.assertEqual(a.series["price"], b.series["price"])
        self.assertNotEqual(a.series["price"], c.series["price"])

    def test_conservation_and_limits(self):
        sc = small()
        sim = Simulation(sc, 3)
        cash0 = sum(a.cash for a in sim.agents)
        shares0 = sum(a.shares for a in sim.agents)
        result = sim.run()
        self.assertAlmostEqual(sum(a.cash for a in result.agents), cash0, delta=1e-3)
        self.assertEqual(sum(a.shares for a in result.agents), shares0)
        for a in result.agents:
            self.assertGreaterEqual(a.shares, -a.p["max_short"], a.kind)
            self.assertLessEqual(a.shares, a.p["max_position"], a.kind)
        self.assertGreater(sum(result.series["volume"]), 0)

    def test_price_tracks_fair_value(self):
        stats = market_stats(run_scenario(small(), 1))
        self.assertLess(stats["mean_abs_mispricing"], 0.05)

    def test_negative_news_moves_price_down(self):
        sc = small(events=[{"tick": 100, "headline": "bad", "fundamental_change": -0.1, "sentiment": -0.5}])
        run = run_scenario(sc, 2)
        impact = event_impacts(run)[0]
        self.assertLess(impact["return_50"], -0.05)
        self.assertLess(impact["worst_return"], -0.07)

    def test_validation_errors(self):
        bad_param = copy.deepcopy(BASE)
        bad_param["population"]["momentum"]["params"] = {"long_windw": 30}
        with self.assertRaisesRegex(ValueError, "long_windw"):
            Scenario.from_dict(bad_param)
        bad_kind = copy.deepcopy(BASE)
        bad_kind["population"]["whale"] = {"count": 1}
        with self.assertRaisesRegex(ValueError, "whale"):
            Scenario.from_dict(bad_kind)
        no_mm = copy.deepcopy(BASE)
        del no_mm["population"]["market_maker"]
        with self.assertRaisesRegex(ValueError, "market_maker"):
            Scenario.from_dict(no_mm)
        with self.assertRaisesRegex(ValueError, "outside"):
            small(events=[{"tick": 5000}])

    def test_bundled_scenarios_load(self):
        for path in (ROOT / "scenarios").glob("*.json"):
            Scenario.load(path)

    def test_reports(self):
        sc = small(events=[{"tick": 50, "headline": "<b>x</b>", "fundamental_change": 0.05}])
        runs = [run_scenario(sc, s) for s in range(3)]
        self.assertEqual(monte_carlo_summary(runs)["runs"], 3)
        self.assertEqual(len(trader_stats(runs[0])), 6)
        with tempfile.TemporaryDirectory() as tmp:
            summary = write_outputs(runs, Path(tmp))
            html = (Path(tmp) / "report.html").read_text()
            self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
            self.assertNotIn("<b>x</b>", html)
            self.assertIn("monte_carlo", summary)
            self.assertTrue((Path(tmp) / "timeseries.csv").exists())


if __name__ == "__main__":
    unittest.main()
