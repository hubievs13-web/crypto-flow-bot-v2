from __future__ import annotations

import logging
from datetime import UTC, datetime

from crypto_flow_bot_v2.candidate_engine import CandidateEngineResult
from crypto_flow_bot_v2.config import parse_config
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
            regime=MarketRegime.RANGE,
            metrics={},
        )


class FakeSignalEngine:
    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        return SignalDecision(
            symbol=snapshot.symbol,
            timestamp=snapshot.timestamp,
            signal_type=SignalType.NO_TRADE,
            direction=SignalDirection.NONE,
            confidence=50,
            entry_price=None,
            stop_loss=None,
            take_profit_levels=(),
            reasons=("not enough evidence",),
            blocked_reason="confidence_below_signal_minimum",
        )


class FakePositionManager:
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
        return PositionEvent(
            event_type=PositionEventType.IGNORED,
            symbol=decision.symbol,
            timestamp=decision.timestamp,
            message="decision ignored",
        )


class FakeTelegramAlerts:
    def __init__(self) -> None:
        self.signal_calls: list[SignalDecision] = []
        self.position_event_calls: list[PositionEvent] = []
        self.no_trade_diagnostic_calls: list[SignalDecision] = []

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        self.signal_calls.append(decision)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        self.position_event_calls.append(event)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def send_no_trade_diagnostic(self, decision: SignalDecision) -> TelegramAlertResult:
        self.no_trade_diagnostic_calls.append(decision)
        return TelegramAlertResult(status=TelegramAlertStatus.SKIPPED, message="skipped")


class FakeCandidateEngine:
    def __init__(self) -> None:
        self.process_calls: list[SignalDecision] = []
        self.discard_calls: list[SignalDecision] = []

    def process(
        self,
        snapshot: MarketSnapshot,
        decision: SignalDecision,
    ) -> CandidateEngineResult:
        self.process_calls.append(decision)
        return CandidateEngineResult(decision=None, reason="candidate_saved_or_updated")

    def discard_decision(self, decision: SignalDecision) -> None:
        self.discard_calls.append(decision)


def test_live_diagnostics_summary_logs_interval_counts(caplog) -> None:
    config = _config()
    alerts = FakeTelegramAlerts()
    candidate_engine = FakeCandidateEngine()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(),
        signal_engine=FakeSignalEngine(),
        position_manager=FakePositionManager(),
        telegram_alerts=alerts,
        cycle_interval_seconds=1,
        sleeper=lambda _: None,
        candidate_engine=candidate_engine,
        diagnostic_summary_interval_cycles=2,
    )

    with caplog.at_level(logging.INFO, logger="crypto_flow_bot_v2.live_runner"):
        stats = runner.run(max_cycles=2)

    summaries = [
        record.getMessage()
        for record in caplog.records
        if "live diagnostics summary:" in record.getMessage()
    ]

    assert stats.cycles == 2
    assert summaries == [
        "live diagnostics summary: cycles=2 "
        "blocked_reason_counts=confidence_below_signal_minimum=2 "
        "candidate_engine_result_counts=candidate_saved_or_updated=2 "
        "decisions_evaluated=2 opened=0 alerts_sent=0 alerts_skipped=2"
    ]
    assert len(candidate_engine.process_calls) == 2
    assert candidate_engine.discard_calls == []
    assert alerts.signal_calls == []
    assert alerts.position_event_calls == []
    assert len(alerts.no_trade_diagnostic_calls) == 2


def _config():
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
            "candidate_engine": {
                "enabled": True,
                "min_candidate_score": 0.60,
                "signal_threshold": 0.70,
                "candidate_ttl_minutes": 180,
                "min_maturity_ticks": 2,
                "max_maturity_bonus": 0.03,
                "max_candidates_total": 100,
                "max_candidates_per_symbol": 2,
                "hard_filters_required": True,
            },
        }
    )
