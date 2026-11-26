import json, sys, unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "trackers"))
import canada, bundle

VALET_JSON = json.dumps({"observations": [
    {"d": "2026-11-24", "FXUSDCAD": {"v": "1.4200"}, "V39079": {"v": "2.50"}},
    {"d": "2026-11-25", "FXUSDCAD": {"v": "1.4219"}, "V39079": {"v": "2.50"}, "BD.CDN.2YR.DQ.YLD": {"v": "3.24"}},
    {"d": "2026-11-26", "FXUSDCAD": {"v": "1.4243"}, "V39079": {"v": ""}},
]})
EVENTS = """<div>November 20, 2026</div><div>Interest Rate Announcement</div>
<div class="x">December 9, 2026</div> <span>Interest Rate Announcement</span>
<div>January 27, 2027</div><a>Interest Rate Announcement and Monetary Policy Report</a>
<div>February 10, 2027</div><a>Speech by the Governor</a>"""


def series(vals, start=1):
    return [(f"2026-{1 + (i // 28):02d}-{1 + i % 28:02d}", v) for i, v in enumerate(vals)]


class CanadaTest(unittest.TestCase):
    def test_parse_valet_drops_blanks(self):
        d = canada.parse_valet(VALET_JSON)
        self.assertEqual(d["FXUSDCAD"][-1], ("2026-11-26", 1.4243))
        self.assertEqual(len(d["V39079"]), 2)
        self.assertEqual(d["BD.CDN.2YR.DQ.YLD"], [("2026-11-25", 3.24)])

    def test_boc_events_future_only_with_mpr(self):
        ev = canada.parse_boc_events(EVENTS, date(2026, 11, 26))
        self.assertEqual(ev, [{"date": "2026-12-09", "with_mpr": False}, {"date": "2027-01-27", "with_mpr": True}])

    def test_policy_history_and_lean(self):
        rows = series([2.25] * 5 + [2.5] * 5)
        h = canada.policy_history(rows)
        self.assertEqual(len(h), 1); self.assertEqual(h[0]["chg_bp"], 25); self.assertEqual(h[0]["rate"], 2.5)
        self.assertEqual(canada.lean(74), "hikes"); self.assertEqual(canada.lean(-30), "cuts"); self.assertEqual(canada.lean(10), "hold")

    def test_spread_uses_common_dates(self):
        a = series([3.0 + 0.01 * i for i in range(30)])
        b = series([4.0] * 25)
        s = canada.spread(a, b)
        self.assertEqual(s["as_of"], b[-1][0]); self.assertEqual(s["bp"], -76); self.assertEqual(s["chg_20_bp"], 20)

    def test_level_units(self):
        lv = canada.level(series([1.40] * 20 + [1.414]), "price")
        self.assertAlmostEqual(lv["chg_1"], 1.0); self.assertEqual(lv["chg_unit"], "%")
        lv = canada.level(series([3.0] * 20 + [3.1]), "pct")
        self.assertEqual(lv["chg_20"], 10.0); self.assertEqual(lv["chg_unit"], "bp")

    def test_fx_move_and_flag(self):
        import random
        random.seed(1)
        p, rows = 1.35, []
        for i in range(300):
            p *= 1 + random.gauss(0, 0.003) + (0.004 if i >= 280 else 0)
            rows.append((f"d{i:04d}", p))
        fx = canada.fx_move(rows)
        self.assertGreater(fx["move20_sigma"], 2)
        res = {"levels": {"usdcad": canada.level(rows, "price")}, "fx": fx, "spreads": {}, "boc": {}}
        self.assertTrue(any(f.startswith("CAD weaker") for f in canada.flags(res, date(2026, 11, 26))))

    def test_corr_perfect(self):
        a = series([1 + 0.01 * ((-1) ** i) * (i % 5) + i * 0.001 for i in range(80)])
        self.assertEqual(canada.corr(a, a, 60), 1.0)
        self.assertIsNone(canada.corr(a, a[:5], 60))

    def test_desk_docs_shape(self):
        res = {"note": "x", "levels": {"usdcad": {"label": "USD/CAD", "as_of": "2026-11-26", "last": 1.4243, "chg_1": 0.17, "chg_5": 0, "chg_20": 1.47, "chg_unit": "%", "pctile_3y": 89}},
               "fx": {"move20_sigma": 1.26}, "boc": {"rate": 2.5, "market_lean": "hikes", "next_decisions": [{"date": "2026-12-09", "with_mpr": False}]},
               "spreads": {"Canada minus US 2-year": {"bp": -139}}, "flags": [], "gaps": [], "sources": []}
        d = canada.desk_docs(res, "2026-11-26")
        self.assertEqual(set(d), {"meta_canada", "day_canada"})
        self.assertEqual(d["day_canada"]["next_boc"], "2026-12-09"); self.assertEqual(d["day_canada"]["ca_us_2y_bp"], -139)

    def test_bundle_inlines_common(self):
        src = bundle.bundle("canada.py")
        self.assertIn("inlined from common.py", src); self.assertNotIn("from common import", src)


if __name__ == "__main__":
    unittest.main()
