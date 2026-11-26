"""Grade the desk's one-day S&P up/down calls against naive baselines.

Baselines (all no-judgment, all knowable when the call was made):
  formula  : the plain VIX formula. With zero drift it always says 50% on up/down.
  follow   : "trend follows yesterday". Lean 60% in the direction of the last
             completed session before the call. (60/40 is fixed in advance, not fitted.)
  always_dn: always 40% up. Shown only as a warning: it would have looked good in a
             falling month, which is why a single month cannot prove skill.

Usage: python3 baselines.py <dir of ledger prediction JSON files> [--json out.json]
Closes come from analyses/data/spx_daily.csv plus the verified closes in
analyses/desk/backtest_baseline.py (later dates win). Not investment advice.
"""
import csv, glob, json, math, re, statistics as st, sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAN = 0.60

def load_closes():
    spx = {}
    with open(ROOT / "data" / "spx_daily.csv") as f:
        for r in csv.DictReader(f):
            spx[r["date"]] = float(r["close"])
    src = (ROOT / "desk" / "backtest_baseline.py").read_text()
    m = re.search(r"^SPX=(\{.*?\})", src, re.M)
    if m:
        spx.update(json.loads(m.group(1)))
    return spx

UPDOWN = re.compile(r"^S&P 500 closes up on", re.I)

def monday(d):
    x = date.fromisoformat(d)
    return (x - timedelta(days=x.weekday())).isoformat()

def rows_from(dirpath, spx):
    days = sorted(spx)
    out = []
    for f in sorted(glob.glob(str(Path(dirpath) / "*.json"))):
        d = json.load(open(f)); x = d.get("data", d)
        if x.get("status") not in ("hit", "miss") or not UPDOWN.search(x.get("claim", "")):
            continue
        res, made = x["resolves"], x["made"]
        if res not in spx:
            continue
        prior = [t for t in days if t < res and t <= made]
        if len(prior) < 1:
            continue
        d0 = prior[-1]
        i = days.index(d0)
        if i == 0:
            continue
        ymove = spx[d0] / spx[days[i - 1]] - 1
        y = 1 if x["status"] == "hit" else 0
        out.append(dict(
            id=Path(f).stem, made=made, resolves=res, week=monday(res), y=y,
            desk=float(x["prob"]),
            formula=x.get("prob_base") if isinstance(x.get("prob_base"), (int, float)) else 0.5,
            sim=x.get("prob_sim") if isinstance(x.get("prob_sim"), (int, float)) else None,
            follow=LEAN if ymove > 0 else 1 - LEAN,
            always_dn=1 - LEAN,
            yday=d0, yday_move=round(ymove * 100, 2),
        ))
    out.sort(key=lambda r: (r["resolves"], r["made"], r["id"]))
    return out

def brier(rs, k):
    xs = [(r[k], r["y"]) for r in rs if r[k] is not None]
    return (round(st.mean((p - y) ** 2 for p, y in xs), 3), len(xs)) if xs else (None, 0)

def hits(rs, k):
    """Directional record: calls at exactly 50% are 'no call' and left out."""
    xs = [(r[k], r["y"]) for r in rs if r[k] is not None and r[k] != 0.5]
    return (sum((p > 0.5) == (y == 1) for p, y in xs), len(xs))

FORECASTERS = ["desk", "formula", "sim", "follow", "always_dn"]

def summarise(rs):
    s = {"n": len(rs), "ups": sum(r["y"] for r in rs)}
    for k in FORECASTERS:
        b, n = brier(rs, k); h, m = hits(rs, k)
        s[k] = {"brier": b, "n": n, "right": h, "called": m}
    return s

def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    spx = load_closes()
    rs = rows_from(a[0], spx)
    weeks = {}
    for r in rs:
        weeks.setdefault(r["week"], []).append(r)
    report = {"lean": LEAN, "all": summarise(rs),
              "weeks": [{"week_of": w, **summarise(v)} for w, v in sorted(weeks.items())],
              "rows": rs}
    al = report["all"]
    print(f"one-day S&P up/down calls graded: {al['n']} (S&P closed up {al['ups']})")
    print("forecaster   Brier   n   right/called")
    for k in FORECASTERS:
        v = al[k]
        print(f"{k:<11} {v['brier'] if v['brier'] is not None else '  -  ':>6} {v['n']:>3}   {v['right']}/{v['called']}")
    for w in report["weeks"]:
        print(w["week_of"], "n", w["n"], "desk", w["desk"]["brier"], "follow", w["follow"]["brier"], "formula", w["formula"]["brier"])
    if "--json" in a:
        json.dump(report, open(a[a.index("--json") + 1], "w"), indent=1)

if __name__ == "__main__":
    main()
