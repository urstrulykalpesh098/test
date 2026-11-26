import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "trackers"))
import vixterm

CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n01/04/2011,16.06,16.06,16.06,16.060000\n01/05/2011,1,1,1,15.5\nbad,row\n"


def ser(v9, v, v3, n=30):
    ds = [f"2026-10-{i:02d}" for i in range(1, n + 1)]
    spx = {d: 100 * (1.01 if i % 2 else 0.99) for i, d in enumerate(ds)}
    return {"VIX9D": {d: v9 for d in ds}, "VIX": {d: v for d in ds}, "VIX3M": {d: v3 for d in ds}, "SPX": spx}


class VixTerm(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(vixterm.parse_cboe(CSV), {"2011-01-04": 16.06, "2011-01-05": 15.5})
        self.assertEqual(vixterm.parse_cboe("DATE,SPX\n11/25/2026,7182.78\n"), {"2026-11-25": 7182.78})

    def test_states(self):
        self.assertEqual(vixterm.state_of(0.80), "steep contango")
        self.assertEqual(vixterm.state_of(0.90), "contango")
        self.assertEqual(vixterm.state_of(0.97), "flat")
        self.assertEqual(vixterm.state_of(1.00), "backwardation")

    def test_readout_backwardation(self):
        r = vixterm.readout(ser=ser(30, 28, 26))
        self.assertEqual(r["state"], "backwardation")
        self.assertEqual(r["shape"], "inverted")
        self.assertEqual(r["sessions_in_state"], 30)
        self.assertEqual(r["last_backwardation_date"], "2026-10-30")
        self.assertIn("Context only", r["finding"])
        w = r["next_week_vol"]
        self.assertTrue(w and w["with_curve"] > 0 and w["without_curve"] > 0)

    def test_desk_docs(self):
        d = vixterm.desk_docs(vixterm.readout(ser=ser(30, 28, 26)), "2026-10-30")
        self.assertEqual(d["meta_vixterm"]["updated"], "2026-10-30")
        self.assertEqual(d["day_vixterm"]["state"], "backwardation")
        self.assertIn("Context only", d["day_vixterm"]["line"])

    def test_readout_contango(self):
        r = vixterm.readout(ser=ser(12, 14, 17))
        self.assertEqual(r["state"], "steep contango")
        self.assertEqual(r["shape"], "upward")
        self.assertIsNone(r["last_backwardation_date"])


if __name__ == "__main__":
    unittest.main()
