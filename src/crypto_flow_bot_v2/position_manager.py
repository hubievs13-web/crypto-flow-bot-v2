"""Virtual position lifecycle management.

This module tracks simulated positions only. It never talks to Binance private APIs, never places
orders, and never sends Telegram messages.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from crypto_flow_bot_v2.config import BotConfig, RiskConfig
from crypto_flow_bot_v2.models import (
    ExitPlan,
    SignalDecision,
    SignalDirection,
    SignalType,
    VirtualPosition,
)


class PositionEventType(StrEnum):
    """Virtual position manager event categories."""

    OPENED = "OPENED"
    BLOCKED = "BLOCKED"
    UPDATED = "UPDATED"
    CLOSED = "CLOSED"
    IGNORED = "IGNORED"


class PositionExitReason(StrEnum):
    """Reasons for closing a virtual position."""

    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    REASON_INVALIDATION = "REASON_INVALIDATION"
    MANUAL = "MANUAL"


@dataclass(frozen=True, slots=True)
class PositionEvent:
    """Result emitted after a virtual position manager operation."""

    event_type: PositionEventType
    symbol: str
    timestamp: datetime
    position: VirtualPosition | None = None
    exit_reason: PositionExitReason | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    message: str | None = None


@dataclass(slots=True)
class _PositionState:
    position: VirtualPosition
    peak_price: float
    trough_price: float
    hit_take_profit_levels: set[float]


class VirtualPositionManager:
    """Stateful manager for simulated RFA positions.

    It enforces the PR 5 lifecycle gates that PR 4 intentionally excluded: one active position per
    symbol, post-close cooldowns, adaptive trailing updates, take-profit completion, time stops,
    and reason invalidation. All state is in memory and virtual.
    """

    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._positions: dict[str, _PositionState] = {}
        self._cooldown_until: dict[str, datetime] = {}

    def active_positions(self) -> tuple[VirtualPosition, ...]:
        """Return all active virtual positions."""

        return tuple(state.position for state in self._positions.values())

    def get_active_position(self, symbol: str) -> VirtualPosition | None:
        """Return the active virtual position for a symbol, if one exists."""

        state = self._positions.get(_normalize_symbol(symbol))
        if state is None:
            return None
        return state.position

    def has_active_position(self, symbol: str) -> bool:
        """Return whether a symbol already has an active virtual position."""

        return self.get_active_position(symbol) is not None

    def is_on_cooldown(self, symbol: str, timestamp: datetime) -> bool:
        """Return whether a symbol is still inside its post-close cooldown window."""

        cooldown_until = self._cooldown_until.get(_normalize_symbol(symbol))
        return cooldown_until is not None and timestamp < cooldown_until

    def open_from_decision(self, decision: SignalDecision) -> PositionEvent:
        """Open a virtual position from a tradeable RFA decision when gates allow it."""

        symbol = _normalize_symbol(decision.symbol)
        if not _is_tradeable_decision(decision):
            return PositionEvent(
                event_type=PositionEventType.IGNORED,
                symbol=symbol,
                timestamp=decision.timestamp,
                message="decision is not a tradeable signal",
            )
        if self.has_active_position(symbol):
            return PositionEvent(
                event_type=PositionEventType.BLOCKED,
                symbol=symbol,
                timestamp=decision.timestamp,
                position=self.get_active_position(symbol),
                message="active position already exists for symbol",
            )
        if self.is_on_cooldown(symbol, decision.timestamp):
            return PositionEvent(
                event_type=PositionEventType.BLOCKED,
                symbol=symbol,
                timestamp=decision.timestamp,
                message="symbol cooldown is still active",
            )

        assert decision.entry_price is not None
        assert decision.stop_loss is not None
        exit_plan = ExitPlan(
            stop_loss=decision.stop_loss,
            take_profit_levels=decision.take_profit_levels,
            trailing_stop=decision.stop_loss,
            time_stop_minutes=self._config.risk.max_position_minutes,
            invalidation_reason=None,
        )
        position = VirtualPosition(
            symbol=symbol,
            direction=decision.direction,
            entry_price=decision.entry_price,
            opened_at=decision.timestamp,
            exit_plan=exit_plan,
            confidence=decision.confidence,
            source_signal_type=decision.signal_type,
        )
        self._positions[symbol] = _PositionState(
            position=position,
            peak_price=decision.entry_price,
            trough_price=decision.entry_price,
            hit_take_profit_levels=set(),
        )
        return PositionEvent(
            event_type=PositionEventType.OPENED,
            symbol=symbol,
            timestamp=decision.timestamp,
            position=position,
            message="virtual position opened",
        )

    def update_price(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        invalidation_reason: str | None = None,
    ) -> PositionEvent:
        """Update an active virtual position with a new market price."""

        _validate_positive_price(price)
        normalized_symbol = _normalize_symbol(symbol)
        state = self._positions.get(normalized_symbol)
        if state is None:
            return PositionEvent(
                event_type=PositionEventType.IGNORED,
                symbol=normalized_symbol,
                timestamp=timestamp,
                message="no active position for symbol",
            )

        if invalidation_reason is not None and invalidation_reason.strip():
            return self.close_position(
                symbol=normalized_symbol,
                price=price,
                timestamp=timestamp,
                reason=PositionExitReason.REASON_INVALIDATION,
                message=invalidation_reason.strip(),
            )

        updated_state = _with_updated_trailing_stop(state, price, self._config.risk)
        self._positions[normalized_symbol] = updated_state
        close_event = self._close_event_if_needed(updated_state, price, timestamp)
        if close_event is not None:
            return close_event

        new_hits = _new_take_profit_hits(updated_state, price)
        if new_hits:
            updated_state.hit_take_profit_levels.update(new_hits)
            return PositionEvent(
                event_type=PositionEventType.UPDATED,
                symbol=normalized_symbol,
                timestamp=timestamp,
                position=updated_state.position,
                message=f"take_profit_hit:{','.join(str(level) for level in sorted(new_hits))}",
            )

        return PositionEvent(
            event_type=PositionEventType.UPDATED,
            symbol=normalized_symbol,
            timestamp=timestamp,
            position=updated_state.position,
            message="virtual position updated",
        )

    def close_position(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        reason: PositionExitReason = PositionExitReason.MANUAL,
        message: str | None = None,
    ) -> PositionEvent:
        """Close an active virtual position without touching any real exchange account."""

        _validate_positive_price(price)
        normalized_symbol = _normalize_symbol(symbol)
        state = self._positions.pop(normalized_symbol, None)
        if state is None:
            return PositionEvent(
                event_type=PositionEventType.IGNORED,
                symbol=normalized_symbol,
                timestamp=timestamp,
                message="no active position for symbol",
            )

        closed_position = replace(state.position, active=False)
        self._cooldown_until[normalized_symbol] = timestamp + timedelta(
            minutes=self._config.risk.cooldown_minutes
        )
        return PositionEvent(
            event_type=PositionEventType.CLOSED,
            symbol=normalized_symbol,
            timestamp=timestamp,
            position=closed_position,
            exit_reason=reason,
            exit_price=price,
            pnl_pct=_pnl_pct(state.position, price),
            message=message or f"virtual position closed: {reason.value}",
        )

    def _close_event_if_needed(
        self,
        state: _PositionState,
        price: float,
        timestamp: datetime,
    ) -> PositionEvent | None:
        position = state.position
        if _time_stop_reached(position, timestamp):
            return self.close_position(
                symbol=position.symbol,
                price=price,
                timestamp=timestamp,
                reason=PositionExitReason.TIME_STOP,
            )
        if _stop_reached(position, price):
            trailing_stop = position.exit_plan.trailing_stop
            reason = (
                PositionExitReason.TRAILING_STOP
                if trailing_stop is not None and trailing_stop != position.exit_plan.stop_loss
                else PositionExitReason.STOP_LOSS
            )
            return self.close_position(
                symbol=position.symbol,
                price=price,
                timestamp=timestamp,
                reason=reason,
            )
        if _final_take_profit_reached(position, price):
            return self.close_position(
                symbol=position.symbol,
                price=price,
                timestamp=timestamp,
                reason=PositionExitReason.TAKE_PROFIT,
            )
        return None


def _is_tradeable_decision(decision: SignalDecision) -> bool:
    return (
        decision.signal_type is not SignalType.NO_TRADE
        and decision.direction is not SignalDirection.NONE
        and decision.blocked_reason is None
        and decision.entry_price is not None
        and decision.stop_loss is not None
        and bool(decision.take_profit_levels)
    )


def _with_updated_trailing_stop(
    state: _PositionState,
    price: float,
    risk_config: RiskConfig,
) -> _PositionState:
    position = state.position
    risk_distance = abs(position.entry_price - position.exit_plan.stop_loss)
    atr = risk_distance / risk_config.atr_stop_multiplier
    trail_distance = atr * risk_config.trailing_atr_multiplier

    peak_price = max(state.peak_price, price)
    trough_price = min(state.trough_price, price)
    current_stop = position.exit_plan.trailing_stop or position.exit_plan.stop_loss
    if position.direction is SignalDirection.LONG:
        next_stop = max(current_stop, peak_price - trail_distance, position.exit_plan.stop_loss)
    else:
        next_stop = min(current_stop, trough_price + trail_distance, position.exit_plan.stop_loss)

    exit_plan = replace(position.exit_plan, trailing_stop=next_stop)
    return _PositionState(
        position=replace(position, exit_plan=exit_plan),
        peak_price=peak_price,
        trough_price=trough_price,
        hit_take_profit_levels=set(state.hit_take_profit_levels),
    )


def _new_take_profit_hits(state: _PositionState, price: float) -> set[float]:
    position = state.position
    if position.direction is SignalDirection.LONG:
        hit_levels = {level for level in position.exit_plan.take_profit_levels if price >= level}
    else:
        hit_levels = {level for level in position.exit_plan.take_profit_levels if price <= level}
    return hit_levels - state.hit_take_profit_levels


def _final_take_profit_reached(position: VirtualPosition, price: float) -> bool:
    if position.direction is SignalDirection.LONG:
        return price >= max(position.exit_plan.take_profit_levels)
    return price <= min(position.exit_plan.take_profit_levels)


def _stop_reached(position: VirtualPosition, price: float) -> bool:
    stop = position.exit_plan.trailing_stop or position.exit_plan.stop_loss
    if position.direction is SignalDirection.LONG:
        return price <= stop
    return price >= stop


def _time_stop_reached(position: VirtualPosition, timestamp: datetime) -> bool:
    time_stop_minutes = position.exit_plan.time_stop_minutes
    if time_stop_minutes is None:
        return False
    return timestamp - position.opened_at >= timedelta(minutes=time_stop_minutes)


def _pnl_pct(position: VirtualPosition, exit_price: float) -> float:
    if position.direction is SignalDirection.LONG:
        return round(((exit_price - position.entry_price) / position.entry_price) * 100, 10)
    return round(((position.entry_price - exit_price) / position.entry_price) * 100, 10)


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        msg = "symbol must be a non-empty string."
        raise ValueError(msg)
    return symbol.strip().upper()


def _validate_positive_price(price: float) -> None:
    if price <= 0:
        msg = "price must be positive."
        raise ValueError(msg)
