import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "desk"))
import skill as K

# 40 fake sessions of FRED closes, then the four real ones from 19-24 Nov 2026
DATES = [f"2026-09-{d:02d}" for d in range(1, 31)] + [f"2026-10-{d:02d}" for d in range(1, 11)]
SP = {d: 7000 + 5 * i for i, d in enumerate(DATES)}
VIX = {d: 20 + (i % 3) for i, d in enumerate(DATES)}
for d, s, v in [("2026-11-19", 7175.83, 28.44), ("2026-11-20", 6910.39, 35.89),
                ("2026-11-23", 7237.17, 26.62), ("2026-11-24", 7201.09, 26.36)]:
    SP[d], VIX[d] = s, v


class Classify(unittest.TestCase):
    def test_types(self):
        self.assertEqual(K.classify("S&P 500 closes up on Fri 20 Nov (above Thu close 7,175.83)")[0], "updown")
        t, s = K.classify("S&P 500 Tue 24 Nov close lands inside 7,030-7,445 (80% band)")
        self.assertEqual((t, s), ("range", {"lo": 7030.0, "hi": 7445.0}))
        t, s = K.classify("S&P 500 closes below the 5 Nov close 7,353.73 on Tue 17 Nov")
        self.assertEqual((t, s["side"], s["k"]), ("level", "below", 7353.73))
        self.assertEqual(K.classify("VIX closes between 23 and 37 on Tue 24 Nov")[1], {"lo": 23.0, "hi": 37.0})
        self.assertTrue(K.classify("S&P 500 closes above its 200-day average (~7,351) on Tue 24 Nov")[1]["ma200"])
        # path-dependent and non-S&P calls are left out
        self.assertIsNone(K.classify("S&P 500 closes below the 5 Nov crash close 7,353.73 on any day through Fri 20 Nov"))
        self.assertIsNone(K.classify("NVDA closes up on Wed 18 Nov (above Tue 17 Nov close)"))


class Grade(unittest.TestCase):
    def test_fred_overrules_ledger(self):
        # ledger says hit, but on FRED the 24 Nov close (7,201.09) fell from 7,237.17
        x = dict(claim="S&P 500 closes up on Tue 24 Nov (above Mon close 7,237.17)", made="2026-11-24",
                 resolves="2026-11-24", prob=0.3, status="hit", source="Desk pre-open")
        r, why = K.grade("pre24-up", x, SP, VIX)
        self.assertIsNone(why)
        self.assertEqual((r["y"], r["base"], r["agrees"]), (0, 0.54, False))

    def test_open_without_official_close(self):
        x = dict(claim="S&P 500 closes up on Wed 25 Nov", made="2026-11-24", resolves="2026-11-25",
                 prob=0.5, status="hit")
        self.assertEqual(K.grade("wed25-up", x, SP, VIX), (None, "no official close yet"))

    def test_formula_uses_close_known_at_call_time(self):
        # close run on 23 Nov knows the 23 Nov close; one session to 24 Nov
        x = dict(claim="S&P 500 Tue 24 Nov close lands inside 7,030-7,445", made="2026-11-23",
                 resolves="2026-11-24", prob=0.8, status="hit", source="Desk close")
        r, _ = K.grade("tue24-range", x, SP, VIX)
        s = 26.62 / 100 / 252 ** 0.5
        want = K.N(K.math.log(7445 / 7237.17) / s) - K.N(K.math.log(7030 / 7237.17) / s)
        self.assertAlmostEqual(r["base"], round(want, 4), places=4)
        self.assertEqual(r["y"], 1)

    def test_vix_baseline_in_unit_range(self):
        x = dict(claim="VIX closes between 23 and 37 on Tue 24 Nov", made="2026-11-23", resolves="2026-11-24",
                 prob=0.78, status="hit", source="Desk close")
        r, _ = K.grade("tue24-vix", x, SP, VIX)
        self.assertTrue(0 < r["base"] < 1)
        self.assertEqual(r["y"], 1)


class Meter(unittest.TestCase):
    @staticmethod
    def fake(n_days, desk, base, y):
        return [{"id": f"c{i}", "type": "updown", "resolves": f"d{i:03d}", "prob": desk, "base": base,
                 "alt": 0.5, "y": y(i), "ledger": "hit", "agrees": True} for i in range(n_days)]

    def test_clear_skill(self):
        t = K.test(self.fake(60, 0.9, 0.54, lambda i: 1))
        self.assertGreater(t["ci95"][0], 0)
        self.assertEqual(K.verdict(t)[0], "skill")
        self.assertLess(t["p_value"], 0.01)

    def test_clear_cost(self):
        t = K.test(self.fake(60, 0.1, 0.54, lambda i: 1))
        self.assertEqual(K.verdict(t)[0], "worse")

    def test_noise_says_too_early(self):
        t = K.test(self.fake(12, 0.6, 0.54, lambda i: i % 2))
        v, words = K.verdict(t, "updown")
        self.assertIn(v, ("early", "noise"))
        self.assertTrue(t["ci95"][0] <= 0 <= t["ci95"][1])

    def test_build_today_line(self):
        preds = {"tue24-up": dict(claim="S&P 500 closes up on Tue 24 Nov (above Mon close 7,237.17)",
                                  made="2026-11-23", resolves="2026-11-24", prob=0.48, status="miss",
                                  source="Desk close"),
                 "fri20-up": dict(claim="S&P 500 closes up on Fri 20 Nov (above Thu close 7,175.83)",
                                  made="2026-11-19", resolves="2026-11-20", prob=0.48, status="miss",
                                  source="Desk close")}
        res = K.build(preds, SP, VIX, today="2026-11-26")
        self.assertEqual(res["n_used"], 2)
        self.assertTrue(res["today_line"].startswith("Skill or luck:"))
        self.assertEqual(res["types"]["updown"]["base_brier"], round(0.54 ** 2, 4))
        rows = K.table(res)
        self.assertEqual(rows[0]["type"], "all")


if __name__ == "__main__":
    unittest.main()
