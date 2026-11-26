"""Desk Scorecard: desk vs VIX formula vs simulator vs "trend follows yesterday", by week.

Self-contained (stdlib only) so a scheduled run can store it in the Desk Ledger
(method/scorecard_script) and run it from a scratch folder, like the flows script.

Usage:
  python3 scorecard.py --pred <dir of ledger prediction JSON> --days <dir of Desk Daily days JSON>
                       [--book meta_book.json] [--out full.json] [--rows rows.json]

Inputs are ArtifactData out_dir dumps. Closes come from Desk Daily days/{date}
(sp.close, sp.prev, vix.close) plus a small seed of verified closes before 9 Nov 2026.
Weeks are keyed by the Monday of the week a call resolves in (a call graded early
counts in the current week). --rows writes the {rows, meta} file the page loads.

Baselines (no judgment, all knowable when the call was made):
  formula   : zero drift, daily sigma = VIX/100/sqrt(252) from the last close before the call.
              It says 50% on every up/down call.
  follow    : lean 60% in the direction of the last finished session before an up/down call.
              60/40 was fixed in advance, not fitted.
  always_dn : 40% up every day. A warning only: in a falling month it looks smart without skill.
Not investment advice.
"""
import json, math, re, statistics as st, sys
from datetime import date, timedelta
from pathlib import Path

LEAN = 0.60
# Verified closes before the Desk Daily day docs begin (from analyses/data/spx_daily.csv and
# analyses/desk/backtest_baseline.py). prev = the prior session's close, for the day's move.
SEED = {"2026-11-06": {"close": 7376.86, "prev": 7353.73, "vix": 25.64}}

N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
num = lambda s: float(s.replace(",", ""))

def load_dir(d):
    out = {}
    for f in sorted(Path(d).glob("*.json")):
        x = json.load(open(f)); out[f.stem] = x.get("data", x)
    return out

def load_days(d):
    days = {k: dict(v) for k, v in SEED.items()}
    if d:
        for k, x in load_dir(d).items():
            sp, vx = x.get("sp") or {}, x.get("vix") or {}
            if isinstance(sp.get("close"), (int, float)):
                days[k] = {"close": float(sp["close"]), "prev": sp.get("prev"), "vix": vx.get("close")}
    return days

def monday(d):
    x = date.fromisoformat(d); return (x - timedelta(days=x.weekday())).isoformat()

def is_pre(pid, x):
    return ("pre-open" in x.get("source", "").lower()) or pid.startswith(("pre", "mg", "mon"))

def last_close(days, made, resolves, pre):
    ks = sorted(days)
    prior = [d for d in ks if d < made] if pre else [d for d in ks if d <= made]
    prior = [d for d in prior if d < resolves]
    return prior[-1] if prior else None

def formula_prob(claim, made, resolves, pre, days):
    """Plain VIX formula, same rules as analyses/desk/backtest_baseline.py."""
    c = claim.replace("–", "-").replace("—", "-")
    if "S&P" not in c or "VIX" in c[:4] or resolves not in days:
        return None
    if re.search(r"any day|at least one|high-to-low|range|intraday|within 21|through year", c, re.I) and not re.search(r"inside|between", c, re.I):
        return None
    d0 = last_close(days, made, resolves, pre)
    if not d0 or not days[d0].get("vix"):
        return None
    C, V = days[d0]["close"], float(days[d0]["vix"])
    h = len([d for d in days if d0 < d <= resolves])
    if h < 1:
        return None
    s = V / 100 / math.sqrt(252) * math.sqrt(h)
    m = re.search(r"(?:inside|between)\s+([\d,]{4,6}(?:\.\d+)?)\s*(?:-|and|to)\s*([\d,]{4,6}(?:\.\d+)?)", c)
    if m:
        a, b = sorted([num(m.group(1)), num(m.group(2))]); return N(math.log(b / C) / s) - N(math.log(a / C) / s)
    m = re.search(r"(above|below|higher than|lower than|under|over)\s+(?:Fri\w*\s+|its\s+|the\s+)?(?:200-day[^0-9]*)?([\d,]{4,6}(?:\.\d+)?)", c)
    if m:
        K = num(m.group(2)); p = N(math.log(C / K) / s); return p if m.group(1) in ("above", "higher than", "over") else 1 - p
    if re.search(r"closes up|up on the day|ends the week higher|closes higher", c, re.I):
        return 0.5
    return None

UPDOWN = re.compile(r"^S&P 500 closes up on", re.I)

def graded(preds):
    return [(k, x) for k, x in sorted(preds.items())
            if x.get("status") in ("hit", "miss") and isinstance(x.get("prob"), (int, float))]

def updown_rows(calls, days):
    out = []
    for pid, x in calls:
        if not UPDOWN.search(x.get("claim", "")) or x["resolves"] not in days:
            continue
        d0 = last_close(days, x["made"], x["resolves"], is_pre(pid, x))
        if not d0 or not days[d0].get("prev"):
            continue
        mv = days[d0]["close"] / float(days[d0]["prev"]) - 1
        out.append(dict(id=pid, resolves=x["resolves"], y=int(x["status"] == "hit"), desk=float(x["prob"]),
                        follow=LEAN if mv > 0 else 1 - LEAN, always_dn=1 - LEAN, formula=0.5,
                        yday=d0, yday_move=round(mv * 100, 2)))
    return out

