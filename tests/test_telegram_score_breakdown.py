from datetime import UTC, datetime

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import (
    SignalDecision,
    SignalDirection,
    SignalScoreBreakdown,
    SignalType,
)
from crypto_flow_bot_v2.telegram import format_signal_decision

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_telegram_signal_message_contains_score_breakdown() -> None:
    text = format_signal_decision(_decision_with_breakdown(), _config())

    assert "Base score: <b>71</b>" in text
    assert "Regime: <code>TREND_UP</code>" in text
    assert "Regime confidence: <b>0.72</b>" in text
    assert "Regime adjustment: <b>+3</b>" in text
    assert "Final score: <b>74</b>" in text


def _decision_with_breakdown() -> SignalDecision:
    return SignalDecision(
        symbol="BTCUSDT",
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=74,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence", "governor: passed (cooldown ok, rank=1)"),
        score_breakdown=SignalScoreBreakdown(
            base_score=71,
            regime="TREND_UP",
            regime_confidence=0.72,
            regime_adjustment=3,
            final_score=74,
            reason="trend alignment confirmed",
        ),
    )


def _config() -> BotConfig:
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
