from datetime import UTC, datetime

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
    VirtualPosition,
)
from crypto_flow_bot_v2.position_manager import PositionEvent, PositionEventType
from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeSnapshotBuilder:
    def build(self, symbol: str) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            timestamp=NOW,
            entry_timeframe="15m",
            context_timeframe="1h",
            macro_timeframe="4h",
            price=100.0,
            regime=MarketRegime.TREND_UP,
            metrics={},
        )


class NoTradeSignalEngine:
    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        return SignalDecision(
            symbol=snapshot.symbol,
            timestamp=snapshot.timestamp,
            signal_type=SignalType.NO_TRADE,
            direction=SignalDirection.NONE,
            confidence=56,
            entry_price=None,
            stop_loss=None,
            take_profit_levels=(),
            reasons=("insufficient RFA confluence",),
            blocked_reason="insufficient_rfa_confluence",
        )


class RecordingPositionManager:
    def __init__(self) -> None:
        self.open_calls: list[SignalDecision] = []

    def active_positions(self) -> tuple[VirtualPosition, ...]:
        return ()

    def update_price(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        invalidation_reason: str | None = None,
    ) -> PositionEvent:
        return PositionEvent(
            event_type=PositionEventType.IGNORED,
            symbol=symbol,
            timestamp=timestamp,
            message="no active position for symbol",
        )

    def open_from_decision(self, decision: SignalDecision) -> PositionEvent:
        self.open_calls.append(decision)
        return PositionEvent(
            event_type=PositionEventType.IGNORED,
            symbol=decision.symbol,
            timestamp=decision.timestamp,
            message="decision ignored",
        )


class RecordingTelegramAlerts:
    def __init__(self) -> None:
        self.signal_calls: list[SignalDecision] = []
        self.position_event_calls: list[PositionEvent] = []
        self.no_trade_diagnostic_calls: list[SignalDecision] = []
        self.raw_send_calls: list[str] = []

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        self.signal_calls.append(decision)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        self.position_event_calls.append(event)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def send_no_trade_diagnostic(self, decision: SignalDecision) -> TelegramAlertResult:
        self.no_trade_diagnostic_calls.append(decision)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def _send(self, text: str) -> TelegramAlertResult:
        self.raw_send_calls.append(text)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")


def test_no_trade_decision_does_not_send_telegram_diagnostic() -> None:
    config = _config(symbols=("BTCUSDT",))
    position_manager = RecordingPositionManager()
    telegram_alerts = RecordingTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(),
        signal_engine=NoTradeSignalEngine(),
        position_manager=position_manager,
        telegram_alerts=telegram_alerts,
    )

    report = runner.run_once()

    assert report.snapshots_built == 1
    assert report.decisions_evaluated == 1
    assert report.positions_opened == 0
    assert report.positions_closed == 0
    assert report.telegram_alerts_sent == 0
    assert report.telegram_alerts_skipped == 0
    assert report.telegram_alert_errors == 0
    assert len(position_manager.open_calls) == 1
    assert telegram_alerts.signal_calls == []
    assert telegram_alerts.position_event_calls == []
    assert telegram_alerts.no_trade_diagnostic_calls == []
    assert telegram_alerts.raw_send_calls == []


def _config(symbols: tuple[str, ...]) -> BotConfig:
    return parse_config(
        {
            "symbols": list(symbols),
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
