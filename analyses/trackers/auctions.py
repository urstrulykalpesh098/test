"""Eye View Treasury auction tracker: how well the government's note and bond sales went, from Treasury's own data.

Sources (free, no key): TreasuryDirect auction API (www.treasurydirect.gov/TA_WS, current within a day) for the last
~5 months, and Treasury Fiscal Data API (api.fiscaldata.treasury.gov, history; it can lag by weeks)
  /v1/accounting/od/auctions_query     results of every marketable auction (bid-to-cover, who bought, high yield)
  /v1/accounting/od/upcoming_auctions  announced auctions not yet held

What it measures, per coupon auction (notes, bonds, TIPS; bills are skipped as noise)
  bid-to-cover   bids received / amount sold. Lower = less demand.
  dealer share   share of the competitive amount left with primary dealers, who must bid. Higher = buyers stayed away.
  indirect share share taken by indirect bidders (mostly foreign and domestic investors bidding through dealers).
Each auction is compared with the previous 6 auctions of the same original term.

Not covered (listed under "gaps"): the "tail" (high yield minus the when-issued yield at 1 pm) needs intraday
when-issued quotes, which are not free. Dealer share and bid-to-cover are the free stand-ins.

Analysis only. Not investment advice. Context for the desk, never blended into forecasts until tested.

Usage
  python auctions.py                          readout -> analyses/output/auctions_latest.json
  python auctions.py --desk OUT.json [--date YYYY-MM-DD]
      writes {"meta_auctions": ..., "day_auctions": ...} for Desk Daily meta/auctions and days/<date>.auctions
"""
import argparse, json, statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

try:
    from common import get
except ImportError:
    from .common import get

VERSION = "auctions v1.1 (2026-11-26)"
HERE = Path(__file__).resolve().parent
FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/"
TD_UP = "https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json"  # announced only; coupons appear about a week ahead
TD = "https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days={days}&type={kind}"
COUPON_TYPES = ("Note", "Bond", "TIPS Note", "TIPS Bond")
PRIOR_N, RECENT_DAYS, STALE_DAYS = 6, 14, 10


def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def fetch(endpoint, params):
    rows, page = [], 1
    while True:
        q = {**params, "page[size]": "1000", "page[number]": str(page)}
        d = json.loads(get(FD + endpoint + "?" + urlencode(q, safe="[]:,-")))
        rows += d.get("data", [])
        if page >= (d.get("meta", {}).get("total-pages") or 1): return rows
        page += 1


def treasurydirect(days=150):
    """Recent results from TreasuryDirect (current within a day; Fiscal Data can lag by weeks), mapped to Fiscal Data field names."""
    out = []
    for kind in ("Note", "Bond", "TIPS"):
        for x in json.loads(get(TD.format(days=days, kind=kind))):
            if x.get("floatingRate") == "Yes": continue
            n = lambda k: _f(x.get(k)) or 0.0
            comp = n("primaryDealersCompetitiveParAwarded") + n("directBiddersCompetitiveParAwarded") + n("indirectBiddersCompetitiveParAwarded")
            tips = x.get("inflationProtected") == "Yes"
            out.append({"auction_date": (x.get("auctionDate") or x.get("competitiveAuctionCloseDate") or "")[:10], "cusip": x.get("cusip"),
                        "security_type": ("TIPS " if tips else "") + (x.get("securityType") or ""), "security_term": x.get("securityTerm"),
                        "issue_date": (x.get("issueDate") or "")[:10], "maturity_date": (x.get("maturityDate") or "")[:10],
                        "bid_to_cover_ratio": x.get("bidToCoverRatio"), "comp_accepted": comp or None,
                        "primary_dealer_accepted": x.get("primaryDealersCompetitiveParAwarded"),
                        "indirect_bidder_accepted": x.get("indirectBiddersCompetitiveParAwarded"), "high_yield": x.get("highYield"),
                        "offering_amt": x.get("offeringAmount"), "inflation_index_security": "Yes" if tips else "No",
                        "reopening": x.get("reopening"), "src": "TreasuryDirect"})
    return out


