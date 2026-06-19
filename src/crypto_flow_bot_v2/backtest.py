"""Backtest and replay engine for historical MarketSnapshot streams.

The module replays already-built snapshots through the RFA engine and virtual position manager.
It never fetches Binance data, sends Telegram messages, or touches real exchange orders.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.models import MarketSnapshot, SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.position_manager import (
    PositionEvent,
    PositionEventType,
    VirtualPositionManager,
)
from crypto_flow_bot_v2.rfa_engine import RFAEngine


class ReplayEventType(StrEnum):
    """Replay event categories emitted by BacktestReplayEngine."""

    DECISION = "DECISION"
    POSITION_EVENT = "POSITION_EVENT"


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One chronological replay event."""

    timestamp: datetime
    symbol: str
    event_type: ReplayEventType
    decision: SignalDecision | None = None
    position_event: PositionEvent | None = None

    def __post_init__(self) -> None:
        has_decision = self.decision is not None
        has_position_event = self.position_event is not None
        if self.event_type is ReplayEventType.DECISION and not has_decision:
            msg = "decision event requires a SignalDecision payload."
            raise ValueError(msg)
        if self.event_type is ReplayEventType.POSITION_EVENT and not has_position_event:
            msg = "position event requires a PositionEvent payload."
            raise ValueError(msg)
        if has_decision and has_position_event:
            msg = "replay event cannot contain both decision and position event payloads."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    """Aggregate summary for a replay run."""

    symbols: tuple[str, ...]
    started_at: datetime | None
    ended_at: datetime | None
    snapshots_processed: int
    signals_seen: int
    positions_opened: int
    positions_closed: int
    wins: int
    losses: int
    total_pnl_pct: float
    average_pnl_pct: float
    max_drawdown_pct: float
    open_positions: int


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Full replay output."""

    events: tuple[ReplayEvent, ...]
    summary: BacktestSummary


class HistoricalSnapshotSource(Protocol):
    """Read-only historical snapshot source used by the replay engine."""

    def snapshots(self, symbols: Sequence[str] | None = None) -> Iterable[MarketSnapshot]:
        """Yield historical snapshots for all or selected symbols."""


@dataclass(frozen=True, slots=True)
class InMemorySnapshotSource:
    """Deterministic in-memory snapshot source for tests and small fixture replays."""

    _snapshots: tuple[MarketSnapshot, ...]

    def __init__(self, snapshots: Iterable[MarketSnapshot]) -> None:
        object.__setattr__(self, "_snapshots", _sorted_snapshots(tuple(snapshots)))

    def snapshots(self, symbols: Sequence[str] | None = None) -> Iterable[MarketSnapshot]:
        """Return stored snapshots, optionally filtered by symbol."""

        if symbols is None:
            return self._snapshots
        selected_symbols = {_normalize_symbol(symbol) for symbol in symbols}
        return tuple(
            snapshot
            for snapshot in self._snapshots
            if _normalize_symbol(snapshot.symbol) in selected_symbols
        )


class BacktestReplayEngine:
    """Replay MarketSnapshot streams through RFA decisions and virtual positions.

    The engine is intentionally offline and side-effect free outside its in-memory virtual position
    manager. It does not fetch market data, send Telegram alerts, or execute real trades.
    """

    def __init__(
        self,
        config: BotConfig,
        signal_engine: RFAEngine | None = None,
        position_manager: VirtualPositionManager | None = None,
    ) -> None:
        self._signal_engine = signal_engine or RFAEngine(config)
        self._position_manager = position_manager or VirtualPositionManager(config)

    def run(
        self,
        snapshot_source: HistoricalSnapshotSource | Iterable[MarketSnapshot],
        symbols: Sequence[str] | None = None,
    ) -> ReplayResult:
        """Replay historical snapshots and return chronological events plus a summary."""

        snapshots = _load_snapshots(snapshot_source=snapshot_source, symbols=symbols)
        events: list[ReplayEvent] = []

        for snapshot in snapshots:
            decision = self._signal_engine.evaluate(snapshot)
            events.append(_decision_event(decision))

            price_event = self._position_manager.update_price(
                symbol=snapshot.symbol,
                price=snapshot.price,
                timestamp=snapshot.timestamp,
            )
            if price_event.event_type is not PositionEventType.IGNORED:
                events.append(_position_event(price_event))

            if price_event.event_type is PositionEventType.CLOSED:
                continue
            if self._position_manager.has_active_position(snapshot.symbol):
                continue

            open_event = self._position_manager.open_from_decision(decision)
            if open_event.event_type is not PositionEventType.IGNORED:
                events.append(_position_event(open_event))

        final_events = tuple(events)
        return ReplayResult(
            events=final_events,
            summary=_build_summary(
                snapshots=snapshots,
                events=final_events,
                open_positions=len(self._position_manager.active_positions()),
                requested_symbols=symbols,
            ),
        )


def _load_snapshots(
    snapshot_source: HistoricalSnapshotSource | Iterable[MarketSnapshot],
    symbols: Sequence[str] | None,
) -> tuple[MarketSnapshot, ...]:
    if hasattr(snapshot_source, "snapshots"):
        raw_snapshots = snapshot_source.snapshots(symbols)
    else:
        raw_snapshots = snapshot_source

    snapshots = tuple(raw_snapshots)
    if symbols is not None and not hasattr(snapshot_source, "snapshots"):
        selected_symbols = {_normalize_symbol(symbol) for symbol in symbols}
        snapshots = tuple(
            snapshot
            for snapshot in snapshots
            if _normalize_symbol(snapshot.symbol) in selected_symbols
        )
    return _sorted_snapshots(snapshots)


def _sorted_snapshots(snapshots: tuple[MarketSnapshot, ...]) -> tuple[MarketSnapshot, ...]:
    return tuple(sorted(snapshots, key=lambda snapshot: (snapshot.timestamp, snapshot.symbol)))


def _decision_event(decision: SignalDecision) -> ReplayEvent:
    return ReplayEvent(
        timestamp=decision.timestamp,
        symbol=_normalize_symbol(decision.symbol),
        event_type=ReplayEventType.DECISION,
        decision=decision,
    )


def _position_event(event: PositionEvent) -> ReplayEvent:
    return ReplayEvent(
        timestamp=event.timestamp,
        symbol=_normalize_symbol(event.symbol),
        event_type=ReplayEventType.POSITION_EVENT,
        position_event=event,
    )


def _build_summary(
    snapshots: tuple[MarketSnapshot, ...],
    events: tuple[ReplayEvent, ...],
    open_positions: int,
    requested_symbols: Sequence[str] | None,
) -> BacktestSummary:
    decisions = tuple(event.decision for event in events if event.decision is not None)
    position_events = tuple(
        event.position_event for event in events if event.position_event is not None
    )
    closed_events = tuple(
        event for event in position_events if event.event_type is PositionEventType.CLOSED
    )
    pnl_values = tuple(event.pnl_pct or 0.0 for event in closed_events)
    total_pnl = round(sum(pnl_values), 10)
    positions_closed = len(closed_events)

    average_pnl = 0.0
    if positions_closed:
        average_pnl = round(total_pnl / positions_closed, 10)

    return BacktestSummary(
        symbols=_summary_symbols(snapshots=snapshots, requested_symbols=requested_symbols),
        started_at=snapshots[0].timestamp if snapshots else None,
        ended_at=snapshots[-1].timestamp if snapshots else None,
        snapshots_processed=len(snapshots),
        signals_seen=sum(1 for decision in decisions if _is_trade_signal(decision)),
        positions_opened=sum(
            1 for event in position_events if event.event_type is PositionEventType.OPENED
        ),
        positions_closed=positions_closed,
        wins=sum(1 for pnl in pnl_values if pnl > 0),
        losses=sum(1 for pnl in pnl_values if pnl < 0),
        total_pnl_pct=total_pnl,
        average_pnl_pct=average_pnl,
        max_drawdown_pct=_max_drawdown_pct(pnl_values),
        open_positions=open_positions,
    )


def _summary_symbols(
    snapshots: tuple[MarketSnapshot, ...],
    requested_symbols: Sequence[str] | None,
) -> tuple[str, ...]:
    if snapshots:
        return tuple(dict.fromkeys(_normalize_symbol(snapshot.symbol) for snapshot in snapshots))
    if requested_symbols is None:
        return ()
    return tuple(dict.fromkeys(_normalize_symbol(symbol) for symbol in requested_symbols))


def _is_trade_signal(decision: SignalDecision) -> bool:
    return (
        decision.signal_type is not SignalType.NO_TRADE
        and decision.direction is not SignalDirection.NONE
        and decision.blocked_reason is None
    )


def _max_drawdown_pct(pnl_values: tuple[float, ...]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return round(max_drawdown, 10)


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        msg = "symbol must be a non-empty string."
        raise ValueError(msg)
    return symbol.strip().upper()
