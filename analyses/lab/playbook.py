"""Event and setup playbooks (upgrade 6): "what usually happened next after days like this?"

1. Setup playbook: find the 150 past days whose setup looked most like the latest close
   (VIX level, 5-day S&P move, 20-day trend, VIX curve) and show what the S&P and VIX did
   over the next 1, 5 and 20 days, as a spread of outcomes, not one guess.
2. Rate-decision playbook: days the Fed changed its target (FRED DFEDTARU), and the S&P path
   around them. Free data only shows changes; meetings that held rates are not in it, so
   this is cuts and hikes only (flagged in the output).
Writes analyses/output/lab/playbook.json. Not investment advice; analysis only.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.backbone.history import load, HIST  # noqa: E402
from analyses.lab.core import quantiles, rate, r4  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "lab"


def setups(hist=HIST):
    spx, vix, vxv = load("SP500", hist), load("VIXCLS", hist), load("VXVCLS", hist)
    days = sorted(set(spx) & set(vix) & set(vxv))
    rows = []
    for i in range(20, len(days)):
        d = days[i]
        rows.append({"i": i, "date": d, "vix": vix[d], "r5": spx[d] / spx[days[i - 5]] - 1,
                     "r20": spx[d] / spx[days[i - 20]] - 1, "curve": vxv[d] / vix[d]})
    return days, spx, vix, rows


def analogs(hist=HIST, k=150, gap=10):
    days, spx, vix, rows = setups(hist)
    keys = ("vix", "r5", "r20", "curve")
    mu = {x: sum(r[x] for r in rows) / len(rows) for x in keys}
    sd = {x: (sum((r[x] - mu[x]) ** 2 for r in rows) / len(rows)) ** 0.5 for x in keys}
    today = rows[-1]
    cand = []
    for r in rows[:-20]:  # need 20 days of future
        dist = math.sqrt(sum(((r[x] - today[x]) / sd[x]) ** 2 for x in keys))
        cand.append((dist, r))
    cand.sort(key=lambda t: t[0])
    picked = []
    for dist, r in cand:  # keep analogs at least `gap` days apart so one episode doesn't dominate
        if all(abs(r["i"] - p["i"]) >= gap for _, p in picked):
            picked.append((dist, r))
        if len(picked) >= k:
            break
    out = {"today": {x: r4(today[x]) for x in keys} | {"date": today["date"]}, "n": len(picked), "horizons": {}}
    for h in (1, 5, 20):
        rets = [spx[days[r["i"] + h]] / spx[days[r["i"]]] - 1 for _, r in picked]
        vch = [vix[days[r["i"] + h]] - vix[days[r["i"]]] for _, r in picked]
        allr = [spx[days[i + h]] / spx[days[i]] - 1 for i in range(20, len(days) - h)]
        out["horizons"][f"h{h}"] = {
            "p_up": r4(rate(x > 0 for x in rets)), "p_up_all_days": r4(rate(x > 0 for x in allr)),
            "spx_ret_q": {q: r4(v) for q, v in quantiles(rets).items()},
            "vix_change_q": {q: r4(v) for q, v in quantiles(vch).items()},
            "worst": r4(min(rets)), "best": r4(max(rets)),
        }
    out["closest"] = [{"date": r["date"], "distance": r4(dist), "vix": r["vix"], "r5": r4(r["r5"]),
                       "next20": r4(spx[days[r["i"] + 20]] / spx[days[r["i"]]] - 1)} for dist, r in picked[:12]]
    return out


def rate_decisions(hist=HIST):
    tgt, spx = load("DFEDTARU", hist), load("SP500", hist)
    tdays = sorted(tgt)
    sdays = sorted(spx)
    events = []
    for a, b in zip(tdays, tdays[1:]):
        if tgt[b] != tgt[a]:
            events.append((b, round((tgt[b] - tgt[a]) * 100)))
    out = []
    for d, bp in events:
        after = [x for x in sdays if x >= d]
        before = [x for x in sdays if x < d]
        if len(after) < 6 or len(before) < 1:
            continue
        c0 = spx[before[-1]]
        out.append({"date": d, "change_bp": bp, "day_ret": r4(spx[after[0]] / c0 - 1),
                    "ret_5d": r4(spx[after[5]] / c0 - 1),
                    "ret_20d": r4(spx[after[20]] / c0 - 1) if len(after) > 20 else None})
    cuts = [e for e in out if e["change_bp"] < 0]
    hikes = [e for e in out if e["change_bp"] > 0]
    summ = lambda xs, f: {"n": len(xs), "p_up": r4(rate(e[f] > 0 for e in xs if e[f] is not None)),
                          "median": r4(sorted(e[f] for e in xs if e[f] is not None)[len([e for e in xs if e[f] is not None]) // 2]) if xs else None}
    return {"note": "Only meetings that changed rates are visible in free FRED data; holds are missing. S&P history starts Nov 2016.",
            "events": out, "cuts": {f: summ(cuts, f) for f in ("day_ret", "ret_5d", "ret_20d")},
            "hikes": {f: summ(hikes, f) for f in ("day_ret", "ret_5d", "ret_20d")}}


def run(hist=HIST, out=OUT):
    res = {"setup": analogs(hist), "rate_decisions": rate_decisions(hist)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "playbook.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    r = run()
    print(json.dumps(r["setup"]["today"]), r["setup"]["n"])
    for h, v in r["setup"]["horizons"].items():
        print(h, v["p_up"], v["p_up_all_days"], v["spx_ret_q"]["0.1"], v["spx_ret_q"]["0.5"], v["spx_ret_q"]["0.9"])
    print([c["date"] for c in r["setup"]["closest"]])
    print("cuts", r["rate_decisions"]["cuts"]); print("hikes", r["rate_decisions"]["hikes"])
