from datetime import UTC, datetime

import pytest

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.models import MarketRegime, MarketSnapshot, SignalDecision
from crypto_flow_bot_v2.models import SignalDirection, SignalType, VirtualPosition
from crypto_flow_bot_v2.position_manager import PositionEvent, PositionEventType
from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeSnapshotBuilder:
    def __init__(self, snapshot: MarketSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []

    def build(self, symbol: str) -> MarketSnapshot:
        self.calls.append(symbol)
        return self.snapshot


class FakeSignalEngine:
    def __init__(self, decision: SignalDecision) -> None:
        self.decision = decision
        self.calls: list[MarketSnapshot] = []

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        self.calls.append(snapshot)
        return self.decision


class FakePositionManager:
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


class FakeTelegramAlerts:
    def __init__(self, status: TelegramAlertStatus = TelegramAlertStatus.SENT) -> None:
        self.status = status
        self.signal_calls: list[SignalDecision] = []
        self.position_event_calls: list[PositionEvent] = []
        self.no_trade_diagnostic_calls: list[SignalDecision] = []

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        self.signal_calls.append(decision)
        return TelegramAlertResult(status=self.status, message=self.status.value)

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        self.position_event_calls.append(event)
        return TelegramAlertResult(status=self.status, message=self.status.value)

    def send_no_trade_diagnostic(self, decision: SignalDecision) -> TelegramAlertResult:
        self.no_trade_diagnostic_calls.append(decision)
        return TelegramAlertResult(status=self.status, message=self.status.value)


def test_no_trade_decision_logs_symbol_reason_confidence_and_sends_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _config(symbols=("BTCUSDT",))
    snapshot = _snapshot("BTCUSDT")
    decision = _no_trade_decision(
        "BTCUSDT",
        blocked_reason="macro_alignment_conflict",
        confidence=64,
    )
    position_manager = FakePositionManager()
    alerts = FakeTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(snapshot),
        signal_engine=FakeSignalEngine(decision),
        position_manager=position_manager,
        telegram_alerts=alerts,
    )

    with caplog.at_level("INFO"):
        report = runner.run_once()

    assert report.snapshots_built == 1
    assert report.decisions_evaluated == 1
    assert report.positions_opened == 0
    assert report.telegram_alerts_sent == 1
    assert report.telegram_alerts_skipped == 0
    assert report.telegram_alert_errors == 0
    assert alerts.no_trade_diagnostic_calls == [decision]
    assert alerts.signal_calls == []
    assert alerts.position_event_calls == []
    assert position_manager.open_calls == [decision]
    assert _logged_no_trade(caplog, "BTCUSDT", "macro_alignment_conflict", 64)


def test_no_trade_diagnostic_send_failure_is_counted_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingTelegramAlerts(FakeTelegramAlerts):
        def send_no_trade_diagnostic(self, decision: SignalDecision) -> TelegramAlertResult:
            raise RuntimeError("telegram down")

    config = _config(symbols=("ETHUSDT",))
    decision = _no_trade_decision("ETHUSDT", blocked_reason="missing_metrics", confidence=0)
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(_snapshot("ETHUSDT")),
        signal_engine=FakeSignalEngine(decision),
        position_manager=FakePositionManager(),
        telegram_alerts=FailingTelegramAlerts(),
    )

    with caplog.at_level("ERROR"):
        report = runner.run_once()

    assert report.decisions_evaluated == 1
    assert report.telegram_alert_errors == 1
    assert any(
        "failed to send NO_TRADE diagnostic for symbol=ETHUSDT" in record.getMessage()
        for record in caplog.records
    )


def _snapshot(symbol: str) -> MarketSnapshot:
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


def _no_trade_decision(symbol: str, blocked_reason: str, confidence: int) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=confidence,
        entry_price=None,
        stop_loss=None,
        take_profit_levels=(),
        reasons=("not enough evidence",),
        blocked_reason=blocked_reason,
    )


def _logged_no_trade(
    caplog: pytest.LogCaptureFixture,
    symbol: str,
    blocked_reason: str,
    confidence: int,
) -> bool:
    return any(
        "live NO_TRADE:" in record.getMessage()
        and f"symbol={symbol}" in record.getMessage()
        and f"blocked_reason={blocked_reason}" in record.getMessage()
        and f"confidence={confidence}" in record.getMessage()
        for record in caplog.records
    )


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
                "bot_" "token_env": "BOT_" "ENV",
                "chat_" "id_env": "CHAT_" "ENV",
                "base_url": "https://api.telegram" ".org",
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
