from datetime import UTC, datetime, timedelta

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.position_manager import (
    PositionEventType,
    PositionExitReason,
    VirtualPositionManager,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_position_manager_opens_tradeable_signal_and_blocks_duplicate() -> None:
    manager = VirtualPositionManager(_config())

    opened = manager.open_from_decision(_long_decision())
    duplicate = manager.open_from_decision(_long_decision(timestamp=NOW + timedelta(minutes=1)))

    assert opened.event_type is PositionEventType.OPENED
    assert opened.position is not None
    assert opened.position.symbol == "BTCUSDT"
    assert opened.position.exit_plan.trailing_stop == 97.0
    assert duplicate.event_type is PositionEventType.BLOCKED
    assert duplicate.message == "active position already exists for symbol"


def test_position_manager_ignores_no_trade_decision() -> None:
    manager = VirtualPositionManager(_config())
    decision = SignalDecision(
        symbol="BTCUSDT",
        timestamp=NOW,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=60,
        entry_price=None,
        stop_loss=None,
        blocked_reason="confidence_below_signal_minimum",
    )

    event = manager.open_from_decision(decision)

    assert event.event_type is PositionEventType.IGNORED
    assert manager.active_positions() == ()


def test_position_manager_trailing_stop_ratchets_and_closes_long() -> None:
    manager = VirtualPositionManager(_config())
    manager.open_from_decision(_long_decision())

    update = manager.update_price("btcusdt", price=106.0, timestamp=NOW + timedelta(minutes=15))
    closed = manager.update_price("BTCUSDT", price=103.5, timestamp=NOW + timedelta(minutes=30))

    assert update.event_type is PositionEventType.UPDATED
    assert update.position is not None
    assert update.position.exit_plan.trailing_stop == 104.0
    assert closed.event_type is PositionEventType.CLOSED
    assert closed.exit_reason is PositionExitReason.TRAILING_STOP
    assert closed.pnl_pct == 3.5
    assert manager.active_positions() == ()


def test_position_manager_closes_at_final_take_profit() -> None:
    manager = VirtualPositionManager(_config())
    manager.open_from_decision(_long_decision())

    closed = manager.update_price("BTCUSDT", price=108.0, timestamp=NOW + timedelta(minutes=30))

    assert closed.event_type is PositionEventType.CLOSED
    assert closed.exit_reason is PositionExitReason.TAKE_PROFIT
    assert closed.pnl_pct == 8.0


def test_position_manager_sets_cooldown_after_close() -> None:
    manager = VirtualPositionManager(_config())
    manager.open_from_decision(_long_decision())
    manager.close_position(
        symbol="BTCUSDT",
        price=101.0,
        timestamp=NOW + timedelta(minutes=10),
    )

    blocked = manager.open_from_decision(_long_decision(timestamp=NOW + timedelta(minutes=20)))
    opened_after_cooldown = manager.open_from_decision(
        _long_decision(timestamp=NOW + timedelta(minutes=71))
    )

    assert blocked.event_type is PositionEventType.BLOCKED
    assert blocked.message == "symbol cooldown is still active"
    assert opened_after_cooldown.event_type is PositionEventType.OPENED


def test_position_manager_closes_by_time_stop() -> None:
    manager = VirtualPositionManager(_config())
    manager.open_from_decision(_long_decision())

    event = manager.update_price("BTCUSDT", price=101.0, timestamp=NOW + timedelta(minutes=240))

    assert event.event_type is PositionEventType.CLOSED
    assert event.exit_reason is PositionExitReason.TIME_STOP


def test_position_manager_closes_short_with_positive_pnl() -> None:
    manager = VirtualPositionManager(_config())
    manager.open_from_decision(_short_decision())

    event = manager.update_price("ETHUSDT", price=92.0, timestamp=NOW + timedelta(minutes=30))

    assert event.event_type is PositionEventType.CLOSED
    assert event.exit_reason is PositionExitReason.TAKE_PROFIT
    assert event.pnl_pct == 8.0


def test_position_manager_closes_on_reason_invalidation() -> None:
    manager = VirtualPositionManager(_config())
    manager.open_from_decision(_long_decision())

    event = manager.update_price(
        "BTCUSDT",
        price=99.0,
        timestamp=NOW + timedelta(minutes=30),
        invalidation_reason="context_structure_broken",
    )

    assert event.event_type is PositionEventType.CLOSED
    assert event.exit_reason is PositionExitReason.REASON_INVALIDATION
    assert event.message == "context_structure_broken"


def _long_decision(timestamp: datetime = NOW) -> SignalDecision:
    return SignalDecision(
        symbol="BTCUSDT",
        timestamp=timestamp,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=86,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0, 108.0),
        reasons=("rfa confluence",),
    )


def _short_decision() -> SignalDecision:
    return SignalDecision(
        symbol="ETHUSDT",
        timestamp=NOW,
        signal_type=SignalType.SHORT_CONTINUATION,
        direction=SignalDirection.SHORT,
        confidence=86,
        entry_price=100.0,
        stop_loss=103.0,
        take_profit_levels=(97.0, 95.0, 92.0),
        reasons=("rfa confluence",),
    )


def _config() -> BotConfig:
    return parse_config(
        {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
            "binance": {
                "base_url": "https://fapi.binance.com",
                "timeout_seconds": 10.0,
                "kline_limit": 300,
                "derivatives_data_limit": 100,
            },
            "telegram": {"enabled": False, "bot_token_env": "A", "chat_id_env": "B"},
            "logging": {"level": "INFO", "jsonl_path": "logs/events.jsonl"},
            "risk": {
                "min_risk_reward": 1.5,
                "atr_stop_multiplier": 1.5,
                "atr_tp_multipliers": [1.5, 2.5, 4.0],
                "trailing_atr_multiplier": 1.0,
                "max_position_minutes": 240,
                "cooldown_minutes": 60,
            },
            "rfa_engine": {
                "min_signal_confidence": 70,
                "watch_confidence": 60,
                "strong_signal_confidence": 85,
                "require_context_alignment": True,
                "require_macro_alignment": True,
            },
        }
    )
