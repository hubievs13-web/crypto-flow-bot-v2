"""RFA signal engine for MarketSnapshot decisions.

The engine is pure decision logic over normalized snapshots. It does not fetch Binance data,
send Telegram messages, track active positions, enforce cooldowns, run backtests, or execute trades.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite

from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.models import (
    MarketRegime,
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
)

REQUIRED_METRICS = (
    "entry_return_pct",
    "context_return_pct",
    "macro_return_pct",
    "entry_atr",
    "entry_atr_pct",
    "entry_taker_buy_quote_ratio",
    "open_interest",
    "funding_rate",
    "long_short_ratio",
    "taker_buy_sell_ratio",
    "liquidation_buy_notional",
    "liquidation_sell_notional",
)
MIN_EVIDENCE_COMPONENTS = 6
MIN_DIRECTIONAL_EDGE = 5


@dataclass(frozen=True, slots=True)
class _SignalCandidate:
    direction: SignalDirection
    signal_type: SignalType
    confidence: int
    evidence_count: int
    context_aligned: bool
    macro_aligned: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ExitLevels:
    stop_loss: float
    take_profit_levels: tuple[float, ...]
    risk_reward: float


class RFAEngine:
    """Score snapshots with multi-factor Regime-Flow-Alpha confluence.

    A trade decision requires several independent evidence components to align. A single metric
    crossing a threshold is never enough to emit a trade signal.
    """

    def __init__(self, config: BotConfig) -> None:
        self._config = config

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        """Evaluate one snapshot and return a trade or NO_TRADE decision."""

        missing_metrics = _missing_metrics(snapshot)
        if missing_metrics:
            return _no_trade(
                snapshot=snapshot,
                confidence=0,
                reasons=(f"missing required RFA metrics: {', '.join(missing_metrics)}",),
                blocked_reason=f"missing_metrics:{','.join(missing_metrics)}",
            )

        atr = _metric_float(snapshot, "entry_atr")
        open_interest = _metric_float(snapshot, "open_interest")
        if atr <= 0:
            return _no_trade(
                snapshot=snapshot,
                confidence=0,
                reasons=("entry ATR must be positive for adaptive exits",),
                blocked_reason="invalid_entry_atr",
            )
        if open_interest <= 0:
            return _no_trade(
                snapshot=snapshot,
                confidence=0,
                reasons=("open interest must be positive for derivatives confirmation",),
                blocked_reason="invalid_open_interest",
            )

        long_candidate = _score_direction(snapshot, SignalDirection.LONG)
        short_candidate = _score_direction(snapshot, SignalDirection.SHORT)
        best, runner_up = sorted(
            (long_candidate, short_candidate),
            key=lambda candidate: candidate.confidence,
            reverse=True,
        )

        if best.confidence - runner_up.confidence < MIN_DIRECTIONAL_EDGE:
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(
                    *best.reasons,
                    "long/short scores are too close for a clean directional edge",
                ),
                blocked_reason="directional_edge_too_small",
            )

        if self._config.rfa_engine.require_context_alignment and not best.context_aligned:
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(*best.reasons, "context timeframe conflicts with the candidate direction"),
                blocked_reason="context_alignment_conflict",
            )

        if self._config.rfa_engine.require_macro_alignment and not best.macro_aligned:
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(*best.reasons, "macro timeframe conflicts with the candidate direction"),
                blocked_reason="macro_alignment_conflict",
            )

        min_evidence_components = self._config.rfa_engine.min_evidence_components
        if best.evidence_count < min_evidence_components:
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(
                    *best.reasons,
                    f"only {best.evidence_count} RFA components aligned; "
                    f"required {min_evidence_components}",
                ),
                blocked_reason="insufficient_rfa_confluence",
            )

        exits = _build_exit_levels(snapshot, best.direction, self._config)
        if exits is None:
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(*best.reasons, "ATR exit levels would produce invalid prices"),
                blocked_reason="invalid_exit_levels",
            )

        if exits.risk_reward < self._config.risk.min_risk_reward:
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(
                    *best.reasons,
                    f"risk/reward {exits.risk_reward:.2f} is below the configured minimum",
                ),
                blocked_reason="risk_reward_below_minimum",
            )

        if best.confidence < self._config.rfa_engine.min_signal_confidence:
            band = (
                "watch_only"
                if best.confidence >= self._config.rfa_engine.watch_confidence
                else "ignore"
            )
            return _no_trade(
                snapshot=snapshot,
                confidence=best.confidence,
                reasons=(*best.reasons, f"confidence band is {band}"),
                blocked_reason="confidence_below_signal_minimum",
            )

        return SignalDecision(
            symbol=snapshot.symbol,
            timestamp=snapshot.timestamp,
            signal_type=best.signal_type,
            direction=best.direction,
            confidence=best.confidence,
            entry_price=snapshot.price,
            stop_loss=exits.stop_loss,
            take_profit_levels=exits.take_profit_levels,
            reasons=(*best.reasons, f"risk/reward={exits.risk_reward:.2f}"),
            blocked_reason=None,
        )

    def evaluate_many(self, snapshots: Sequence[MarketSnapshot]) -> tuple[SignalDecision, ...]:
        """Evaluate multiple snapshots without adding stateful position or cooldown checks."""

        return tuple(self.evaluate(snapshot) for snapshot in snapshots)


def _score_direction(snapshot: MarketSnapshot, direction: SignalDirection) -> _SignalCandidate:
    reasons: list[str] = []
    score = 0
    evidence_count = 0
    sign = _direction_sign(direction)
    signal_type = _signal_type_for(snapshot.regime, direction)

    def add(points: int, reason: str) -> None:
        nonlocal score, evidence_count
        score += points
        evidence_count += 1
        reasons.append(f"+{points}: {reason}")

    regime_points = _regime_points(snapshot.regime, direction)
    if regime_points > 0:
        add(regime_points, f"regime {snapshot.regime.value} supports {signal_type.value}")
    else:
        reasons.append(f"regime {snapshot.regime.value} does not support {direction.value}")

    entry_return = _metric_float(snapshot, "entry_return_pct")
    context_return = _metric_float(snapshot, "context_return_pct")
    macro_return = _metric_float(snapshot, "macro_return_pct")
    context_aligned = sign * context_return > 0
    macro_aligned = sign * macro_return > 0

    _add_signed_return_component(add, reasons, sign * entry_return, "entry 15m momentum", 10)
    _add_signed_return_component(add, reasons, sign * context_return, "context 1h structure", 14)
    _add_signed_return_component(add, reasons, sign * macro_return, "macro 4h filter", 14)

    flow_ratio = _metric_float(snapshot, "entry_taker_buy_quote_ratio")
    if direction is SignalDirection.LONG:
        if flow_ratio >= 0.60:
            add(8, "entry taker buy quote share confirms long flow")
        elif flow_ratio > 0.52:
            add(4, "entry taker buy quote share is mildly long-biased")
        else:
            reasons.append("entry taker buy quote share does not confirm long flow")
    elif flow_ratio <= 0.40:
        add(8, "entry taker sell quote share confirms short flow")
    elif flow_ratio < 0.48:
        add(4, "entry taker sell quote share is mildly short-biased")
    else:
        reasons.append("entry taker quote share does not confirm short flow")

    taker_ratio = _metric_float(snapshot, "taker_buy_sell_ratio")
    if direction is SignalDirection.LONG:
        if taker_ratio >= 1.30:
            add(12, "taker buy/sell pressure confirms long flow")
        elif taker_ratio > 1.05:
            add(6, "taker buy/sell pressure is mildly long-biased")
        else:
            reasons.append("taker buy/sell pressure does not confirm long flow")
    elif taker_ratio <= 0.77:
        add(12, "taker buy/sell pressure confirms short flow")
    elif taker_ratio < 0.95:
        add(6, "taker buy/sell pressure is mildly short-biased")
    else:
        reasons.append("taker buy/sell pressure does not confirm short flow")

    funding_rate = _metric_float(snapshot, "funding_rate")
    funding_alignment = sign * funding_rate
    is_reversal = signal_type in {SignalType.LONG_REVERSAL, SignalType.SHORT_REVERSAL}
    if 0 < funding_alignment <= 0.001:
        add(4, "funding is directionally aligned without being extreme")
    elif is_reversal and funding_alignment < 0:
        add(3, "funding is contrarian for a reversal setup")
    else:
        reasons.append("funding does not add usable directional confirmation")

    long_short_ratio = _metric_float(snapshot, "long_short_ratio")
    if direction is SignalDirection.LONG:
        if long_short_ratio >= 1.10:
            add(6, "global long/short ratio confirms long bias")
        elif long_short_ratio > 1.00:
            add(3, "global long/short ratio is mildly long-biased")
        else:
            reasons.append("global long/short ratio does not confirm long bias")
    elif long_short_ratio <= 0.90:
        add(6, "global long/short ratio confirms short bias")
    elif long_short_ratio < 1.00:
        add(3, "global long/short ratio is mildly short-biased")
    else:
        reasons.append("global long/short ratio does not confirm short bias")

    buy_liquidations = _metric_float(snapshot, "liquidation_buy_notional")
    sell_liquidations = _metric_float(snapshot, "liquidation_sell_notional")
    if direction is SignalDirection.LONG and buy_liquidations > sell_liquidations:
        add(6, "forced-buy liquidation notional supports upside pressure")
    elif direction is SignalDirection.SHORT and sell_liquidations > buy_liquidations:
        add(6, "forced-sell liquidation notional supports downside pressure")
    else:
        reasons.append("liquidation notional does not confirm the candidate direction")

    atr_pct = _metric_float(snapshot, "entry_atr_pct")
    if 0.15 <= atr_pct <= 3.50:
        add(8, "entry ATR percentage is tradeable for adaptive risk")
    elif 0 < atr_pct <= 5.00:
        add(4, "entry ATR percentage is usable but not ideal")
    else:
        reasons.append("entry ATR percentage is outside the preferred volatility band")

    confidence = max(0, min(100, score))
    return _SignalCandidate(
        direction=direction,
        signal_type=signal_type,
        confidence=confidence,
        evidence_count=evidence_count,
        context_aligned=context_aligned,
        macro_aligned=macro_aligned,
        reasons=tuple(reasons),
    )


def _add_signed_return_component(
    add: Callable[[int, str], None],
    reasons: list[str],
    signed_return_pct: float,
    name: str,
    max_points: int,
) -> None:
    if signed_return_pct >= 1.00:
        add(max_points, f"{name} is directionally aligned")
    elif signed_return_pct >= 0.25:
        add(max_points // 2, f"{name} is mildly directionally aligned")
    else:
        reasons.append(f"{name} is not directionally aligned")


def _regime_points(regime: MarketRegime, direction: SignalDirection) -> int:
    if direction is SignalDirection.LONG and regime is MarketRegime.TREND_UP:
        return 18
    if direction is SignalDirection.SHORT and regime is MarketRegime.TREND_DOWN:
        return 18
    if regime is MarketRegime.SQUEEZE_SETUP:
        return 8
    if regime is MarketRegime.RANGE:
        return 4
    if direction is SignalDirection.LONG and regime in {
        MarketRegime.TREND_DOWN,
        MarketRegime.EXHAUSTION,
    }:
        return 12
    if direction is SignalDirection.SHORT and regime in {
        MarketRegime.TREND_UP,
        MarketRegime.EXHAUSTION,
    }:
        return 12
    return 0


def _signal_type_for(regime: MarketRegime, direction: SignalDirection) -> SignalType:
    if direction is SignalDirection.LONG:
        if regime in {MarketRegime.TREND_UP, MarketRegime.SQUEEZE_SETUP}:
            return SignalType.LONG_CONTINUATION
        return SignalType.LONG_REVERSAL
    if regime in {MarketRegime.TREND_DOWN, MarketRegime.SQUEEZE_SETUP}:
        return SignalType.SHORT_CONTINUATION
    return SignalType.SHORT_REVERSAL


def _build_exit_levels(
    snapshot: MarketSnapshot,
    direction: SignalDirection,
    config: BotConfig,
) -> _ExitLevels | None:
    atr = _metric_float(snapshot, "entry_atr")
    stop_distance = atr * config.risk.atr_stop_multiplier
    target_distances = tuple(atr * multiplier for multiplier in config.risk.atr_tp_multipliers)

    if direction is SignalDirection.LONG:
        stop_loss = snapshot.price - stop_distance
        take_profit_levels = tuple(snapshot.price + distance for distance in target_distances)
        reward = max(level - snapshot.price for level in take_profit_levels)
        risk = snapshot.price - stop_loss
    else:
        stop_loss = snapshot.price + stop_distance
        take_profit_levels = tuple(snapshot.price - distance for distance in target_distances)
        reward = max(snapshot.price - level for level in take_profit_levels)
        risk = stop_loss - snapshot.price

    levels = (stop_loss, *take_profit_levels)
    if any(level <= 0 or not isfinite(level) for level in levels):
        return None
    if risk <= 0 or reward <= 0:
        return None

    return _ExitLevels(
        stop_loss=stop_loss,
        take_profit_levels=take_profit_levels,
        risk_reward=reward / risk,
    )


def _missing_metrics(snapshot: MarketSnapshot) -> tuple[str, ...]:
    return tuple(metric for metric in REQUIRED_METRICS if metric not in snapshot.metrics)


def _metric_float(snapshot: MarketSnapshot, key: str) -> float:
    value = snapshot.metrics[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"MarketSnapshot metric '{key}' must be numeric."
        raise ValueError(msg)
    result = float(value)
    if not isfinite(result):
        msg = f"MarketSnapshot metric '{key}' must be finite."
        raise ValueError(msg)
    return result


def _direction_sign(direction: SignalDirection) -> int:
    if direction is SignalDirection.LONG:
        return 1
    if direction is SignalDirection.SHORT:
        return -1
    msg = "RFA candidates require LONG or SHORT direction."
    raise ValueError(msg)


def _no_trade(
    snapshot: MarketSnapshot,
    confidence: int,
    reasons: tuple[str, ...],
    blocked_reason: str,
) -> SignalDecision:
    return SignalDecision(
        symbol=snapshot.symbol,
        timestamp=snapshot.timestamp,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=max(0, min(100, confidence)),
        entry_price=None,
        stop_loss=None,
        take_profit_levels=(),
        reasons=reasons,
        blocked_reason=blocked_reason,
    )
