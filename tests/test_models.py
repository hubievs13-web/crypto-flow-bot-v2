from datetime import UTC, datetime

import pytest

from crypto_flow_bot_v2.models import (
    ExitPlan,
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
    VirtualPosition,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_market_snapshot_accepts_core_fields() -> None:
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        timestamp=NOW,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=100_000.0,
        regime=MarketRegime.TREND_UP,
        metrics={"funding_rate": 0.0001, "open_interest_change": 1.2},
    )

    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.regime is MarketRegime.TREND_UP
    assert snapshot.metrics["funding_rate"] == 0.0001


def test_signal_decision_validates_confidence_range() -> None:
    with pytest.raises(ValueError, match="confidence"):
        SignalDecision(
            symbol="BTCUSDT",
            timestamp=NOW,
            signal_type=SignalType.LONG_CONTINUATION,
            direction=SignalDirection.LONG,
            confidence=101,
            entry_price=100_000.0,
            stop_loss=98_000.0,
            take_profit_levels=(103_000.0,),
            reasons=("test",),
        )


def test_no_trade_requires_none_direction() -> None:
    decision = SignalDecision(
        symbol="ETHUSDT",
        timestamp=NOW,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=55,
        entry_price=None,
        stop_loss=None,
        take_profit_levels=(),
        reasons=("insufficient confidence",),
        blocked_reason="confidence_below_threshold",
    )

    assert decision.signal_type is SignalType.NO_TRADE
    assert decision.direction is SignalDirection.NONE
    assert decision.blocked_reason == "confidence_below_threshold"


def test_no_trade_rejects_trade_direction() -> None:
    with pytest.raises(ValueError, match="NO_TRADE"):
        SignalDecision(
            symbol="ETHUSDT",
            timestamp=NOW,
            signal_type=SignalType.NO_TRADE,
            direction=SignalDirection.LONG,
            confidence=55,
            entry_price=None,
            stop_loss=None,
        )


def test_virtual_position_requires_real_direction() -> None:
    exit_plan = ExitPlan(
        stop_loss=98.0,
        take_profit_levels=(103.0, 105.0, 108.0),
        trailing_stop=101.0,
        time_stop_minutes=240,
        invalidation_reason="context_structure_broken",
    )

    position = VirtualPosition(
        symbol="SOLUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        opened_at=NOW,
        exit_plan=exit_plan,
        confidence=82,
        source_signal_type=SignalType.LONG_CONTINUATION,
    )

    assert position.active is True
    assert position.exit_plan.take_profit_levels == (103.0, 105.0, 108.0)


def test_virtual_position_rejects_none_direction() -> None:
    with pytest.raises(ValueError, match="direction"):
        VirtualPosition(
            symbol="SOLUSDT",
            direction=SignalDirection.NONE,
            entry_price=100.0,
            opened_at=NOW,
            exit_plan=ExitPlan(stop_loss=98.0, take_profit_levels=(103.0,)),
            confidence=80,
        )
