from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
)
from crypto_flow_bot_v2.position_manager import PositionEvent, VirtualPositionManager
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
    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")


class FakeCandidateEngine:
    def __init__(self, result: object) -> None:
        self.result = result
        self.process_calls: list[tuple[MarketSnapshot, SignalDecision]] = []
        self.discard_calls: list[SignalDecision] = []

    def process(self, snapshot: MarketSnapshot, decision: SignalDecision) -> object:
        self.process_calls.append((snapshot, decision))
        return self.result

    def discard_decision(self, decision: SignalDecision) -> None:
        self.discard_calls.append(decision)


def test_live_trace_includes_full_candidate_engine_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _config(symbols=("BTCUSDT",))
    decision = _trade_decision("BTCUSDT")
    candidate = SimpleNamespace(
        current_score=0.66,
        best_score=0.71,
        maturity_ticks=3,
        missing_conditions=("score_below_signal_threshold", "insufficient_rfa_confluence"),
        hard_filters_passed=False,
    )
    candidate_result = SimpleNamespace(
        decision=None,
        candidate=candidate,
        reason="candidate_saved_or_updated",
    )
    candidate_engine = FakeCandidateEngine(candidate_result)
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")}),
        signal_engine=FakeSignalEngine({"BTCUSDT": decision}),
        position_manager=VirtualPositionManager(config),
        telegram_alerts=FakeTelegramAlerts(),
        candidate_engine=candidate_engine,
    )

    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        report = runner.run_once()

    trace = _only_trace(caplog)
    assert report.positions_opened == 0
    assert len(candidate_engine.process_calls) == 1
    assert candidate_engine.discard_calls == []
    assert trace["candidate_engine"] == {
        "reason": "candidate_saved_or_updated",
        "emitted": False,
        "current_score": 0.66,
        "best_score": 0.71,
        "maturity_ticks": 3,
        "missing_conditions": [
            "score_below_signal_threshold",
            "insufficient_rfa_confluence",
        ],
        "hard_filters_passed": False,
    }


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


def _trade_decision(symbol: str) -> SignalDecision:
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
            "candidate_engine": {
                "enabled": True,
                "min_candidate_score": 0.55,
                "signal_threshold": 0.72,
                "candidate_ttl_minutes": 90,
                "min_maturity_ticks": 2,
                "max_maturity_bonus": 0.08,
                "max_candidates_total": 20,
                "max_candidates_per_symbol": 3,
                "hard_filters_required": True,
            },
        }
    )