def merge(fd_rows, td_rows):
    """Fiscal Data for history, TreasuryDirect wins where both have the same auction."""
    key = lambda r: (r.get("cusip"), (r.get("auction_date") or "")[:10])
    m = {key(r): r for r in fd_rows if (r.get("bid_to_cover_ratio") or "null") != "null" and _f(r.get("high_yield")) is not None}
    m.update({key(r): r for r in td_rows if _f(r.get("bid_to_cover_ratio")) is not None})
    return list(m.values())


def term_years(r):
    """Original term in whole years, so a '9-Year 10-Month' reopening groups with the 10-year."""
    try:
        y = (date.fromisoformat(r["maturity_date"]) - date.fromisoformat(r["issue_date"])).days / 365.25
        return max(1, round(y))
    except (KeyError, ValueError, TypeError):
        return None


def metrics(r):
    comp = _f(r.get("comp_accepted")) or _f(r.get("total_accepted"))
    pd_, ind = _f(r.get("primary_dealer_accepted")), _f(r.get("indirect_bidder_accepted"))
    kind = "TIPS" if "TIPS" in (r.get("security_type") or "") or (r.get("inflation_index_security") == "Yes") else "Nominal"
    return {"date": r.get("auction_date"), "cusip": r.get("cusip"), "type": r.get("security_type"), "kind": kind,
            "term": r.get("security_term"), "years": term_years(r), "high_yield": _f(r.get("high_yield")),
            "btc": _f(r.get("bid_to_cover_ratio")), "size_usd": _f(r.get("offering_amt")),
            "dealer_pct": round(100 * pd_ / comp, 1) if pd_ is not None and comp else None,
            "indirect_pct": round(100 * ind / comp, 1) if ind is not None and comp else None,
            "reopening": r.get("reopening") == "Yes"}


def score(a, prior):
    """Compare one auction with earlier ones of the same kind and term."""
    out = dict(a)
    for k in ("btc", "dealer_pct", "indirect_pct"):
        xs = [p[k] for p in prior if p.get(k) is not None]
        if a.get(k) is None or len(xs) < 3: out[k + "_vs_avg"] = None; continue
        m, sd = st.mean(xs), st.pstdev(xs)
        out[k + "_avg"] = round(m, 2)
        out[k + "_vs_avg"] = round(a[k] - m, 2)
        out[k + "_z"] = round((a[k] - m) / sd, 2) if sd else None
    zb, zd = out.get("btc_z"), out.get("dealer_pct_z")
    out["verdict"] = ("weak" if (zb is not None and zb <= -1) and (zd is not None and zd >= 1) else
                      "strong" if (zb is not None and zb >= 1) and (zd is not None and zd <= -1) else
                      "soft" if (zb is not None and zb <= -1.5) or (zd is not None and zd >= 1.5) else "normal")
    out["prior_n"] = len(prior)
    return out


def analyse(rows, today):
    coupons = [metrics(r) for r in rows if r.get("security_type") in COUPON_TYPES and _f(r.get("bid_to_cover_ratio")) is not None
               and _f(r.get("high_yield")) is not None]  # no high yield = floating-rate note, skipped
    coupons.sort(key=lambda a: a["date"])
    scored = []
    for i, a in enumerate(coupons):
        prior = [p for p in coupons[:i] if p["kind"] == a["kind"] and p["years"] == a["years"]][-PRIOR_N:]
        scored.append(score(a, prior))
    since = (today - timedelta(days=RECENT_DAYS)).isoformat()
    recent = [a for a in scored if a["date"] >= since]
    return scored, recent


def flags(recent):
    F = []
    for a in recent:
        if a["verdict"] == "weak":
            F.append(f"Weak {a['term']} {a['kind'].lower()} auction {a['date']}: bid-to-cover {a['btc']} (avg {a.get('btc_avg')}), dealers kept {a['dealer_pct']}% (avg {a.get('dealer_pct_avg')})")
        elif a["verdict"] == "strong" and (a["years"] or 0) >= 10:
            F.append(f"Strong {a['term']} auction {a['date']}: bid-to-cover {a['btc']}, dealers kept only {a['dealer_pct']}%")
    return F


