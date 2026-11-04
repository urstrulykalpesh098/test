"""Trader archetypes.

Every agent receives a read-only MarketView each time it is active and
returns a Decision (optionally cancel its resting orders, then submit new
ones). The engine enforces cash, position and short limits, so strategies
only express intent.

Most strategies work by choosing a *target position* and trading toward it,
which keeps inventories bounded and behaviour easy to reason about.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from .orderbook import BUY, SELL


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class OrderRequest:
    side: str
    qty: int
    price: Optional[float] = None  # None = market order
    ttl: Optional[int] = None


@dataclass
class Decision:
    orders: List[OrderRequest] = field(default_factory=list)
    cancel_all: bool = False


class Trader:
    kind = "trader"
    label = "Trader"
    description = ""

    BASE: Dict[str, float] = dict(
        activity=0.2,      # probability of acting on a given tick
        max_position=1000, # max long shares
        max_short=0,       # max short shares (0 = long only)
        margin=0.0,        # extra buying power as a fraction of wealth
        info_lag=0,        # ticks of delay on fundamental information
        info_noise=0.0,    # per-observation noise on fundamental estimate
        bias_sd=0.0,       # persistent per-agent valuation bias
        order_ttl=20,      # lifetime of passive limit orders, in ticks
        max_order=100,     # largest single order
        min_trade=1,       # ignore rebalances smaller than this
    )
    DEFAULTS: Dict[str, float] = {}

    def __init__(self, agent_id: int, rng: random.Random, cash: float,
                 shares: int, params: Optional[dict] = None) -> None:
        params = dict(params or {})
        allowed = {**self.BASE, **self.DEFAULTS}
        unknown = set(params) - set(allowed)
        if unknown:
            raise ValueError(
                f"unknown parameter(s) for {self.kind}: {', '.join(sorted(unknown))}; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
        self.p = {**allowed, **params}
        self.id = agent_id
        self.rng = rng
        self.cash = float(cash)
        self.shares = int(shares)
        self.initial_cash = self.cash
        self.initial_shares = self.shares
        self.bias = rng.gauss(0.0, self.p["bias_sd"]) if self.p["bias_sd"] > 0 else 0.0
        self.n_trades = 0
        self.volume = 0

    # ----------------------------------------------------------- accessors
    @property
    def activity(self) -> float:
        return self.p["activity"]

    @property
    def info_lag(self) -> int:
        return int(self.p["info_lag"])

    def wealth(self, price: float) -> float:
        return self.cash + self.shares * price

    def initial_wealth(self, price: float) -> float:
        return self.initial_cash + self.initial_shares * price

    # ------------------------------------------------------------ strategy
    def decide(self, view) -> Decision:  # pragma: no cover - abstract
        raise NotImplementedError

    def _scaled_target(self, strength: float, neutral: float) -> float:
        """Map strength in [-1, 1] onto [-max_short, max_position] around neutral."""
        if strength >= 0:
            return neutral + strength * (self.p["max_position"] - neutral)
        return neutral + strength * (neutral + self.p["max_short"])

    def _trade_toward(self, target: float, view, aggressive: bool,
                      limit: Optional[float] = None) -> Decision:
        """Trade toward a target position.

        aggressive + no limit -> market order; aggressive + limit -> marketable
        limit order that rests at `limit` if not filled; otherwise a passive
        order one tick inside the spread.
        """
        target = clamp(target, -self.p["max_short"], self.p["max_position"])
        diff = int(round(target - self.shares))
        if abs(diff) < max(1, self.p["min_trade"]):
            return Decision(cancel_all=True)
        side = BUY if diff > 0 else SELL
        qty = min(abs(diff), int(self.p["max_order"]))
        if aggressive and limit is None:
            return Decision([OrderRequest(side, qty)], cancel_all=True)
        if aggressive:
            return Decision([OrderRequest(side, qty, limit, int(self.p["order_ttl"]))], cancel_all=True)
        price = self._passive_price(side, view)
        return Decision([OrderRequest(side, qty, price, int(self.p["order_ttl"]))], cancel_all=True)

    @staticmethod
    def _passive_price(side: str, view) -> float:
        ts = view.tick_size
        bid, ask, ref = view.best_bid, view.best_ask, view.last_price
        if side == BUY:
            price = bid + ts if bid is not None else ref * 0.999
            if ask is not None:
                price = min(price, ask - ts)
        else:
            price = ask - ts if ask is not None else ref * 1.001
            if bid is not None:
                price = max(price, bid + ts)
        return price


class Fundamentalist(Trader):
    kind = "fundamentalist"
    label = "Value investors"
    description = "Buy below and sell above their (lagged, noisy) estimate of fair value."
    DEFAULTS = dict(
        activity=0.1, max_position=1000, info_lag=5, info_noise=0.01, bias_sd=0.02,
        threshold=0.01, conviction_gap=0.08, urgent_gap=0.05, max_order=200,
    )

    def decide(self, view) -> Decision:
        price = view.last_price
        estimate = view.observed_fundamental(self) * (1 + self.bias)
        gap = estimate / price - 1
        if abs(gap) < self.p["threshold"]:
            return Decision()
        strength = clamp(gap / self.p["conviction_gap"], -1, 1)
        target = self._scaled_target(strength, self.initial_shares)
        # Urgent orders cross the spread but never pay more (or sell for less)
        # than the agent's own view of fair value, so they anchor the price.
        half = self.p["threshold"] / 2
        limit = estimate * (1 - half) if gap > 0 else estimate * (1 + half)
        return self._trade_toward(target, view, aggressive=abs(gap) > self.p["urgent_gap"], limit=limit)


class Institutional(Fundamentalist):
    kind = "institutional"
    label = "Institutions"
    description = "Large, well-informed value funds that work big orders in slices."
    DEFAULTS = dict(
        Fundamentalist.DEFAULTS,
        activity=0.3, max_position=20000, info_lag=1, info_noise=0.003, bias_sd=0.01,
        threshold=0.015, conviction_gap=0.1, urgent_gap=0.04, max_order=300, order_ttl=10,
    )


class Momentum(Trader):
    kind = "momentum"
    label = "Trend followers"
    description = "Go long when the short moving average is above the long one, short when below."
    DEFAULTS = dict(
        activity=0.1, max_position=800, max_short=400, margin=0.5,
        short_window=10, long_window=50, sensitivity=0.03, max_order=60, min_trade=5,
    )

    def decide(self, view) -> Decision:
        prices = view.prices
        long_w, short_w = int(self.p["long_window"]), int(self.p["short_window"])
        if len(prices) < long_w:
            return Decision()
        ma_short = sum(prices[-short_w:]) / short_w
        ma_long = sum(prices[-long_w:]) / long_w
        strength = clamp((ma_short / ma_long - 1) / self.p["sensitivity"], -1, 1)
        return self._trade_toward(self._scaled_target(strength, 0), view, aggressive=True)


class MeanReversion(Trader):
    kind = "mean_reversion"
    label = "Mean reverters"
    description = "Fade statistically stretched moves back toward the recent average."
    DEFAULTS = dict(
        activity=0.2, max_position=600, max_short=300, margin=0.5,
        window=30, z_entry=0.75, z_full=2.5, max_order=100, min_trade=5,
    )

    def decide(self, view) -> Decision:
        window = int(self.p["window"])
        prices = view.prices
        if len(prices) < window:
            return Decision()
        recent = prices[-window:]
        mean = sum(recent) / window
        sd = math.sqrt(sum((x - mean) ** 2 for x in recent) / window)
        if sd <= 1e-12:
            return Decision()
        z = (view.last_price - mean) / sd
        if abs(z) < self.p["z_entry"]:
            return self._trade_toward(0, view, aggressive=False)
        strength = -clamp(z / self.p["z_full"], -1, 1)
        return self._trade_toward(self._scaled_target(strength, 0), view, aggressive=False)


class Retail(Trader):
    kind = "retail"
    label = "Retail traders"
    description = "Herd on sentiment, chase recent returns, act on stale news and panic-sell at a stop-loss."
    DEFAULTS = dict(
        activity=0.05, max_position=300, info_lag=30, info_noise=0.05,
        herding=0.8, chase=15.0, value_weight=2.0, noise=0.4, lookback=20,
        stop_loss=0.15, cooldown=50, max_order=60, min_trade=5,
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.peak_wealth: Optional[float] = None
        self.cooldown_until = -1
        self.panics = 0

    def decide(self, view) -> Decision:
        price = view.last_price
        wealth = self.wealth(price)
        self.peak_wealth = wealth if self.peak_wealth is None else max(self.peak_wealth, wealth)
        if view.tick < self.cooldown_until:
            return Decision()
        if self.shares > 0 and wealth < self.peak_wealth * (1 - self.p["stop_loss"]):
            self.cooldown_until = view.tick + int(self.p["cooldown"])
            self.peak_wealth = wealth
            self.panics += 1
            return Decision([OrderRequest(SELL, self.shares)], cancel_all=True)

        prices = view.prices
        lookback = int(self.p["lookback"])
        past = prices[-lookback] if len(prices) >= lookback else prices[0]
        recent_return = price / past - 1
        value_hint = view.observed_fundamental(self) / price - 1
        score = (
            self.p["herding"] * view.sentiment
            + self.p["chase"] * recent_return
            + self.p["value_weight"] * value_hint
            + self.p["noise"] * self.rng.gauss(0, 1)
        )
        target = self._scaled_target(clamp(score, -1, 1), self.initial_shares)
        return self._trade_toward(target, view, aggressive=True)


class MarketMaker(Trader):
    kind = "market_maker"
    label = "Market makers"
    description = "Quote both sides, widen with volatility, skew away from inventory, pull back under stress."
    DEFAULTS = dict(
        activity=0.9, max_position=5000, max_short=5000, margin=1.0,
        half_spread=0.002, vol_mult=0.5, max_half_spread=0.02, quote_size=200, levels=3,
        level_step=0.0015, skew=0.004, order_ttl=3, stress_widen=6.0,
    )

    def decide(self, view) -> Decision:
        ref = view.last_price
        mid = view.mid
        if mid is not None and abs(mid / ref - 1) < 0.02:
            ref = mid
        stress = view.mm_stress
        size = int(round(self.p["quote_size"] * (1 - stress)))
        if size < 1:
            return Decision(cancel_all=True)
        widen = 1 + self.p["stress_widen"] * stress
        half = min(self.p["half_spread"] + self.p["vol_mult"] * view.volatility,
                   self.p["max_half_spread"]) * widen
        # Inventory is measured against the starting book so a maker that is
        # endowed with shares still quotes symmetrically at the open.
        inventory = (self.shares - self.initial_shares) / self.p["max_position"]
        center = ref * (1 - self.p["skew"] * inventory)
        ttl = int(self.p["order_ttl"])
        orders: List[OrderRequest] = []
        for level in range(int(self.p["levels"])):
            offset = half + level * self.p["level_step"] * widen
            if self.shares < self.p["max_position"]:
                orders.append(OrderRequest(BUY, size, center * (1 - offset), ttl))
            if self.shares > -self.p["max_short"]:
                orders.append(OrderRequest(SELL, size, center * (1 + offset), ttl))
        return Decision(orders, cancel_all=True)


AGENT_TYPES: Dict[str, Type[Trader]] = {
    cls.kind: cls
    for cls in (MarketMaker, Institutional, Fundamentalist, Momentum, MeanReversion, Retail)
}


def build_agent(kind: str, agent_id: int, rng: random.Random, cash: float,
                shares: int, params: Optional[dict] = None) -> Trader:
    try:
        cls = AGENT_TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown trader type {kind!r}; choose from {', '.join(AGENT_TYPES)}") from None
    return cls(agent_id, rng, cash, shares, params)
