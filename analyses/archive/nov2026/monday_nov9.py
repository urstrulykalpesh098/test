"""Monday 9 Nov 2026: one simulated session, minute by minute.

Built from the user's own reports ("The Week the AI Trade Broke", "Weekend
Update 7 Nov", "5 Nov Adversarial Briefing") plus real S&P 500 closes from
FMP (analyses/data/spx_daily.csv).

Real anchors
  * Friday close 7,376.86; Thursday close 7,353.73 (session low 7,350.35)
  * 200-day average 7,325 (computed from the CSV; the reports say ~7,323)
  * VIX 25.64  -> implied ~1.6% daily move
  * Pending forced flow: vol-target funds still de-risking (briefing: "3-15 days, still ahead of us")
  * Leveraged ETFs rebalance into the close in the direction of the day's move
  * Tuesday: October CPI (8:30am) + CoreWeave Q3 after the close -> Monday is pre-event positioning

Three branches for Monday's news flow, each run many times, plus a
counterfactual with the forced-flow traders removed to measure their effect.

Run:  python analyses/monday_nov9.py [--runs 120]
Out:  analyses/output/monday_nov9.json  (feeds the replay UI)
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marketsim.agents import AGENT_TYPES  # noqa: E402
from marketsim.analysis import _pct  # noqa: E402
from marketsim.engine import run_scenario  # noqa: E402
from marketsim.scenario import Scenario  # noqa: E402

DAY = 390                     # one tick = one minute, 9:30-16:00 ET
FRIDAY_CLOSE = 7376.86
THURSDAY_LOW = 7350.35
VIX = 25.64
SCALE = FRIDAY_CLOSE / 100.0  # simulation runs on an index where Friday's close = 100

closes = [float(r["close"]) for r in csv.DictReader(open(ROOT / "analyses" / "data" / "spx_daily.csv"))]
MA200 = sum(closes[-200:]) / 200
MA50 = sum(closes[-50:]) / 50
DAILY_IMPLIED = VIX / 100 / math.sqrt(252)
rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
DAILY_REALISED_20 = statistics.stdev(rets[-20:])

KEY_LEVELS = {
    "Friday close": FRIDAY_CLOSE,
    "Thursday low": THURSDAY_LOW,
    "200-day average": round(MA200, 2),
}

# Calibrated for a deep index market: tight quotes, value buyers who step in
# within a fraction of a percent, and position limits symmetric around each
# group's starting holdings so no group has a built-in buy or sell bias.
POPULATION = {
    "market_maker":   {"count": 6,   "cash": 3_000_000, "shares": 0,
                       "params": {"half_spread": 0.0003, "vol_mult": 0.3, "max_half_spread": 0.004,
                                  "level_step": 0.0004, "quote_size": 400, "levels": 4,
                                  "max_position": 8000, "max_short": 8000, "skew": 0.002}},
    "dealer_gamma":   {"count": 2,   "cash": 2_000_000, "shares": 0,
                       "params": {"gamma": 120, "max_position": 2500, "max_short": 2500,
                                  "rehedge_threshold": 40, "max_order": 150, "day_ticks": DAY}},
    "institutional":  {"count": 5,   "cash": 2_000_000, "shares": 10_000,
                       "params": {"activity": 0.15, "threshold": 0.006, "conviction_gap": 0.04,
                                  "urgent_gap": 0.02}},
    "fundamentalist": {"count": 30,  "cash": 100_000,   "shares": 500,
                       "params": {"activity": 0.06, "info_lag": 15, "threshold": 0.004,
                                  "conviction_gap": 0.03, "urgent_gap": 0.015, "info_noise": 0.004,
                                  "bias_sd": 0.004}},
    "vol_target":     {"count": 3,   "cash": 200_000,   "shares": 15_000,
                       "params": {"target_fraction": 0.9, "max_order": 40, "day_ticks": DAY}},
    "leveraged_etf":  {"count": 1,   "cash": -800_000,  "shares": 12_000,
                       "params": {"leverage": 3.0, "rebalance_window": 20, "day_ticks": DAY}},
    "momentum":       {"count": 25,  "cash": 100_000,   "shares": 0,
                       "params": {"activity": 0.08, "sensitivity": 0.003, "max_position": 400,
                                  "max_short": 400, "max_order": 40}},
    "mean_reversion": {"count": 15,  "cash": 100_000,   "shares": 0,
                       "params": {"activity": 0.1}},
    "retail":         {"count": 150, "cash": 20_000,    "shares": 100,
                       "params": {"activity": 0.03, "max_position": 200, "info_noise": 0.01,
                                  "chase": 4.0, "value_weight": 1.0}},
}

# Who they are in the real market (shown in the UI)
WHO = {
    "market_maker": "Bank market-making desks and electronic wholesalers quoting both sides",
    "dealer_gamma": "Bank options desks hedging the puts customers bought after Thursday",
    "institutional": "Pensions, mutual funds and asset managers",
    "fundamentalist": "Value-focused active managers",
    "vol_target": "Risk-parity and volatility-control funds",
    "leveraged_etf": "3x index and chip ETFs (SOXL-style) rebalancing daily",
    "momentum": "CTAs and trend followers",
    "mean_reversion": "Short-term statistical-arbitrage desks",
    "retail": "Individual investors via brokerage apps",
}

BRANCHES = {
    "grind": {
        "title": "Quiet grind before CPI",
        "story": "No new shock over the weekend. The market waits for Tuesday's CPI and CoreWeave, "
                 "while vol-target funds keep working off the selling that Thursday's spike triggered.",
        "tells": "Futures within ±0.3% on Sunday night; Asia steady; VIX opens 24–26.",
        "events": [
            {"tick": 0, "headline": "Open: no fresh weekend shock; CPI and CoreWeave on Tuesday", "sentiment": -0.15},
            {"tick": 240, "headline": "13:30 — positioning lightens ahead of CPI", "sentiment": -0.1},
        ],
        "overrides": {},
    },
    "contagion": {
        "title": "AI-credit stress spreads",
        "story": "CoreWeave's weekend letter and record-low stock are read as capitulation. GPU-backed "
                 "credit headlines spread at the open, and a second leg arrives mid-afternoon.",
        "tells": "Futures −0.8% or worse on Sunday night; Korea and Japan down again; VIX above 28 at the open.",
        "events": [
            {"tick": 0, "headline": "Open: AI-credit worries spread after CoreWeave's weekend letter",
             "fundamental_change": -0.012, "sentiment": -0.5, "mm_stress": 0.3, "duration": 60},
            {"tick": 280, "headline": "14:10 — report of a GPU-backed loan repriced wider",
             "fundamental_change": -0.006, "sentiment": -0.4, "mm_stress": 0.25, "duration": 40},
        ],
        "overrides": {"dealer_gamma": {"gamma": 220}, "vol_target": {"target_fraction": 0.8}},
    },
    "relief": {
        "title": "Friday's bounce extends",
        "story": "Friday's late chip rally (+4.21%) carries over, oil-peace hopes hold and the vol "
                 "funds have already done much of their selling. Dealers are less short gamma.",
        "tells": "Futures +0.5% or better; chips higher in Asia; VIX opens below 24.",
        "events": [
            {"tick": 0, "headline": "Open: chips extend Friday's bounce, oil-peace hopes hold",
             "fundamental_change": 0.008, "sentiment": 0.4},
        ],
        "overrides": {"dealer_gamma": {"gamma": 50}, "vol_target": {"target_fraction": 0.93}},
    },
}

FORCED = ("dealer_gamma", "vol_target", "leveraged_etf")


def build(branch: str, forced: bool = True) -> Scenario:
    b = BRANCHES[branch]
    pop = copy.deepcopy(POPULATION)
    for kind, params in b["overrides"].items():
        pop[kind]["params"].update(params)
    if not forced:
        for kind in FORCED:
            pop[kind]["count"] = 0
    return Scenario.from_dict({
        "name": f"monday_{branch}", "description": b["story"], "ticks": DAY,
        "initial_price": 100.0,
        "fundamental": {"vol": DAILY_IMPLIED / math.sqrt(DAY), "drift": 0.0},
        "sentiment": {"decay": 0.995, "feedback": 8.0},
        "population": pop, "events": b["events"],
    })


def to_spx(x: float) -> float:
    return round(x * SCALE, 2)


def stats_for(runs):
    closes = [r.series["price"][-1] * SCALE for r in runs]
    lows = [min(r.series["price"]) * SCALE for r in runs]
    highs = [max(r.series["price"]) * SCALE for r in runs]
    last30 = [r.series["price"][-1] / r.series["price"][-31] - 1 for r in runs]
    q = lambda xs, p: round(_pct(xs, p), 2)
    return {
        "close": {p: q(closes, p) for p in (0.05, 0.25, 0.5, 0.75, 0.95)},
        "close_return_median": statistics.median(c / FRIDAY_CLOSE - 1 for c in closes),
        "low": {p: q(lows, p) for p in (0.05, 0.5)},
        "high": {p: q(highs, p) for p in (0.5, 0.95)},
        "range_median_pct": statistics.median((h - l) / FRIDAY_CLOSE for h, l in zip(highs, lows)),
        "p_close_below_200d": sum(c < MA200 for c in closes) / len(closes),
        "p_trade_below_200d": sum(l < MA200 for l in lows) / len(lows),
        "p_close_below_thu_low": sum(c < THURSDAY_LOW for c in closes) / len(closes),
        "p_close_up": sum(c > FRIDAY_CLOSE for c in closes) / len(closes),
        "last30_median": statistics.median(last30),
        "closes": [round(c, 1) for c in closes],
    }


def group_summary(runs):
    """Per trader group: net buying as % of the day's volume, and return on the group's capital."""
    out = {}
    for kind in runs[0].flows:
        share, ret = [], []
        for r in runs:
            vol = sum(r.series["volume"]) or 1
            share.append(sum(r.flows[kind]) / vol)
            agents = [a for a in r.agents if a.kind == kind]
            start = sum(a.initial_wealth(100.0) for a in agents)
            end = sum(a.wealth(r.final_price) for a in agents)
            ret.append(end / start - 1 if start > 0 else 0.0)
        out[kind] = {
            "net_pct_volume": statistics.median(share),
            "return_median": statistics.median(ret),
            "return_p05": _pct(ret, 0.05),
            "return_p95": _pct(ret, 0.95),
        }
    return out


def bands(runs):
    n = len(runs[0].series["price"])
    res = {}
    for p in (0.05, 0.25, 0.5, 0.75, 0.95):
        res[str(p)] = [to_spx(_pct([r.series["price"][i] for r in runs], p)) for i in range(n)]
    return res


def replay(run, forced_counterfactual_close):
    s = run.series
    events = [{"t": e["tick"], "headline": e["headline"]} for e in run.events]
    # derive narrative markers from the run itself
    price = [to_spx(x) for x in s["price"]]
    crossed = next((i for i, p in enumerate(price) if p < MA200), None)
    if crossed is not None:
        events.append({"t": crossed, "headline": f"Index trades below the 200-day average ({MA200:,.0f})", "auto": True})
    flows = {k: v for k, v in run.flows.items()}
    vt = flows.get("vol_target")
    if vt:
        total = sum(vt)
        if total < 0:
            cum, half = 0, None
            for i, x in enumerate(vt):
                cum += x
                if cum <= total / 2:
                    half = i
                    break
            if half is not None:
                events.append({"t": half, "headline": "Vol-target funds have done half of today's selling", "auto": True})
    le = flows.get("leveraged_etf")
    if le and any(le):
        first = next(i for i, x in enumerate(le) if x)
        direction = "buy" if sum(le) > 0 else "sell"
        events.append({"t": first, "headline": f"Leveraged ETFs start their closing rebalance ({direction})", "auto": True})
    events.sort(key=lambda e: e["t"])
    agents = {}
    for kind in flows:
        group = [a for a in run.agents if a.kind == kind]
        start = sum(a.initial_wealth(100.0) for a in group)
        end = sum(a.wealth(run.final_price) for a in group)
        agents[kind] = {"count": len(group), "return": (end / start - 1) if start > 0 else 0.0,
                        "net_pct_volume": sum(flows[kind]) / (sum(s["volume"]) or 1)}
    return {
        "seed": run.seed,
        "price": price,
        "fair": [to_spx(x) for x in s["fundamental"]],
        "volume": s["volume"],
        "spread_bps": [round(x, 1) if x else None for x in s["spread_bps"]],
        "sentiment": [round(x, 3) for x in s["sentiment"]],
        "flows": flows,
        "events": events,
        "agents": agents,
        "close_without_forced": forced_counterfactual_close,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=120)
    args = ap.parse_args()
    out = {
        "meta": {
            "date": "2026-11-09", "runs_per_branch": args.runs, "minutes": DAY,
            "friday_close": FRIDAY_CLOSE, "thursday_low": THURSDAY_LOW, "ma200": round(MA200, 2),
            "ma50": round(MA50, 2), "vix": VIX, "implied_daily": DAILY_IMPLIED,
            "realised_daily_20d": DAILY_REALISED_20, "levels": KEY_LEVELS,
            "population": {k: {"count": v["count"], "label": AGENT_TYPES[k].label, "who": WHO[k],
                               "does": AGENT_TYPES[k].description} for k, v in POPULATION.items()},
            "history": [{"date": d["date"], "close": float(d["close"])}
                        for d in list(csv.DictReader(open(ROOT / "analyses" / "data" / "spx_daily.csv")))[-30:]],
        },
        "branches": {},
    }
    for key, b in BRANCHES.items():
        print(f"{key}: forced flows on", file=sys.stderr)
        runs = [run_scenario(build(key, True), 5000 + i) for i in range(args.runs)]
        print(f"{key}: forced flows off", file=sys.stderr)
        base = [run_scenario(build(key, False), 5000 + i) for i in range(args.runs)]
        st, st0 = stats_for(runs), stats_for(base)
        # representative replay: the run whose close is nearest the median
        med = st["close"][0.5]
        pick = min(range(len(runs)), key=lambda i: abs(runs[i].series["price"][-1] * SCALE - med))
        out["branches"][key] = {
            "title": b["title"], "story": b["story"], "tells": b["tells"],
            "stats": st, "stats_without_forced": st0,
            "forced_effect_median": st["close_return_median"] - st0["close_return_median"],
            "groups": group_summary(runs),
            "bands": bands(runs),
            "replay": replay(runs[pick], round(base[pick].series["price"][-1] * SCALE, 2)),
        }
    dest = ROOT / "analyses" / "output" / "monday_nov9.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {dest} ({dest.stat().st_size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
