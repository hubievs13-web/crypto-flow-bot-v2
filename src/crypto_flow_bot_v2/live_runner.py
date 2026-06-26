"""Live Telegram-only alert runner.

The runner orchestrates public Binance market data, normalized snapshots, RFA decisions,
virtual position lifecycle management, and Telegram alerts. It never uses Binance private APIs
and never places, modifies, or cancels real exchange orders.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path
from time import sleep
from typing import Protocol

from crypto_flow_bot_v2.binance import BinanceFuturesClient
from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.logging import get_logger
from crypto_flow_bot_v2.models import (
    MarketSnapshot,
    SignalDecision,
    SignalDirection,
    SignalType,
    VirtualPosition,
)
from crypto_flow_bot_v2.persistence import JsonPositionStateStore, PersistentVirtualPositionManager
from crypto_flow_bot_v2.position_manager import (
    PositionEvent,
    PositionEventType,
    VirtualPositionManager,
)
from crypto_flow_bot_v2.regime_lite import RegimeLiteScoringLayer
from crypto_flow_bot_v2.rfa_engine import RFAEngine
from crypto_flow_bot_v2.signal_governor import (
    SignalGovernor,
    SignalGovernorDecision,
    SignalGovernorResult,
)
from crypto_flow_bot_v2.snapshot_builder import MarketSnapshotBuilder
from crypto_flow_bot_v2.telegram import (
    TelegramAlertResult,
    TelegramAlertService,
    TelegramAlertStatus,
)

LOGGER = get_logger(__name__)
Sleeper = Callable[[float], None]


class SnapshotBuilder(Protocol):
    """Snapshot builder protocol used by the live runner."""

    def build(self, symbol: str) -> MarketSnapshot:
        """Build one snapshot for a symbol."""


class SignalEngine(Protocol):
    """Signal engine protocol used by the live runner."""

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        """Evaluate one market snapshot."""


class PositionManager(Protocol):
    """Virtual position manager protocol used by the live runner."""

    def active_positions(self) -> tuple[VirtualPosition, ...]:
        """Return active virtual positions."""

    def update_price(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        invalidation_reason: str | None = None,
    ) -> PositionEvent:
        """Update one virtual position with the latest market price."""

    def open_from_decision(self, decision: SignalDecision) -> PositionEvent:
        """Open a virtual position from a tradeable decision when allowed."""


class TelegramAlerts(Protocol):
    """Telegram alert protocol used by the live runner."""

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        """Send one signal alert."""

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        """Send one virtual-position lifecycle alert."""


@dataclass(frozen=True, slots=True)
class LiveCycleReport:
    """Summary for one live polling cycle."""

    snapshots_built: int = 0
    build_errors: int = 0
    decisions_evaluated: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    telegram_alerts_sent: int = 0
    telegram_alerts_skipped: int = 0
    telegram_alert_errors: int = 0
    active_positions: int = 0
    symbol_errors: int = 0


@dataclass(frozen=True, slots=True)
class LiveRunStats:
    """Aggregate summary for a live runner execution."""

    cycles: int
    snapshots_built: int
    build_errors: int
    decisions_evaluated: int
    positions_opened: int
    positions_closed: int
    telegram_alerts_sent: int
    telegram_alerts_skipped: int
    telegram_alert_errors: int
    last_report: LiveCycleReport | None = None
    symbol_errors: int = 0


@dataclass(frozen=True, slots=True)
class _SymbolCycleResult:
    snapshot_built: bool = False
    build_error: bool = False
    decision_evaluated: bool = False
    position_opened: bool = False
    position_closed: bool = False
    telegram_alerts_sent: int = 0
    telegram_alerts_skipped: int = 0
    telegram_alert_errors: int = 0
    symbol_error: bool = False


@dataclass(frozen=True, slots=True)
class _GovernorSymbolState:
    result: _SymbolCycleResult
    decision: SignalDecision | None = None


@dataclass(frozen=True, slots=True)
class _AlertCounter:
    sent: int = 0
    skipped: int = 0
    errors: int = 0


class LiveAlertRunner:
    """Run live Telegram-only RFA alert cycles without real exchange execution."""

    def __init__(
        self,
        config: BotConfig,
        snapshot_builder: SnapshotBuilder,
        signal_engine: SignalEngine,
        position_manager: PositionManager,
        telegram_alerts: TelegramAlerts,
        cycle_interval_seconds: int = 900,
        sleeper: Sleeper = sleep,
        signal_governor: SignalGovernor | None = None,
    ) -> None:
        _validate_cycle_interval_seconds(cycle_interval_seconds)
        self._config = config
        self._snapshot_builder = snapshot_builder
        self._signal_engine = signal_engine
        self._position_manager = position_manager
        self._telegram_alerts = telegram_alerts
        self._cycle_interval_seconds = cycle_interval_seconds
        self._sleeper = sleeper
        self._signal_governor = signal_governor or SignalGovernor(config)

    @classmethod
    def from_config(
        cls,
        config: BotConfig,
        cycle_interval_seconds: int = 900,
        position_state_path: str | Path | None = None,
    ) -> LiveAlertRunner:
        """Build the production live runner stack from configuration."""

        data_client = BinanceFuturesClient.from_config(config.binance)
        snapshot_builder = MarketSnapshotBuilder(data_client=data_client, config=config)
        position_manager: PositionManager = VirtualPositionManager(config)
        if position_state_path is not None:
            store = JsonPositionStateStore(Path(position_state_path))
            position_manager = PersistentVirtualPositionManager(
                manager=VirtualPositionManager(config),
                store=store,
            )
            LOGGER.info("Virtual position persistence enabled: path=%s", position_state_path)

        base_signal_engine = RFAEngine(config)
        signal_engine: SignalEngine = RegimeLiteScoringLayer(
            config=config,
            base_engine=base_signal_engine,
        )

        return cls(
            config=config,
            snapshot_builder=snapshot_builder,
            signal_engine=signal_engine,
            position_manager=position_manager,
            telegram_alerts=TelegramAlertService(config),
            cycle_interval_seconds=cycle_interval_seconds,
            signal_governor=SignalGovernor(config),
        )

    def run(self, max_cycles: int | None = None) -> LiveRunStats:
        """Run the live loop until max_cycles is reached, or forever when unset."""

        _validate_max_cycles(max_cycles)

        cycles = 0
        last_report: LiveCycleReport | None = None
        totals = _MutableTotals()
        while max_cycles is None or cycles < max_cycles:
            last_report = self.run_once()
            totals.add(last_report)
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                self._sleeper(self._cycle_interval_seconds)

        return totals.to_stats(cycles=cycles, last_report=last_report)

    def run_once(self, symbols: Sequence[str] | None = None) -> LiveCycleReport:
        """Run one polling cycle over configured or explicit symbols."""

        selected_symbols = self._config.symbols if symbols is None else tuple(symbols)
        if self._config.signal_governor.enabled:
            results = self._run_once_with_governor(selected_symbols)
        else:
            results = tuple(self._run_symbol(symbol) for symbol in selected_symbols)
        report = _report_from_results(
            results=results,
            active_positions=len(self._position_manager.active_positions()),
        )
        _log_cycle_report(report)
        return report

    def _run_once_with_governor(
        self,
        selected_symbols: tuple[str, ...],
    ) -> tuple[_SymbolCycleResult, ...]:
        states = {
            symbol: self._run_symbol_until_decision(symbol)
            for symbol in selected_symbols
        }
        trade_candidates = tuple(
            state.decision
            for state in states.values()
            if state.decision is not None and _is_trade_candidate(state.decision)
        )
        governor_result = self._select_governed_signals(trade_candidates)
        results_by_symbol = {symbol: state.result for symbol, state in states.items()}

        for symbol, state in states.items():
            decision = state.decision
            if decision is None:
                continue
            if not _is_trade_candidate(decision):
                results_by_symbol[symbol] = self._open_after_decision(
                    decision=decision,
                    base_result=state.result,
                    governor_decision=None,
                )

        for item in governor_result.skipped:
            _log_governor_skipped(item)
            results_by_symbol[item.decision.symbol] = _extend_result(
                results_by_symbol[item.decision.symbol],
                telegram_alerts_skipped=1,
            )

        for item in governor_result.allowed:
            _log_governor_passed(item)
            results_by_symbol[item.decision.symbol] = self._open_after_decision(
                decision=item.decision,
                base_result=results_by_symbol[item.decision.symbol],
                governor_decision=item,
            )

        return tuple(results_by_symbol[symbol] for symbol in selected_symbols)

    def _select_governed_signals(
        self,
        trade_candidates: tuple[SignalDecision, ...],
    ) -> SignalGovernorResult:
        try:
            return self._signal_governor.select(trade_candidates)
        except Exception:
            LOGGER.exception("signal governor failed; fail-open preserving old signal flow")
            return SignalGovernorResult(
                allowed=tuple(
                    SignalGovernorDecision(
                        decision=decision,
                        passed=True,
                        reason="governor error; fail-open",
                        rank=index,
                        final_score=decision.confidence,
                    )
                    for index, decision in enumerate(trade_candidates, start=1)
                ),
                skipped=(),
            )

    def _run_symbol_until_decision(self, symbol: str) -> _GovernorSymbolState:
        try:
            snapshot = self._snapshot_builder.build(symbol)
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "snapshot_build",
                symbol,
            )
            return _GovernorSymbolState(
                result=_SymbolCycleResult(build_error=True, symbol_error=True),
            )

        close_alert = _AlertCounter()
        try:
            update_event = self._position_manager.update_price(
                symbol=snapshot.symbol,
                price=snapshot.price,
                timestamp=snapshot.timestamp,
            )
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "position_update",
                snapshot.symbol,
            )
            return _GovernorSymbolState(
                result=_SymbolCycleResult(snapshot_built=True, symbol_error=True),
            )

        position_closed = update_event.event_type is PositionEventType.CLOSED
        if position_closed:
            close_alert = self._send_position_event(update_event)

        try:
            decision = self._signal_engine.evaluate(snapshot)
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "signal_evaluate",
                snapshot.symbol,
            )
            return _GovernorSymbolState(
                result=_SymbolCycleResult(
                    snapshot_built=True,
                    position_closed=position_closed,
                    telegram_alerts_sent=close_alert.sent,
                    telegram_alerts_skipped=close_alert.skipped,
                    telegram_alert_errors=close_alert.errors,
                    symbol_error=True,
                ),
            )
        _log_decision(decision)

        decision_alert = _AlertCounter()
        if _is_no_trade_decision(decision):
            decision_alert = self._send_no_trade_diagnostic(decision)

        alerts = _combine_alerts(close_alert, decision_alert)
        return _GovernorSymbolState(
            result=_SymbolCycleResult(
                snapshot_built=True,
                decision_evaluated=True,
                position_closed=position_closed,
                telegram_alerts_sent=alerts.sent,
                telegram_alerts_skipped=alerts.skipped,
                telegram_alert_errors=alerts.errors,
            ),
            decision=decision,
        )

    def _run_symbol(self, symbol: str) -> _SymbolCycleResult:
        try:
            snapshot = self._snapshot_builder.build(symbol)
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "snapshot_build",
                symbol,
            )
            return _SymbolCycleResult(build_error=True, symbol_error=True)

        close_alert = _AlertCounter()
        try:
            update_event = self._position_manager.update_price(
                symbol=snapshot.symbol,
                price=snapshot.price,
                timestamp=snapshot.timestamp,
            )
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "position_update",
                snapshot.symbol,
            )
            return _SymbolCycleResult(snapshot_built=True, symbol_error=True)

        position_closed = update_event.event_type is PositionEventType.CLOSED
        if position_closed:
            close_alert = self._send_position_event(update_event)

        try:
            decision = self._signal_engine.evaluate(snapshot)
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "signal_evaluate",
                snapshot.symbol,
            )
            return _SymbolCycleResult(
                snapshot_built=True,
                position_closed=position_closed,
                telegram_alerts_sent=close_alert.sent,
                telegram_alerts_skipped=close_alert.skipped,
                telegram_alert_errors=close_alert.errors,
                symbol_error=True,
            )
        _log_decision(decision)

        decision_alert = _AlertCounter()
        if _is_no_trade_decision(decision):
            decision_alert = self._send_no_trade_diagnostic(decision)

        base_result = _SymbolCycleResult(
            snapshot_built=True,
            decision_evaluated=True,
            position_closed=position_closed,
            telegram_alerts_sent=close_alert.sent + decision_alert.sent,
            telegram_alerts_skipped=close_alert.skipped + decision_alert.skipped,
            telegram_alert_errors=close_alert.errors + decision_alert.errors,
        )
        return self._open_after_decision(
            decision=decision,
            base_result=base_result,
            governor_decision=None,
        )

    def _open_after_decision(
        self,
        decision: SignalDecision,
        base_result: _SymbolCycleResult,
        governor_decision: SignalGovernorDecision | None,
    ) -> _SymbolCycleResult:
        decision_to_open = _with_governor_reason(decision, governor_decision)
        try:
            open_event = self._position_manager.open_from_decision(decision_to_open)
        except Exception:
            LOGGER.exception(
                "live symbol stage failed: stage=%s symbol=%s",
                "position_open",
                decision.symbol,
            )
            return _extend_result(base_result, symbol_error=True)

        position_opened = open_event.event_type is PositionEventType.OPENED
        if not position_opened:
            return base_result

        signal_alert = self._send_signal(decision_to_open)
        if governor_decision is not None and signal_alert.sent > 0:
            self._signal_governor.record_sent(decision_to_open)
        position_alert = self._send_position_event(open_event)
        open_alerts = _combine_alerts(signal_alert, position_alert)
        return _extend_result(
            base_result,
            position_opened=True,
            telegram_alerts_sent=open_alerts.sent,
            telegram_alerts_skipped=open_alerts.skipped,
            telegram_alert_errors=open_alerts.errors,
        )

    def _send_signal(self, decision: SignalDecision) -> _AlertCounter:
        try:
            return _counter_from_alert_result(self._telegram_alerts.send_signal(decision))
        except Exception:
            LOGGER.exception("failed to send signal alert for symbol=%s", decision.symbol)
            return _AlertCounter(errors=1)

    def _send_position_event(self, event: PositionEvent) -> _AlertCounter:
        try:
            return _counter_from_alert_result(self._telegram_alerts.send_position_event(event))
        except Exception:
            LOGGER.exception("failed to send position alert for symbol=%s", event.symbol)
            return _AlertCounter(errors=1)

    def _send_no_trade_diagnostic(self, decision: SignalDecision) -> _AlertCounter:
        try:
            sender = getattr(self._telegram_alerts, "send_no_trade_diagnostic", None)
            if callable(sender):
                result = sender(decision)
            else:
                raw_send = getattr(self._telegram_alerts, "_send", None)
                if not callable(raw_send):
                    LOGGER.warning(
                        "NO_TRADE Telegram diagnostic skipped: no sender available symbol=%s "
                        "blocked_reason=%s",
                        decision.symbol,
                        decision.blocked_reason or "",
                    )
                    return _AlertCounter(skipped=1)
                result = raw_send(_format_no_trade_diagnostic(decision))
        except Exception:
            LOGGER.exception(
                "failed to send NO_TRADE diagnostic for symbol=%s blocked_reason=%s",
                decision.symbol,
                decision.blocked_reason or "",
            )
            return _AlertCounter(errors=1)

        counter = _counter_from_alert_result(result)
        if result.status is TelegramAlertStatus.SKIPPED:
            LOGGER.warning(
                "NO_TRADE Telegram diagnostic skipped for symbol=%s blocked_reason=%s: %s",
                decision.symbol,
                decision.blocked_reason or "",
                result.message,
            )
        return counter


@dataclass(slots=True)
class _MutableTotals:
    snapshots_built: int = 0
    build_errors: int = 0
    decisions_evaluated: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    telegram_alerts_sent: int = 0
    telegram_alerts_skipped: int = 0
    telegram_alert_errors: int = 0
    symbol_errors: int = 0

    def add(self, report: LiveCycleReport) -> None:
        """Add one cycle report to aggregate totals."""

        self.snapshots_built += report.snapshots_built
        self.build_errors += report.build_errors
        self.decisions_evaluated += report.decisions_evaluated
        self.positions_opened += report.positions_opened
        self.positions_closed += report.positions_closed
        self.telegram_alerts_sent += report.telegram_alerts_sent
        self.telegram_alerts_skipped += report.telegram_alerts_skipped
        self.telegram_alert_errors += report.telegram_alert_errors
        self.symbol_errors += report.symbol_errors

    def to_stats(self, cycles: int, last_report: LiveCycleReport | None) -> LiveRunStats:
        """Convert mutable aggregate totals into an immutable run summary."""

        return LiveRunStats(
            cycles=cycles,
            snapshots_built=self.snapshots_built,
            build_errors=self.build_errors,
            decisions_evaluated=self.decisions_evaluated,
            positions_opened=self.positions_opened,
            positions_closed=self.positions_closed,
            telegram_alerts_sent=self.telegram_alerts_sent,
            telegram_alerts_skipped=self.telegram_alerts_skipped,
            telegram_alert_errors=self.telegram_alert_errors,
            last_report=last_report,
            symbol_errors=self.symbol_errors,
        )


def _report_from_results(
    results: tuple[_SymbolCycleResult, ...],
    active_positions: int,
) -> LiveCycleReport:
    return LiveCycleReport(
        snapshots_built=sum(result.snapshot_built for result in results),
        build_errors=sum(result.build_error for result in results),
        decisions_evaluated=sum(result.decision_evaluated for result in results),
        positions_opened=sum(result.position_opened for result in results),
        positions_closed=sum(result.position_closed for result in results),
        telegram_alerts_sent=sum(result.telegram_alerts_sent for result in results),
        telegram_alerts_skipped=sum(result.telegram_alerts_skipped for result in results),
        telegram_alert_errors=sum(result.telegram_alert_errors for result in results),
        active_positions=active_positions,
        symbol_errors=sum(result.symbol_error for result in results),
    )


def _log_cycle_report(report: LiveCycleReport) -> None:
    LOGGER.info(
        "live cycle completed: snapshots=%s build_errors=%s decisions=%s opened=%s "
        "closed=%s alerts_sent=%s alerts_skipped=%s alert_errors=%s active=%s "
        "symbol_errors=%s",
        report.snapshots_built,
        report.build_errors,
        report.decisions_evaluated,
        report.positions_opened,
        report.positions_closed,
        report.telegram_alerts_sent,
        report.telegram_alerts_skipped,
        report.telegram_alert_errors,
        report.active_positions,
        report.symbol_errors,
    )


def _log_decision(decision: SignalDecision) -> None:
    if _is_no_trade_decision(decision):
        LOGGER.info(
            "live NO_TRADE: symbol=%s blocked_reason=%s confidence=%s signal_type=%s "
            "direction=%s reasons=%s",
            decision.symbol,
            decision.blocked_reason or "",
            decision.confidence,
            decision.signal_type.value,
            decision.direction.value,
            " | ".join(decision.reasons),
        )
        return

    LOGGER.info(
        "live TRADE_DECISION: symbol=%s signal_type=%s direction=%s confidence=%s "
        "blocked_reason=%s score_breakdown=%s reasons=%s",
        decision.symbol,
        decision.signal_type.value,
        decision.direction.value,
        decision.confidence,
        decision.blocked_reason or "",
        _score_breakdown_log(decision),
        " | ".join(decision.reasons),
    )


def _score_breakdown_log(decision: SignalDecision) -> str:
    breakdown = decision.score_breakdown
    if breakdown is None:
        return "none"
    return (
        f"base={breakdown.base_score} regime={breakdown.regime} "
        f"regime_confidence={breakdown.regime_confidence:.2f} "
        f"regime_adjustment={breakdown.regime_adjustment:+d} final={breakdown.final_score}"
    )


def _is_no_trade_decision(decision: SignalDecision) -> bool:
    return decision.signal_type is SignalType.NO_TRADE


def _is_trade_candidate(decision: SignalDecision) -> bool:
    return (
        decision.signal_type is not SignalType.NO_TRADE
        and decision.direction is not SignalDirection.NONE
        and decision.blocked_reason is None
        and decision.entry_price is not None
        and decision.stop_loss is not None
        and bool(decision.take_profit_levels)
    )


def _with_governor_reason(
    decision: SignalDecision,
    governor_decision: SignalGovernorDecision | None,
) -> SignalDecision:
    if governor_decision is None:
        return decision
    return replace(
        decision,
        reasons=(
            *decision.reasons,
            f"governor: passed ({governor_decision.reason}, rank={governor_decision.rank})",
        ),
    )


def _log_governor_passed(item: SignalGovernorDecision) -> None:
    LOGGER.info(
        "signal governor passed: symbol=%s direction=%s reason=%s rank=%s final_score=%s",
        item.decision.symbol,
        item.decision.direction.value,
        item.reason,
        item.rank,
        item.final_score,
    )


def _log_governor_skipped(item: SignalGovernorDecision) -> None:
    LOGGER.info(
        "%s %s skipped by governor: reason=%s rank=%s final_score=%s",
        item.decision.symbol,
        item.decision.direction.value,
        item.reason,
        item.rank,
        item.final_score,
    )


def _format_no_trade_diagnostic(decision: SignalDecision) -> str:
    lines = [
        "<b>RFA NO_TRADE diagnostic</b>",
        f"Symbol: <b>{escape(decision.symbol)}</b>",
        f"Blocked reason: <code>{escape(decision.blocked_reason or 'none')}</code>",
        f"Confidence: <b>{decision.confidence}/100</b>",
        f"Signal type: <code>{escape(decision.signal_type.value)}</code>",
        f"Direction: <code>{escape(decision.direction.value)}</code>",
        f"Timestamp: <code>{escape(decision.timestamp.isoformat())}</code>",
    ]
    if decision.reasons:
        lines.extend(("", "<b>Reasons</b>"))
        lines.extend(f"• {escape(reason)}" for reason in decision.reasons[:8])
    return "\n".join(lines)


def _counter_from_alert_result(result: TelegramAlertResult) -> _AlertCounter:
    if result.status is TelegramAlertStatus.SENT:
        return _AlertCounter(sent=1)
    if result.status is TelegramAlertStatus.SKIPPED:
        return _AlertCounter(skipped=1)
    return _AlertCounter(errors=1)


def _combine_alerts(*counters: _AlertCounter) -> _AlertCounter:
    return _AlertCounter(
        sent=sum(counter.sent for counter in counters),
        skipped=sum(counter.skipped for counter in counters),
        errors=sum(counter.errors for counter in counters),
    )


def _extend_result(
    result: _SymbolCycleResult,
    *,
    position_opened: bool = False,
    telegram_alerts_sent: int = 0,
    telegram_alerts_skipped: int = 0,
    telegram_alert_errors: int = 0,
    symbol_error: bool = False,
) -> _SymbolCycleResult:
    return _SymbolCycleResult(
        snapshot_built=result.snapshot_built,
        build_error=result.build_error,
        decision_evaluated=result.decision_evaluated,
        position_opened=result.position_opened or position_opened,
        position_closed=result.position_closed,
        telegram_alerts_sent=result.telegram_alerts_sent + telegram_alerts_sent,
        telegram_alerts_skipped=result.telegram_alerts_skipped + telegram_alerts_skipped,
        telegram_alert_errors=result.telegram_alert_errors + telegram_alert_errors,
        symbol_error=result.symbol_error or symbol_error,
    )


def _validate_cycle_interval_seconds(cycle_interval_seconds: int) -> None:
    if cycle_interval_seconds <= 0:
        msg = "cycle_interval_seconds must be positive."
        raise ValueError(msg)


def _validate_max_cycles(max_cycles: int | None) -> None:
    if max_cycles is not None and max_cycles <= 0:
        msg = "max_cycles must be positive when provided."
        raise ValueError(msg)
