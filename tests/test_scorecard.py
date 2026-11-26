import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "scorecard"))
import scorecard as S

DAYS = {"2026-11-19": {"close": 7175.83, "prev": 7323.63, "vix": 28.44},
        "2026-11-20": {"close": 6910.39, "prev": 7175.83, "vix": 35.89},
        "2026-11-23": {"close": 7237.17, "prev": 6910.39, "vix": 26.62},
        "2026-11-24": {"close": 7201.09, "prev": 7237.17, "vix": 26.36}}

class T(unittest.TestCase):
    def test_follow_and_weeks(self):
        preds = {
            # pre-open on 24 Nov: last session 23 Nov was up -> follow leans up 60% -> miss
            "pre24-up": dict(claim="S&P 500 closes up on Tue 24 Nov (above Mon close 7,237.17)", made="2026-11-24",
                             resolves="2026-11-24", prob=0.3, status="miss", source="Desk pre-open"),
            # close call made 19 Nov (down day) for 20 Nov -> follow leans down (40% up) -> miss scores 0.16
            "fri20-up": dict(claim="S&P 500 closes up on Fri 20 Nov (above Thu close 7,175.83)", made="2026-11-19",
                             resolves="2026-11-20", prob=0.48, status="miss", source="Desk close"),
        }
        out = S.build(preds, dict(DAYS), today="2026-11-26")
        ud = {r["id"]: r for r in out["updown"]}
        self.assertEqual(ud["pre24-up"]["yday"], "2026-11-23")
        self.assertAlmostEqual(ud["pre24-up"]["follow"], 0.6)
        self.assertEqual(ud["fri20-up"]["yday"], "2026-11-19")
        self.assertAlmostEqual(ud["fri20-up"]["follow"], 0.4)
        allr = out["rows"][-1]
        self.assertEqual(allr["week_of"], "All weeks")
        self.assertEqual(allr["ud_follow_brier"], round((0.36 + 0.16) / 2, 3))
        self.assertEqual([r["week_of"] for r in out["rows"][:-1]], ["2026-11-16", "2026-11-23"])

    def test_formula_band(self):
        p = S.formula_prob("S&P 500 closes inside 7,000-7,400 on Tue 24 Nov", "2026-11-23", "2026-11-24", False, dict(DAYS))
        self.assertTrue(0.5 < p < 1)

if __name__ == "__main__":
    unittest.main()
