"""Miss autopsy: group the desk's graded calls by possible cause and show where the misses cluster.

Reads the Desk Ledger predictions and the Desk Daily day docs (as saved by ArtifactData with out_dir, one JSON
file per doc, or plain JSON lists) and cuts the graded calls along every dimension we can measure without hindsight
about the call itself:

  claim      what kind of call: up/down, range band, VIX level, S&P level, single stock, macro release, other
  conf       the probability bin the desk gave (0-30, 30-50, 50-70, 70-85, 85-100%)
  horizon    days from made to resolves (next session, 2-5 days, longer)
  run        which run made it (close, pre-open, midday, Monday Guess, previews)
  prior_day  the regime label of the last finished day before the call was made (known at the time)
  move       how big the S&P move was on the resolve day vs what the VIX priced (quiet, normal, bigger than priced)
  gap        whether the S&P opened 0.5%+ away from the prior close on the resolve day
  grading    whether the grade rested on conflicting or unofficial figures
  wrong_tag  the pre-mortem tag stored with the call (method/notes rule 6), when present

For every group it reports n, misses, hit rate and Brier, and how far that Brier sits from the overall Brier.
"Candidates" are groups with n >= 5 whose Brier is at least 0.05 worse than overall, each with a chance
check (share of random same-size groups of graded calls that score at least as badly). These are leads for the
Sunday review to look at, never rules: a lesson still needs the method/notes promotion test.

Analysis only. Not investment advice.

Usage
  python miss_autopsy.py --pred DIR_OR_JSON --days DIR_OR_JSON [--out report.json] [--since YYYY-MM-DD]
  -> prints a readout and writes {"date", "n", "overall", "groups": [{dimension, cause, n, misses, hit_rate, brier, excess}], "candidates": [...]}
     ready to store as Desk Ledger reports/miss_autopsy_<date>.
"""
import argparse, json, random, re
from datetime import date
from pathlib import Path

VERSION = "miss autopsy v1.0 (2026-11-26)"
TICKERS = r"\b(NVDA|AMD|AVGO|MU|TSLA|AAPL|MSFT|GOOGL|AMZN|META|CRWV|ORCL|IBIT|SMH|SOXL|QQQ|Nvidia|Oracle|CoreWeave|Anthropic)\b"


def load(src):
    p = Path(src)
    if p.is_dir():
        out = []
        for f in sorted(p.glob("*.json")):
            d = json.loads(f.read_text())
            doc = d.get("data", d)
            doc.setdefault("id", d.get("id") or f.stem)
            out.append(doc)
        return out
    d = json.loads(p.read_text())
    return d if isinstance(d, list) else list(d.values())


def claim_type(c):
    c = c or ""
    if re.search(r"\bVIX\b", c): return "VIX level"
    if re.search(TICKERS, c, re.I): return "single stock or theme"
    if re.search(r"\b(CPI|PCE|payrolls|jobs|FOMC|Fed|GDP)\b", c): return "macro or Fed"
    if re.search(r"inside|range|band|between", c, re.I): return "S&P range band"
    if re.search(r"closes? (up|down|higher|lower)|\bup on\b|\bdown on\b|green|red", c, re.I): return "S&P up or down"
    if re.search(r"S&P|SPX|200-day|\d,\d{3}", c): return "S&P level"
    return "other"


def conf_bin(p):
    for lo, hi, name in ((0, .3, "0-30%"), (.3, .5, "30-50%"), (.5, .7, "50-70%"), (.7, .85, "70-85%"), (.85, 1.01, "85-100%")):
        if lo <= p < hi: return name
    return "unknown"


def run_name(s):
    s = (s or "").lower()
    for k, v in (("desk close", "close run"), ("pre-open", "pre-open run"), ("midday", "midday run"), ("monday guess", "Monday Guess"),
                 ("morning", "morning briefing"), ("preview", "event preview"), ("night", "event preview")):
        if k in s: return v
    return "other"


def _d(s):
    try: return date.fromisoformat(str(s)[:10])
    except ValueError: return None


def features(p, days_by_date, day_list):
    made, res = _d(p.get("made")), _d(p.get("resolves"))
    f = {"claim": claim_type(p.get("claim")), "conf": conf_bin(p["prob"]), "run": run_name(p.get("source")),
         "grading": "conflicting or unofficial figures" if re.search(r"unofficial|conflict|no cboe|single-sourced", p.get("outcome") or "", re.I) else "clean figures"}
    if p.get("wrong_tag"): f["wrong_tag"] = p["wrong_tag"]
    if made and res:
        h = (res - made).days
        f["horizon"] = "same or next session" if h <= 1 else ("2-5 days" if h <= 5 else "over 5 days")
    # The made-day itself counts only for close-run calls, which are written after that day's close.
    known = (lambda dd: dd <= made) if f["run"] == "close run" else (lambda dd: dd < made)
    prior = [d for d in day_list if made and _d(d["date"]) and known(_d(d["date"]))]
    if prior and prior[-1].get("regime_label"): f["prior_day"] = "after " + prior[-1]["regime_label"].get("label", "?")
    rd = days_by_date.get(str(res)) if res else None
    if rd and rd.get("sp"):
        sp = rd["sp"]
        if sp.get("prev") and sp.get("close"):
            mv = abs(sp["close"] / sp["prev"] - 1) * 100
            imp = rd.get("implied_pct")
            f["move"] = ("bigger than VIX priced" if imp and mv > imp else "quiet (<0.5%)" if mv < .5 else "normal")
        if sp.get("prev") and sp.get("open"):
            f["gap"] = "gap open 0.5%+" if abs(sp["open"] / sp["prev"] - 1) * 100 >= .5 else "no gap"
    return f


