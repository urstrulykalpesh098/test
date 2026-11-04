"""Simulation loop: news and regimes -> fair value -> agent decisions -> matching."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

from .agents import Decision, OrderRequest, Trader, build_agent, clamp
from .orderbook import BUY, OrderBook
from .scenario import Scenario

VOL_WINDOW = 50
SLIPPAGE_BUFFER = 1.02  # headroom when sizing market buys against cash


class MarketView:
    """What an agent is allowed to see. Fair value only via observed_fundamental."""

    __slots__ = ("_sim",)

    def __init__(self, sim: "Simulation") -> None:
        self._sim = sim

    @property
    def tick(self) -> int:
        return self._sim.t

    @property
    def tick_size(self) -> float:
        return self._sim.book.tick_size

    @property
    def prices(self) -> List[float]:
        return self._sim.close_history

    @property
    def last_price(self) -> float:
        return self._sim.last_price

    @property
    def best_bid(self) -> Optional[float]:
        return self._sim.book.best_bid()

    @property
    def best_ask(self) -> Optional[float]:
        return self._sim.book.best_ask()

    @property
    def mid(self) -> Optional[float]:
        return self._sim.book.mid()

    @property
    def sentiment(self) -> float:
        return self._sim.sentiment

    @property
    def volatility(self) -> float:
        return self._sim.volatility

    @property
    def mm_stress(self) -> float:
        return self._sim.mm_stress

    def observed_fundamental(self, agent: Trader) -> float:
        history = self._sim.fundamental_history
        idx = max(0, len(history) - 1 - agent.info_lag)
        value = history[idx]
        noise = agent.p["info_noise"]
        return value * math.exp(noise * agent.rng.gauss(0, 1)) if noise > 0 else value


@dataclass
class RunResult:
    scenario: Scenario
    seed: int
    series: Dict[str, list]
    events: List[dict]
    agents: List[Trader]

    @property
    def final_price(self) -> float:
        return self.series["price"][-1]


class Simulation:
    def __init__(self, scenario: Scenario, seed: int = 0) -> None:
        self.scenario = scenario
        self.seed = seed
        self.rng = random.Random(seed)
        self.book = OrderBook(scenario.tick_size)
        self.agents: List[Trader] = []
        for spec in scenario.population:
            for _ in range(spec.count):
                agent_rng = random.Random(self.rng.getrandbits(64))
                self.agents.append(
                    build_agent(spec.kind, len(self.agents), agent_rng, spec.cash, spec.shares, spec.params)
                )
        self.market_makers = [a for a in self.agents if a.kind == "market_maker"]
        self.others = [a for a in self.agents if a.kind != "market_maker"]

        self.t = 0
        self.fundamental = scenario.initial_fundamental
        self.sentiment = 0.0
        self.volatility = 0.0
        self.mm_stress = 0.0
        self.close_history: List[float] = [scenario.initial_price]
        self.fundamental_history: List[float] = [self.fundamental]
        self._events: Dict[int, list] = defaultdict(list)
        for ev in scenario.events:
            self._events[ev.tick].append(ev)
        self._vol_regimes: List[tuple] = []     # (end_tick, vol)
        self._stress_regimes: List[tuple] = []  # (end_tick, stress)
        self.event_log: List[dict] = []
        self.series: Dict[str, list] = {
            k: [] for k in ("price", "fundamental", "volume", "trades", "bid", "ask", "spread_bps", "sentiment", "mm_stress")
        }
        self.view = MarketView(self)

    @property
    def last_price(self) -> float:
        return self.book.last_price if self.book.last_price is not None else self.close_history[-1]

    # ------------------------------------------------------------------ step
    def _apply_events(self, t: int) -> None:
        for ev in self._events.get(t, ()):
            if ev.fundamental_vol is not None:
                self._vol_regimes.append((t + ev.duration, ev.fundamental_vol))
            if ev.mm_stress is not None:
                self._stress_regimes.append((t + ev.duration, ev.mm_stress))
            self.fundamental *= 1 + ev.fundamental_change
            self.sentiment = clamp(self.sentiment + ev.sentiment, -1, 1)
            self.event_log.append({
                "tick": t, "headline": ev.headline, "fundamental_change": ev.fundamental_change,
                "sentiment": ev.sentiment, "fundamental_vol": ev.fundamental_vol,
                "mm_stress": ev.mm_stress, "duration": ev.duration,
            })
        self._vol_regimes = [r for r in self._vol_regimes if r[0] > t]
        self._stress_regimes = [r for r in self._stress_regimes if r[0] > t]

    def _update_state(self) -> None:
        sc = self.scenario
        vol = self._vol_regimes[-1][1] if self._vol_regimes else sc.fundamental_vol
        self.mm_stress = self._stress_regimes[-1][1] if self._stress_regimes else 0.0
        shock = self.rng.gauss(0, 1)
        self.fundamental *= math.exp(sc.fundamental_drift - 0.5 * vol * vol + vol * shock)
        self.fundamental_history.append(self.fundamental)

        hist = self.close_history
        last_ret = math.log(hist[-1] / hist[-2]) if len(hist) >= 2 else 0.0
        self.sentiment = clamp(self.sentiment * sc.sentiment_decay + sc.sentiment_feedback * last_ret, -1, 1)

        window = hist[-(VOL_WINDOW + 1):]
        rets = [math.log(b / a) for a, b in zip(window, window[1:])]
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            self.volatility = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))

    def _allowed_qty(self, agent: Trader, req: OrderRequest) -> int:
        open_buy, open_sell, open_buy_notional = self.book.open_exposure(agent.id)
        if req.side == BUY:
            ref = req.price if req.price is not None else (self.book.best_ask() or self.last_price) * SLIPPAGE_BUFFER
            wealth = agent.wealth(self.last_price)
            budget = agent.cash - open_buy_notional + agent.p["margin"] * max(wealth, 0.0)
            by_cash = math.floor(budget / ref) if ref > 0 else 0
            by_position = agent.p["max_position"] - agent.shares - open_buy
            return int(max(0, min(req.qty, by_cash, by_position)))
        by_position = agent.shares - open_sell + agent.p["max_short"]
        return int(max(0, min(req.qty, by_position)))

    def _submit(self, agent: Trader, req: OrderRequest) -> tuple:
        qty = self._allowed_qty(agent, req)
        if qty <= 0:
            return 0, 0
        _, trades = self.book.submit(agent.id, req.side, qty, req.price, self.t, req.ttl)
        volume = 0
        for tr in trades:
            buyer, seller = self.agents[tr.buyer_id], self.agents[tr.seller_id]
            notional = tr.price * tr.qty
            buyer.cash -= notional
            buyer.shares += tr.qty
            seller.cash += notional
            seller.shares -= tr.qty
            for a in (buyer, seller):
                a.n_trades += 1
                a.volume += tr.qty
            volume += tr.qty
        return volume, len(trades)

    def step(self, t: int) -> None:
        self.t = t
        self._apply_events(t)
        self._update_state()
        self.book.expire(t)

        others = list(self.others)
        self.rng.shuffle(others)
        volume = n_trades = 0
        for agent in self.market_makers + others:
            if agent.rng.random() >= agent.activity:
                continue
            decision: Decision = agent.decide(self.view)
            if decision.cancel_all:
                self.book.cancel_agent(agent.id)
            for req in decision.orders:
                v, n = self._submit(agent, req)
                volume += v
                n_trades += n

        close = self.last_price
        self.close_history.append(close)
        bid, ask = self.book.best_bid(), self.book.best_ask()
        s = self.series
        s["price"].append(close)
        s["fundamental"].append(self.fundamental)
        s["volume"].append(volume)
        s["trades"].append(n_trades)
        s["bid"].append(bid)
        s["ask"].append(ask)
        s["spread_bps"].append((ask - bid) / ((ask + bid) / 2) * 1e4 if bid and ask else None)
        s["sentiment"].append(self.sentiment)
        s["mm_stress"].append(self.mm_stress)

    def run(self) -> RunResult:
        for t in range(self.scenario.ticks):
            self.step(t)
        return RunResult(self.scenario, self.seed, self.series, self.event_log, self.agents)


def run_scenario(scenario: Scenario, seed: int = 0) -> RunResult:
    return Simulation(scenario, seed).run()
