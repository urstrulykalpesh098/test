import json, sys, unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "trackers"))
import credit, policy

TX_HTML = """Number of Bills: 2<br><div class="bill-search-results">
        <div class="row">
          <div class="bill-search-result-label"><a href="http://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&amp;Bill=HB167">HB 167  </a></div>
          <div class="bill-search-result-data"></div>
          <div class="bill-search-result-data"><b>Author</b>:
		</div>
          <div class="bill-search-result-data">Martinez Fischer</div>
          <div class="bill-search-result-label"><b>Last Action:</b></div>
          <div class="bill-search-result-data">11/09/2026 H Filed</div>
          <div class="bill-search-result-label"><b>Caption</b>:
		</div>
          <div class="bill-search-result-data">Relating to the repeal of the exemptions from sales and use taxes for property used in certain data centers.</div>
        </div>
        <div class="row">
          <div class="bill-search-result-label"><a href="http://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&amp;Bill=HB103">HB 103  </a></div>
          <div class="bill-search-result-data"></div>
          <div class="bill-search-result-data"><b>Author</b>:
		</div>
          <div class="bill-search-result-data">Martinez</div>
          <div class="bill-search-result-label"><b>Last Action:</b></div>
          <div class="bill-search-result-data">11/09/2026 H Filed</div>
          <div class="bill-search-result-label"><b>Caption</b>:
		</div>
          <div class="bill-search-result-data">Relating to the prosecution of reckless discharge of a firearm.</div>
        </div>
</div>"""

IDX = """Form Type   Company Name     CIK
---------------------------------------------------------------------------------------------------------------------------------------------
424B2            JPMORGAN CHASE FINANCIAL CO. LLC                              1665650     20261125    edgar/data/1665650/x.txt
424B5            ACME CORP                                                     1234567     20261125    edgar/data/1234567/x.txt
RW               SONIC LIGHTING, INC.                                          7654321     20261125    edgar/data/7654321/x.txt
8-K              OTHER INC                                                     1111111     20261125    edgar/data/1111111/x.txt
"""


class Credit(unittest.TestCase):
    def test_describe_bp(self):
        rows = [(f"2026-01-{i + 1:02d}", 3.0 + 0.01 * i) for i in range(25)]
        d = credit.describe(rows, "pct")
        self.assertEqual(d["chg_5"], 5.0)   # 0.05 pct points = 5bp
        self.assertEqual(d["chg_20"], 20.0)
        self.assertEqual(d["pctile_3y"], 100)

    def test_parse_idx(self):
        p = credit.parse_form_idx(IDX)
        self.assertEqual(p["424B2"], ["JPMORGAN CHASE FINANCIAL CO. LLC"])
        self.assertEqual(p["RW"], ["SONIC LIGHTING, INC."])
        self.assertNotIn("8-K", p)

    def test_flags(self):
        sp = {"BAMLH0A0HYM2": {"label": "HY OAS", "last": 3.7, "chg_20": 54.0, "pctile_3y": 97}}
        F = credit.flags(sp, {"sofr": {"minus_iorb_bp": 4}, "srf": {"max_2w_usd": 0}}, {"b5_3d_ratio": 0.9, "counts": {}})
        self.assertTrue(any("+54bp" in f for f in F))
        self.assertTrue(any("above IORB" in f for f in F))
        self.assertFalse(any("424B5" in f for f in F))


class Policy(unittest.TestCase):
    def test_parse_and_tag(self):
        total, bills = policy.parse_tx_report(TX_HTML)
        self.assertEqual(total, 2)
        self.assertEqual([b["bill"] for b in bills], ["HB167", "HB103"])
        self.assertEqual(bills[0]["author"], "Martinez Fischer")
        self.assertEqual(policy.tag(bills[0]["caption"]), ["data_centers"])
        self.assertEqual(policy.tag(bills[1]["caption"]), [])

    def test_incremental(self):
        calls = []
        orig = policy.get
        policy.get = lambda url, **k: (calls.append(url), TX_HTML)[1]
        try:
            first = policy.texas(None, today=date(2026, 11, 11))
            self.assertEqual(len(calls), 3)  # Mon-Wed backfill
            self.assertTrue(first["first_run"])
            calls.clear()
            second = policy.texas(first, today=date(2026, 11, 12))
            # Re-reads yesterday and reads today only
            self.assertEqual(len(calls), 2)
            self.assertFalse(second["first_run"])
            self.assertEqual(second["tagged_total"], 1)
            self.assertEqual(second["new_tagged"], [])
        finally:
            policy.get = orig

    def test_calendar_dates(self):
        jan = date.fromisoformat(policy.CALENDAR[0]["date"])
        self.assertEqual(jan.weekday(), 1)          # a Tuesday
        self.assertTrue(8 <= jan.day <= 14)         # the second one
        self.assertEqual((date.fromisoformat(policy.CALENDAR[1]["date"]) - jan).days + 1, 60)
        self.assertEqual((date.fromisoformat(policy.CALENDAR[2]["date"]) - jan).days + 1, 140)


if __name__ == "__main__":
    unittest.main()
