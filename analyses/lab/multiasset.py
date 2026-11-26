"""Multi-asset board (upgrade 3): the same daily call on many markets, graded automatically.

For each market, each run makes two calls from data known at the last close:
  * up/down: P(next value > last value), the market's own long-run up-rate (honest baseline)
  * 80% range for the next value, sized from recent behaviour (EWMA vol x a width fitted
    on the first half of history and checked on the second half)
Calls are appended to analyses/data/calls/calls.jsonl and graded once the backbone has
the answer. Many markets means many graded calls a day, so skill (or the lack of it)
shows up in weeks instead of years. Not investment advice; analysis only.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.backbone.history import load, HIST  # noqa: E402
from analyses.lab.core import Z80, ewma_vol, rate, wilson, brier, r4  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CALLS = ROOT / "analyses" / "data" / "calls" / "calls.jsonl"
OUT = ROOT / "analyses" / "output" / "lab"

# id: (label, kind) kind "log" = % moves, "diff" = level changes (yields, spreads)
ASSETS = {
    "SP500": ("S&P 500", "log"),
    "NASDAQCOM": ("Nasdaq Composite", "log"),
    "DJIA": ("Dow Jones", "log"),
    "VIXCLS": ("VIX", "log"),
    "DGS10": ("10-year yield", "diff"),
    "DGS2": ("2-year yield", "diff"),
    "BAMLH0A0HYM2": ("High-yield spread", "diff"),
    "DCOILWTICO": ("WTI oil", "log"),
    "DEXCAUS": ("CAD per USD", "log"),
    "DTWEXBGS": ("Broad dollar", "log"),
}


def moves(vals, kind):
    if kind == "log":
        return [math.log(vals[i + 1] / vals[i]) for i in range(len(vals) - 1) if vals[i] > 0 and vals[i + 1] > 0]
    return [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]


def study(sid, kind, hist=HIST):
    s = load(sid, hist)
    days = sorted(s)
    vals = [s[d] for d in days]
    m = moves(vals, kind)
    ew = ewma_vol(m)
    zs = [m[j] / ew[j - 1] for j in range(21, len(m)) if ew[j - 1] > 0]
    half = len(zs) // 2
    first = sorted(abs(z) for z in zs[:half])
    k = first[int(0.8 * (len(first) - 1))] / Z80
    test = [abs(z) <= Z80 * k for z in zs[half:]]
    ups = [x > 0 for x in m]
    return {"sid": sid, "n": len(m), "first": days[0], "last": days[-1], "k": r4(k),
            "band_hit_test": r4(rate(test)), "band_ci95": wilson(sum(test), len(test)),
            "up_rate": r4(rate(ups)), "last_value": vals[-1], "sigma_now": ew[-1], "kind": kind}


def make_calls(stats, made_at):
    calls = []
    for sid, st in stats.items():
        v, sig, k = st["last_value"], st["sigma_now"], st["k"]
        if st["kind"] == "log":
            lo, hi = v * math.exp(-Z80 * k * sig), v * math.exp(Z80 * k * sig)
        else:
            lo, hi = v - Z80 * k * sig, v + Z80 * k * sig
        calls.append({"id": f"{st['last']}_{sid}", "asset": sid, "label": ASSETS[sid][0], "asof": st["last"],
                      "made_at": made_at, "h": 1, "value0": v, "p_up": st["up_rate"],
                      "lo": round(lo, 4), "hi": round(hi, 4), "status": "open"})
    return calls


def read_calls(path=CALLS):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def grade(calls, hist=HIST):
    cache = {}
    for c in calls:
        if c["status"] != "open":
            continue
        s = cache.setdefault(c["asset"], load(c["asset"], hist))
        later = sorted(d for d in s if d > c["asof"])
        if len(later) < c["h"]:
            continue
        d = later[c["h"] - 1]
        v = s[d]
        c.update(status="graded", resolved=d, value1=v, up=int(v > c["value0"]),
                 in_band=int(c["lo"] <= v <= c["hi"]))
    return calls


def summary(calls):
    g = [c for c in calls if c["status"] == "graded"]
    by = {}
    for c in g:
        by.setdefault(c["asset"], []).append(c)
    per = {a: {"n": len(x), "band_hit": r4(rate(c["in_band"] for c in x)),
               "brier": r4(brier((c["p_up"], c["up"]) for c in x))} for a, x in by.items()}
    return {"graded": len(g), "open": sum(c["status"] == "open" for c in calls),
            "band_hit": r4(rate(c["in_band"] for c in g)) if g else None,
            "brier": r4(brier((c["p_up"], c["up"]) for c in g)) if g else None, "per_asset": per}


def run(hist=HIST, calls_path=CALLS, out=OUT, made_at=None):
    from datetime import datetime, timezone
    made_at = made_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = {sid: study(sid, kind, hist) for sid, (_, kind) in ASSETS.items()}
    calls = grade(read_calls(calls_path), hist)
    have = {c["id"] for c in calls}
    new = [c for c in make_calls(stats, made_at) if c["id"] not in have]
    calls += new
    calls_path.parent.mkdir(parents=True, exist_ok=True)
    calls_path.write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in calls))
    res = {"made_at": made_at, "assets": {sid: dict(st, label=ASSETS[sid][0]) for sid, st in stats.items()},
           "today": [c for c in calls if c["status"] == "open"], "record": summary(calls),
           "recent_graded": [c for c in calls if c["status"] == "graded"][-40:]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "multiasset.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    r = run()
    for sid, st in r["assets"].items():
        print(f"{st['label']:18s} last={st['last']} band k={st['k']} test hit={st['band_hit_test']} up-rate={st['up_rate']}")
    print("open calls:", len(r["today"]), "record:", r["record"])
