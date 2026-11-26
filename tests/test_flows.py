import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "flows"))
import flows

class T(unittest.TestCase):
    def test_shift(self):
        self.assertEqual(flows._shift(2026, 1, -1), "2025-12")
        self.assertEqual(flows._shift(2026, 10, -12), "2025-10")
    def test_rebalance_sign_and_size(self):
        orig = flows.proshares_aum
        flows.proshares_aum = lambda tk: ({"TQQQ": 10e9, "SQQQ": 1e9}.get(tk), "x")
        try:
            r = flows.lev_rebalance({"Nasdaq-100": -2.0})
        finally:
            flows.proshares_aum = orig
        # TQQQ 3*2*1%*10B = 0.6B, SQQQ (-3)(-4)*1%*1B = 0.12B -> 0.72B per 1%; at -2% = -1.44B
        e = r["by_index"]["Nasdaq-100"]
        self.assertEqual(e["per_1pct_move_usd"], 720_000_000)
        self.assertEqual(e["est_close_flow_usd"], -1_440_000_000)
    def test_pctile(self):
        self.assertEqual(flows.pctile(5, [1, 2, 3, 4, 5]), 100)

if __name__ == "__main__":
    unittest.main()
