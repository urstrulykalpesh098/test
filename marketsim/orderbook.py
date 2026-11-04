"""Limit order book with price-time priority matching.

Market orders (price=None) sweep the opposite side until filled or the book
is empty; any unfilled remainder is dropped. Limit orders match against
crossing liquidity and the remainder rests in the book. Self-trades are
prevented by cancelling the agent's resting order (cancel-oldest policy).
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

BUY = "buy"
SELL = "sell"


@dataclass
class Order:
    order_id: int
    agent_id: int
    side: str
    qty: int
    price: Optional[float]
    tick: int
    ttl: Optional[int] = None
    remaining: int = field(init=False)

    def __post_init__(self) -> None:
        self.remaining = self.qty


@dataclass(frozen=True)
class Trade:
    tick: int
    price: float
    qty: int
    buyer_id: int
    seller_id: int
    aggressor: str


class OrderBook:
    def __init__(self, tick_size: float = 0.01) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        self.tick_size = tick_size
        self._bids: List[Tuple[float, int, Order]] = []  # (-price, seq, order)
        self._asks: List[Tuple[float, int, Order]] = []  # (price, seq, order)
        self._seq = itertools.count()
        self._ids = itertools.count(1)
        self.orders: Dict[int, Order] = {}
        self._by_agent: Dict[int, Set[int]] = {}
        self.last_price: Optional[float] = None

    # ------------------------------------------------------------------ prices
    def round_price(self, price: float) -> float:
        ticks = max(1, round(price / self.tick_size))
        return round(ticks * self.tick_size, 8)

    def _top(self, heap: List[Tuple[float, int, Order]]) -> Optional[Order]:
        while heap and heap[0][2].order_id not in self.orders:
            heapq.heappop(heap)
        return heap[0][2] if heap else None

    def best_bid(self) -> Optional[float]:
        order = self._top(self._bids)
        return order.price if order else None

    def best_ask(self) -> Optional[float]:
        order = self._top(self._asks)
        return order.price if order else None

    def mid(self) -> Optional[float]:
        bid, ask = self.best_bid(), self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    def depth(self, side: str) -> int:
        """Total resting quantity on one side of the book."""
        return sum(o.remaining for o in self.orders.values() if o.side == side)

    # --------------------------------------------------------------- bookkeeping
    def _rest(self, order: Order) -> None:
        self.orders[order.order_id] = order
        self._by_agent.setdefault(order.agent_id, set()).add(order.order_id)
        if order.side == BUY:
            heapq.heappush(self._bids, (-order.price, next(self._seq), order))
        else:
            heapq.heappush(self._asks, (order.price, next(self._seq), order))

    def _remove(self, order_id: int) -> Optional[Order]:
        order = self.orders.pop(order_id, None)
        if order is not None:
            ids = self._by_agent.get(order.agent_id)
            if ids:
                ids.discard(order_id)
        return order

    def _maybe_compact(self) -> None:
        # Cancelled orders stay in the heaps until they surface; rebuild
        # occasionally so memory stays proportional to live orders.
        for name in ("_bids", "_asks"):
            heap = getattr(self, name)
            if len(heap) > 4 * len(self.orders) + 256:
                live = [item for item in heap if item[2].order_id in self.orders]
                heapq.heapify(live)
                setattr(self, name, live)

    def cancel(self, order_id: int) -> bool:
        return self._remove(order_id) is not None

    def cancel_agent(self, agent_id: int) -> int:
        ids = list(self._by_agent.get(agent_id, ()))
        for order_id in ids:
            self._remove(order_id)
        return len(ids)

    def expire(self, tick: int) -> int:
        expired = [
            oid for oid, o in self.orders.items()
            if o.ttl is not None and tick - o.tick >= o.ttl
        ]
        for oid in expired:
            self._remove(oid)
        return len(expired)

    def open_exposure(self, agent_id: int) -> Tuple[int, int, float]:
        """(resting buy qty, resting sell qty, resting buy notional)."""
        buy_qty = sell_qty = 0
        buy_notional = 0.0
        for oid in self._by_agent.get(agent_id, ()):
            order = self.orders[oid]
            if order.side == BUY:
                buy_qty += order.remaining
                buy_notional += order.remaining * order.price
            else:
                sell_qty += order.remaining
        return buy_qty, sell_qty, buy_notional

    # ------------------------------------------------------------------ orders
    def submit(
        self,
        agent_id: int,
        side: str,
        qty: int,
        price: Optional[float],
        tick: int,
        ttl: Optional[int] = None,
    ) -> Tuple[Order, List[Trade]]:
        if side not in (BUY, SELL):
            raise ValueError(f"invalid side: {side!r}")
        if qty <= 0:
            raise ValueError("qty must be positive")
        px = None if price is None else self.round_price(price)
        order = Order(next(self._ids), agent_id, side, int(qty), px, tick, ttl)
        trades = self._match(order)
        if order.remaining > 0 and order.price is not None:
            self._rest(order)
        self._maybe_compact()
        return order, trades

    def _match(self, order: Order) -> List[Trade]:
        trades: List[Trade] = []
        book = self._asks if order.side == BUY else self._bids
        while order.remaining > 0:
            resting = self._top(book)
            if resting is None:
                break
            if order.price is not None:
                if order.side == BUY and resting.price > order.price + 1e-9:
                    break
                if order.side == SELL and resting.price < order.price - 1e-9:
                    break
            if resting.agent_id == order.agent_id:
                self._remove(resting.order_id)  # self-trade prevention
                continue
            qty = min(order.remaining, resting.remaining)
            order.remaining -= qty
            resting.remaining -= qty
            if order.side == BUY:
                buyer, seller = order.agent_id, resting.agent_id
            else:
                buyer, seller = resting.agent_id, order.agent_id
            trades.append(Trade(order.tick, resting.price, qty, buyer, seller, order.side))
            self.last_price = resting.price
            if resting.remaining == 0:
                self._remove(resting.order_id)
        return trades
