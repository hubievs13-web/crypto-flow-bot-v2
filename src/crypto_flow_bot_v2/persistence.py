"""Persistence for virtual position state.

This module persists simulated positions only. It never stores exchange credentials, never uses
Binance private APIs, and never places real orders.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from crypto_flow_bot_v2.models import (
    ExitPlan,
    SignalDecision,
    SignalDirection,
    SignalType,
    VirtualPosition,
)
from crypto_flow_bot_v2.position_manager import (
    PositionEvent,
    PositionEventType,
    PositionExitReason,
    PositionManagerSnapshot,
    PositionStateSnapshot,
    VirtualPositionManager,
)

STATE_VERSION = 1


class PositionPersistenceError(RuntimeError):
    """Raised when virtual-position persistence cannot load or save state."""


class PositionStateStore(Protocol):
    """Storage protocol for virtual-position manager snapshots."""

    def load(self) -> PositionManagerSnapshot:
        """Load persisted virtual-position state."""

    def save(self, snapshot: PositionManagerSnapshot) -> None:
        """Persist virtual-position state."""


@dataclass(frozen=True, slots=True)
class JsonPositionStateStore:
    """JSON-file store for virtual-position manager state."""

    path: Path

    def load(self) -> PositionManagerSnapshot:
        """Load virtual-position state from JSON, returning empty state when absent."""

        if not self.path.exists():
            return PositionManagerSnapshot()
        raw_text = self.path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return PositionManagerSnapshot()

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            msg = f"Invalid JSON position state file: {self.path}"
            raise PositionPersistenceError(msg) from exc
        return _snapshot_from_payload(payload)

    def save(self, snapshot: PositionManagerSnapshot) -> None:
        """Atomically save virtual-position state to JSON."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _snapshot_to_payload(snapshot)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


class PersistentVirtualPositionManager:
    """Autosaving wrapper around VirtualPositionManager."""

    def __init__(self, manager: VirtualPositionManager, store: PositionStateStore) -> None:
        self._manager = manager
        self._store = store
        self._manager.restore_state(store.load())
        self._save()

    def active_positions(self) -> tuple[VirtualPosition, ...]:
        """Return all active virtual positions."""

        return self._manager.active_positions()

    def get_active_position(self, symbol: str) -> VirtualPosition | None:
        """Return the active virtual position for a symbol, if one exists."""

        return self._manager.get_active_position(symbol)

    def has_active_position(self, symbol: str) -> bool:
        """Return whether a symbol already has an active virtual position."""

        return self._manager.has_active_position(symbol)

    def is_on_cooldown(self, symbol: str, timestamp: datetime) -> bool:
        """Return whether a symbol is still inside its post-close cooldown window."""

        return self._manager.is_on_cooldown(symbol, timestamp)

    def open_from_decision(self, decision: SignalDecision) -> PositionEvent:
        """Open a virtual position and persist state when state changes."""

        event = self._manager.open_from_decision(decision)
        if event.event_type is PositionEventType.OPENED:
            self._save()
        return event

    def update_price(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        invalidation_reason: str | None = None,
    ) -> PositionEvent:
        """Update a virtual position and persist state when state changes."""

        event = self._manager.update_price(
            symbol=symbol,
            price=price,
            timestamp=timestamp,
            invalidation_reason=invalidation_reason,
        )
        if event.event_type in {PositionEventType.UPDATED, PositionEventType.CLOSED}:
            self._save()
        return event

    def close_position(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        reason: PositionExitReason = PositionExitReason.MANUAL,
        message: str | None = None,
    ) -> PositionEvent:
        """Close a virtual position and persist state when state changes."""

        event = self._manager.close_position(
            symbol=symbol,
            price=price,
            timestamp=timestamp,
            reason=reason,
            message=message,
        )
        if event.event_type is PositionEventType.CLOSED:
            self._save()
        return event

    def snapshot_state(self) -> PositionManagerSnapshot:
        """Return current persisted-manager state."""

        return self._manager.snapshot_state()

    def restore_state(self, snapshot: PositionManagerSnapshot) -> None:
        """Restore manager state and persist it immediately."""

        self._manager.restore_state(snapshot)
        self._save()

    def _save(self) -> None:
        self._store.save(self._manager.snapshot_state())


def _snapshot_to_payload(snapshot: PositionManagerSnapshot) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "positions": [_position_state_to_payload(item) for item in snapshot.positions],
        "cooldown_until": {
            symbol: timestamp.isoformat()
            for symbol, timestamp in snapshot.normalized_cooldown_until().items()
        },
    }


