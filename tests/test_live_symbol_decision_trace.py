from datetime import UTC, datetime

import pytest

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalScoreBreakdown,
    SignalType,
)
from crypto_flow_bot_v2.position_manager import (
    PositionEvent,
    VirtualPositionManager,
)
from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeSnapshotBuilder:
    def __init__(self, snapshots: dict[str, MarketSnapshot]) -> None:
        self.snapshots = snapshots

    def build(self, symbol: str) -> MarketSnapshot:
        return self.snapshots[symbol]


class FakeSignalEngine:
    def __init__(self, decisions: dict[str, SignalDecision]) -> None:
        self.decisions = decisions

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        return self.decisions[snapshot.symbol]


class FakeTelegramAlerts:
    def __init__(self, status: TelegramAlertStatus = TelegramAlertStatus.SENT) -> None:
        self.status = status

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        return TelegramAlertResult(status=self.status, message=self.status.value)

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        return TelegramAlertResult(status=self.status, message=self.status.value)


def test_live_symbol_decision_trace_for_opened_trade(caplog: pytest.LogCaptureFixture) -> None:
    config = _config(symbols=("BTCUSDT",))
    decision = _trade_decision(
        "BTCUSDT",
        score_breakdown=SignalScoreBreakdown(
            base_score=76,
            regime="TREND_UP",
            regime_confidence=0.82,
            regime_adjustment=3,
            final_score=79,
            reason="regime confirmation",
        ),
    )
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")}),
        signal_engine=FakeSignalEngine({"BTCUSDT": decision}),
        position_manager=VirtualPositionManager(config),
        telegram_alerts=FakeTelegramAlerts(),
    )

    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        runner.run_once()

    trace = _only_trace(caplog)
    assert trace["symbol"] == "BTCUSDT"
    assert trace["timestamp"] == NOW.isoformat()
    assert trace["rfa_decision"] == "LONG_CONTINUATION"
    assert trace["direction"] == "LONG"
    assert trace["confidence"] == 80
    assert trace["blocked_reason"] is None
    assert trace["score_breakdown"] == {
        "base_score": 76,
        "regime": "TREND_UP",
        "regime_confidence": 0.82,
        "regime_adjustment": 3,
        "final_score": 79,
        "reason": "regime confirmation",
    }
    assert trace["position_opened"] is True
    assert trace["telegram_sent"] == 2
    assert trace["telegram_skipped"] == 0
    assert trace["telegram_errors"] == 0


def test_live_symbol_decision_trace_for_no_trade(caplog: pytest.LogCaptureFixture) -> None:
    config = _config(symbols=("BTCUSDT",))
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")}),
        signal_engine=FakeSignalEngine({"BTCUSDT": _no_trade_decision("BTCUSDT")}),
        position_manager=VirtualPositionManager(config),
        telegram_alerts=FakeTelegramAlerts(),
    )

    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        runner.run_once()

    trace = _only_trace(caplog)
    assert trace["symbol"] == "BTCUSDT"
    assert trace["rfa_decision"] == "NO_TRADE"
    assert trace["direction"] == "NONE"
    assert trace["confidence"] == 50
    assert trace["blocked_reason"] == "confidence_below_signal_minimum"
    assert trace["score_breakdown"] is None
    assert trace["position_opened"] is False
    assert trace["telegram_sent"] == 0
    assert trace["telegram_skipped"] == 1
    assert trace["telegram_errors"] == 0


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


def _trade_decision(
    symbol: str,
    score_breakdown: SignalScoreBreakdown | None = None,
) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=80,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence", "risk/reward=1.67"),
        score_breakdown=score_breakdown,
    )


def _no_trade_decision(symbol: str) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=50,
        entry_price=None,
        stop_loss=None,
        take_profit_levels=(),
        reasons=("not enough evidence",),
        blocked_reason="confidence_below_signal_minimum",
    )


def _only_trace(caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    traces = [
        record.live_symbol_decision_trace
        for record in caplog.records
        if hasattr(record, "live_symbol_decision_trace")
    ]
    assert len(traces) == 1
    return traces[0]


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