def run(today=None):
    today = today or date.today()
    res = {"version": VERSION, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "disclaimer": "Analysis only. Not investment advice.", "gaps": []}
    try:
        rows = fetch("auctions_query", {"filter": f"auction_date:gte:{(today - timedelta(days=800)).isoformat()},auction_date:lte:{today.isoformat()}",
                                        "sort": "auction_date"})
        try: rows = merge(rows, treasurydirect())
        except Exception as e: res["gaps"].append(f"TreasuryDirect recent results: {type(e).__name__}: {e}"); rows = merge(rows, [])
        rows = [r for r in rows if (r.get("auction_date") or "") <= today.isoformat()]
        scored, recent = analyse(rows, today)
        res["recent"] = recent
        res["last_by_term"] = {f"{a['kind']} {a['years']}y": a for a in scored}  # latest auction of each term
        res["counts"] = {"coupon_auctions": len(scored), "since": scored[0]["date"] if scored else None}
        res["latest_result"] = scored[-1]["date"] if scored else None
        if res["latest_result"] and (today - date.fromisoformat(res["latest_result"])).days > STALE_DAYS:
            res["gaps"].append(f"Treasury Fiscal Data is behind: newest coupon auction with results is {res['latest_result']}; later auctions are missing, not normal")
    except Exception as e:
        res["recent"], res["error"] = [], f"{type(e).__name__}: {e}"; res["gaps"].append(f"auction results: {res['error']}")
    try:
        up = json.loads(get(TD_UP))
        res["upcoming"] = [{"date": (u.get("auctionDate") or u.get("competitiveAuctionCloseDate") or "")[:10], "type": u.get("securityType"),
                            "term": u.get("securityTerm"), "size_usd": _f(u.get("offeringAmount")), "announced": (u.get("announcementDate") or "")[:10]}
                           for u in up if u.get("securityType") in ("Note", "Bond", "TIPS")][:12]
    except Exception as e:
        res["upcoming"] = []; res["gaps"].append(f"upcoming auctions: {type(e).__name__}: {e}")
    res["flags"] = flags(res["recent"])
    res["gaps"].append("Auction tail (high yield vs 1 pm when-issued yield): needs intraday when-issued quotes, not free; dealer share and bid-to-cover used instead")
    res["source"] = [TD.format(days="N", kind="Note|Bond|TIPS"), FD + "auctions_query"]
    return res


def desk_docs(res, day):
    keep = ("date", "term", "kind", "years", "high_yield", "btc", "btc_avg", "btc_z", "dealer_pct", "dealer_pct_avg", "dealer_pct_z",
            "indirect_pct", "indirect_pct_avg", "verdict", "size_usd")
    meta = {"updated": day, "version": VERSION, "latest_result": res.get("latest_result"), "recent": [{k: a.get(k) for k in keep} for a in res.get("recent", [])],
            "last_by_term": {t: {k: a.get(k) for k in keep} for t, a in (res.get("last_by_term") or {}).items()},
            "upcoming": res.get("upcoming", []), "flags": res["flags"], "gaps": res["gaps"], "source": res["source"]}
    held = [a for a in res.get("recent", []) if a["date"] == day]
    return {"meta_auctions": meta, "day_auctions": {"held": [{k: a.get(k) for k in keep} for a in held], "flags": res["flags"]}}


def summary(r):
    L = [f"TREASURY AUCTIONS {r['generated_utc']} UTC (analysis only, not investment advice)"]
    L.append(f"  newest result on file: {r.get('latest_result')}")
    for a in (r.get("recent") or list((r.get("last_by_term") or {}).values())):
        L.append(f"  {a['date']} {a['term']} {a['kind']}: yield {a['high_yield']}%, bid-to-cover {a['btc']} (avg {a.get('btc_avg')}), "
                 f"dealers {a['dealer_pct']}% (avg {a.get('dealer_pct_avg')}), indirect {a['indirect_pct']}% -> {a['verdict']}")
    for u in r.get("upcoming", []): L.append(f"  upcoming {u['date']} {u['term']} {u['type']}" + (f" ${u['size_usd'] / 1e9:.0f}B" if u.get("size_usd") else ""))
    for f in r["flags"]: L.append(f"  FLAG: {f}")
    for g in r["gaps"]: L.append(f"  gap: {g}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "output" / "auctions_latest.json"))
    ap.add_argument("--desk", help="write Desk Daily docs to this path")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()
    res = run(date.fromisoformat(a.date))
    if a.desk: Path(a.desk).write_text(json.dumps(desk_docs(res, a.date), indent=1))
    else:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(summary(res))


if __name__ == "__main__":
    main()