def _snapshot_from_payload(payload: Any) -> PositionManagerSnapshot:
    data = _expect_mapping(payload, "root")
    version = data.get("version")
    if version != STATE_VERSION:
        msg = f"Unsupported position state version: {version!r}"
        raise PositionPersistenceError(msg)

    positions_raw = data.get("positions", [])
    if not isinstance(positions_raw, list):
        msg = "Position state field 'positions' must be a list."
        raise PositionPersistenceError(msg)
    cooldown_raw = data.get("cooldown_until", {})
    if not isinstance(cooldown_raw, dict):
        msg = "Position state field 'cooldown_until' must be a mapping."
        raise PositionPersistenceError(msg)

    cooldown_until = {
        str(symbol).upper(): _parse_datetime(value) for symbol, value in cooldown_raw.items()
    }
    return PositionManagerSnapshot(
        positions=tuple(_position_state_from_payload(item) for item in positions_raw),
        cooldown_until=cooldown_until,
    )


def _position_state_to_payload(item: PositionStateSnapshot) -> dict[str, Any]:
    return {
        "position": _position_to_payload(item.position),
        "peak_price": item.peak_price,
        "trough_price": item.trough_price,
        "hit_take_profit_levels": list(item.hit_take_profit_levels),
    }


def _position_state_from_payload(payload: Any) -> PositionStateSnapshot:
    data = _expect_mapping(payload, "position_state")
    hit_levels = data.get("hit_take_profit_levels", [])
    if not isinstance(hit_levels, list):
        msg = "Position state field 'hit_take_profit_levels' must be a list."
        raise PositionPersistenceError(msg)
    return PositionStateSnapshot(
        position=_position_from_payload(data.get("position")),
        peak_price=_required_float(data, "peak_price"),
        trough_price=_required_float(data, "trough_price"),
        hit_take_profit_levels=tuple(float(level) for level in hit_levels),
    )


def _position_to_payload(position: VirtualPosition) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "direction": position.direction.value,
        "entry_price": position.entry_price,
        "opened_at": position.opened_at.isoformat(),
        "exit_plan": _exit_plan_to_payload(position.exit_plan),
        "confidence": position.confidence,
        "active": position.active,
        "source_signal_type": (
            position.source_signal_type.value if position.source_signal_type is not None else None
        ),
    }


def _position_from_payload(payload: Any) -> VirtualPosition:
    data = _expect_mapping(payload, "position")
    source_signal_type = data.get("source_signal_type")
    return VirtualPosition(
        symbol=_required_str(data, "symbol").upper(),
        direction=SignalDirection(_required_str(data, "direction")),
        entry_price=_required_float(data, "entry_price"),
        opened_at=_parse_datetime(data.get("opened_at")),
        exit_plan=_exit_plan_from_payload(data.get("exit_plan")),
        confidence=_required_int(data, "confidence"),
        active=bool(data.get("active", True)),
        source_signal_type=(
            SignalType(source_signal_type) if isinstance(source_signal_type, str) else None
        ),
    )


def _exit_plan_to_payload(exit_plan: ExitPlan) -> dict[str, Any]:
    return {
        "stop_loss": exit_plan.stop_loss,
        "take_profit_levels": list(exit_plan.take_profit_levels),
        "trailing_stop": exit_plan.trailing_stop,
        "time_stop_minutes": exit_plan.time_stop_minutes,
        "invalidation_reason": exit_plan.invalidation_reason,
    }


def _exit_plan_from_payload(payload: Any) -> ExitPlan:
    data = _expect_mapping(payload, "exit_plan")
    take_profit_levels = data.get("take_profit_levels")
    if not isinstance(take_profit_levels, list) or not take_profit_levels:
        msg = "Exit plan field 'take_profit_levels' must be a non-empty list."
        raise PositionPersistenceError(msg)
    time_stop_minutes = data.get("time_stop_minutes")
    if time_stop_minutes is not None and not isinstance(time_stop_minutes, int):
        msg = "Exit plan field 'time_stop_minutes' must be an integer or null."
        raise PositionPersistenceError(msg)
    invalidation_reason = data.get("invalidation_reason")
    if invalidation_reason is not None and not isinstance(invalidation_reason, str):
        msg = "Exit plan field 'invalidation_reason' must be a string or null."
        raise PositionPersistenceError(msg)
    return ExitPlan(
        stop_loss=_required_float(data, "stop_loss"),
        take_profit_levels=tuple(float(level) for level in take_profit_levels),
        trailing_stop=_optional_float(data, "trailing_stop"),
        time_stop_minutes=time_stop_minutes,
        invalidation_reason=invalidation_reason,
    )


def _expect_mapping(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        msg = f"Position state field '{name}' must be a mapping."
        raise PositionPersistenceError(msg)
    return payload


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Position state field '{key}' must be a non-empty string."
        raise PositionPersistenceError(msg)
    return value.strip()


def _required_float(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"Position state field '{key}' must be numeric."
        raise PositionPersistenceError(msg)
    return float(value)


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"Position state field '{key}' must be numeric or null."
        raise PositionPersistenceError(msg)
    return float(value)


def _required_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"Position state field '{key}' must be an integer."
        raise PositionPersistenceError(msg)
    return value


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        msg = "Position state datetime fields must be non-empty ISO strings."
        raise PositionPersistenceError(msg)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"Invalid position state datetime: {value!r}"
        raise PositionPersistenceError(msg) from exc
