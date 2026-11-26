import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "scorecard"))
import baselines as B, scorecard as S

def write(d, pid, **x):
    (Path(d) / f"{pid}.json").write_text(json.dumps(x))

class T(unittest.TestCase):
    def test_follow_uses_last_session_before_call(self):
        with tempfile.TemporaryDirectory() as d:
            # Nov 23 was +4.73%, Nov 24 closed down. Pre-open call on Nov 24 -> follow leans up -> miss.
            write(d, "pre24-up", claim="S&P 500 closes up on Tue 24 Nov (above Mon close 7,237.17)",
                  made="2026-11-24", resolves="2026-11-24", prob=0.3, status="miss", source="Pre-open")
            # Close call made Nov 19 (a -2.02% day) for Nov 20 -> follow leans down.
            write(d, "fri20-up", claim="S&P 500 closes up on Fri 20 Nov (above Thu close 7,175.83)",
                  made="2026-11-19", resolves="2026-11-20", prob=0.48, status="miss", source="Desk close")
            rs = {r["id"]: r for r in B.rows_from(d, B.load_closes())}
            self.assertEqual(rs["pre24-up"]["yday"], "2026-11-23")
            self.assertAlmostEqual(rs["pre24-up"]["follow"], 0.6)
            self.assertEqual(rs["fri20-up"]["yday"], "2026-11-19")
            self.assertAlmostEqual(rs["fri20-up"]["follow"], 0.4)
            out = S.build(d)
            self.assertEqual(out["running"]["updown"]["n"], 2)
            self.assertEqual(out["running"]["updown"]["follow_brier"], round((0.36 + 0.16) / 2, 3))

if __name__ == "__main__":
    unittest.main()
