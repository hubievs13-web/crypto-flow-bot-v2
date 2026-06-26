from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from math import isfinite
from typing import Protocol

from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.logging import get_logger
from crypto_flow_bot_v2.models import MarketSnapshot, SignalDecision, SignalDirection
from crypto_flow_bot_v2.models import SignalScoreBreakdown, SignalType

LOGGER = get_logger(__name__)


class LiteMarketRegime(StrEnum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    CHOP = "CHOP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RegimeDetection:
    regime: LiteMarketRegime
    confidence: float
    reason: str
    debug: dict[str, float | str] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Regime detection confidence must be between 0 and 1.")


class BaseSignalEngine(Protocol):
    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision: ...


class RegimeDetector(Protocol):
    def detect(self, snapshot: MarketSnapshot) -> RegimeDetection: ...


class DefaultRegimeLiteDetector:
    def detect(self, snapshot: MarketSnapshot) -> RegimeDetection:
        metrics = snapshot.metrics
        required = ("entry_return_pct", "context_return_pct", "macro_return_pct", "entry_atr_pct")
        missing = tuple(key for key in required if key not in metrics)
        if missing:
            return RegimeDetection(
                LiteMarketRegime.UNKNOWN,
                0.0,
                f"missing regime metrics: {', '.join(missing)}",
            )
        entry_return = _metric_float(metrics, "entry_return_pct")
        context_return = _metric_float(metrics, "context_return_pct")
        macro_return = _metric_float(metrics, "macro_return_pct")
        atr_pct = _metric_float(metrics, "entry_atr_pct")
        debug = {
            "entry_return_pct": entry_return,
            "context_return_pct": context_return,
            "macro_return_pct": macro_return,
            "entry_atr_pct": atr_pct,
        }
        if atr_pct >= 4.0 or context_return * macro_return < 0:
            confidence = _clamp_float(0.68 + min(abs(context_return - macro_return) / 8.0, 0.18))
            return RegimeDetection(
                LiteMarketRegime.CHOP,
                confidence,
                "conflicting higher-timeframe structure or excessive ATR chop",
                debug,
            )
        if context_return > 0 and macro_return >= 0:
            confidence = _trend_confidence(entry_return, context_return, macro_return, atr_pct, 1)
            return RegimeDetection(
                LiteMarketRegime.TREND_UP,
                confidence,
                "context and macro returns align upward",
                debug,
            )
        if context_return < 0 and macro_return <= 0:
            confidence = _trend_confidence(entry_return, context_return, macro_return, atr_pct, -1)
            return RegimeDetection(
                LiteMarketRegime.TREND_DOWN,
                confidence,
                "context and macro returns align downward",
                debug,
            )
        if abs(context_return) <= 0.75 and abs(macro_return) <= 1.50 and atr_pct <= 2.50:
            confidence = _clamp_float(0.66 + max(0.0, 0.75 - abs(context_return)) / 20.0)
            return RegimeDetection(
                LiteMarketRegime.RANGE,
                confidence,
                "higher-timeframe returns are muted and ATR is contained",
                debug,
            )
        return RegimeDetection(
            LiteMarketRegime.UNKNOWN,
            0.0,
            "regime structure is not clean enough for adjustment",
            debug,
        )


class RegimeLiteScoringLayer:
    def __init__(
        self,
        config: BotConfig,
        base_engine: BaseSignalEngine,
        detector: RegimeDetector | None = None,
    ) -> None:
        self._config = config
        self._base_engine = base_engine
        self._detector = detector or DefaultRegimeLiteDetector()

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        return self.apply(snapshot, self._base_engine.evaluate(snapshot))

    def apply(self, snapshot: MarketSnapshot, decision: SignalDecision) -> SignalDecision:
        config = self._config.market_regime
        if not config.enabled or not _is_trade_decision(decision):
            return decision
        base_score = decision.confidence
        try:
            detection = self._detector.detect(snapshot)
        except Exception:
            LOGGER.exception(
                "Regime-Lite detector failed; continuing with zero adjustment: symbol=%s",
                decision.symbol,
            )
            detection = RegimeDetection(
                LiteMarketRegime.UNKNOWN,
                0.0,
                "regime detector exception; fail-open zero adjustment",
            )
            return _with_breakdown(decision, base_score, detection, 0)
        adjustment = self._adjustment(snapshot, decision, detection)
        if adjustment > 0 and base_score < config.apply_bonus_only_if_base_score_at_least:
            adjustment = 0
        final_score = _clamp_int(base_score + adjustment)
        return _with_breakdown(decision, base_score, detection, final_score - base_score)

    def _adjustment(
        self,
        snapshot: MarketSnapshot,
        decision: SignalDecision,
        detection: RegimeDetection,
    ) -> int:
        config = self._config.market_regime
        if detection.regime is LiteMarketRegime.UNKNOWN:
            return 0
        if detection.confidence < config.min_confidence_for_adjustment:
            return 0
        raw = _raw_adjustment(snapshot, decision.direction, detection)
        raw = max(-config.max_negative_adjustment, min(config.max_positive_adjustment, raw))
        if raw < 0:
            floor_adjustment = self._config.rfa_engine.min_signal_confidence - decision.confidence
            raw = max(raw, min(0, floor_adjustment))
        return raw


def _with_breakdown(
    decision: SignalDecision,
    base_score: int,
    detection: RegimeDetection,
    adjustment: int,
) -> SignalDecision:
    final_score = _clamp_int(base_score + adjustment)
    reason = (
        f"regime_lite: {detection.regime.value} confidence={detection.confidence:.2f} "
        f"adjustment={adjustment:+d} ({detection.reason})"
    )
    return replace(
        decision,
        confidence=final_score,
        reasons=(*decision.reasons, reason),
        score_breakdown=SignalScoreBreakdown(
            base_score=base_score,
            regime=detection.regime.value,
            regime_confidence=detection.confidence,
            regime_adjustment=adjustment,
            final_score=final_score,
            reason=detection.reason,
        ),
    )


def _raw_adjustment(
    snapshot: MarketSnapshot,
    direction: SignalDirection,
    detection: RegimeDetection,
) -> int:
    if detection.regime is LiteMarketRegime.CHOP:
        return -4 if detection.confidence >= 0.75 else -3
    if direction is SignalDirection.LONG:
        if detection.regime is LiteMarketRegime.TREND_UP:
            return 3 if detection.confidence >= 0.75 else 2
        if detection.regime is LiteMarketRegime.TREND_DOWN:
            return -3 if detection.confidence >= 0.75 else -2
        if detection.regime is LiteMarketRegime.RANGE:
            return _range_adjustment(snapshot, direction)
    if direction is SignalDirection.SHORT:
        if detection.regime is LiteMarketRegime.TREND_DOWN:
            return 3 if detection.confidence >= 0.75 else 2
        if detection.regime is LiteMarketRegime.TREND_UP:
            return -3 if detection.confidence >= 0.75 else -2
        if detection.regime is LiteMarketRegime.RANGE:
            return _range_adjustment(snapshot, direction)
    return 0


def _range_adjustment(snapshot: MarketSnapshot, direction: SignalDirection) -> int:
    entry_return = snapshot.metrics.get("entry_return_pct", 0.0)
    if isinstance(entry_return, bool) or not isinstance(entry_return, int | float):
        return 0
    value = float(entry_return)
    if direction is SignalDirection.LONG:
        if value <= -0.50:
            return 2
        if value <= -0.20:
            return 1
        return -1 if value >= 0.75 else 0
    if direction is SignalDirection.SHORT:
        if value >= 0.50:
            return 2
        if value >= 0.20:
            return 1
        return -1 if value <= -0.75 else 0
    return 0


def _is_trade_decision(decision: SignalDecision) -> bool:
    return (
        decision.signal_type is not SignalType.NO_TRADE
        and decision.direction is not SignalDirection.NONE
        and decision.blocked_reason is None
    )


def _trend_confidence(
    entry_return: float,
    context_return: float,
    macro_return: float,
    atr_pct: float,
    sign: int,
) -> float:
    strength = min((abs(context_return) + abs(macro_return)) / 8.0, 0.28)
    entry_alignment = 0.06 if sign * entry_return > 0 else 0.0
    volatility_penalty = 0.06 if atr_pct >= 3.25 else 0.0
    return _clamp_float(0.62 + strength + entry_alignment - volatility_penalty)


def _metric_float(metrics: dict[str, float | int | str | bool], key: str) -> float:
    value = metrics[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Regime-Lite metric '{key}' must be numeric.")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"Regime-Lite metric '{key}' must be finite.")
    return result


def _clamp_float(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp_int(value: int) -> int:
    return max(0, min(100, value))
