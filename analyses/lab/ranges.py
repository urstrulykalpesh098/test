"""Rule 5 v5: 80% ranges that adapt to conditions (approved by Rk 26 Nov 2026).

S&P:  sigma = 0.96 x 20-day realized daily vol of S&P log returns.
      Storm (VIX > 25, or 3-month VIX below VIX): sigma = max(that, VIX/100/sqrt(252)).
      80% range = close x exp(+/- 1.28 x sigma x sqrt(trading days)).
VIX:  sigma = 1.0 x 20-day realized vol of daily VIX log changes;
      80% band = VIX x exp(+/- 1.28 x sigma x sqrt(trading days)).
Widths fitted on 2016-2021 (S&P) / 1990-2021 (VIX) and checked on 2022 onward.
Not investment advice; analysis only.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.backbone.history import aligned, load, HIST  # noqa: E402
from analyses.lab.core import Z80, r4  # noqa: E402

K_SPX, FLOOR, K_VIX, SPLIT = 0.96, 1.0, 1.0, "2022-01-01"
OUT = Path(__file__).resolve().parents[1] / "output" / "lab"


def rv20(rets):
    return math.sqrt(sum(r * r for r in rets[-20:]) / 20)


def spx_range(close, vix, vix3m, last21_closes, h=1):
    rets = [math.log(b / a) for a, b in zip(last21_closes, last21_closes[1:])]
    vs = vix / 100 / math.sqrt(252)
    storm = vix > 25 or (vix3m is not None and vix3m < vix)
    s = max(K_SPX * rv20(rets), FLOOR * vs) if storm else K_SPX * rv20(rets)
    w = Z80 * s * math.sqrt(h)
    return {"lo": close * math.exp(-w), "hi": close * math.exp(w), "half_width_pct": 100 * (math.exp(w) - 1), "storm": storm}


def vix_band(vix, last21_vix, h=1):
    rets = [math.log(b / a) for a, b in zip(last21_vix, last21_vix[1:])]
    w = Z80 * K_VIX * rv20(rets) * math.sqrt(h)
    return {"lo": vix * math.exp(-w), "hi": vix * math.exp(w), "half_width_pct": 100 * (math.exp(w) - 1)}


def backtest(hist=HIST):
    rows = aligned("SP500", "VIXCLS", "VXVCLS", hist=hist)
    res = {}
    for h in (1, 5):
        rec = []
        for j in range(21, len(rows) - h):
            r = spx_range(rows[j][1], rows[j][2], rows[j][3], [x[1] for x in rows[j - 20:j + 1]], h)
            c2 = rows[j + h][1]
            old = abs(math.log(c2 / rows[j][1])) <= Z80 * 1.6 * rows[j][2] / 100 / math.sqrt(252) * math.sqrt(h)
            rec.append((rows[j + h][0], r["storm"], r["lo"] <= c2 <= r["hi"], old))
        res[f"spx_h{h}"] = summarize(rec)
    v = load("VIXCLS", hist); d = sorted(v)
    vx = load("VXVCLS", hist)
    for h in (1, 5):
        rec = []
        for j in range(21, len(d) - h):
            b = vix_band(v[d[j]], [v[x] for x in d[j - 20:j + 1]], h)
            v2 = v[d[j + h]]
            st = v[d[j]] > 25 or (d[j] in vx and vx[d[j]] < v[d[j]])
            rec.append((d[j + h], st, b["lo"] <= v2 <= b["hi"], abs(v2 / v[d[j]] - 1) <= 0.25 * math.sqrt(h)))
        res[f"vix_h{h}"] = summarize(rec)
    last = rows[-1]
    res["today"] = {"date": last[0],
                    "spx": {k: r4(x) if isinstance(x, float) else x for k, x in spx_range(last[1], last[2], last[3], [x[1] for x in rows[-21:]]).items()},
                    "vix": {k: r4(x) for k, x in vix_band(v[d[-1]], [v[x] for x in d[-21:]]).items()}}
    return res


def summarize(rec):
    f = lambda s, i: r4(sum(r[i] for r in s) / len(s)) if s else None
    oos = [r for r in rec if r[0] >= SPLIT]
    part = lambda i: {"oos": f(oos, i), "calm": f([r for r in oos if not r[1]], i),
                      "storm": f([r for r in oos if r[1]], i), "last15": f(rec[-15:], i)}
    return {"n_oos": len(oos), "new": part(2), "old": part(3)}


def run(hist=HIST, out=OUT):
    res = backtest(hist)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ranges.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
