import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "flows"))
import flows


class T(unittest.TestCase):
    def test_shift(self):
        self.assertEqual(flows._shift(2026, 1, -1), "2025-12")
        self.assertEqual(flows._shift(2026, 10, -12), "2025-10")

    def test_isodate(self):
        self.assertEqual(flows._isodate("Nov 25, 2026"), "2026-11-25")
        self.assertEqual(flows._isodate("11/25/2026"), "2026-11-25")

    def test_rebalance_math(self):
        # Bull 3x, AUM_start 10B, index -1%: fund -3%, AUM_end 9.7B. Must sell L(L-1) r A0 = 6 x 1% x 10B = 0.6B.
        # Bear -3x, AUM_start 1B, index -1%: fund +3%, AUM_end 1.03B. Must sell 12 x 1% x 1B = 0.12B.
        pages = {"TQQQ": {"aum": 9.7e9, "nav": 97.0, "nav_chg": -3.0, "as_of": "2026-11-25", "url": "x"},
                 "SQQQ": {"aum": 1.03e9, "nav": 103.0, "nav_chg": 3.0, "as_of": "2026-11-25", "url": "x"}}
        orig = flows.proshares
        flows.proshares = lambda tk: pages.get(tk, {"aum": None})
        try:
            r = flows.lev_rebalance()
        finally:
            flows.proshares = orig
        e = r["last_session"]["Nasdaq-100"]
        self.assertAlmostEqual(e["flow"], -0.72e9, delta=1e3)
        self.assertEqual(e["index_ret_pct"], -1.0)

    def test_ivv_flow_carry(self):
        orig = flows.get
        flows.get = lambda url: '"sharesOutstanding":{"formattedValue":"1,010","formattedAsOfDate":"Nov 26, 2026"} "name":"Net Assets of Fund","value":"$101,000"'
        try:
            s = flows.ishares_snapshot({"as_of": "2026-11-25", "shares_out": 1000})
            same = flows.ishares_snapshot(s)
        finally:
            flows.get = orig
        self.assertEqual(s["flow_usd"], 1000)  # 10 new shares x $100
        self.assertEqual(same["flow_usd"], 1000)

    def test_pctile(self):
        self.assertEqual(flows.pctile(5, [1, 2, 3, 4, 5]), 100)


if __name__ == "__main__":
    unittest.main()