br = lambda xs: round(st.mean((p - y) ** 2 for p, y in xs), 3) if xs else None

def hits(rs, k):
    xs = [(r[k], r["y"]) for r in rs if r[k] != 0.5]
    return sum((p > 0.5) == (y == 1) for p, y in xs), len(xs)

def block(calls, days, ud):
    allc = [(float(x["prob"]), int(x["status"] == "hit")) for _, x in calls]
    md, mb, sp = [], [], []
    for pid, x in calls:
        y = int(x["status"] == "hit")
        b = x.get("prob_base")
        if not isinstance(b, (int, float)):
            b = formula_prob(x["claim"], x["made"], x["resolves"], is_pre(pid, x), days)
        if b is not None:
            md.append((float(x["prob"]), y)); mb.append((b, y))
        if isinstance(x.get("prob_sim"), (int, float)):
            sp.append((float(x["prob"]), float(x["prob_sim"]), y))
    return {
        "n": len(allc), "hits": sum(y for _, y in allc), "desk_brier_all": br(allc),
        "said_avg": round(st.mean(p for p, _ in allc), 3) if allc else None,
        "n_matched": len(md), "desk_brier": br(md), "formula_brier": br(mb),
        "n_sim": len(sp), "desk_brier_simset": br([(p, y) for p, _, y in sp]), "sim_brier": br([(s, y) for _, s, y in sp]),
        "ud_n": len(ud), "ud_days": len({r["resolves"] for r in ud}), "ud_ups": sum(r["y"] for r in ud),
        "ud_desk_brier": br([(r["desk"], r["y"]) for r in ud]),
        "ud_follow_brier": br([(r["follow"], r["y"]) for r in ud]),
        "ud_formula_brier": br([(r["formula"], r["y"]) for r in ud]),
        "ud_always_dn_brier": br([(r["always_dn"], r["y"]) for r in ud]),
        "ud_desk_right": hits(ud, "desk")[0], "ud_desk_called": hits(ud, "desk")[1],
        "ud_follow_right": hits(ud, "follow")[0], "ud_follow_called": hits(ud, "follow")[1],
    }

def book_by_week(book):
    if not book:
        return {}
    b = book.get("data", book)
    curve = sorted(b.get("curve") or [], key=lambda c: c["date"])
    if not curve:
        return {}
    e0, s0 = float(b.get("start") or curve[0]["equity"]), float(curve[0]["spy"])
    return {monday(c["date"]): {"book_equity": round(float(c["equity"]), 2),
                                "book_ret_pct": round((float(c["equity"]) / e0 - 1) * 100, 2),
                                "spy_ret_pct": round((float(c["spy"]) / s0 - 1) * 100, 2),
                                "book_points": len([x for x in curve if x["date"] <= c["date"]])} for c in curve}

BOOK_KEYS = ("book_equity", "book_ret_pct", "spy_ret_pct", "book_points")

def build(preds, days, book=None, today=None):
    today = today or date.today().isoformat()
    calls = graded(preds)
    ud = updown_rows(calls, days)
    wk = lambda x: monday(min(x["resolves"], today))
    weeks = sorted({wk(x) for _, x in calls})
    bw = book_by_week(book)
    rows = []
    for w in weeks:
        cw = [(k, x) for k, x in calls if wk(x) == w]
        r = {"week_of": w, **block(cw, days, [u for u in ud if monday(min(u["resolves"], today)) == w])}
        r.update({k: bw.get(w, {}).get(k) for k in BOOK_KEYS})
        rows.append(r)
    allr = {"week_of": "All weeks", **block(calls, days, ud)}
    allr.update({k: (bw[max(bw)].get(k) if bw else None) for k in BOOK_KEYS})
    return {"updated": today, "lean": LEAN, "rows": rows + [allr], "updown": ud}

def main(a):
    g = lambda f: a[a.index(f) + 1] if f in a else None
    if not g("--pred"):
        sys.exit(__doc__)
    out = build(load_dir(g("--pred")), load_days(g("--days")), json.load(open(g("--book"))) if g("--book") else None)
    if g("--out"):
        json.dump(out, open(g("--out"), "w"), indent=1)
    if g("--rows"):
        json.dump({"rows": out["rows"], "meta": [
            {"label": "scorecard.py", "value": Path(__file__).read_text(), "type": "code", "lang": "python"},
            {"label": "Input", "value": "Desk Ledger predictions (graded hit/miss), Desk Daily days/* closes and meta/book"},
            {"label": "Updated", "value": out["updated"]}]}, open(g("--rows"), "w"), indent=0)
    for r in out["rows"]:
        print(f"{r['week_of']:<10} n={r['n']:<3} desk_all={r['desk_brier_all']} | S&P {r['n_matched']}: desk {r['desk_brier']} formula {r['formula_brier']} | sim {r['n_sim']} | up/down {r['ud_n']} ({r['ud_days']} days): desk {r['ud_desk_brier']} follow {r['ud_follow_brier']} always_dn {r['ud_always_dn_brier']}")

if __name__ == "__main__":
    main(sys.argv[1:])
