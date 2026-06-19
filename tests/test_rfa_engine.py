from datetime import UTC, datetime

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDirection,
    SignalType,
)
from crypto_flow_bot_v2.rfa_engine import RFAEngine

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_rfa_engine_emits_long_continuation_with_atr_exits() -> None:
    decision = RFAEngine(_config()).evaluate(_snapshot())

    assert decision.signal_type is SignalType.LONG_CONTINUATION
    assert decision.direction is SignalDirection.LONG
    assert decision.confidence >= 85
    assert decision.entry_price == 100.0
    assert decision.stop_loss == 97.0
    assert decision.take_profit_levels == (103.0, 105.0, 108.0)
    assert decision.blocked_reason is None
    assert any(reason.startswith("risk/reward=") for reason in decision.reasons)


def test_rfa_engine_emits_short_continuation_with_atr_exits() -> None:
    snapshot = _snapshot(
        regime=MarketRegime.TREND_DOWN,
        metrics={
            "entry_return_pct": -1.4,
            "context_return_pct": -2.1,
            "macro_return_pct": -3.2,
            "entry_atr": 2.0,
            "entry_atr_pct": 2.0,
            "entry_taker_buy_quote_ratio": 0.36,
            "open_interest": 12_000.0,
            "funding_rate": -0.0002,
            "long_short_ratio": 0.78,
            "taker_buy_sell_ratio": 0.70,
            "liquidation_buy_notional": 20_000.0,
            "liquidation_sell_notional": 120_000.0,
        },
    )

    decision = RFAEngine(_config()).evaluate(snapshot)

    assert decision.signal_type is SignalType.SHORT_CONTINUATION
    assert decision.direction is SignalDirection.SHORT
    assert decision.confidence >= 85
    assert decision.stop_loss == 103.0
    assert decision.take_profit_levels == (97.0, 95.0, 92.0)
    assert decision.blocked_reason is None


def test_rfa_engine_blocks_macro_conflict() -> None:
    snapshot = _snapshot(metrics={**_long_metrics(), "macro_return_pct": -2.0})

    decision = RFAEngine(_config()).evaluate(snapshot)

    assert decision.signal_type is SignalType.NO_TRADE
    assert decision.direction is SignalDirection.NONE
    assert decision.blocked_reason == "macro_alignment_conflict"
    assert decision.entry_price is None
    assert decision.stop_loss is None


def test_rfa_engine_blocks_low_confidence_watch_only_decision() -> None:
    snapshot = _snapshot(
        regime=MarketRegime.RANGE,
        metrics={
            "entry_return_pct": 0.30,
            "context_return_pct": 0.30,
            "macro_return_pct": 0.30,
            "entry_atr": 2.0,
            "entry_atr_pct": 2.0,
            "entry_taker_buy_quote_ratio": 0.53,
            "open_interest": 12_000.0,
            "funding_rate": 0.0,
            "long_short_ratio": 1.01,
            "taker_buy_sell_ratio": 1.01,
            "liquidation_buy_notional": 0.0,
            "liquidation_sell_notional": 0.0,
        },
    )

    decision = RFAEngine(_config()).evaluate(snapshot)

    assert decision.signal_type is SignalType.NO_TRADE
    assert decision.confidence < 70
    assert decision.blocked_reason in {
        "confidence_below_signal_minimum",
        "directional_edge_too_small",
        "insufficient_rfa_confluence",
    }


def test_rfa_engine_blocks_missing_required_metric() -> None:
    metrics = dict(_long_metrics())
    del metrics["funding_rate"]
    snapshot = _snapshot(metrics=metrics)

    decision = RFAEngine(_config()).evaluate(snapshot)

    assert decision.signal_type is SignalType.NO_TRADE
    assert decision.blocked_reason == "missing_metrics:funding_rate"


def _snapshot(
    regime: MarketRegime = MarketRegime.TREND_UP,
    metrics: dict[str, float] | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        timestamp=NOW,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=100.0,
        regime=regime,
        metrics=_long_metrics() if metrics is None else metrics,
    )


def _long_metrics() -> dict[str, float]:
    return {
        "entry_return_pct": 1.4,
        "context_return_pct": 2.1,
        "macro_return_pct": 3.2,
        "entry_atr": 2.0,
        "entry_atr_pct": 2.0,
        "entry_taker_buy_quote_ratio": 0.64,
        "open_interest": 12_000.0,
        "funding_rate": 0.0002,
        "long_short_ratio": 1.22,
        "taker_buy_sell_ratio": 1.40,
        "liquidation_buy_notional": 120_000.0,
        "liquidation_sell_notional": 20_000.0,
    }


def _config() -> BotConfig:
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
    )
