from datetime import UTC, datetime, timedelta

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.signal_governor import SignalGovernor

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_governor_does_not_limit_signals_per_scan() -> None:
    governor = SignalGovernor(
        _config(
            max_signals_per_hour=10,
            same_direction_cluster_limit=10,
        )
    )
    decisions = tuple(_decision(symbol, score) for symbol, score in _scores(5))

    result = governor.select(decisions)

    assert [item.decision.symbol for item in result.allowed] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
    ]
    assert result.skipped == ()


def test_max_signals_per_hour_limits_signal_count() -> None:
    governor = SignalGovernor(_config(max_signals_per_hour=1))
    first = _decision("BTCUSDT", 90, timestamp=NOW)
    governor.record_sent(first)

    result = governor.select((_decision("ETHUSDT", 88, timestamp=NOW + timedelta(minutes=10)),))

    assert result.allowed == ()
    assert result.skipped[0].reason == "max_signals_per_hour reached"


def test_per_symbol_cooldown_works() -> None:
    governor = SignalGovernor(_config(per_symbol_cooldown_minutes=90))
    first = _decision("BTCUSDT", 90, timestamp=NOW)
    governor.record_sent(first)

    result = governor.select((_decision("BTCUSDT", 95, timestamp=NOW + timedelta(minutes=30)),))

    assert result.allowed == ()
    assert result.skipped[0].reason == "per_symbol_cooldown active"


def test_same_direction_signals_are_limited() -> None:
    governor = SignalGovernor(
        _config(
            max_signals_per_hour=5,
            same_direction_cluster_limit=2,
        )
    )
    decisions = (
        _decision("BTCUSDT", 90, direction=SignalDirection.LONG),
        _decision("ETHUSDT", 89, direction=SignalDirection.LONG),
        _decision("SOLUSDT", 88, direction=SignalDirection.LONG),
    )

    result = governor.select(decisions)

    assert [item.decision.symbol for item in result.allowed] == ["BTCUSDT", "ETHUSDT"]
    assert result.skipped[0].decision.symbol == "SOLUSDT"
    assert result.skipped[0].reason == "same_direction_cluster_limit reached"


def test_best_signals_are_ranked_by_score_risk_reward_and_volume_confirmation() -> None:
    governor = SignalGovernor(
        _config(
            max_signals_per_hour=3,
            same_direction_cluster_limit=3,
        )
    )
    decisions = (
        _decision("BTCUSDT", 80, take_profit_levels=(104.0, 106.0), reasons=("rfa",)),
        _decision("ETHUSDT", 80, take_profit_levels=(104.0, 108.0), reasons=("rfa",)),
        _decision(
            "SOLUSDT",
            80,
            take_profit_levels=(104.0, 108.0),
            reasons=("taker volume confirms flow",),
        ),
    )

    result = governor.select(decisions)

    assert [item.decision.symbol for item in result.allowed] == ["SOLUSDT", "ETHUSDT", "BTCUSDT"]


def test_governor_does_not_remove_all_signals_without_reason() -> None:
    governor = SignalGovernor(_config(max_signals_per_hour=4))

    result = governor.select((_decision("BTCUSDT", 80), _decision("ETHUSDT", 79)))

    assert len(result.allowed) == 2
    assert result.skipped == ()


def _scores(count: int) -> tuple[tuple[str, int], ...]:
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    return tuple((symbols[index], 90 - index) for index in range(count))


def _decision(
    symbol: str,
    score: int,
    *,
    direction: SignalDirection = SignalDirection.LONG,
    timestamp: datetime = NOW,
    take_profit_levels: tuple[float, ...] = (103.0, 105.0),
    reasons: tuple[str, ...] = ("rfa confluence",),
) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=timestamp,
        signal_type=(
            SignalType.LONG_CONTINUATION
            if direction is SignalDirection.LONG
            else SignalType.SHORT_CONTINUATION
        ),
        direction=direction,
        confidence=score,
        entry_price=100.0,
        stop_loss=97.0 if direction is SignalDirection.LONG else 103.0,
        take_profit_levels=take_profit_levels,
        reasons=reasons,
    )


def _config(
    *,
    max_signals_per_hour: int = 4,
    per_symbol_cooldown_minutes: int = 90,
    same_direction_cluster_limit: int = 2,
) -> BotConfig:
    raw = _raw_config()
    raw["signal_governor"] = {
        "enabled": True,
        "max_signals_per_hour": max_signals_per_hour,
        "per_symbol_cooldown_minutes": per_symbol_cooldown_minutes,
        "same_direction_cluster_limit": same_direction_cluster_limit,
        "ranking": {
            "primary": "final_score",
            "secondary": "risk_reward",
            "tertiary": "volume_confirmation",
        },
    }
    return parse_config(raw)


def _raw_config() -> dict[str, object]:
    return {
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
