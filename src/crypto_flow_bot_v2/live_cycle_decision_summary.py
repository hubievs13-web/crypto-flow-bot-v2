"""Structured live-runner per-cycle decision summary diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from crypto_flow_bot_v2 import live_runner, live_symbol_decision_trace

SUMMARY_EVENT = "live_cycle_decision_summary"
_TRACE_EVENT = live_symbol_decision_trace.TRACE_EVENT
_ORIGINAL_RUN_ONCE = live_runner.LiveAlertRunner.run_once
_ACTIVE_CYCLE_TRACES: list[dict[str, object]] | None = None


def install_live_cycle_decision_summary() -> None:
    """Install structured per-cycle decision summary logging on LiveAlertRunner."""

    runner_cls = live_runner.LiveAlertRunner
    if getattr(runner_cls, "_live_cycle_decision_summary_installed", False):
        return

    runner_cls.run_once = _run_once_with_decision_summary  # type: ignore[method-assign]
    live_symbol_decision_trace._log_live_symbol_decision_trace = (  # type: ignore[attr-defined]
        _log_symbol_trace_and_capture
    )
    runner_cls._live_cycle_decision_summary_installed = True


def _run_once_with_decision_summary(
    self: live_runner.LiveAlertRunner,
    symbols: Sequence[str] | None = None,
) -> live_runner.LiveCycleReport:
    global _ACTIVE_CYCLE_TRACES

    previous_traces = _ACTIVE_CYCLE_TRACES
    cycle_traces: list[dict[str, object]] = []
    _ACTIVE_CYCLE_TRACES = cycle_traces
    try:
        report = _ORIGINAL_RUN_ONCE(self, symbols=symbols)
    finally:
        _ACTIVE_CYCLE_TRACES = previous_traces

    _log_live_cycle_decision_summary(report=report, traces=tuple(cycle_traces))
    return report


def _log_symbol_trace_and_capture(
    *,
    symbol: str,
    decision: object | None,
    result: live_runner._SymbolCycleResult,  # noqa: SLF001
    governor_decision: object | None = None,
) -> None:
    payload = live_symbol_decision_trace._symbol_decision_trace_payload(  # noqa: SLF001
        symbol=symbol,
        decision=decision,
        result=result,
        governor_decision=governor_decision,
    )
    if _ACTIVE_CYCLE_TRACES is not None:
        _ACTIVE_CYCLE_TRACES.append(payload)
    live_runner.LOGGER.info(
        _TRACE_EVENT,
        extra={"event": _TRACE_EVENT, _TRACE_EVENT: payload},
    )


def _log_live_cycle_decision_summary(
    *,
    report: live_runner.LiveCycleReport,
    traces: tuple[dict[str, object], ...],
) -> None:
    live_runner.LOGGER.info(
        SUMMARY_EVENT,
        extra={
            "event": SUMMARY_EVENT,
            SUMMARY_EVENT: _cycle_decision_summary_payload(report=report, traces=traces),
        },
    )


def _cycle_decision_summary_payload(
    *,
    report: live_runner.LiveCycleReport,
    traces: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return {
        "symbols_checked": len(traces),
        "rfa_trade": _rfa_trade_count(traces),
        "rfa_no_trade": _rfa_no_trade_count(traces),
        "candidate_emitted": _candidate_count(traces, "emitted"),
        "candidate_saved": _candidate_count(traces, "saved"),
        "candidate_blocked": _candidate_count(traces, "blocked"),
        "governor_allowed": _governor_count(traces, passed=True),
        "governor_skipped": _governor_count(traces, passed=False),
        "positions_opened": report.positions_opened,
        "telegram_sent": report.telegram_alerts_sent,
        "telegram_errors": report.telegram_alert_errors,
        "top_blocked_reasons": _top_blocked_reasons(traces),
    }


def _rfa_trade_count(traces: tuple[dict[str, object], ...]) -> int:
    return sum(
        trace.get("rfa_decision") not in (None, "NO_TRADE")
        for trace in traces
    )


def _rfa_no_trade_count(traces: tuple[dict[str, object], ...]) -> int:
    return sum(trace.get("rfa_decision") == "NO_TRADE" for trace in traces)


def _candidate_count(traces: tuple[dict[str, object], ...], bucket: str) -> int:
    return sum(_candidate_bucket(trace.get("candidate_engine")) == bucket for trace in traces)


def _candidate_bucket(candidate: object) -> str | None:
    if not isinstance(candidate, dict):
        return None
    reason = candidate.get("reason")
    if reason == "candidate engine disabled":
        return None
    if candidate.get("emitted") is True:
        return "emitted"
    if reason == "candidate_saved_or_updated":
        return "saved"
    return "blocked"


def _governor_count(traces: tuple[dict[str, object], ...], *, passed: bool) -> int:
    return sum(
        isinstance(trace.get("governor"), dict)
        and trace["governor"].get("passed") is passed
        for trace in traces
    )


def _top_blocked_reasons(traces: tuple[dict[str, object], ...]) -> list[dict[str, int | str]]:
    reasons: Counter[str] = Counter()
    for trace in traces:
        blocked_reason = trace.get("blocked_reason")
        if isinstance(blocked_reason, str) and blocked_reason:
            reasons[blocked_reason] += 1

        candidate = trace.get("candidate_engine")
        if _candidate_bucket(candidate) == "blocked" and isinstance(candidate, dict):
            reason = candidate.get("reason")
            if isinstance(reason, str) and reason:
                reasons[reason] += 1

        governor = trace.get("governor")
        if isinstance(governor, dict) and governor.get("passed") is False:
            reason = governor.get("reason")
            if isinstance(reason, str) and reason:
                reasons[reason] += 1

    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(
            reasons.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]
