"""Protective signal governor for ranked, rate-limited alert selection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from crypto_flow_bot_v2.config import BotConfig, SignalGovernorConfig
from crypto_flow_bot_v2.models import SignalDecision, SignalDirection, SignalType


@dataclass(frozen=True, slots=True)
class SignalGovernorDecision:
    """Governor decision for one signal candidate."""

    decision: SignalDecision
    passed: bool
    reason: str
    rank: int
    final_score: int


@dataclass(frozen=True, slots=True)
class SignalGovernorResult:
    """Batch governor result for one scan."""

    allowed: tuple[SignalGovernorDecision, ...]
    skipped: tuple[SignalGovernorDecision, ...]


@dataclass(frozen=True, slots=True)
class _RankedSignal:
    decision: SignalDecision
    rank: int
    final_score: int
    risk_reward: float
    volume_confirmation: float


class SignalGovernor:
    """Fail-open-safe stateful limiter for trade signal alerts."""

    def __init__(self, config: BotConfig) -> None:
        self._config = config.signal_governor
        self._history: list[SignalDecision] = []
        self._last_sent_by_symbol: dict[str, datetime] = {}

    def select(self, decisions: tuple[SignalDecision, ...]) -> SignalGovernorResult:
        """Rank a scan's candidates and return signals allowed by governor limits."""

        if not self._config.enabled:
            return SignalGovernorResult(
                allowed=tuple(
                    SignalGovernorDecision(
                        decision=decision,
                        passed=True,
                        reason="signal governor disabled",
                        rank=index,
                        final_score=decision.confidence,
                    )
                    for index, decision in enumerate(decisions, start=1)
                ),
                skipped=(),
            )
        if not decisions:
            return SignalGovernorResult(allowed=(), skipped=())

        scan_time = max(decision.timestamp for decision in decisions)
        self._prune(scan_time)
        ranked = _rank(decisions, self._config)

        allowed: list[SignalGovernorDecision] = []
        skipped: list[SignalGovernorDecision] = []
        remaining_hour_slots = self._config.max_signals_per_hour - len(self._history)
        direction_counts = Counter(decision.direction for decision in self._history)

        for item in ranked:
            reason = self._skip_reason(
                item=item,
                allowed_count=len(allowed),
                remaining_hour_slots=remaining_hour_slots,
                direction_counts=direction_counts,
                scan_time=scan_time,
            )
            if reason is None:
                allowed.append(
                    SignalGovernorDecision(
                        decision=item.decision,
                        passed=True,
                        reason="ranked signal passed governor limits",
                        rank=item.rank,
                        final_score=item.final_score,
                    )
                )
                remaining_hour_slots -= 1
                direction_counts[item.decision.direction] += 1
            else:
                skipped.append(
                    SignalGovernorDecision(
                        decision=item.decision,
                        passed=False,
                        reason=reason,
                        rank=item.rank,
                        final_score=item.final_score,
                    )
                )

        return SignalGovernorResult(allowed=tuple(allowed), skipped=tuple(skipped))

    def record_sent(self, decision: SignalDecision) -> None:
        """Record a successfully sent signal for hourly and per-symbol limits."""

        if not self._config.enabled:
            return
        self._history.append(decision)
        self._last_sent_by_symbol[decision.symbol] = decision.timestamp
        self._prune(decision.timestamp)

    def _skip_reason(
        self,
        item: _RankedSignal,
        allowed_count: int,
        remaining_hour_slots: int,
        direction_counts: Counter[SignalDirection],
        scan_time: datetime,
    ) -> str | None:
        if allowed_count >= self._config.max_signals_per_scan:
            return "max_signals_per_scan reached"
        if remaining_hour_slots <= 0:
            return "max_signals_per_hour reached"
        if self._symbol_on_cooldown(item.decision, scan_time):
            return "per_symbol_cooldown active"
        if direction_counts[item.decision.direction] >= self._config.same_direction_cluster_limit:
            return "same_direction_cluster_limit reached"
        return None

    def _symbol_on_cooldown(self, decision: SignalDecision, scan_time: datetime) -> bool:
        last_sent_at = self._last_sent_by_symbol.get(decision.symbol)
        if last_sent_at is None:
            return False
        cooldown_until = last_sent_at + timedelta(minutes=self._config.per_symbol_cooldown_minutes)
        return scan_time < cooldown_until

    def _prune(self, now: datetime) -> None:
        hour_cutoff = now - timedelta(hours=1)
        self._history = [
            decision for decision in self._history if decision.timestamp >= hour_cutoff
        ]
        cooldown_cutoff = now - timedelta(minutes=self._config.per_symbol_cooldown_minutes)
        self._last_sent_by_symbol = {
            symbol: timestamp
            for symbol, timestamp in self._last_sent_by_symbol.items()
            if timestamp >= cooldown_cutoff
        }


