from datetime import UTC, datetime

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import ExitPlan, SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.models import VirtualPosition
from crypto_flow_bot_v2.position_manager import (
    PositionEvent,
    PositionEventType,
    PositionExitReason,
)
from crypto_flow_bot_v2.telegram import (
    TelegramAlertService,
    TelegramAlertStatus,
    TelegramSendResult,
    format_position_event,
    format_signal_decision,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeTelegramTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def send_message(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        parse_mode: str,
    ) -> TelegramSendResult:
        self.calls.append((bot_token, chat_id, text, parse_mode))
        return TelegramSendResult(ok=True, message_id=42)


def test_format_signal_decision_includes_core_trade_plan() -> None:
    text = format_signal_decision(_long_decision(), _config())

    assert "<b>RFA SIGNAL — STRONG</b>" in text
    assert "BTCUSDT" in text
    assert "LONG_CONTINUATION" in text
    assert "Confidence: <b>86/100</b>" in text
    assert "Entry: <code>100</code>" in text
    assert "Stop loss: <code>97</code>" in text
    assert "Take profit: <code>103 / 105 / 108</code>" in text
    assert "Risk/reward: <code>2.67</code>" in text
    assert "rfa confluence" in text


def test_telegram_alert_service_sends_alertable_signal(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ENV", "TOKEN")
    monkeypatch.setenv("CHAT_ENV", "CHAT")
    transport = FakeTelegramTransport()
    service = TelegramAlertService(_config(enabled=True), transport=transport)

    result = service.send_signal(_long_decision())

    assert result.status is TelegramAlertStatus.SENT
    assert result.send_result == TelegramSendResult(ok=True, message_id=42)
    assert len(transport.calls) == 1
    bot_token, chat_id, text, parse_mode = transport.calls[0]
    assert bot_token == "TOKEN"
    assert chat_id == "CHAT"
    assert "RFA SIGNAL" in text
    assert parse_mode == "HTML"


def test_telegram_alert_service_skips_disabled_signal(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ENV", "TOKEN")
    monkeypatch.setenv("CHAT_ENV", "CHAT")
    transport = FakeTelegramTransport()
    service = TelegramAlertService(_config(enabled=False), transport=transport)

    result = service.send_signal(_long_decision())

    assert result.status is TelegramAlertStatus.SKIPPED
    assert result.message == "telegram alerts are disabled"
    assert transport.calls == []


def test_telegram_alert_service_skips_missing_environment(monkeypatch) -> None:
    monkeypatch.delenv("BOT_ENV", raising=False)
    monkeypatch.delenv("CHAT_ENV", raising=False)
    transport = FakeTelegramTransport()
    service = TelegramAlertService(_config(enabled=True), transport=transport)

    result = service.send_signal(_long_decision())

    assert result.status is TelegramAlertStatus.SKIPPED
    assert result.message == "telegram credentials are not configured in environment"
    assert transport.calls == []


def test_telegram_alert_service_skips_no_trade_decision(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ENV", "TOKEN")
    monkeypatch.setenv("CHAT_ENV", "CHAT")
    transport = FakeTelegramTransport()
    service = TelegramAlertService(_config(enabled=True), transport=transport)

    result = service.send_signal(
        SignalDecision(
            symbol="BTCUSDT",
            timestamp=NOW,
            signal_type=SignalType.NO_TRADE,
            direction=SignalDirection.NONE,
            confidence=65,
            blocked_reason="confidence_below_signal_minimum",
        )
    )

    assert result.status is TelegramAlertStatus.SKIPPED
    assert result.message == "signal decision is not alertable"
    assert transport.calls == []


def test_format_position_event_closed_includes_exit_details() -> None:
    text = format_position_event(
        PositionEvent(
            event_type=PositionEventType.CLOSED,
            symbol="BTCUSDT",
            timestamp=NOW,
            position=_position(active=False),
            exit_reason=PositionExitReason.TAKE_PROFIT,
            exit_price=108.0,
            pnl_pct=8.0,
            message="virtual position closed: TAKE_PROFIT",
        )
    )

    assert "<b>VIRTUAL POSITION CLOSED</b>" in text
    assert "BTCUSDT" in text
    assert "TAKE_PROFIT" in text
    assert "Exit: <code>108</code>" in text
    assert "PnL: <b>8.00%</b>" in text


def test_telegram_alert_service_sends_opened_position_event(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ENV", "TOKEN")
    monkeypatch.setenv("CHAT_ENV", "CHAT")
    transport = FakeTelegramTransport()
    service = TelegramAlertService(_config(enabled=True), transport=transport)

    result = service.send_position_event(
        PositionEvent(
            event_type=PositionEventType.OPENED,
            symbol="BTCUSDT",
            timestamp=NOW,
            position=_position(),
            message="virtual position opened",
        )
    )

    assert result.status is TelegramAlertStatus.SENT
    assert len(transport.calls) == 1
    assert "VIRTUAL POSITION OPENED" in transport.calls[0][2]


def _long_decision() -> SignalDecision:
    return SignalDecision(
        symbol="BTCUSDT",
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=86,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0, 108.0),
        reasons=("rfa confluence", "risk/reward=2.67"),
    )


def _position(active: bool = True) -> VirtualPosition:
    return VirtualPosition(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        opened_at=NOW,
        exit_plan=ExitPlan(
            stop_loss=97.0,
            take_profit_levels=(103.0, 105.0, 108.0),
            trailing_stop=97.0,
            time_stop_minutes=240,
            invalidation_reason=None,
        ),
        confidence=86,
        source_signal_type=SignalType.LONG_CONTINUATION,
        active=active,
    )


def _config(enabled: bool = True) -> BotConfig:
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
            "telegram": {
                "enabled": enabled,
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
