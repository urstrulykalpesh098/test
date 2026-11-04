"""Scenario files: market setup, trader population and scheduled events."""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agents import AGENT_TYPES, build_agent
from .forecast import Forecast


@dataclass
class PopulationSpec:
    kind: str
    count: int
    cash: float
    shares: int
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    tick: int
    headline: str = ""
    fundamental_change: float = 0.0       # relative jump in fair value, e.g. -0.08
    sentiment: float = 0.0                # added to market sentiment, clamped to [-1, 1]
    fundamental_vol: Optional[float] = None  # temporary volatility regime
    mm_stress: Optional[float] = None     # 0..1, market makers pull liquidity
    duration: int = 0                     # ticks a regime lasts


@dataclass
class Scenario:
    name: str
    description: str
    ticks: int
    initial_price: float
    initial_fundamental: float
    tick_size: float
    fundamental_vol: float
    fundamental_drift: float
    sentiment_decay: float
    sentiment_feedback: float
    population: List[PopulationSpec]
    events: List[Event]
    baseline_forecast: Optional[Dict[str, Any]] = None  # config from the JSON file
    base_dir: Optional[Path] = None                     # resolves relative CSV paths
    # Filled in by attach_forecast() before a run:
    forecast: Optional[Forecast] = None
    fair_value_path: Optional[List[float]] = None       # per-tick multiplier on fair value
    ticks_per_step: int = 1

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scenario":
        def need(cond: bool, msg: str) -> None:
            if not cond:
                raise ValueError(f"scenario {data.get('name', '?')!r}: {msg}")

        ticks = int(data.get("ticks", 1000))
        need(ticks > 0, "ticks must be positive")
        price = float(data.get("initial_price", 100.0))
        need(price > 0, "initial_price must be positive")
        fundamental = data.get("fundamental", {})
        sentiment = data.get("sentiment", {})

        population = []
        for kind, spec in data.get("population", {}).items():
            need(kind in AGENT_TYPES, f"unknown trader type {kind!r} (choose from {', '.join(AGENT_TYPES)})")
            count = int(spec.get("count", 0))
            need(count >= 0, f"{kind}.count must be >= 0")
            pop = PopulationSpec(
                kind, count, float(spec.get("cash", 100_000)), int(spec.get("shares", 0)),
                dict(spec.get("params", {})),
            )
            try:  # surface typos in params now, not mid-run
                build_agent(kind, -1, random.Random(0), pop.cash, pop.shares, pop.params)
            except ValueError as exc:
                need(False, str(exc))
            population.append(pop)
        need(sum(p.count for p in population) > 0, "population is empty")
        need(any(p.kind == "market_maker" and p.count for p in population),
             "include at least one market_maker so the book has liquidity")

        events = []
        for raw in data.get("events", []):
            ev = Event(**raw)
            need(0 <= ev.tick < ticks, f"event at tick {ev.tick} is outside 0..{ticks - 1}")
            need(ev.fundamental_change > -1, "fundamental_change must be > -1")
            need(ev.mm_stress is None or 0 <= ev.mm_stress <= 1, "mm_stress must be in [0, 1]")
            need(ev.duration >= 0, "duration must be >= 0")
            events.append(ev)
        events.sort(key=lambda e: e.tick)

        baseline = data.get("baseline_forecast")
        if baseline is not None:
            need(isinstance(baseline, dict) and baseline.get("csv"), "baseline_forecast needs a 'csv' path")
            unknown = set(baseline) - {"csv", "column", "ticks_per_step", "model", "vol_from_band", "checkpoint"}
            need(not unknown, f"unknown baseline_forecast key(s): {', '.join(sorted(unknown))}")
            need(int(baseline.get("ticks_per_step", 10)) >= 1, "baseline_forecast.ticks_per_step must be >= 1")
            need(baseline.get("model", "auto") in ("auto", "timesfm", "statistical"),
                 "baseline_forecast.model must be auto, timesfm or statistical")

        return cls(
            name=str(data.get("name", "scenario")),
            description=str(data.get("description", "")),
            ticks=ticks,
            initial_price=price,
            initial_fundamental=float(fundamental.get("initial", price)),
            tick_size=float(data.get("tick_size", 0.01)),
            fundamental_vol=float(fundamental.get("vol", 0.001)),
            fundamental_drift=float(fundamental.get("drift", 0.0)),
            sentiment_decay=float(sentiment.get("decay", 0.98)),
            sentiment_feedback=float(sentiment.get("feedback", 5.0)),
            population=population,
            events=events,
            baseline_forecast=baseline,
        )

    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        with open(path, encoding="utf-8") as fh:
            sc = cls.from_dict(json.load(fh))
        sc.base_dir = Path(path).resolve().parent
        return sc

    def resolve_path(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute() or self.base_dir is None or p.exists():
            return p
        return self.base_dir / p


def attach_forecast(sc: Scenario, fc: Forecast, ticks_per_step: int, vol_from_band: bool = True) -> None:
    """Make fair value follow the forecast's median path (events still apply on top).

    With vol_from_band, per-tick fair-value noise is set from the forecast's
    10-90% band, so the simulated spread of outcomes matches the forecast's
    uncertainty before any scenario events are added.
    """
    sc.forecast = fc
    sc.ticks_per_step = ticks_per_step
    sc.fair_value_path = fc.relative_path(sc.ticks, ticks_per_step)
    sc.fundamental_drift = 0.0
    step_vol = fc.per_step_vol()
    if vol_from_band and step_vol:
        sc.fundamental_vol = step_vol / math.sqrt(ticks_per_step)
