"""VIX term structure study: does backwardation predict bigger S&P moves or range misses,
beyond what VIX level and recent realized vol already say?

Data: Cboe daily closes of VIX9D, VIX, VIX3M and SPX (analyses/data/history/CBOE_*.csv,
refreshed by analyses/trackers/vixterm.py --pull), 4 Jan 2011 (first VIX9D) to the latest close.
Every signal uses only that day's close; outcomes are the following sessions.

Tests
 1. By curve state: next-day move, move vs what VIX priced, 80% range misses, next 5-day vol.
 2. Same, holding VIX level fixed (buckets), so "backwardation happens when VIX is high" is not
    mistaken for a separate signal.
 3. Out of sample: fit log(next 5-day realized vol) on log VIX and log 20-day realized vol,
    2011-2018; then add the two curve ratios; score both on 2019 onward. A 21-day block
    bootstrap gives a 95% interval for the error difference.
 4. Rule 5 v5 (the desk's live 80% range, which already widens when VIX3M < VIX): miss rate by state.
 5. Direction after backwardation (forward 5 and 21 day S&P returns), for the record.

Usage: python3 vix_term.py [--json out.json]
Standard library only. Not investment advice; analysis only.
"""
import argparse, json, math, random, statistics as st, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.trackers.vixterm import load, state_of, STATES  # noqa: E402

Z80 = 1.2815515655446004
SPLIT = "2019-01-01"
SQ252 = math.sqrt(252)


def build():
    v9, v, v3, spx = (load(s) for s in ("VIX9D", "VIX", "VIX3M", "SPX"))
    ds = sorted(set(spx) & set(v) & set(v3) & set(v9))
    sd = sorted(d for d in spx if d >= "2010-11-01")
    idx = {d: i for i, d in enumerate(sd)}
    rets = [None] + [math.log(spx[b] / spx[a]) for a, b in zip(sd, sd[1:])]
    rows = []
    for d in ds:
        i = idx[d]
        if i < 21 or i + 5 >= len(sd):
            continue
        past = rets[i - 19:i + 1]
        fut5 = rets[i + 1:i + 6]
        rv20 = math.sqrt(sum(r * r for r in past) / 20)
        fwd21 = math.log(spx[sd[i + 21]] / spx[d]) if i + 21 < len(sd) else None
        rows.append({
            "d": d, "vix": v[d], "main": v[d] / v3[d], "front": v9[d] / v[d], "rv20": rv20,
            "r1": rets[i + 1], "rv5": math.sqrt(sum(r * r for r in fut5) / 5),
            "fwd5": sum(fut5), "fwd21": fwd21,
        })
    return rows


def misses(r):
    imp = r["vix"] / 100 / SQ252
    a = abs(r["r1"])
    storm = r["vix"] > 25 or r["main"] > 1
    s5 = max(0.96 * r["rv20"], imp) if storm else 0.96 * r["rv20"]
    return {"vix_range": a > Z80 * imp, "rv_range": a > Z80 * 0.96 * r["rv20"], "rule5": a > Z80 * s5}


def summarize(rs):
    if not rs:
        return None
    m = [misses(r) for r in rs]
    n = len(rs)
    return {
        "days": n,
        "avg_abs_move_pct": round(100 * st.mean(abs(r["r1"]) for r in rs), 3),
        "move_vs_vix_priced": round(st.mean(abs(r["r1"]) / (r["vix"] / 100 / SQ252) for r in rs), 3),
        "miss_vix_range": round(sum(x["vix_range"] for x in m) / n, 3),
        "miss_rv_range": round(sum(x["rv_range"] for x in m) / n, 3),
        "miss_rule5": round(sum(x["rule5"] for x in m) / n, 3),
        "next5_vol_vs_vix": round(st.mean(r["rv5"] * SQ252 * 100 / r["vix"] for r in rs), 3),
        "avg_vix": round(st.mean(r["vix"] for r in rs), 1),
    }


def episodes(rows, test=lambda r: r["main"] >= 1, gap=5):
    """Count separate runs (runs closer than `gap` rows are merged)."""
    n, last = 0, -999
    for i, r in enumerate(rows):
        if test(r):
            if i - last > gap:
                n += 1
            last = i
    return n


def ols(X, y):
    k = len(X[0])
    A = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)]
    for c in range(k):  # Gauss-Jordan
        p = max(range(c, k), key=lambda r: abs(A[r][c]))
        A[c], A[p], b[c], b[p] = A[p], A[c], b[p], b[c]
        for r in range(k):
            if r != c:
                f = A[r][c] / A[c][c]
                A[r] = [a - f * cc for a, cc in zip(A[r], A[c])]
                b[r] -= f * b[c]
    return [b[i] / A[i][i] for i in range(k)]


def block_ci(diff, block=21, reps=2000, seed=7):
    rnd = random.Random(seed)
    n = len(diff)
    means = []
    for _ in range(reps):
        s = []
        while len(s) < n:
            j = rnd.randrange(0, n - block)
            s.extend(diff[j:j + block])
        means.append(st.mean(s[:n]))
    means.sort()
    return round(means[int(0.025 * reps)], 5), round(means[int(0.975 * reps)], 5)


