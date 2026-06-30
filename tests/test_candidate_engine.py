from datetime import UTC, datetime, timedelta

from crypto_flow_bot_v2.candidate_engine import StatefulCandidateEngine
from crypto_flow_bot_v2.config import parse_config
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_candidate_is_created_for_near_miss_score() -> None:
    engine = StatefulCandidateEngine(_config())

    result = engine.process(_snapshot(), _trade_decision(confidence=70))

    assert result.decision is None
    assert len(engine.candidates) == 1
    candidate = engine.candidates[0]
    assert candidate.key.as_string() == "BTCUSDT:LONG:LONG_CONTINUATION:15m"
    assert candidate.current_score == 0.70
    assert candidate.best_score == 0.70
    assert candidate.maturity_ticks == 1


def test_candidate_is_updated_instead_of_duplicated() -> None:
    engine = StatefulCandidateEngine(_config())

    engine.process(_snapshot(), _trade_decision(confidence=70))
    engine.process(
        _snapshot(timestamp=NOW + timedelta(minutes=15)),
        _trade_decision(confidence=75, timestamp=NOW + timedelta(minutes=15)),
    )

    assert len(engine.candidates) == 1
    candidate = engine.candidates[0]
    assert candidate.current_score == 0.75
    assert candidate.best_score == 0.75
    assert candidate.maturity_ticks == 2
    assert candidate.last_seen_at == NOW + timedelta(minutes=15)


def test_candidate_expires_by_ttl() -> None:
    engine = StatefulCandidateEngine(_config())
    engine.process(_snapshot(), _trade_decision(confidence=70))

    engine.prune(NOW + timedelta(minutes=121))

    assert engine.candidates == ()


def test_candidate_is_invalidated_when_score_falls_below_minimum() -> None:
    engine = StatefulCandidateEngine(_config())
    engine.process(_snapshot(), _trade_decision(confidence=70))

    result = engine.process(
        _snapshot(timestamp=NOW + timedelta(minutes=15)),
        _trade_decision(confidence=60, timestamp=NOW + timedelta(minutes=15)),
    )

    assert result.decision is None
    assert result.reason == "score_below_min_candidate_score"
    assert engine.candidates == ()


def test_maturity_bonus_is_capped() -> None:
    engine = StatefulCandidateEngine(_config())

    first = engine.process(_snapshot(), _trade_decision(confidence=79))
    second = engine.process(
        _snapshot(timestamp=NOW + timedelta(minutes=15)),
        _trade_decision(confidence=79, timestamp=NOW + timedelta(minutes=15)),
    )
    third = engine.process(
        _snapshot(timestamp=NOW + timedelta(minutes=30)),
        _trade_decision(confidence=79, timestamp=NOW + timedelta(minutes=30)),
    )

    assert first.decision is None
    assert second.decision is not None
    assert third.decision is not None
    assert second.decision.confidence == 84
    assert third.decision.confidence == 84


def test_candidate_cannot_signal_without_hard_filters() -> None:
    engine = StatefulCandidateEngine(_config())

    first = engine.process(_snapshot(), _trade_decision(confidence=79, stop_loss=None))
    second = engine.process(
        _snapshot(timestamp=NOW + timedelta(minutes=15)),
        _trade_decision(
            confidence=79,
            stop_loss=None,
            timestamp=NOW + timedelta(minutes=15),
        ),
    )

    assert first.decision is None
    assert second.decision is None
    assert len(engine.candidates) == 1
    assert engine.candidates[0].hard_filters_passed is False


def test_parse_config_candidate_engine_section() -> None:
    raw = _raw_config()
    raw["candidate_engine"] = {
        "enabled": True,
        "min_candidate_score": 0.65,
        "signal_threshold": 0.80,
        "candidate_ttl_minutes": 120,
        "min_maturity_ticks": 2,
        "max_maturity_bonus": 0.05,
        "max_candidates_total": 100,
        "max_candidates_per_symbol": 2,
        "hard_filters_required": True,
    }

    config = parse_config(raw)

    assert config.candidate_engine.enabled is True
    assert config.candidate_engine.min_candidate_score == 0.65
    assert config.candidate_engine.signal_threshold == 0.80
    assert config.candidate_engine.max_maturity_bonus == 0.05


def _snapshot(
    symbol: str = "BTCUSDT",
    timestamp: datetime = NOW,
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        timestamp=timestamp,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=100.0,
        regime=MarketRegime.TREND_UP,
        metrics={},
    )


def _trade_decision(
    *,
    confidence: int,
    timestamp: datetime = NOW,
    stop_loss: float | None = 97.0,
) -> SignalDecision:
    return SignalDecision(
        symbol="BTCUSDT",
        timestamp=timestamp,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=confidence,
        entry_price=100.0,
        stop_loss=stop_loss,
        take_profit_levels=(103.0, 105.0) if stop_loss is not None else (),
        reasons=("+10: rfa confluence", "risk/reward=1.67"),
    )


def _config():
    return parse_config(_raw_config())


def _raw_config() -> dict[str, object]:
    return {
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
            "min_candidate_score": 0.65,
            "signal_threshold": 0.80,
            "candidate_ttl_minutes": 120,
            "min_maturity_ticks": 2,
            "max_maturity_bonus": 0.05,
            "max_candidates_total": 100,
            "max_candidates_per_symbol": 2,
            "hard_filters_required": True,
        },
    }
