from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crypto_flow_bot_v2.backtest import (
    BacktestReplayEngine,
    InMemorySnapshotSource,
    ReplayEvent,
    ReplayEventType,
)
from crypto_flow_bot_v2.config import load_config
from crypto_flow_bot_v2.models import MarketRegime, MarketSnapshot
from crypto_flow_bot_v2.position_manager import PositionEventType, PositionExitReason

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def test_backtest_replay_opens_and_closes_virtual_long() -> None:
    config = load_config()
    snapshots = InMemorySnapshotSource(
        (
            _long_snapshot(price=100.0, timestamp=BASE_TIME),
            _long_snapshot(price=109.0, timestamp=BASE_TIME + timedelta(minutes=15)),
        )
    )

    result = BacktestReplayEngine(config).run(snapshots)

    closed_events = [
        event.position_event
        for event in result.events
        if event.position_event is not None
        and event.position_event.event_type is PositionEventType.CLOSED
    ]

    assert result.summary.snapshots_processed == 2
    assert result.summary.signals_seen == 2
    assert result.summary.positions_opened == 1
    assert result.summary.positions_closed == 1
    assert result.summary.wins == 1
    assert result.summary.open_positions == 0
    assert closed_events[0].exit_reason is PositionExitReason.TAKE_PROFIT
    assert closed_events[0].pnl_pct == 9.0


def test_backtest_replay_filters_symbols_before_evaluation() -> None:
    config = load_config()
    snapshots = InMemorySnapshotSource(
        (
            _long_snapshot(symbol="ETHUSDT", price=2000.0, timestamp=BASE_TIME),
            _long_snapshot(symbol="BTCUSDT", price=100.0, timestamp=BASE_TIME),
        )
    )

    result = BacktestReplayEngine(config).run(snapshots, symbols=("BTCUSDT",))

    assert result.summary.symbols == ("BTCUSDT",)
    assert result.summary.snapshots_processed == 1
    assert all(event.symbol == "BTCUSDT" for event in result.events)


def test_empty_replay_returns_zero_summary_for_requested_symbols() -> None:
    result = BacktestReplayEngine(load_config()).run((), symbols=("solusdt",))

    assert result.events == ()
    assert result.summary.symbols == ("SOLUSDT",)
    assert result.summary.started_at is None
    assert result.summary.ended_at is None
    assert result.summary.snapshots_processed == 0
    assert result.summary.total_pnl_pct == 0.0


def test_replay_event_requires_matching_payload() -> None:
    with pytest.raises(ValueError, match="requires a SignalDecision payload"):
        ReplayEvent(
            timestamp=BASE_TIME,
            symbol="BTCUSDT",
            event_type=ReplayEventType.DECISION,
        )


def _long_snapshot(
    symbol: str = "BTCUSDT",
    price: float = 100.0,
    timestamp: datetime = BASE_TIME,
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        timestamp=timestamp,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=price,
        regime=MarketRegime.TREND_UP,
        metrics={
            "entry_return_pct": 1.25,
            "context_return_pct": 1.1,
            "macro_return_pct": 1.0,
            "entry_atr": 2.0,
            "entry_atr_pct": 2.0,
            "entry_taker_buy_quote_ratio": 0.66,
            "open_interest": 1_000_000.0,
            "funding_rate": 0.0002,
            "long_short_ratio": 1.2,
            "taker_buy_sell_ratio": 1.4,
            "liquidation_buy_notional": 100_000.0,
            "liquidation_sell_notional": 10_000.0,
        },
    )
