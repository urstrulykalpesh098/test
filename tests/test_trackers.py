import json, sys, unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "trackers"))
import credit, policy, auctions
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "desk"))
import miss_autopsy

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


def _auction(d, btc, dealer, term="10-Year", issue="2026-01-15", mat="2036-01-15"):
    return {"auction_date": d, "security_type": "Note", "security_term": term, "issue_date": issue, "maturity_date": mat,
            "bid_to_cover_ratio": str(btc), "comp_accepted": "40000000000", "primary_dealer_accepted": str(dealer * 4e8),
            "indirect_bidder_accepted": str(60 * 4e8), "high_yield": "4.2", "offering_amt": "42000000000"}


class Auctions(unittest.TestCase):
    def test_weak_vs_prior(self):
        rows = [_auction(f"2026-0{m}-10", 2.5 + 0.02 * (m % 2), 12 + (m % 2)) for m in range(1, 8)]
        rows.append(_auction("2026-11-20", 2.2, 22, term="9-Year 10-Month", issue="2026-11-25", mat="2036-09-15"))  # a reopening
        scored, recent = auctions.analyse(rows, date(2026, 11, 26))
        self.assertEqual(len(recent), 1)
        a = recent[0]
        self.assertEqual(a["years"], 10)          # reopening grouped with the 10-year
        self.assertEqual(a["prior_n"], 6)
        self.assertEqual(a["verdict"], "weak")
        self.assertEqual(a["dealer_pct"], 22.0)
        self.assertTrue(auctions.flags(recent)[0].startswith("Weak 9-Year 10-Month"))


    def test_merge_prefers_treasurydirect(self):
        fd = [dict(_auction("2026-11-10", 2.3, 10), cusip="X"), dict(_auction("2026-11-12", "null", 10), cusip="Y")]
        td = [dict(_auction("2026-11-10", 2.5, 9), cusip="X", src="TreasuryDirect")]
        m = auctions.merge(fd, td)
        self.assertEqual(len(m), 1)                 # the null-result row is dropped
        self.assertEqual(m[0]["src"], "TreasuryDirect")


class Divergence(unittest.TestCase):
    def test_fires_and_backtests(self):
        ds = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(200)]
        spx = [(d, 100 + 0.1 * i) for i, d in enumerate(ds)]            # steady new highs
        hy = [(d, 3.0 + (0.02 * (i - 150) if i > 150 else 0)) for i, d in enumerate(ds)]  # +2bp a day after day 150
        r = credit.divergence(hy, spx)
        self.assertTrue(r["now"]["firing"])
        self.assertEqual(r["sample"]["episodes"], 1)
        self.assertEqual(r["after_episodes"]["5d"]["pct_down"], 0)


class Autopsy(unittest.TestCase):
    def test_groups(self):
        preds = [{"id": f"p{i}", "claim": "VIX closes above 30 on Mon", "prob": 0.8, "status": "miss", "made": "2026-11-20", "resolves": "2026-11-23", "source": "Desk close"} for i in range(5)]
        preds += [{"id": f"q{i}", "claim": "S&P 500 closes up on Mon", "prob": 0.6, "status": "hit", "made": "2026-11-20", "resolves": "2026-11-23", "source": "Desk pre-open"} for i in range(5)]
        preds.append({"id": "open1", "claim": "x", "prob": 0.5, "status": "open"})
        days = [{"date": "2026-11-20", "regime_label": {"label": "Chop"}}, {"date": "2026-11-23", "sp": {"open": 101, "close": 103, "prev": 100}, "implied_pct": 1.5}]
        r = miss_autopsy.autopsy(preds, days)
        self.assertEqual(r["n"], 10)
        g = {(x["dimension"], x["cause"]): x for x in r["groups"]}
        self.assertEqual(g[("claim", "VIX level")]["misses"], 5)
        self.assertEqual(g[("prior_day", "after Chop")]["n"], 5)  # only close-run calls see the made day
        self.assertEqual(g[("move", "bigger than VIX priced")]["n"], 10)
        self.assertEqual(g[("gap", "gap open 0.5%+")]["n"], 10)
        self.assertEqual(r["candidates"][0]["cause"], "VIX level")


if __name__ == "__main__":
    unittest.main()
