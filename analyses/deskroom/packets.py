"""Desk Room: one small briefing packet per specialist seat, built from the nightly
hub data and the backbone history. Each packet is what that seat's Claude reads
before the meeting; the Head of desk reads every seat's post, not the raw data.

    python analyses/deskroom/packets.py   -> analyses/output/hub/deskroom_packets.json

Stdlib only. Analysis only, not investment advice.
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analyses.backbone.history import load, HIST  # noqa: E402

HUB = ROOT / "analyses" / "output" / "hub" / "hub_data.json"
OUT = ROOT / "analyses" / "output" / "hub" / "deskroom_packets.json"

SEATS = [
    ("vol", "Volatility desk", "VIX, its 3-month curve, how big tomorrow's ranges should be, and whether VIX is over- or under-pricing real moves.",
     ["VIXCLS", "VXVCLS", "SP500"]),
    ("rates", "Rates desk", "Treasury yields, curve shape, inflation expectations, real yields and the Fed's policy rate.",
     ["DGS3MO", "DGS2", "DGS10", "DGS30", "T10Y2Y", "T10YIE", "DFII10", "DFEDTARU"]),
    ("credit", "Credit & funding desk", "Corporate bond spreads, financial-conditions indexes and the plumbing: SOFR, fed funds, reverse repo, Fed balance sheet.",
     ["BAMLH0A0HYM2", "BAMLC0A0CM", "NFCI", "STLFSI4", "SOFR", "DFF", "RRPONTSYD", "WALCL"]),
    ("cross", "Cross-asset desk", "Stocks across indexes, the dollar, the Canadian dollar, euro, yen and oil/gas: what the other markets are saying.",
     ["SP500", "NASDAQCOM", "DJIA", "DTWEXBGS", "DEXCAUS", "DEXUSEU", "DEXJPUS", "DCOILWTICO", "DHHNGSP"]),
    ("history", "History & playbooks desk", "Look-alike days from the past and what followed, Fed rate-decision history, and the backtested rules.",
     ["SP500", "VIXCLS"]),
    ("skeptic", "Red team", "Argues against the room. Checks the desk's own track record, which models have no edge, and where the desk was wrong recently.",
     []),
]


def r(x, d=4):
    return None if x is None else round(x, d)


def series_card(sid, names):
    try:
        s = load(sid)
    except FileNotFoundError:
        return None
    ds = sorted(s)
    if not ds:
        return None
    v = [s[d] for d in ds]
    def back(n):
        return v[-1 - n] if len(v) > n else None
    last = v[-1]
    yr = v[-252:]
    card = {"id": sid, "name": names.get(sid, sid), "last_date": ds[-1], "last": r(last, 4)}
    for n, k in ((1, "chg_1"), (5, "chg_5"), (20, "chg_20")):
        b = back(n)
        if b is not None:
            card[k] = r(last - b, 4)
            if b:
                card[k + "_pct"] = r((last / b - 1) * 100, 2)
    lo, hi = min(yr), max(yr)
    card["pctile_1y"] = r((sum(1 for x in yr if x <= last) / len(yr)) * 100, 0)
    card["range_1y"] = [r(lo, 4), r(hi, 4)]
    return card


def build(hub=None):
    hub = hub or json.loads(HUB.read_text())
    names = {k: v.get("name", k) for k, v in hub["backbone"].items()}
    M, A, P, L, R, RG = hub["multiasset"], hub["analysts"], hub["playbook"], hub["lab"], hub["research"], hub.get("ranges", {})
    calls = {c["asset"]: c for c in M.get("today", [])}

    def calls_for(ids):
        return [{k: c.get(k) for k in ("label", "asof", "value0", "lo", "hi", "p_up")} for i, c in calls.items() if i in ids]

    extra = {
        "vol": {"todays_ranges": RG.get("today"), "range_rule_hit_rates": {k: v for k, v in RG.items() if k != "today"},
                 "vix_vs_realized": L.get("vol_premium"), "vix_curve_regimes": L.get("term")},
        "rates": {"fed_rate_changes_recent": (P.get("rate_decisions", {}).get("events") or [])[-6:],
                   "note": P.get("rate_decisions", {}).get("note")},
        "credit": {"note": "The credit-spread analyst was archived on 27 Nov 2026 (no edge over the up-rate); read the spreads directly."},
        "cross": {"board_record": M.get("record"), "board_band_hit_rates": {k: {"band_hit_test": v.get("band_hit_test"), "up_rate": v.get("up_rate")} for k, v in M.get("assets", {}).items()}},
        "history": {"setup_today": P.get("setup", {}).get("today"), "analogs": {h: {k: v.get(k) for k in ("p_up", "p_up_all_days", "spx_ret_q", "worst", "best")} for h, v in P.get("setup", {}).get("horizons", {}).items()},
                     "closest_days": P.get("setup", {}).get("closest", [])[:6]},
        "skeptic": {"archived_analyst_scores_h1": A.get("horizons", {}).get("h1"), "analysts_archived": A.get("archived"),
                     "research_verdicts": [{k: h.get(k) for k in ("id", "belief", "verdict", "plain")} for h in R.get("hypotheses", [])],
                     "board_record": M.get("record"), "recent_graded": M.get("recent_graded", [])[-10:]},
    }
    seats = []
    for key, title, beat, sids in SEATS:
        cards = [c for c in (series_card(s, names) for s in sids) if c]
        seats.append({"key": key, "title": title, "beat": beat, "series": cards,
                      "desk_calls": calls_for(sids), "extra": extra[key]})
    asof = L.get("asof")
    return {"built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "hub_built_at": hub.get("built_at"),
            "asof": asof, "seats": seats, "disclaimer": "Analysis only. Not investment advice."}


def run():
    out = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    return {"seats": len(out["seats"]), "asof": out["asof"]}


if __name__ == "__main__":
    print(run(), OUT.stat().st_size if OUT.exists() else 0)
