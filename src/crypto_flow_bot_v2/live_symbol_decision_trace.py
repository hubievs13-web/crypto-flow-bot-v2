"""Structured live-runner per-symbol decision trace diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, replace

from crypto_flow_bot_v2 import live_runner
from crypto_flow_bot_v2.models import MarketSnapshot, SignalDecision
from crypto_flow_bot_v2.position_manager import PositionEventType
from crypto_flow_bot_v2.signal_governor import SignalGovernorDecision, SignalGovernorResult

TRACE_EVENT = "live_symbol_decision_trace"


@dataclass(frozen=True, slots=True)
class _TraceGovernorState:
    result: live_runner._SymbolCycleResult  # noqa: SLF001
    decision: SignalDecision | None = None
    rfa_decision: SignalDecision | None = None


def install_live_symbol_decision_trace() -> None:
    """Install structured per-symbol decision tracing on LiveAlertRunner."""

    runner_cls = live_runner.LiveAlertRunner
    if getattr(runner_cls, "_live_symbol_decision_trace_installed", False):
        return

    runner_cls._run_symbol = _run_symbol  # type: ignore[method-assign]
    runner_cls._run_symbol_until_decision = (  # type: ignore[method-assign]
        _run_symbol_until_decision
    )
    runner_cls._run_once_with_governor = _run_once_with_governor  # type: ignore[method-assign]
    runner_cls._live_symbol_decision_trace_installed = True


def _run_once_with_governor(
    self: live_runner.LiveAlertRunner,
    selected_symbols: tuple[str, ...],
) -> tuple[live_runner._SymbolCycleResult, ...]:  # noqa: SLF001
    states = {symbol: self._run_symbol_until_decision(symbol) for symbol in selected_symbols}
    trade_candidates = tuple(
        state.decision
        for state in states.values()
        if state.decision is not None
        and live_runner._is_trade_candidate(state.decision)  # noqa: SLF001
    )
    governor_result = _select_governed_signals(self, trade_candidates)
    results_by_symbol = {symbol: state.result for symbol, state in states.items()}
    governor_by_symbol: dict[str, SignalGovernorDecision] = {}

    for symbol, state in states.items():
        decision = state.decision
        if decision is not None and not live_runner._is_trade_candidate(decision):  # noqa: SLF001
            results_by_symbol[symbol] = self._open_after_decision(
                decision=decision,
                base_result=state.result,
                governor_decision=None,
            )

    for item in governor_result.skipped:
        live_runner._log_governor_skipped(item)  # noqa: SLF001
        governor_by_symbol[item.decision.symbol] = item
        results_by_symbol[item.decision.symbol] = live_runner._extend_result(  # noqa: SLF001
            results_by_symbol[item.decision.symbol],
            telegram_alerts_skipped=1,
        )

    for item in governor_result.allowed:
        live_runner._log_governor_passed(item)  # noqa: SLF001
        governor_by_symbol[item.decision.symbol] = item
        results_by_symbol[item.decision.symbol] = self._open_after_decision(
            decision=item.decision,
            base_result=results_by_symbol[item.decision.symbol],
            governor_decision=item,
        )

    for symbol in selected_symbols:
        _log_live_symbol_decision_trace(
            symbol=symbol,
            decision=states[symbol].rfa_decision,
            result=results_by_symbol[symbol],
            governor_decision=governor_by_symbol.get(symbol),
        )
    return tuple(results_by_symbol[symbol] for symbol in selected_symbols)



def _with_decision_diagnostics(
    result: live_runner._SymbolCycleResult,  # noqa: SLF001
    decision: SignalDecision,
    candidate_result: object | None,
) -> live_runner._SymbolCycleResult:  # noqa: SLF001
    return replace(
        result,
        blocked_reason=decision.blocked_reason,
        candidate_engine_reason=(
            None if candidate_result is None else getattr(candidate_result, "reason", None)
        ),
    )


def _select_governed_signals(
    runner: live_runner.LiveAlertRunner,
    trade_candidates: tuple[SignalDecision, ...],
) -> SignalGovernorResult:
    return runner._select_governed_signals(trade_candidates)  # noqa: SLF001


def _run_symbol_until_decision(
    self: live_runner.LiveAlertRunner,
    symbol: str,
) -> _TraceGovernorState:
    try:
        snapshot = self._snapshot_builder.build(symbol)  # noqa: SLF001
    except Exception:
        live_runner.LOGGER.exception(
            "live symbol stage failed: stage=%s symbol=%s",
            "snapshot_build",
            symbol,
        )
        return _TraceGovernorState(
            result=live_runner._SymbolCycleResult(  # noqa: SLF001
                build_error=True,
                symbol_error=True,
            )
        )

    close_alert = live_runner._AlertCounter()  # noqa: SLF001
    try:
        update_event = self._position_manager.update_price(  # noqa: SLF001
            symbol=snapshot.symbol,
            price=snapshot.price,
            timestamp=snapshot.timestamp,
        )
    except Exception:
        live_runner.LOGGER.exception(
            "live symbol stage failed: stage=%s symbol=%s",
            "position_update",
            snapshot.symbol,
        )
        return _TraceGovernorState(
            result=live_runner._SymbolCycleResult(  # noqa: SLF001
                snapshot_built=True,
                symbol_error=True,
            )
        )

    position_closed = update_event.event_type is PositionEventType.CLOSED
    if position_closed:
        close_alert = self._send_position_event(update_event)  # noqa: SLF001

    try:
        decision = self._signal_engine.evaluate(snapshot)  # noqa: SLF001
    except Exception:
        live_runner.LOGGER.exception(
            "live symbol stage failed: stage=%s symbol=%s",
            "signal_evaluate",
            snapshot.symbol,
        )
        return _TraceGovernorState(
            result=live_runner._SymbolCycleResult(  # noqa: SLF001
                snapshot_built=True,
                position_closed=position_closed,
                telegram_alerts_sent=close_alert.sent,
                telegram_alerts_skipped=close_alert.skipped,
                telegram_alert_errors=close_alert.errors,
                symbol_error=True,
            )
        )

    live_runner._log_decision(decision)  # noqa: SLF001
    decision_alert = live_runner._AlertCounter()  # noqa: SLF001
    if live_runner._is_no_trade_decision(decision):  # noqa: SLF001
        decision_alert = self._send_no_trade_diagnostic(decision)  # noqa: SLF001

    alerts = live_runner._combine_alerts(close_alert, decision_alert)  # noqa: SLF001
    candidate_decision = self._candidate_engine_decision(snapshot, decision)  # noqa: SLF001
    candidate_result = getattr(self, "_last_candidate_engine_result", None)
    result = _with_decision_diagnostics(
        live_runner._SymbolCycleResult(  # noqa: SLF001
            snapshot_built=True,
            decision_evaluated=True,
            position_closed=position_closed,
            telegram_alerts_sent=alerts.sent,
            telegram_alerts_skipped=alerts.skipped,
            telegram_alert_errors=alerts.errors,
        ),
        decision,
        candidate_result,
    )
    return _TraceGovernorState(
        result=result,
        decision=candidate_decision,
        rfa_decision=decision,
    )


def _run_symbol(
    self: live_runner.LiveAlertRunner,
    symbol: str,
) -> live_runner._SymbolCycleResult:  # noqa: SLF001
    try:
        snapshot = self._snapshot_builder.build(symbol)  # noqa: SLF001
    except Exception:
        live_runner.LOGGER.exception(
            "live symbol stage failed: stage=%s symbol=%s",
            "snapshot_build",
            symbol,
        )
        result = live_runner._SymbolCycleResult(build_error=True, symbol_error=True)  # noqa: SLF001
        _log_live_symbol_decision_trace(symbol=symbol, decision=None, result=result)
        return result

    close_alert = live_runner._AlertCounter()  # noqa: SLF001
    try:
        update_event = self._position_manager.update_price(  # noqa: SLF001
            symbol=snapshot.symbol,
            price=snapshot.price,
            timestamp=snapshot.timestamp,
        )
    except Exception:
        live_runner.LOGGER.exception(
            "live symbol stage failed: stage=%s symbol=%s",
            "position_update",
            snapshot.symbol,
        )
        result = live_runner._SymbolCycleResult(  # noqa: SLF001
            snapshot_built=True,
            symbol_error=True,
        )
        _log_live_symbol_decision_trace(symbol=snapshot.symbol, decision=None, result=result)
        return result

    position_closed = update_event.event_type is PositionEventType.CLOSED
    if position_closed:
        close_alert = self._send_position_event(update_event)  # noqa: SLF001

    decision = _evaluate_decision_or_trace_error(self, snapshot, close_alert, position_closed)
    if isinstance(decision, live_runner._SymbolCycleResult):  # noqa: SLF001
        return decision

    live_runner._log_decision(decision)  # noqa: SLF001
    decision_alert = live_runner._AlertCounter()  # noqa: SLF001
    if live_runner._is_no_trade_decision(decision):  # noqa: SLF001
        decision_alert = self._send_no_trade_diagnostic(decision)  # noqa: SLF001

    base_result = live_runner._SymbolCycleResult(  # noqa: SLF001
        snapshot_built=True,
        decision_evaluated=True,
        position_closed=position_closed,
        telegram_alerts_sent=close_alert.sent + decision_alert.sent,
        telegram_alerts_skipped=close_alert.skipped + decision_alert.skipped,
        telegram_alert_errors=close_alert.errors + decision_alert.errors,
    )
    candidate_decision = self._candidate_engine_decision(snapshot, decision)  # noqa: SLF001
    candidate_result = getattr(self, "_last_candidate_engine_result", None)
    base_result = _with_decision_diagnostics(base_result, decision, candidate_result)
    if candidate_decision is None:
        _log_live_symbol_decision_trace(
            symbol=snapshot.symbol,
            decision=decision,
            result=base_result,
        )
        return base_result

    result = self._open_after_decision(  # noqa: SLF001
        decision=candidate_decision,
        base_result=base_result,
        governor_decision=None,
    )
    _log_live_symbol_decision_trace(symbol=snapshot.symbol, decision=decision, result=result)
    return result


def _evaluate_decision_or_trace_error(
    runner: live_runner.LiveAlertRunner,
    snapshot: MarketSnapshot,
    close_alert: live_runner._AlertCounter,  # noqa: SLF001
    position_closed: bool,
) -> SignalDecision | live_runner._SymbolCycleResult:  # noqa: SLF001
    try:
        return runner._signal_engine.evaluate(snapshot)  # noqa: SLF001
    except Exception:
        live_runner.LOGGER.exception(
            "live symbol stage failed: stage=%s symbol=%s",
            "signal_evaluate",
            snapshot.symbol,
        )
        result = live_runner._SymbolCycleResult(  # noqa: SLF001
            snapshot_built=True,
            position_closed=position_closed,
            telegram_alerts_sent=close_alert.sent,
            telegram_alerts_skipped=close_alert.skipped,
            telegram_alert_errors=close_alert.errors,
            symbol_error=True,
        )
        _log_live_symbol_decision_trace(symbol=snapshot.symbol, decision=None, result=result)
        return result


def _log_live_symbol_decision_trace(
    *,
    symbol: str,
    decision: SignalDecision | None,
    result: live_runner._SymbolCycleResult,  # noqa: SLF001
    governor_decision: SignalGovernorDecision | None = None,
) -> None:
    live_runner.LOGGER.info(
        TRACE_EVENT,
        extra={
            "event": TRACE_EVENT,
            TRACE_EVENT: _symbol_decision_trace_payload(
                symbol=symbol,
                decision=decision,
                result=result,
                governor_decision=governor_decision,
            ),
        },
    )


def _symbol_decision_trace_payload(
    *,
    symbol: str,
    decision: SignalDecision | None,
    result: live_runner._SymbolCycleResult,  # noqa: SLF001
    governor_decision: SignalGovernorDecision | None,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": decision.timestamp.isoformat() if decision is not None else None,
        "rfa_decision": decision.signal_type.value if decision is not None else None,
        "direction": decision.direction.value if decision is not None else None,
        "confidence": decision.confidence if decision is not None else None,
        "blocked_reason": decision.blocked_reason if decision is not None else None,
        "score_breakdown": _score_breakdown_trace(decision),
        "position_opened": result.position_opened,
        "position_closed": result.position_closed,
        "telegram_sent": result.telegram_alerts_sent,
        "telegram_skipped": result.telegram_alerts_skipped,
        "telegram_errors": result.telegram_alert_errors,
        "snapshot_built": result.snapshot_built,
        "build_error": result.build_error,
        "decision_evaluated": result.decision_evaluated,
        "symbol_error": result.symbol_error,
        "governor": _governor_trace(governor_decision),
    }


def _score_breakdown_trace(
    decision: SignalDecision | None,
) -> dict[str, int | float | str] | None:
    if decision is None or decision.score_breakdown is None:
        return None
    breakdown = decision.score_breakdown
    return {
        "base_score": breakdown.base_score,
        "regime": breakdown.regime,
        "regime_confidence": breakdown.regime_confidence,
        "regime_adjustment": breakdown.regime_adjustment,
        "final_score": breakdown.final_score,
        "reason": breakdown.reason,
    }


def _governor_trace(
    governor_decision: SignalGovernorDecision | None,
) -> dict[str, bool | int | float | str | None] | None:
    if governor_decision is None:
        return None
    return {
        "passed": governor_decision.passed,
        "reason": governor_decision.reason,
        "rank": governor_decision.rank,
        "final_score": governor_decision.final_score,
    }
