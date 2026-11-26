"""Desk of specialists (upgrade 4): each analyst looks at ONE kind of evidence and
says how likely the S&P is to close higher tomorrow (h=1) and in a week (h=5).

Each analyst is a one-feature logistic model refit every 63 trading days on past data
only (walk-forward), so every scored probability is out-of-sample. The desk blends
them with weights proportional to 1 / trailing Brier (same idea as method/notes rule 3).
The red team argues the opposite of the blend; if it ever scores better, the blend's
tilts are hurting. Not investment advice; analysis only.
Writes analyses/output/lab/analysts.json.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.backbone.history import load, asof, HIST  # noqa: E402
from analyses.lab.core import fit_logit, logit_p, brier, r4  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "lab"

ANALYSTS = {
    "trend": "Trend follower: 20-day S&P return. Rising markets tend to keep rising?",
    "bounce": "Bounce hunter: yesterday's move in VIX units. Big drops get bought?",
    "fear": "Fear gauge: VIX vs its 60-day average. Panic means opportunity?",
    "curve": "Vol curve: 3-month VIX / VIX. An inverted curve means stress.",
    "credit": "Credit watcher: 20-day change in high-yield spreads. Bonds lead stocks?",
    "rates": "Rates watcher: 20-day change in the 10-year yield.",
    "dollar": "Dollar watcher: 20-day change in the broad dollar.",
}


def features(hist=HIST):
    spx, vix = load("SP500", hist), load("VIXCLS", hist)
    vxv, hy, ty, usd = load("VXVCLS", hist), load("BAMLH0A0HYM2", hist), load("DGS10", hist), load("DTWEXBGS", hist)
    days = sorted(set(spx) & set(vix))
    rows = []
    for i in range(60, len(days)):
        d = days[i]
        c = spx[d]
        f = {
            "trend": math.log(c / spx[days[i - 20]]),
            "bounce": math.log(c / spx[days[i - 1]]) / (vix[days[i - 1]] / 100 / math.sqrt(252)),
            "fear": vix[d] / (sum(vix[x] for x in days[i - 60:i]) / 60) - 1,
        }
        if d in vxv:
            f["curve"] = vxv[d] / vix[d]
        for key, s, scale in (("credit", hy, 1.0), ("rates", ty, 1.0), ("dollar", usd, 0.01)):
            a, b = asof(s, d), asof(s, days[i - 20])
            if a is not None and b is not None and d >= min(s):
                f[key] = (a - b) if key != "dollar" else math.log(a / b)
        rows.append((i, d, c, f))
    return days, spx, rows


def walk_forward(days, spx, rows, h, refit=63, min_train=500):
    """Return list of (date, y, {analyst: p}) out-of-sample."""
    idx = {d: k for k, d in enumerate(days)}
    lab = [(d, f, (int(spx[days[idx[d] + h]] > c) if idx[d] + h < len(days) else None)) for _, d, c, f in rows]
    out, models, last_fit = [], {}, -10**9
    for t in range(len(lab)):
        d, f, y = lab[t]
        if t - last_fit >= refit and t >= min_train:
            train = lab[: max(0, t - h)]  # labels known by t
            models = {}
            for a in list(ANALYSTS) + ["base"]:
                xs, ys = [], []
                for _, ff, yy in train:
                    if yy is None:
                        continue
                    if a == "base":
                        xs.append(0.0); ys.append(yy)
                    elif a in ff:
                        xs.append(ff[a]); ys.append(yy)
                if len(xs) >= 250:
                    mu = sum(xs) / len(xs); sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5 or 1
                    a_, b_ = fit_logit([(x - mu) / sd for x in xs], ys)
                    models[a] = (a_, b_, mu, sd)
            last_fit = t
        if not models or y is None:
            continue
        ps = {}
        for a, (a_, b_, mu, sd) in models.items():
            x = 0.0 if a == "base" else f.get(a)
            if x is not None:
                ps[a] = logit_p(a_, b_, (x - mu) / sd)
        out.append((d, y, ps))
    return out


def blend(seq, window=250):
    """Add 'desk' (1/Brier weighted) and 'red_team' (mirror of the desk around base)."""
    hist = {}
    res = []
    for d, y, ps in seq:
        ws = {}
        for a, p in ps.items():
            past = hist.get(a, [])[-window:]
            if len(past) >= 60:
                ws[a] = 1 / brier(past)
        if ws:
            tot = sum(ws.values())
            desk = sum(ps[a] * w for a, w in ws.items()) / tot
        else:
            desk = sum(ps.values()) / len(ps)
        base = ps.get("base", 0.5)
        ps = dict(ps, desk=desk, red_team=min(0.99, max(0.01, 2 * base - desk)))
        for a, p in ps.items():
            hist.setdefault(a, []).append((p, y))
        res.append((d, y, ps, {a: r4(w / sum(ws.values())) for a, w in ws.items()} if ws else {}))
    return res


def score(res, since=None):
    table = {}
    for d, y, ps, _ in res:
        if since and d < since:
            continue
        for a, p in ps.items():
            table.setdefault(a, []).append((p, y))
    out = {}
    for a, pairs in table.items():
        b = brier(pairs)
        out[a] = {"n": len(pairs), "brier": r4(b), "avg_p": r4(sum(p for p, _ in pairs) / len(pairs)),
                  "hit": r4(sum((p > 0.5) == (y == 1) for p, y in pairs) / len(pairs))}
    return dict(sorted(out.items(), key=lambda kv: kv[1]["brier"]))


def run(hist=HIST, out=OUT):
    days, spx, rows = features(hist)
    result = {"asof": days[-1], "analysts": ANALYSTS, "horizons": {}}
    for h in (1, 5):
        res = blend(walk_forward(days, spx, rows, h))
        last = res[-1]
        result["horizons"][f"h{h}"] = {
            "all": score(res), "last_year": score(res, since=res[-252][0]),
            "latest_scored_day": last[0], "weights": last[3],
        }
    result["today"] = latest_calls(days, spx, rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysts.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def latest_calls(days, spx, rows):
    idx = {d: k for k, d in enumerate(days)}
    _, d, c, f = rows[-1]
    calls = {}
    for h in (1, 5):
        lab = [(ff, (int(spx[days[idx[dd] + h]] > cc) if idx[dd] + h < len(days) else None)) for _, dd, cc, ff in rows]
        ps = {}
        for a in list(ANALYSTS) + ["base"]:
            xs, ys = [], []
            for ff, yy in lab:
                if yy is None:
                    continue
                x = 0.0 if a == "base" else ff.get(a)
                if x is not None:
                    xs.append(x); ys.append(yy)
            x0 = 0.0 if a == "base" else f.get(a)
            if len(xs) < 250 or x0 is None:
                continue
            mu = sum(xs) / len(xs); sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5 or 1
            a_, b_ = fit_logit([(x - mu) / sd for x in xs], ys)
            ps[a] = {"p_up": r4(logit_p(a_, b_, (x0 - mu) / sd)), "reading": r4(x0), "z": r4((x0 - mu) / sd)}
        calls[f"h{h}"] = ps
    return {"date": d, "calls": calls}


if __name__ == "__main__":
    r = run()
    for h, v in r["horizons"].items():
        print(h, "all:", {a: (x["brier"], x["n"]) for a, x in v["all"].items()})
        print(h, "last year:", {a: x["brier"] for a, x in v["last_year"].items()})
        print(h, "weights:", v["weights"])
    print(json.dumps(r["today"], indent=0)[:1500])
