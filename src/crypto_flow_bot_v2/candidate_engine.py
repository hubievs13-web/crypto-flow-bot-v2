"""Stateful Lite candidate engine for near-miss signal setups."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.models import MarketSnapshot, SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.rfa_engine import (
    MIN_DIRECTIONAL_EDGE,
    MIN_EVIDENCE_COMPONENTS,
    _build_exit_levels,
    _metric_float,
    _missing_metrics,
    _score_direction,
)


@dataclass(frozen=True, slots=True)
class CandidateKey:
    """Stable candidate identity: symbol + direction + setup type + timeframe."""

    symbol: str
    direction: SignalDirection
    setup_type: SignalType
    timeframe: str

    @classmethod
    def from_decision(cls, decision: SignalDecision, timeframe: str) -> CandidateKey:
        return cls(
            symbol=decision.symbol.upper(),
            direction=decision.direction,
            setup_type=decision.signal_type,
            timeframe=timeframe,
        )

    def as_string(self) -> str:
        return f"{self.symbol}:{self.direction.value}:{self.setup_type.value}:{self.timeframe}"


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    """Persisted near-miss setup state across live cycles."""

    key: CandidateKey
    first_seen_at: datetime
    last_seen_at: datetime
    current_score: float
    best_score: float
    maturity_ticks: int
    confirmations: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    hard_filters_passed: bool
    last_decision: SignalDecision


@dataclass(frozen=True, slots=True)
class CandidateEngineResult:
    """Candidate engine output for one symbol evaluation."""

    decision: SignalDecision | None
    candidate: SignalCandidate | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class _Observation:
    key: CandidateKey
    current_score: float
    confirmations: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    hard_filters_passed: bool
    hard_invalidation: str | None
    decision: SignalDecision


class StatefulCandidateEngine:
    """Track near-miss setups and promote only matured candidates to signals."""

    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._candidate_config = config.candidate_engine
        self._candidates: dict[CandidateKey, SignalCandidate] = {}

    @property
    def candidates(self) -> tuple[SignalCandidate, ...]:
        return tuple(self._candidates.values())

    def process(
        self,
        snapshot: MarketSnapshot,
        decision: SignalDecision,
    ) -> CandidateEngineResult:
        """Update candidate state and return a signal only when the setup is ready."""

        if not self._candidate_config.enabled:
            return CandidateEngineResult(decision=decision, reason="candidate engine disabled")

        self.prune(snapshot.timestamp)
        observation = self._observe(snapshot=snapshot, decision=decision)
        if observation is None:
            self._discard_symbol(snapshot.symbol)
            return CandidateEngineResult(decision=None, reason="no candidate observation")

        if observation.hard_invalidation is not None:
            self._candidates.pop(observation.key, None)
            return CandidateEngineResult(decision=None, reason=observation.hard_invalidation)

        if observation.current_score < self._candidate_config.min_candidate_score:
            self._candidates.pop(observation.key, None)
            return CandidateEngineResult(decision=None, reason="score_below_min_candidate_score")

        if observation.current_score >= self._candidate_config.signal_threshold:
            self._candidates.pop(observation.key, None)
            if self._hard_filters_allow(observation):
                return CandidateEngineResult(
                    decision=_with_candidate_reason(
                        observation.decision,
                        observation.current_score,
                        maturity_bonus=0.0,
                        maturity_ticks=0,
                    ),
                    reason="score_above_signal_threshold",
                )
            return CandidateEngineResult(decision=None, reason="hard_filters_not_passed")

        candidate = self._upsert_candidate(observation, snapshot.timestamp)
        matured_decision = self._matured_decision(candidate)
        if matured_decision is None:
            return CandidateEngineResult(
                decision=None,
                candidate=candidate,
                reason="candidate_saved_or_updated",
            )
        return CandidateEngineResult(
            decision=matured_decision,
            candidate=candidate,
            reason="candidate_matured",
        )

    def prune(self, now: datetime) -> None:
        """Drop candidates older than the configured TTL."""

        ttl = timedelta(minutes=self._candidate_config.candidate_ttl_minutes)
        self._candidates = {
            key: candidate
            for key, candidate in self._candidates.items()
            if now - candidate.last_seen_at <= ttl
        }

    def discard_decision(self, decision: SignalDecision) -> None:
        """Remove candidate state after a promoted signal has opened a position."""

        if not self._candidate_config.enabled:
            return
        if decision.direction is SignalDirection.NONE or decision.signal_type is SignalType.NO_TRADE:
            return
        self._candidates.pop(
            CandidateKey.from_decision(decision, self._config.timeframes.entry),
            None,
        )

    def _upsert_candidate(
        self,
        observation: _Observation,
        timestamp: datetime,
    ) -> SignalCandidate:
        previous = self._candidates.get(observation.key)
        if previous is None:
            candidate = SignalCandidate(
                key=observation.key,
                first_seen_at=timestamp,
                last_seen_at=timestamp,
                current_score=observation.current_score,
                best_score=observation.current_score,
                maturity_ticks=1,
                confirmations=observation.confirmations,
                missing_conditions=observation.missing_conditions,
                hard_filters_passed=observation.hard_filters_passed,
                last_decision=observation.decision,
            )
        else:
            candidate = replace(
                previous,
                last_seen_at=timestamp,
                current_score=observation.current_score,
                best_score=max(previous.best_score, observation.current_score),
                maturity_ticks=previous.maturity_ticks + 1,
                confirmations=observation.confirmations,
                missing_conditions=observation.missing_conditions,
                hard_filters_passed=observation.hard_filters_passed,
                last_decision=observation.decision,
            )

        self._candidates[observation.key] = candidate
        self._enforce_candidate_limits()
        return self._candidates[observation.key]

    def _matured_decision(self, candidate: SignalCandidate) -> SignalDecision | None:
        if candidate.maturity_ticks < self._candidate_config.min_maturity_ticks:
            return None
        if self._candidate_config.hard_filters_required and not candidate.hard_filters_passed:
            return None

        maturity_bonus = self._maturity_bonus(candidate.maturity_ticks)
        effective_score = candidate.current_score + maturity_bonus
        if effective_score < self._candidate_config.signal_threshold:
            return None

        return _with_candidate_reason(
            candidate.last_decision,
            min(1.0, effective_score),
            maturity_bonus=maturity_bonus,
            maturity_ticks=candidate.maturity_ticks,
        )

    def _maturity_bonus(self, maturity_ticks: int) -> float:
        if maturity_ticks <= 0:
            return 0.0
        tick_ratio = maturity_ticks / self._candidate_config.min_maturity_ticks
        raw_bonus = self._candidate_config.max_maturity_bonus * min(1.0, tick_ratio)
        return min(self._candidate_config.max_maturity_bonus, raw_bonus)

    def _hard_filters_allow(self, observation: _Observation) -> bool:
        return not self._candidate_config.hard_filters_required or observation.hard_filters_passed

    def _enforce_candidate_limits(self) -> None:
        per_symbol = self._candidate_config.max_candidates_per_symbol
        total = self._candidate_config.max_candidates_total

        for symbol in {candidate.key.symbol for candidate in self._candidates.values()}:
            symbol_items = [
                candidate for candidate in self._candidates.values() if candidate.key.symbol == symbol
            ]
            for candidate in _rank_for_eviction(symbol_items)[per_symbol:]:
                self._candidates.pop(candidate.key, None)

        if len(self._candidates) > total:
            for candidate in _rank_for_eviction(self._candidates.values())[total:]:
                self._candidates.pop(candidate.key, None)

    def _discard_symbol(self, symbol: str) -> None:
        normalized = symbol.upper()
        self._candidates = {
            key: candidate
            for key, candidate in self._candidates.items()
            if key.symbol != normalized
        }

    def _observe(
        self,
        snapshot: MarketSnapshot,
        decision: SignalDecision,
    ) -> _Observation | None:
        if _has_directional_shape(decision):
            return self._observe_decision(snapshot, decision)
        return self._observe_snapshot(snapshot)

    def _observe_decision(
        self,
        snapshot: MarketSnapshot,
        decision: SignalDecision,
    ) -> _Observation:
        score = _decision_score(decision)
        missing_conditions = _score_missing_conditions(score, self._candidate_config.signal_threshold)
        hard_filters_passed = _is_trade_shape(decision) and decision.blocked_reason is None
        hard_invalidation = None if hard_filters_passed or decision.blocked_reason is None else decision.blocked_reason
        return _Observation(
            key=CandidateKey.from_decision(decision, snapshot.entry_timeframe),
            current_score=score,
            confirmations=_confirmations(decision.reasons),
            missing_conditions=missing_conditions,
            hard_filters_passed=hard_filters_passed,
            hard_invalidation=hard_invalidation,
            decision=decision,
        )

    def _observe_snapshot(self, snapshot: MarketSnapshot) -> _Observation | None:
        missing_metrics = _missing_metrics(snapshot)
        if missing_metrics:
            return None

        try:
            atr = _metric_float(snapshot, "entry_atr")
            open_interest = _metric_float(snapshot, "open_interest")
        except (KeyError, ValueError):
            return None
        if atr <= 0 or open_interest <= 0:
            return None

        long_candidate = _score_direction(snapshot, SignalDirection.LONG)
        short_candidate = _score_direction(snapshot, SignalDirection.SHORT)
        best, runner_up = sorted(
            (long_candidate, short_candidate),
            key=lambda candidate: candidate.confidence,
            reverse=True,
        )
        hard_invalidation = None
        if best.confidence - runner_up.confidence < MIN_DIRECTIONAL_EDGE:
            hard_invalidation = "directional_edge_too_small"
        elif self._config.rfa_engine.require_context_alignment and not best.context_aligned:
            hard_invalidation = "context_alignment_conflict"
        elif self._config.rfa_engine.require_macro_alignment and not best.macro_aligned:
            hard_invalidation = "macro_alignment_conflict"

        exits = _build_exit_levels(snapshot, best.direction, self._config)
        if exits is None:
            hard_invalidation = "invalid_exit_levels"
        elif exits.risk_reward < self._config.risk.min_risk_reward:
            hard_invalidation = "risk_reward_below_minimum"

        score = best.confidence / 100.0
        missing_conditions = list(_score_missing_conditions(score, self._candidate_config.signal_threshold))
        if best.evidence_count < MIN_EVIDENCE_COMPONENTS:
            missing_conditions.append("insufficient_rfa_confluence")

        hard_filters_passed = hard_invalidation is None and best.evidence_count >= MIN_EVIDENCE_COMPONENTS
        decision = SignalDecision(
            symbol=snapshot.symbol,
            timestamp=snapshot.timestamp,
            signal_type=best.signal_type,
            direction=best.direction,
            confidence=best.confidence,
            entry_price=snapshot.price,
            stop_loss=None if exits is None else exits.stop_loss,
            take_profit_levels=() if exits is None else exits.take_profit_levels,
            reasons=tuple(best.reasons),
            blocked_reason=None if hard_filters_passed else hard_invalidation,
        )
        return _Observation(
            key=CandidateKey.from_decision(decision, snapshot.entry_timeframe),
            current_score=score,
            confirmations=_confirmations(best.reasons),
            missing_conditions=tuple(missing_conditions),
            hard_filters_passed=hard_filters_passed,
            hard_invalidation=hard_invalidation,
            decision=decision,
        )


def _rank_for_eviction(candidates: Iterable[SignalCandidate]) -> tuple[SignalCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.best_score,
                candidate.current_score,
                candidate.last_seen_at,
            ),
            reverse=True,
        )
    )


def _has_directional_shape(decision: SignalDecision) -> bool:
    return decision.signal_type is not SignalType.NO_TRADE and decision.direction is not SignalDirection.NONE


def _is_trade_shape(decision: SignalDecision) -> bool:
    return (
        _has_directional_shape(decision)
        and decision.entry_price is not None
        and decision.stop_loss is not None
        and bool(decision.take_profit_levels)
    )


def _decision_score(decision: SignalDecision) -> float:
    breakdown = decision.score_breakdown
    score = breakdown.final_score if breakdown is not None else decision.confidence
    return max(0.0, min(1.0, score / 100.0))


def _score_missing_conditions(score: float, signal_threshold: float) -> tuple[str, ...]:
    if score < signal_threshold:
        return ("score_below_signal_threshold",)
    return ()


def _confirmations(reasons: tuple[str, ...]) -> tuple[str, ...]:
    confirmations = tuple(reason for reason in reasons if reason.startswith("+"))
    return confirmations or reasons


def _with_candidate_reason(
    decision: SignalDecision,
    effective_score: float,
    *,
    maturity_bonus: float,
    maturity_ticks: int,
) -> SignalDecision:
    confidence = round(max(0.0, min(1.0, effective_score)) * 100)
    return replace(
        decision,
        confidence=confidence,
        blocked_reason=None,
        reasons=(
            *decision.reasons,
            "candidate_engine: "
            f"matured_ticks={maturity_ticks} "
            f"maturity_bonus={maturity_bonus:.2f} "
            f"effective_score={effective_score:.2f}",
        ),
    )
