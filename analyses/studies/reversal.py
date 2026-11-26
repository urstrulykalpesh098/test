"""Streak and reversal study: after a big S&P day, or a run of down days, does the next day
tend to reverse or follow? Answers whether a "trend follows yesterday" rule has any base-rate
support before the desk leans on one.

Usage: python3 reversal.py [--days <dir of Desk Daily days JSON>] [--json out.json]
Data: analyses/data/spx_daily.csv (Nov 2025 to 6 Nov 2026) plus the verified closes in
analyses/desk/backtest_baseline.py and, if given, Desk Daily day docs (later dates win).
Every rate comes with n and a 95% Wilson interval; n under 20 is flagged as too small.
Not investment advice.
"""
import csv, json, math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def closes(days_dir=None):
    spx = {}
    with open(ROOT / "data" / "spx_daily.csv") as f:
        for r in csv.DictReader(f):
            spx[r["date"]] = float(r["close"])
    m = re.search(r"^SPX=(\{.*?\})", (ROOT / "desk" / "backtest_baseline.py").read_text(), re.M)
    if m:
        spx.update(json.loads(m.group(1)))
    if days_dir:
        for f in Path(days_dir).glob("*.json"):
            x = json.load(open(f)); x = x.get("data", x)
            c = (x.get("sp") or {}).get("close")
            if isinstance(c, (int, float)):
                spx[f.stem] = float(c)
    return spx

def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)

def study(spx):
    ds = sorted(spx)
    mv = [(ds[i], spx[ds[i]] / spx[ds[i - 1]] - 1) for i in range(1, len(ds))]
    pairs = [(mv[i][1], mv[i + 1][1], mv[i + 1][0], mv[i - 1][1] if i else None, mv[i - 2][1] if i > 1 else None)
             for i in range(len(mv) - 1)]
    base_up = sum(n > 0 for _, n, *_ in pairs)
    conds = [
        ("Any day", lambda y, p1, p2: True),
        ("After an up day", lambda y, p1, p2: y > 0),
        ("After a down day", lambda y, p1, p2: y < 0),
        ("After a drop of 1% or more", lambda y, p1, p2: y <= -0.01),
        ("After a drop of 2% or more", lambda y, p1, p2: y <= -0.02),
        ("After a gain of 1% or more", lambda y, p1, p2: y >= 0.01),
        ("After 2 down days in a row", lambda y, p1, p2: y < 0 and p1 is not None and p1 < 0),
        ("After 3 down days in a row", lambda y, p1, p2: y < 0 and p1 is not None and p1 < 0 and p2 is not None and p2 < 0),
    ]
    rows = []
    for name, f in conds:
        sel = [(y, n) for y, n, _, p1, p2 in pairs if f(y, p1, p2)]
        k = sum(n > 0 for _, n in sel); nn = len(sel)
        same = sum((n > 0) == (y > 0) for y, n in sel if y != 0)
        lo, hi = wilson(k, nn)
        rows.append({"condition": name, "n": nn, "next_up": k, "next_up_rate": round(k / nn, 3) if nn else None,
                     "ci_lo": lo, "ci_hi": hi, "followed": same,
                     "avg_next_move_pct": round(100 * sum(n for _, n in sel) / nn, 3) if nn else None,
                     "small_sample": nn < 20})
    return {"from": ds[0], "to": ds[-1], "sessions": len(mv), "base_up_rate": round(base_up / len(pairs), 3), "rows": rows}

def main(a):
    g = lambda f: a[a.index(f) + 1] if f in a else None
    out = study(closes(g("--days")))
    print(f"S&P 500 {out['from']} to {out['to']}, {out['sessions']} daily moves; next day up {out['base_up_rate']:.0%} of the time overall")
    print(f"{'condition':<30}{'n':>5}{'next up':>9}{'95% range':>15}{'followed':>10}{'avg next':>10}")
    for r in out["rows"]:
        rng = f"{r['ci_lo']:.0%}-{r['ci_hi']:.0%}" if r["n"] else "-"
        rate = f"{r['next_up_rate']:.0%}" if r["n"] else "-"
        print(f"{r['condition']:<30}{r['n']:>5}{rate:>9}{rng:>15}{r['followed']:>10}{(r['avg_next_move_pct'] or 0):>9.2f}%" + ("  small n" if r["small_sample"] else ""))
    if g("--json"):
        json.dump(out, open(g("--json"), "w"), indent=1)

if __name__ == "__main__":
    main(sys.argv[1:])
