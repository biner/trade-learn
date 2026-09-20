from __future__ import annotations

from tradelearn.backtest.broker import RustBroker
from tradelearn.backtest.models import Order
from tradelearn.engine import Strategy


class DummyData:
    _name = "primary"
    _datetime = [0]


class DummyEngine:
    def __init__(self) -> None:
        self.next_order_id = 1
        self.submissions: list[tuple] = []

    def submit_order(self, *args) -> int:
        order_id = self.next_order_id
        self.next_order_id += 1
        self.submissions.append(args)
        return order_id


class RecordingStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.order_events: list[int] = []
        self.data = DummyData()
        self.datas = [self.data]

    def notify_order(self, order) -> None:
        self.order_events.append(order.status)


def test_oco_sibling_is_canceled_after_rust_fill() -> None:
    broker = RustBroker(cash=10_000)
    engine = DummyEngine()
    broker.bind_engine(engine)
    strategy = RecordingStrategy()
    strategy.broker = broker

    main, stop, limit = strategy.buy_bracket(size=1, stopprice=9.0, limitprice=12.0)
    assert len(engine.submissions) == 1

    broker._process_rust_fills_batch(
        strategy,
        ([main.ref], [1.0], [10.0], [0.0], [0.0], [0.0]),
    )
    assert len(engine.submissions) == 3

    broker._process_rust_fills_batch(
        strategy,
        ([limit.ref], [-1.0], [12.0], [0.0], [0.0], [2.0]),
    )

    assert limit.status == Order.Completed
    assert stop.status == Order.Canceled
    assert Order.Completed in strategy.order_events
    assert Order.Canceled in strategy.order_events


def test_bracket_children_are_deferred_until_parent_fills() -> None:
    broker = RustBroker(cash=10_000)
    engine = DummyEngine()
    broker.bind_engine(engine)
    strategy = RecordingStrategy()
    strategy.broker = broker

    main, stop, limit = strategy.buy_bracket(size=1, stopprice=9.0, limitprice=12.0)

    # 挂起语义（对齐 backtrader）：只有 transmit=True 的成员拉起整组提交；
    # 父单已递交撮合并被接受（Accepted），其余子单保持 Created（**尚未递交市场**，
    # 不得提前置 Accepted），否则从未真正挂出的计划单在被清理时会被误记为「已取消」。
    assert [main.status, stop.status, limit.status] == [
        Order.Accepted,
        Order.Created,
        Order.Created,
    ]
    assert len(engine.submissions) == 1

    broker._process_rust_fills_batch(
        strategy,
        ([main.ref], [1.0], [10.0], [0.0], [0.0], [0.0]),
    )

    # 父单成交后，挂起的子单才被激活递交（此处 2 个子单已随父单提交，共 3 笔）
    assert len(engine.submissions) == 3
    assert stop.status == Order.Accepted
    assert limit.status == Order.Accepted
