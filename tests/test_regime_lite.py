from datetime import UTC, datetime

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
)
from crypto_flow_bot_v2.regime_lite import (
    LiteMarketRegime,
    RegimeDetection,
    RegimeLiteScoringLayer,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class StaticEngine:
    def __init__(self, decision: SignalDecision) -> None:
        self.decision = decision

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        return self.decision


class StaticDetector:
    def __init__(self, detection: RegimeDetection) -> None:
        self.detection = detection

    def detect(self, snapshot: MarketSnapshot) -> RegimeDetection:
        return self.detection


class FailingDetector:
    def detect(self, snapshot: MarketSnapshot) -> RegimeDetection:
        raise RuntimeError("detector failed")


def test_trend_up_adds_small_bonus_for_long() -> None:
    decision = _apply(
        decision=_trade_decision(direction=SignalDirection.LONG, confidence=71),
        detection=RegimeDetection(LiteMarketRegime.TREND_UP, 0.76, "trend up"),
    )

    assert decision.confidence == 74
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime_adjustment == 3


def test_trend_down_adds_small_bonus_for_short() -> None:
    decision = _apply(
        decision=_trade_decision(direction=SignalDirection.SHORT, confidence=71),
        detection=RegimeDetection(LiteMarketRegime.TREND_DOWN, 0.76, "trend down"),
    )

    assert decision.confidence == 74
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime == "TREND_DOWN"


def test_chop_adds_penalty_without_breaking_signal_floor() -> None:
    decision = _apply(
        decision=_trade_decision(direction=SignalDirection.LONG, confidence=80),
        detection=RegimeDetection(LiteMarketRegime.CHOP, 0.80, "chop"),
    )

    assert decision.confidence == 76
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime_adjustment == -4


def test_unknown_regime_gives_zero_adjustment() -> None:
    decision = _apply(
        decision=_trade_decision(direction=SignalDirection.LONG, confidence=72),
        detection=RegimeDetection(LiteMarketRegime.UNKNOWN, 0.0, "unknown"),
    )

    assert decision.confidence == 72
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime_adjustment == 0


def test_low_confidence_gives_zero_adjustment() -> None:
    decision = _apply(
        decision=_trade_decision(direction=SignalDirection.LONG, confidence=72),
        detection=RegimeDetection(LiteMarketRegime.TREND_UP, 0.64, "low confidence"),
    )

    assert decision.confidence == 72
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime_adjustment == 0


def test_detector_exception_gives_zero_adjustment() -> None:
    base = _trade_decision(direction=SignalDirection.LONG, confidence=72)
    layer = RegimeLiteScoringLayer(
        config=_config(market_regime_enabled=True),
        base_engine=StaticEngine(base),
        detector=FailingDetector(),
    )

    decision = layer.evaluate(_snapshot())

    assert decision.confidence == 72
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime_adjustment == 0


def test_positive_adjustment_not_applied_to_weak_base_score() -> None:
    decision = _apply(
        decision=_trade_decision(direction=SignalDirection.LONG, confidence=67),
        detection=RegimeDetection(LiteMarketRegime.TREND_UP, 0.80, "trend up"),
    )

    assert decision.confidence == 67
    assert decision.score_breakdown is not None
    assert decision.score_breakdown.regime_adjustment == 0


def test_disabled_market_regime_preserves_old_decision_object() -> None:
    base = _trade_decision(direction=SignalDirection.LONG, confidence=72)
    layer = RegimeLiteScoringLayer(
        config=_config(market_regime_enabled=False),
        base_engine=StaticEngine(base),
        detector=StaticDetector(RegimeDetection(LiteMarketRegime.TREND_UP, 1.0, "trend up")),
    )

    assert layer.evaluate(_snapshot()) is base


def _apply(decision: SignalDecision, detection: RegimeDetection) -> SignalDecision:
    layer = RegimeLiteScoringLayer(
        config=_config(market_regime_enabled=True),
        base_engine=StaticEngine(decision),
        detector=StaticDetector(detection),
    )
    return layer.evaluate(_snapshot())


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        timestamp=NOW,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=100.0,
        regime=MarketRegime.TREND_UP,
        metrics={
            "entry_return_pct": 1.0,
            "context_return_pct": 2.0,
            "macro_return_pct": 3.0,
            "entry_atr_pct": 1.0,
        },
    )


def _trade_decision(direction: SignalDirection, confidence: int) -> SignalDecision:
    return SignalDecision(
        symbol="BTCUSDT",
        timestamp=NOW,
        signal_type=(
            SignalType.LONG_CONTINUATION
            if direction is SignalDirection.LONG
            else SignalType.SHORT_CONTINUATION
        ),
        direction=direction,
        confidence=confidence,
        entry_price=100.0,
        stop_loss=97.0 if direction is SignalDirection.LONG else 103.0,
        take_profit_levels=(103.0, 105.0) if direction is SignalDirection.LONG else (97.0, 95.0),
        reasons=("rfa confluence", "risk/reward=1.67"),
    )


def _config(market_regime_enabled: bool) -> BotConfig:
    raw = _raw_config()
    raw["market_regime"] = {"enabled": market_regime_enabled}
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
