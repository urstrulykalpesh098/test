"""Statistics for single runs and Monte Carlo batches."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Dict, List

from .agents import AGENT_TYPES
from .engine import RunResult

EVENT_HORIZONS = (10, 50, 200)


def _max_drawdown(prices: List[float]) -> float:
    peak, worst = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        worst = min(worst, p / peak - 1)
    return worst


def market_stats(run: RunResult) -> Dict[str, float]:
    s = run.series
    prices, fundamentals = s["price"], s["fundamental"]
    p0 = run.scenario.initial_price
    rets = [math.log(b / a) for a, b in zip([p0] + prices, prices)]
    spreads = [x for x in s["spread_bps"] if x is not None]
    return {
        "initial_price": p0,
        "final_price": prices[-1],
        "final_fundamental": fundamentals[-1],
        "total_return": prices[-1] / p0 - 1,
        "fundamental_return": fundamentals[-1] / run.scenario.initial_fundamental - 1,
        "min_price": min(prices),
        "max_price": max(prices),
        "max_drawdown": _max_drawdown([p0] + prices),
        "tick_volatility": statistics.pstdev(rets) if len(rets) > 1 else 0.0,
        "total_volume": sum(s["volume"]),
        "total_trades": sum(s["trades"]),
        "avg_spread_bps": statistics.mean(spreads) if spreads else float("nan"),
        "max_spread_bps": max(spreads) if spreads else float("nan"),
        "one_sided_ticks": sum(1 for x in s["spread_bps"] if x is None),
        "mean_abs_mispricing": statistics.mean(abs(p / f - 1) for p, f in zip(prices, fundamentals)),
        "max_abs_mispricing": max(abs(p / f - 1) for p, f in zip(prices, fundamentals)),
    }


def event_impacts(run: RunResult) -> List[dict]:
    prices, fundamentals = run.series["price"], run.series["fundamental"]
    out = []
    for ev in run.events:
        t = ev["tick"]
        before = prices[t - 1] if t > 0 else run.scenario.initial_price
        row = {"tick": t, "headline": ev["headline"], "price_before": before}
        for h in EVENT_HORIZONS:
            if t + h < len(prices):
                row[f"return_{h}"] = prices[t + h] / before - 1
        window = prices[t: t + EVENT_HORIZONS[-1] + 1]
        trough = min(window)
        row["worst_return"] = trough / before - 1
        row["best_return"] = max(window) / before - 1
        row["fair_value_change"] = fundamentals[t] / (fundamentals[t - 1] if t > 0 else run.scenario.initial_fundamental) - 1
        # overshoot: how far price went beyond the new fair value, in the direction of the move
        fv = fundamentals[t]
        if row["fair_value_change"] < 0:
            row["overshoot"] = min(0.0, trough / fv - 1)
        else:
            row["overshoot"] = max(0.0, max(window) / fv - 1)
        out.append(row)
    return out


def trader_stats(run: RunResult) -> List[dict]:
    p0, p1 = run.scenario.initial_price, run.final_price
    groups: Dict[str, list] = defaultdict(list)
    for a in run.agents:
        groups[a.kind].append(a)
    rows = []
    for kind, agents in groups.items():
        start = sum(a.initial_wealth(p0) for a in agents)
        end = sum(a.wealth(p1) for a in agents)
        returns = [a.wealth(p1) / a.initial_wealth(p0) - 1 for a in agents if a.initial_wealth(p0) > 0]
        # Buy-and-hold benchmark: what the starting portfolio would be worth untouched.
        hold = sum(a.initial_cash + a.initial_shares * p1 for a in agents)
        rows.append({
            "kind": kind,
            "label": AGENT_TYPES[kind].label,
            "count": len(agents),
            "start_wealth": start,
            "end_wealth": end,
            "pnl": end - start,
            "return": end / start - 1 if start else 0.0,
            "vs_buy_and_hold": (end - hold) / start if start else 0.0,
            "median_return": statistics.median(returns) if returns else 0.0,
            "pct_losing": sum(r < 0 for r in returns) / len(returns) if returns else 0.0,
            "avg_final_shares": statistics.mean(a.shares for a in agents),
            "volume": sum(a.volume for a in agents),
            "panics": sum(getattr(a, "panics", 0) for a in agents),
        })
    rows.sort(key=lambda r: list(AGENT_TYPES).index(r["kind"]))
    return rows


def _pct(values: List[float], q: float) -> float:
    xs = sorted(values)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def monte_carlo_summary(runs: List[RunResult]) -> dict:
    stats = [market_stats(r) for r in runs]
    metrics = ("total_return", "max_drawdown", "min_price", "max_price", "avg_spread_bps", "max_abs_mispricing")
    summary = {
        m: {q: _pct([s[m] for s in stats], q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)} for m in metrics
    }
    summary["prob_loss"] = sum(s["total_return"] < 0 for s in stats) / len(stats)
    summary["prob_drawdown_10"] = sum(s["max_drawdown"] <= -0.10 for s in stats) / len(stats)
    by_kind: Dict[str, List[float]] = defaultdict(list)
    for r in runs:
        for row in trader_stats(r):
            by_kind[row["kind"]].append(row["return"])
    summary["trader_returns"] = {
        k: {q: _pct(v, q) for q in (0.05, 0.5, 0.95)} for k, v in by_kind.items()
    }
    summary["runs"] = len(runs)
    summary["final_returns"] = [s["total_return"] for s in stats]
    return summary
