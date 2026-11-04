import unittest

from marketsim.orderbook import BUY, SELL, OrderBook


class OrderBookTest(unittest.TestCase):
    def setUp(self):
        self.book = OrderBook(0.01)

    def test_price_time_priority(self):
        self.book.submit(1, SELL, 10, 101.0, 0)
        self.book.submit(2, SELL, 10, 100.5, 0)
        self.book.submit(3, SELL, 10, 100.5, 0)
        _, trades = self.book.submit(9, BUY, 15, None, 1)
        self.assertEqual([(t.seller_id, t.qty, t.price) for t in trades], [(2, 10, 100.5), (3, 5, 100.5)])
        self.assertEqual(self.book.best_ask(), 100.5)
        self.assertEqual(self.book.last_price, 100.5)

    def test_limit_rests_remainder_and_respects_limit(self):
        self.book.submit(1, SELL, 5, 100.0, 0)
        self.book.submit(1, SELL, 5, 102.0, 0)
        order, trades = self.book.submit(2, BUY, 8, 101.0, 0)
        self.assertEqual(sum(t.qty for t in trades), 5)
        self.assertEqual(order.remaining, 3)
        self.assertEqual(self.book.best_bid(), 101.0)
        self.assertEqual(self.book.best_ask(), 102.0)

    def test_market_order_on_empty_book_does_nothing(self):
        order, trades = self.book.submit(1, BUY, 10, None, 0)
        self.assertEqual(trades, [])
        self.assertEqual(self.book.orders, {})

    def test_self_trade_prevention_cancels_resting(self):
        self.book.submit(1, SELL, 10, 100.0, 0)
        self.book.submit(2, SELL, 10, 100.1, 0)
        _, trades = self.book.submit(1, BUY, 10, 100.2, 0)
        self.assertEqual([(t.seller_id, t.price) for t in trades], [(2, 100.1)])
        self.assertIsNone(self.book.best_ask())

    def test_cancel_expire_and_exposure(self):
        self.book.submit(1, BUY, 10, 99.0, 0, ttl=5)
        self.book.submit(1, SELL, 4, 101.0, 0)
        self.assertEqual(self.book.open_exposure(1), (10, 4, 990.0))
        self.book.expire(4)
        self.assertEqual(self.book.best_bid(), 99.0)
        self.book.expire(5)
        self.assertIsNone(self.book.best_bid())
        self.assertEqual(self.book.cancel_agent(1), 1)
        self.assertEqual(self.book.open_exposure(1), (0, 0, 0.0))

    def test_rounding_and_validation(self):
        order, _ = self.book.submit(1, BUY, 1, 99.996, 0)
        self.assertEqual(order.price, 100.0)
        with self.assertRaises(ValueError):
            self.book.submit(1, "hold", 1, 100, 0)
        with self.assertRaises(ValueError):
            self.book.submit(1, BUY, 0, 100, 0)


if __name__ == "__main__":
    unittest.main()