def _rank(
    decisions: tuple[SignalDecision, ...],
    config: SignalGovernorConfig,
) -> tuple[_RankedSignal, ...]:
    items = tuple(
        _RankedSignal(
            decision=decision,
            rank=0,
            final_score=_final_score(decision),
            risk_reward=_risk_reward(decision),
            volume_confirmation=_volume_confirmation(decision),
        )
        for decision in decisions
        if _is_trade_candidate(decision)
    )
    sorted_items = sorted(
        items,
        key=lambda item: tuple(_ranking_value(item, key) for key in _ranking_keys(config)),
        reverse=True,
    )
    return tuple(
        _RankedSignal(
            decision=item.decision,
            rank=index,
            final_score=item.final_score,
            risk_reward=item.risk_reward,
            volume_confirmation=item.volume_confirmation,
        )
        for index, item in enumerate(sorted_items, start=1)
    )


def _ranking_keys(config: SignalGovernorConfig) -> tuple[str, str, str]:
    return (
        config.ranking.primary,
        config.ranking.secondary,
        config.ranking.tertiary,
    )


def _ranking_value(item: _RankedSignal, key: str) -> float:
    if key == "final_score":
        return float(item.final_score)
    if key == "base_score":
        breakdown = item.decision.score_breakdown
        return float(breakdown.base_score if breakdown is not None else item.decision.confidence)
    if key == "risk_reward":
        return item.risk_reward
    if key == "volume_confirmation":
        return item.volume_confirmation
    return 0.0


def _is_trade_candidate(decision: SignalDecision) -> bool:
    return (
        decision.signal_type is not SignalType.NO_TRADE
        and decision.direction is not SignalDirection.NONE
        and decision.blocked_reason is None
        and decision.entry_price is not None
        and decision.stop_loss is not None
        and bool(decision.take_profit_levels)
    )


def _final_score(decision: SignalDecision) -> int:
    breakdown = decision.score_breakdown
    if breakdown is not None:
        return breakdown.final_score
    return decision.confidence


def _risk_reward(decision: SignalDecision) -> float:
    if (
        decision.entry_price is None
        or decision.stop_loss is None
        or not decision.take_profit_levels
    ):
        return 0.0
    if decision.direction is SignalDirection.LONG:
        risk = decision.entry_price - decision.stop_loss
        reward = max(decision.take_profit_levels) - decision.entry_price
    elif decision.direction is SignalDirection.SHORT:
        risk = decision.stop_loss - decision.entry_price
        reward = decision.entry_price - min(decision.take_profit_levels)
    else:
        return 0.0
    if risk <= 0 or reward <= 0:
        return 0.0
    return reward / risk


def _volume_confirmation(decision: SignalDecision) -> float:
    markers = ("volume", "taker", "flow")
    matches = sum(
        1
        for reason in decision.reasons
        if any(marker in reason.lower() for marker in markers)
    )
    return min(1.0, matches / 3.0)