def oos(rows):
    def feats(r, curve):
        x = [1.0, math.log(r["vix"]), math.log(max(r["rv20"], 1e-5))]
        return x + ([math.log(r["main"]), math.log(r["front"])] if curve else [])
    tr = [r for r in rows if r["d"] < SPLIT]
    te = [r for r in rows if r["d"] >= SPLIT]
    y = lambda r: math.log(max(r["rv5"], 1e-5))
    out = {"train": f"{tr[0]['d']} to {tr[-1]['d']}", "test": f"{te[0]['d']} to {te[-1]['d']}", "test_days": len(te)}
    errs = {}
    for name, curve in (("vix_rv", False), ("vix_rv_curve", True)):
        b = ols([feats(r, curve) for r in tr], [y(r) for r in tr])
        e = [(y(r) - sum(c * x for c, x in zip(b, feats(r, curve)))) ** 2 for r in te]
        errs[name] = e
        ybar = st.mean(y(r) for r in te)
        out[name] = {"coef": [round(c, 3) for c in b], "test_rmse": round(math.sqrt(st.mean(e)), 4),
                     "test_r2": round(1 - sum(e) / sum((y(r) - ybar) ** 2 for r in te), 3)}
    diff = [a - b for a, b in zip(errs["vix_rv"], errs["vix_rv_curve"])]  # >0 means curve helps
    out["mse_gain_from_curve"] = round(st.mean(diff), 5)
    out["mse_gain_95ci"] = block_ci(diff)
    # Same idea for next-day size: |r1| scaled, log form
    y1 = lambda r: math.log(abs(r["r1"]) + 1e-4)
    for name, curve in (("next_day_vix_rv", False), ("next_day_vix_rv_curve", True)):
        b = ols([feats(r, curve) for r in tr], [y1(r) for r in tr])
        e = [(y1(r) - sum(c * x for c, x in zip(b, feats(r, curve)))) ** 2 for r in te]
        errs[name] = e
        out[name] = {"coef": [round(c, 3) for c in b], "test_rmse": round(math.sqrt(st.mean(e)), 4)}
    d1 = [a - b for a, b in zip(errs["next_day_vix_rv"], errs["next_day_vix_rv_curve"])]
    out["next_day_mse_gain"] = round(st.mean(d1), 5)
    out["next_day_mse_gain_95ci"] = block_ci(d1)
    return out


def run():
    rows = build()
    by_state = {name: summarize([r for r in rows if state_of(r["main"]) == name]) for _, name in STATES}
    buckets = [(0, 15), (15, 20), (20, 25), (25, 35), (35, 999)]
    controlled = []
    for lo, hi in buckets:
        rs = [r for r in rows if lo <= r["vix"] < hi]
        b = [r for r in rs if r["main"] >= 1]
        c = [r for r in rs if r["main"] < 1]
        controlled.append({"vix": f"{lo}-{hi if hi < 999 else 'up'}", "backwardation": summarize(b), "not": summarize(c),
                           "back_episodes": episodes(rs) if b else 0})
    front_hot = [r for r in rows if r["front"] >= 1.05 and r["main"] < 1]
    oos_res = oos(rows)
    split = {k: {s: summarize([r for r in rows if (r["d"] >= SPLIT) == (k == "2019_on") and (r["main"] >= 1) == (s == "back")])
                 for s in ("back", "not")} for k in ("2011_2018", "2019_on")}
    back = [r for r in rows if r["main"] >= 1]
    allr = rows
    direction = {
        "after_backwardation": {"days": len(back), "episodes": episodes(rows),
                                "fwd5_avg_pct": round(100 * st.mean(r["fwd5"] for r in back), 2),
                                "fwd5_up_share": round(sum(r["fwd5"] > 0 for r in back) / len(back), 3),
                                "fwd21_avg_pct": round(100 * st.mean(r["fwd21"] for r in back if r["fwd21"] is not None), 2),
                                "fwd21_up_share": round(sum(r["fwd21"] > 0 for r in back if r["fwd21"] is not None) /
                                                        sum(r["fwd21"] is not None for r in back), 3)},
        "all_days": {"fwd5_avg_pct": round(100 * st.mean(r["fwd5"] for r in allr), 2),
                     "fwd5_up_share": round(sum(r["fwd5"] > 0 for r in allr) / len(allr), 3),
                     "fwd21_avg_pct": round(100 * st.mean(r["fwd21"] for r in allr if r["fwd21"] is not None), 2),
                     "fwd21_up_share": round(sum(r["fwd21"] > 0 for r in allr if r["fwd21"] is not None) /
                                             sum(r["fwd21"] is not None for r in allr), 3)},
    }
    return {"period": f"{rows[0]['d']} to {rows[-1]['d']}", "days": len(rows),
            "backwardation_days": len(back), "backwardation_episodes": episodes(rows),
            "by_state": by_state, "by_vix_bucket": controlled, "split_periods": split,
            "front_hot_but_main_contango": summarize(front_hot),
            "out_of_sample": oos_res, "direction": direction}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    res = run()
    s = json.dumps(res, indent=1)
    if a.json:
        Path(a.json).write_text(s)
    print(s)
