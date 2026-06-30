from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from crypto_flow_bot_v2.candidate_engine import CandidateEngineResult
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
from crypto_flow_bot_v2.signal_governor import SignalGovernorDecision, SignalGovernorResult
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
    def __init__(self, results: dict[str, CandidateEngineResult]) -> None:
        self.results = results
        self.discarded: list[SignalDecision] = []

    def process(
        self,
        snapshot: MarketSnapshot,
        decision: SignalDecision,
    ) -> CandidateEngineResult:
        return self.results[snapshot.symbol]

    def discard_decision(self, decision: SignalDecision) -> None:
        self.discarded.append(decision)


class FakeSignalGovernor:
    def select(self, decisions: tuple[SignalDecision, ...]) -> SignalGovernorResult:
        by_symbol = {decision.symbol: decision for decision in decisions}
        return SignalGovernorResult(
            allowed=(
                SignalGovernorDecision(
                    decision=by_symbol["BTCUSDT"],
                    passed=True,
                    reason="ranked first",
                    rank=1,
                    final_score=90.0,
                ),
            ),
            skipped=(
                SignalGovernorDecision(
                    decision=by_symbol["ETHUSDT"],
                    passed=False,
                    reason="max signals per scan",
                    rank=2,
                    final_score=82.0,
                ),
            ),
        )

    def record_sent(self, decision: SignalDecision) -> None:
        return None


def test_live_cycle_decision_summary_counts_cycle_outcomes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    config = _config(symbols=symbols)
    decisions = {
        "BTCUSDT": _trade_decision("BTCUSDT", confidence=90),
        "ETHUSDT": _trade_decision("ETHUSDT", confidence=82),
        "SOLUSDT": _trade_decision("SOLUSDT", confidence=68),
        "XRPUSDT": _no_trade_decision("XRPUSDT"),
    }
    candidate_results = {
        "BTCUSDT": CandidateEngineResult(
            decision=decisions["BTCUSDT"],
            candidate=None,
            reason="score_above_signal_threshold",
        ),
        "ETHUSDT": CandidateEngineResult(
            decision=decisions["ETHUSDT"],
            candidate=None,
            reason="candidate_matured",
        ),
        "SOLUSDT": CandidateEngineResult(
            decision=None,
            candidate=_candidate(),
            reason="candidate_saved_or_updated",
        ),
        "XRPUSDT": CandidateEngineResult(
            decision=None,
            candidate=None,
            reason="hard_filters_not_passed",
        ),
    }
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(
            {symbol: _snapshot(symbol) for symbol in symbols},
        ),
        signal_engine=FakeSignalEngine(decisions),
        position_manager=VirtualPositionManager(config),
        telegram_alerts=FakeTelegramAlerts(),
        signal_governor=FakeSignalGovernor(),
        candidate_engine=FakeCandidateEngine(candidate_results),
    )

    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        report = runner.run_once()

    summary = _only_summary(caplog)
    assert report.positions_opened == 1
    assert summary["symbols_checked"] == 4
    assert summary["rfa_trade"] == 3
    assert summary["rfa_no_trade"] == 1
    assert summary["candidate_emitted"] == 2
    assert summary["candidate_saved"] == 1
    assert summary["candidate_blocked"] == 1
    assert summary["governor_allowed"] == 1
    assert summary["governor_skipped"] == 1
    assert summary["positions_opened"] == 1
    assert summary["telegram_sent"] == 2
    assert summary["telegram_errors"] == 0
    assert summary["top_blocked_reasons"] == [
        {"reason": "confidence_below_signal_minimum", "count": 1},
        {"reason": "hard_filters_not_passed", "count": 1},
        {"reason": "max signals per scan", "count": 1},
    ]


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


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        current_score=0.66,
        best_score=0.71,
        maturity_ticks=2,
        missing_conditions=("score_below_signal_threshold",),
        hard_filters_passed=True,
    )


def _trade_decision(symbol: str, *, confidence: int) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=confidence,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence", "risk/reward=1.67"),
    )


def _no_trade_decision(symbol: str) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=50,
        reasons=("not enough evidence",),
        blocked_reason="confidence_below_signal_minimum",
    )


def _only_summary(caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    summaries = [
        record.live_cycle_decision_summary
        for record in caplog.records
        if hasattr(record, "live_cycle_decision_summary")
    ]
    assert len(summaries) == 1
    return summaries[0]


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
            "signal_governor": {
                "enabled": True,
                "max_signals_per_scan": 1,
                "max_signals_per_hour": 4,
                "per_symbol_cooldown_minutes": 90,
                "same_direction_cluster_limit": 2,
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
