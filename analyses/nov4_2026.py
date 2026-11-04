"""Three what-if studies for 4 Nov 2026, run with marketsim.

Real-world inputs (from news reports on 4 Nov 2026):
  * S&P 500 up ~1.5% intraday after Democrats won Congress
  * Market prices ~77% odds of a 25bp Fed hike on 9 Dec (rate 3.75-4.00%)
  * Oil falling further on the election result

Everything else is an explicit assumption listed in ASSUMPTIONS. No real
price history was available in this environment (data hosts are blocked),
so prices are on an index (start = 100) and the TimesFM baseline is not used.

Run:  python analyses/nov4_2026.py [--runs 100]
Writes analyses/output/nov4_2026.json
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marketsim.analysis import _pct, trader_stats  # noqa: E402
from marketsim.engine import run_scenario  # noqa: E402
from marketsim.scenario import Scenario  # noqa: E402

TICKS_PER_DAY = 10
DAILY_VOL = 0.008  # assumption: ~0.8%/day fair-value volatility (calm large-cap index)
ASSUMPTIONS = {
    "ticks_per_trading_day": TICKS_PER_DAY,
    "fair_value_daily_vol": DAILY_VOL,
    "trader_mix": "bundled baseline population: 4 market makers, 5 institutions, 30 value investors, "
                  "25 trend followers, 15 mean reverters, 150 retail traders",
    "fed_outcome_probabilities": {"hike_25bp_as_expected": 0.75, "surprise_hold": 0.20, "surprise_hike_50bp": 0.05},
    "fed_outcome_sizes": "as-expected hike -0.5% fair value; hold +2.5%; 50bp hike -4.5%",
    "energy_shock": "-5% fair value; liquidity stress 0.6 for 5 days in the stressed variant",
}

BASE = json.loads((ROOT / "scenarios" / "baseline.json").read_text())


def scenario(name, ticks, events, vol=DAILY_VOL, population=None):
    d = copy.deepcopy(BASE)
    d.update(name=name, description=name, ticks=ticks, events=events)
    d["fundamental"] = {"vol": vol / TICKS_PER_DAY ** 0.5, "drift": 0.0}
    if population:
        for kind, count in population.items():
            d["population"][kind]["count"] = count
    return Scenario.from_dict(d)


def run_many(sc, runs, seed0=1000):
    return [run_scenario(sc, seed0 + i) for i in range(runs)]


def path_bands(runs):
    n = len(runs[0].series["price"])
    col = lambda i, k: [r.series[k][i] for r in runs]
    return {
        "p05": [_pct(col(i, "price"), 0.05) for i in range(n)],
        "p50": [_pct(col(i, "price"), 0.50) for i in range(n)],
        "p95": [_pct(col(i, "price"), 0.95) for i in range(n)],
        "fair_p50": [_pct(col(i, "fundamental"), 0.50) for i in range(n)],
    }


def horizon_stats(runs, t0, horizons_days, ref_tick=None):
    """Returns from the price just before t0 to each horizon."""
    out = {}
    for d in horizons_days:
        t = min(t0 + d * TICKS_PER_DAY, len(runs[0].series["price"]) - 1)
        rets = []
        for r in runs:
            before = r.series["price"][t0 - 1] if t0 > 0 else r.scenario.initial_price
            rets.append(r.series["price"][t] / before - 1)
        out[d] = {
            "median": statistics.median(rets), "p05": _pct(rets, 0.05), "p95": _pct(rets, 0.95),
            "prob_down": sum(x < 0 for x in rets) / len(rets),
        }
    return out


def worst_drawdown_after(runs, t0, days):
    vals = []
    for r in runs:
        before = r.series["price"][t0 - 1] if t0 > 0 else r.scenario.initial_price
        window = r.series["price"][t0: t0 + days * TICKS_PER_DAY + 1]
        vals.append(min(window) / before - 1)
    return {"median": statistics.median(vals), "p05": _pct(vals, 0.05)}


def overshoot(runs, t0, days):
    """Lowest price relative to the *new* fair value in the window (negative = overshoot)."""
    vals = []
    for r in runs:
        lo = min(range(t0, t0 + days * TICKS_PER_DAY), key=lambda t: r.series["price"][t] / r.series["fundamental"][t])
        vals.append(r.series["price"][lo] / r.series["fundamental"][lo] - 1)
    return {"median": statistics.median(vals), "p05": _pct(vals, 0.05)}


def traders(runs):
    acc = {}
    for r in runs:
        for row in trader_stats(r):
            acc.setdefault(row["label"], []).append(row["return"])
    return {k: {"median": statistics.median(v), "p05": _pct(v, 0.05), "p95": _pct(v, 0.95)} for k, v in acc.items()}


def study_election(n):
    ticks, t0 = 30 * TICKS_PER_DAY, 10
    variants = {
        "real": ("Value re-rated: fair value +1.5%, mood +0.6",
                 [{"tick": t0, "headline": "Democrats win Congress; oil falls", "fundamental_change": 0.015, "sentiment": 0.6}]),
        "mood": ("Mood only: fair value unchanged, mood +0.6",
                 [{"tick": t0, "headline": "Democrats win Congress; oil falls", "sentiment": 0.6}]),
    }
    out = {}
    for key, (label, events) in variants.items():
        runs = run_many(scenario(f"election_{key}", ticks, events), n)
        out[key] = {
            "label": label,
            "returns": horizon_stats(runs, t0, (1, 5, 20)),
            "bands": path_bands(runs),
            "traders": traders(runs),
            "events": [{"tick": t0, "headline": events[0]["headline"]}],
        }
    return out


def study_fed(n):
    ticks, t0 = 40 * TICKS_PER_DAY, 24 * TICKS_PER_DAY  # ~24 trading days from 4 Nov to 9 Dec
    head = "9 Dec FOMC decision"
    outcomes = {
        "hike_25bp_as_expected": ("25bp hike, as priced", {"fundamental_change": -0.005, "sentiment": -0.1}),
        "surprise_hold": ("Surprise hold", {"fundamental_change": 0.025, "sentiment": 0.5}),
        "surprise_hike_50bp": ("Surprise 50bp hike", {"fundamental_change": -0.045, "sentiment": -0.7,
                                                       "fundamental_vol": 3 * DAILY_VOL / TICKS_PER_DAY ** 0.5,
                                                       "duration": 5 * TICKS_PER_DAY}),
    }
    probs = ASSUMPTIONS["fed_outcome_probabilities"]
    out, mixture = {}, []
    for key, (label, ev) in outcomes.items():
        runs = run_many(scenario(f"fed_{key}", ticks, [{"tick": t0, "headline": f"{head}: {label}", **ev}]), n)
        hs = horizon_stats(runs, t0, (1, 5, 15))
        out[key] = {"label": label, "probability": probs[key], "returns": hs,
                    "worst_15d": worst_drawdown_after(runs, t0, 15), "bands": path_bands(runs)}
        k = round(probs[key] * n)  # probability-weighted sample for the blended view
        for r in runs[:k]:
            mixture.append(r.series["price"][t0 + 5 * TICKS_PER_DAY] / r.series["price"][t0 - 1] - 1)
    out["blended_5d"] = {
        "median": statistics.median(mixture), "p05": _pct(mixture, 0.05), "p95": _pct(mixture, 0.95),
        "mean": statistics.mean(mixture), "prob_down_2pct": sum(x < -0.02 for x in mixture) / len(mixture),
        "samples": len(mixture),
    }
    out["event_tick"] = t0
    return out


def study_energy(n):
    ticks, t0 = 30 * TICKS_PER_DAY, 5 * TICKS_PER_DAY
    head = "Oil slides further; energy earnings outlook cut"
    base_ev = {"tick": t0, "headline": head, "fundamental_change": -0.05, "sentiment": -0.6,
               "fundamental_vol": 1.5 * 0.015 / TICKS_PER_DAY ** 0.5, "duration": 10 * TICKS_PER_DAY}
    variants = {
        "normal": ("Liquidity normal", [base_ev]),
        "stressed": ("Market makers pull back (stress 0.6, 5 days)",
                     [dict(base_ev, mm_stress=0.6, duration=5 * TICKS_PER_DAY)]),
    }
    out = {}
    for key, (label, events) in variants.items():
        runs = run_many(scenario(f"energy_{key}", ticks, events, vol=0.015), n)
        spreads = [statistics.mean([x for x in r.series["spread_bps"][t0:t0 + 5 * TICKS_PER_DAY] if x] or [0]) for r in runs]
        out[key] = {
            "label": label,
            "returns": horizon_stats(runs, t0, (1, 5, 20)),
            "worst_10d": worst_drawdown_after(runs, t0, 10),
            "overshoot_10d": overshoot(runs, t0, 10),
            "spread_bps_first_5d": statistics.median(spreads),
            "bands": path_bands(runs),
            "traders": traders(runs),
            "panic_sells": statistics.median(sum(getattr(a, "panics", 0) for a in r.agents) for r in runs),
        }
    out["event_tick"] = t0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    args = ap.parse_args()
    result = {"date": "2026-11-04", "runs_per_variant": args.runs, "assumptions": ASSUMPTIONS}
    for name, fn in (("election", study_election), ("fed", study_fed), ("energy", study_energy)):
        print(f"running {name}...", file=sys.stderr)
        result[name] = fn(args.runs)
    out = ROOT / "analyses" / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "nov4_2026.json").write_text(json.dumps(result, indent=1))
    print(f"wrote {out / 'nov4_2026.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
