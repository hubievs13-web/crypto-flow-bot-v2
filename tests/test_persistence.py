from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.persistence import (
    JsonPositionStateStore,
    PersistentVirtualPositionManager,
    PositionPersistenceError,
)
from crypto_flow_bot_v2.position_manager import (
    PositionEventType,
    PositionExitReason,
    VirtualPositionManager,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_json_position_store_round_trips_active_position(tmp_path: Path) -> None:
    config = _config()
    store = JsonPositionStateStore(tmp_path / "positions.json")
    manager = PersistentVirtualPositionManager(VirtualPositionManager(config), store)

    opened = manager.open_from_decision(_long_decision())
    updated = manager.update_price("BTCUSDT", price=102.0, timestamp=NOW + timedelta(minutes=15))

    restored = PersistentVirtualPositionManager(VirtualPositionManager(config), store)
    position = restored.get_active_position("BTCUSDT")

    assert opened.event_type is PositionEventType.OPENED
    assert updated.event_type is PositionEventType.UPDATED
    assert position is not None
    assert position.symbol == "BTCUSDT"
    assert position.entry_price == 100.0
    assert position.exit_plan.trailing_stop == 100.0


def test_json_position_store_persists_cooldown_after_close(tmp_path: Path) -> None:
    config = _config()
    store = JsonPositionStateStore(tmp_path / "positions.json")
    manager = PersistentVirtualPositionManager(VirtualPositionManager(config), store)

    manager.open_from_decision(_long_decision())
    closed = manager.close_position(
        symbol="BTCUSDT",
        price=101.0,
        timestamp=NOW + timedelta(minutes=10),
        reason=PositionExitReason.MANUAL,
    )
    restored = PersistentVirtualPositionManager(VirtualPositionManager(config), store)

    assert closed.event_type is PositionEventType.CLOSED
    assert restored.get_active_position("BTCUSDT") is None
    assert restored.is_on_cooldown("BTCUSDT", NOW + timedelta(minutes=20)) is True
    assert restored.is_on_cooldown("BTCUSDT", NOW + timedelta(minutes=80)) is False


def test_json_position_store_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "positions.json"
    path.write_text("not-json", encoding="utf-8")
    store = JsonPositionStateStore(path)

    with pytest.raises(PositionPersistenceError, match="Invalid JSON"):
        store.load()


def _long_decision() -> SignalDecision:
    return SignalDecision(
        symbol="BTCUSDT",
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=80,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence", "risk/reward=1.67"),
    )


def _config() -> BotConfig:
    return parse_config(
        {
            "symbols": ["BTCUSDT"],
            "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
            "binance": {
                "base_url": "https://fapi.binance.com",
                "timeout_seconds": 10.0,
                "kline_limit": 300,
                "derivatives_data_limit": 100,
            },
            "telegram": {
                "enabled": True,
                "bot_token_env": "BOT_ENV",
                "chat_id_env": "CHAT_ENV",
                "base_url": "https://api.telegram.org",
                "timeout_seconds": 10.0,
                "parse_mode": "HTML",
            },
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