def perm_p(group_b, all_b, draws=2000, seed=7):
    """Share of random same-size groups (drawn from all graded calls) whose average Brier is at least this group's."""
    k, obs, rng = len(group_b), sum(group_b) / len(group_b), random.Random(seed)
    if k >= len(all_b): return 1.0
    return round(sum(sum(rng.sample(all_b, k)) / k >= obs - 1e-12 for _ in range(draws)) / draws, 3)


def autopsy(preds, days, since=None):
    days = sorted([d for d in days if d.get("date")], key=lambda d: d["date"])
    by_date = {d["date"]: d for d in days}
    graded = [p for p in preds if p.get("status") in ("hit", "miss") and isinstance(p.get("prob"), (int, float))
              and (not since or str(p.get("resolves", "")) >= since)]
    rows = []
    for p in graded:
        y = 1 if p["status"] == "hit" else 0
        rows.append({"id": p.get("id"), "y": y, "b": (p["prob"] - y) ** 2, "f": features(p, by_date, days)})
    n = len(rows)
    if not n: return {"version": VERSION, "n": 0, "groups": [], "candidates": []}
    overall = {"n": n, "misses": sum(1 - r["y"] for r in rows), "brier": round(sum(r["b"] for r in rows) / n, 3)}
    overall["hit_rate"] = round(1 - overall["misses"] / n, 3)
    all_b = [r["b"] for r in rows]
    groups = []
    for dim in ("claim", "conf", "horizon", "run", "prior_day", "move", "gap", "grading", "wrong_tag"):
        vals = sorted({r["f"].get(dim) for r in rows if r["f"].get(dim)})
        for v in vals:
            g = [r for r in rows if r["f"].get(dim) == v]
            m = sum(1 - r["y"] for r in g)
            br = sum(r["b"] for r in g) / len(g)
            groups.append({"dimension": dim, "cause": v, "n": len(g), "misses": m, "hit_rate": round(1 - m / len(g), 3),
                           "brier": round(br, 3), "excess": round(br - overall["brier"], 3),
                           "chance": perm_p([r["b"] for r in g], all_b), "ids": [r["id"] for r in g if not r["y"]][:12]})
    cands = sorted([g for g in groups if g["n"] >= 5 and g["excess"] >= .05], key=lambda g: (-g["excess"], g["chance"]))
    misses = [p for p in graded if p["status"] == "miss"]
    tagged = [p for p in misses if p.get("miss_cause")]
    causes = {}
    for p in tagged: causes[p["miss_cause"]] = causes.get(p["miss_cause"], 0) + 1
    premortem = {"misses_tagged": len(tagged), "by_miss_cause": dict(sorted(causes.items(), key=lambda kv: -kv[1])),
                 "premortem_hit_rate": round(sum(bool(p.get("premortem_hit")) for p in tagged) / len(tagged), 3) if tagged else None}
    return {"version": VERSION, "n": n, "overall": overall, "groups": groups, "candidates": cands[:8], "premortem": premortem,
            "note": "Leads for the Sunday review, not rules. 'chance' = share of random groups of the same size that score at least this badly; under 0.05 is worth a look, above 0.2 is likely noise.",
            "disclaimer": "Analysis only. Not investment advice."}


def summary(r):
    if not r["n"]: return "MISS AUTOPSY: no graded calls"
    o = r["overall"]
    L = [f"MISS AUTOPSY ({r['n']} graded calls): hit rate {o['hit_rate']:.0%}, Brier {o['brier']} (a flat 50% guess scores 0.250)"]
    dim = None
    for g in r["groups"]:
        if g["dimension"] != dim: dim = g["dimension"]; L.append(f"  by {dim}:")
        L.append(f"    {g['cause']:<36} n={g['n']:<3} misses {g['misses']:<3} hit {g['hit_rate']:.0%}  Brier {g['brier']:.3f} ({g['excess']:+.3f})")
    L.append("  candidates (n>=5, Brier 0.05+ worse than overall):")
    for g in r["candidates"]:
        L.append(f"    {g['dimension']}={g['cause']}: Brier {g['brier']} vs {o['brier']}, {g['misses']}/{g['n']} missed, chance {g['chance']}")
    if not r["candidates"]: L.append("    none")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--days", required=True)
    ap.add_argument("--since")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = autopsy(load(a.pred), load(a.days), a.since)
    r["date"] = date.today().isoformat()
    if a.out: Path(a.out).write_text(json.dumps(r, indent=1))
    print(summary(r))


if __name__ == "__main__":
    main()
