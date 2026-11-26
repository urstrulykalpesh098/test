"""Eye View backtest lab: test the desk's rules on years of free history.

Reads analyses/data/history (run analyses/backbone/pull.py first). Writes
analyses/output/lab/lab_results.json. Every study uses only information known
at the time of the call. Not investment advice; analysis only.

Studies
  spx_bands    80% S&P ranges sized at k x the VIX-implied move (rule 5 uses k=1.6)
  vix_bands    80% VIX bands at +/-25% x sqrt(days) (rule 5)
  formula      how the zero-drift VIX formula's tails compare with reality
  vol_premium  VIX vs the volatility that actually followed
  falling_tape P(up) after a falling week vs normal (lesson L4)
  term         VIX 3-month / VIX ratio: inverted curve vs calm curve
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.backbone.history import aligned, load, HIST  # noqa: E402
from analyses.lab.core import Z80, ncdf, rate, wilson, quantiles, vix_bucket, r4  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "lab"


def spx_vix(hist=HIST):
    return aligned("SP500", "VIXCLS", hist=hist)


def spx_bands(rows, ks=(1.0, 1.2, 1.4, 1.6, 1.8, 2.0), hs=(1, 5), split=None):
    """Hit rate of an 80% band = close x exp(+/- Z80 k sigma_h), sigma_h = VIX/100 sqrt(h/252)."""
    out = {}
    for h in hs:
        zs, buckets = [], {}
        for i in range(len(rows) - h):
            d, c, v = rows[i]
            if split and not (split[0] <= d < split[1]):
                continue
            c2 = rows[i + h][1]
            z = math.log(c2 / c) / (v / 100 * math.sqrt(h / 252))
            zs.append(z)
            buckets.setdefault(vix_bucket(v), []).append(z)
        res = {"n": len(zs), "by_k": {}}
        for k in ks:
            hits = sum(abs(z) <= Z80 * k for z in zs)
            res["by_k"][str(k)] = {"hit": r4(hits / len(zs)), "ci95": wilson(hits, len(zs))}
        # width multiple that would have held exactly 80%
        az = sorted(abs(z) for z in zs)
        res["k_for_80"] = r4(az[int(0.8 * (len(az) - 1))] / Z80)
        res["by_vix_at_1.6"] = {b: {"n": len(v), "hit": r4(rate(abs(z) <= Z80 * 1.6 for z in v)),
                                    "k_for_80": r4(sorted(abs(z) for z in v)[int(0.8 * (len(v) - 1))] / Z80)}
                                for b, v in sorted(buckets.items())}
        out[f"h{h}"] = res
    return out


def vix_bands(vix, widths=(0.10, 0.15, 0.20, 0.25, 0.30), hs=(1, 5)):
    days = sorted(vix)
    out = {}
    for h in hs:
        moves, buckets = [], {}
        for i in range(len(days) - h):
            v0, v1 = vix[days[i]], vix[days[i + h]]
            m = abs(v1 / v0 - 1) / math.sqrt(h)
            moves.append(m)
            buckets.setdefault(vix_bucket(v0), []).append(m)
        res = {"n": len(moves), "by_width": {}}
        for w in widths:
            k = sum(m <= w for m in moves)
            res["by_width"][str(w)] = {"hit": r4(k / len(moves)), "ci95": wilson(k, len(moves))}
        s = sorted(moves)
        res["width_for_80"] = r4(s[int(0.8 * (len(s) - 1))])
        res["by_vix_at_0.25"] = {b: {"n": len(v), "hit": r4(rate(m <= 0.25 for m in v)),
                                     "width_for_80": r4(sorted(v)[int(0.8 * (len(v) - 1))])}
                                 for b, v in sorted(buckets.items())}
        out[f"h{h}"] = res
    return out


def formula(rows):
    """Standardised 1-day S&P moves under the VIX formula vs a normal curve."""
    zs = [math.log(rows[i + 1][1] / rows[i][1]) / (rows[i][2] / 100 / math.sqrt(252)) for i in range(len(rows) - 1)]
    n = len(zs)
    tails = {}
    for t in (1.0, 2.0, 3.0):
        tails[str(t)] = {"actual": r4(rate(abs(z) > t for z in zs)), "normal": r4(2 * (1 - ncdf(t)))}
    up = rate(z > 0 for z in zs)
    return {"n": n, "std_of_z": r4(math.sqrt(sum(z * z for z in zs) / n)), "tails": tails,
            "up_rate": r4(up), "up_ci95": wilson(sum(z > 0 for z in zs), n),
            "note": "std_of_z below 1 means VIX usually over-prices the next day; fat tails mean the misses are big when they come."}


def vol_premium(rows, h=21):
    gaps, over = [], 0
    for i in range(len(rows) - h):
        rets = [math.log(rows[j + 1][1] / rows[j][1]) for j in range(i, i + h)]
        rv = math.sqrt(sum(r * r for r in rets) / h * 252) * 100
        gaps.append(rows[i][2] - rv)
        over += rows[i][2] > rv
    return {"n": len(gaps), "vix_above_realized": r4(over / len(gaps)), "gap_quantiles": {k: r4(v) for k, v in quantiles(gaps).items()},
            "note": "Gap = VIX minus the realized vol of the next 21 trading days, in vol points."}


def falling_tape(rows, drop=-0.02):
    base1 = [rows[i + 1][1] > rows[i][1] for i in range(5, len(rows) - 1)]
    cond1, cond5 = [], []
    for i in range(5, len(rows) - 5):
        if rows[i][1] / rows[i - 5][1] - 1 <= drop:
            cond1.append(rows[i + 1][1] > rows[i][1])
            cond5.append(rows[i + 5][1] > rows[i][1])
    base5 = [rows[i + 5][1] > rows[i][1] for i in range(5, len(rows) - 5)]
    return {"drop": drop, "n_cond": len(cond1),
            "p_up_1d_after": r4(rate(cond1)), "ci95_1d": wilson(sum(cond1), len(cond1)), "p_up_1d_all": r4(rate(base1)),
            "p_up_5d_after": r4(rate(cond5)), "ci95_5d": wilson(sum(cond5), len(cond5)), "p_up_5d_all": r4(rate(base5))}


def term(hist=HIST, h=5):
    rows = aligned("SP500", "VIXCLS", "VXVCLS", hist=hist)
    groups = {"inverted (VIX3M < VIX)": [], "flat (1.00-1.10)": [], "calm (>1.10)": []}
    for i in range(len(rows) - h):
        d, c, v, vx = rows[i]
        ratio = vx / v
        g = "inverted (VIX3M < VIX)" if ratio < 1 else "flat (1.00-1.10)" if ratio < 1.10 else "calm (>1.10)"
        rets = [math.log(rows[j + 1][1] / rows[j][1]) for j in range(i, i + h)]
        rv = math.sqrt(sum(r * r for r in rets) / h * 252) * 100
        groups[g].append((rows[i + h][1] / c - 1, rv / v))
    out = {}
    for g, xs in groups.items():
        if not xs:
            continue
        out[g] = {"n": len(xs), "p_up_5d": r4(rate(r > 0 for r, _ in xs)),
                  "median_5d_ret": r4(sorted(r for r, _ in xs)[len(xs) // 2]),
                  "realized_over_vix_median": r4(sorted(q for _, q in xs)[len(xs) // 2])}
    last = rows[-1]
    out["today"] = {"date": last[0], "vix": last[2], "vix3m": last[3], "ratio": r4(last[3] / last[2])}
    return out


def adaptive_bands(rows, vix, lam=0.94, recent=15):
    """Bands from recent behaviour instead of a fixed multiple.
    S&P: sigma = 0.5 x VIX-implied + 0.5 x EWMA realized, width k chosen on the first half,
    tested on the second half and on the last `recent` days. VIX: EWMA of VIX log changes."""
    from analyses.lab.core import ewma_vol
    out = {}
    rets = [math.log(rows[i + 1][1] / rows[i][1]) for i in range(len(rows) - 1)]
    ew = ewma_vol(rets, lam)  # ew[i] = vol known after return i (close i+1)
    zs = []  # z for move from close j to j+1, using info at close j
    for j in range(21, len(rows) - 1):
        sig = 0.5 * rows[j][2] / 100 / math.sqrt(252) + 0.5 * ew[j - 1]
        zs.append((rows[j + 1][0], math.log(rows[j + 1][1] / rows[j][1]) / sig))
    half = len(zs) // 2
    first = sorted(abs(z) for _, z in zs[:half])
    k = first[int(0.8 * (len(first) - 1))] / Z80
    test = [abs(z) <= Z80 * k for _, z in zs[half:]]
    last = [abs(z) <= Z80 * k for _, z in zs[-recent:]]
    fixed_last = []
    for j in range(len(rows) - 1 - recent, len(rows) - 1):
        s1 = rows[j][2] / 100 / math.sqrt(252)
        fixed_last.append(abs(math.log(rows[j + 1][1] / rows[j][1])) <= Z80 * 1.6 * s1)
    out["spx"] = {"k_fit_first_half": r4(k), "hit_second_half": r4(rate(test)), "n_test": len(test),
                  "ci95": wilson(sum(test), len(test)), "hit_last_days": r4(rate(last)), "last_days": recent,
                  "fixed_1.6x_hit_last_days": r4(rate(fixed_last)),
                  "fixed_1.6x_hit_10y": None}
    days = sorted(vix)
    vr = [math.log(vix[days[i + 1]] / vix[days[i]]) for i in range(len(days) - 1)]
    vew = ewma_vol(vr, lam)
    vz = [(days[j + 1], vr[j] / vew[j - 1]) for j in range(21, len(vr))]
    half = len(vz) // 2
    first = sorted(abs(z) for _, z in vz[:half])
    kv = first[int(0.8 * (len(first) - 1))] / Z80
    test = [abs(z) <= Z80 * kv for _, z in vz[half:]]
    last = [abs(z) <= Z80 * kv for _, z in vz[-recent:]]
    fixed_last = [abs(vix[days[i + 1]] / vix[days[i]] - 1) <= 0.25 for i in range(len(days) - 1 - recent, len(days) - 1)]
    tw = Z80 * kv * vew[-1]
    out["vix"] = {"k_fit_first_half": r4(kv), "hit_second_half": r4(rate(test)), "n_test": len(test),
                  "ci95": wilson(sum(test), len(test)), "hit_last_days": r4(rate(last)), "last_days": recent,
                  "fixed_25pct_hit_last_days": r4(rate(fixed_last)),
                  "todays_1d_half_width_pct": r4(100 * (math.exp(tw) - 1))}
    sig_today = 0.5 * rows[-1][2] / 100 / math.sqrt(252) + 0.5 * ew[-1]
    out["spx"]["todays_1d_half_width_pct"] = r4(100 * (math.exp(Z80 * k * sig_today) - 1))
    out["spx"]["fixed_1.6x_today_half_width_pct"] = r4(100 * (math.exp(Z80 * 1.6 * rows[-1][2] / 100 / math.sqrt(252)) - 1))
    return out


def run(hist=HIST, out=OUT):
    rows = spx_vix(hist)
    vix = load("VIXCLS", hist)
    res = {
        "asof": rows[-1][0],
        "spx_days": len(rows), "spx_first": rows[0][0], "vix_days": len(vix), "vix_first": min(vix),
        "spx_bands": spx_bands(rows),
        "spx_bands_last_year": spx_bands(rows, split=(rows[-252][0], "9999")),
        "vix_bands": vix_bands(vix),
        "formula": formula(rows),
        "vol_premium": vol_premium(rows),
        "falling_tape": falling_tape(rows),
        "term": term(hist),
    }
    res["adaptive_bands"] = adaptive_bands(rows, vix)
    res["adaptive_bands"]["spx"]["fixed_1.6x_hit_10y"] = res["spx_bands"]["h1"]["by_k"]["1.6"]["hit"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "lab_results.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    r = run()
    b = r["spx_bands"]; v = r["vix_bands"]
    print("asof", r["asof"], "S&P days", r["spx_days"])
    print("S&P 1d 80% band hit at 1.6x:", b["h1"]["by_k"]["1.6"], "k for 80%:", b["h1"]["k_for_80"])
    print("S&P 5d hit at 1.6x:", b["h5"]["by_k"]["1.6"], "k for 80%:", b["h5"]["k_for_80"])
    print("last year 1d at 1.6x:", r["spx_bands_last_year"]["h1"]["by_k"]["1.6"])
    print("by VIX 1d:", b["h1"]["by_vix_at_1.6"])
    print("VIX 1d +/-25%:", v["h1"]["by_width"]["0.25"], "width for 80%:", v["h1"]["width_for_80"])
    print("VIX 5d +/-25%*sqrt5:", v["h5"]["by_width"]["0.25"], "width for 80%:", v["h5"]["width_for_80"])
    print("VIX by level 1d:", v["h1"]["by_vix_at_0.25"])
    print("formula:", r["formula"])
    print("vol premium:", r["vol_premium"])
    print("falling tape:", r["falling_tape"])
    print("term:", json.dumps(r["term"]))
    print("adaptive:", json.dumps(r["adaptive_bands"]))
