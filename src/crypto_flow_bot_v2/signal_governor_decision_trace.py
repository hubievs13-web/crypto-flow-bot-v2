"""Structured signal governor decision diagnostics."""

from __future__ import annotations

from collections.abc import Callable

from crypto_flow_bot_v2 import live_runner
from crypto_flow_bot_v2.signal_governor import SignalGovernorDecision

TRACE_EVENT = "signal_governor_decision"
_ORIGINAL_LOG_GOVERNOR_PASSED = live_runner._log_governor_passed  # noqa: SLF001
_ORIGINAL_LOG_GOVERNOR_SKIPPED = live_runner._log_governor_skipped  # noqa: SLF001


def install_signal_governor_decision_trace() -> None:
    """Install structured per-decision governor logging."""

    runner_cls = live_runner.LiveAlertRunner
    if getattr(runner_cls, "_signal_governor_decision_trace_installed", False):
        return

    live_runner._log_governor_passed = _log_governor_passed_with_trace  # type: ignore[assignment]
    live_runner._log_governor_skipped = _log_governor_skipped_with_trace  # type: ignore[assignment]
    runner_cls._signal_governor_decision_trace_installed = True


def _log_governor_passed_with_trace(item: SignalGovernorDecision) -> None:
    _log_with_original(_ORIGINAL_LOG_GOVERNOR_PASSED, item)


def _log_governor_skipped_with_trace(item: SignalGovernorDecision) -> None:
    _log_with_original(_ORIGINAL_LOG_GOVERNOR_SKIPPED, item)


def _log_with_original(
    original_logger: Callable[[SignalGovernorDecision], None],
    item: SignalGovernorDecision,
) -> None:
    original_logger(item)
    _log_signal_governor_decision(item)


def _log_signal_governor_decision(item: SignalGovernorDecision) -> None:
    live_runner.LOGGER.info(
        TRACE_EVENT,
        extra={
            "event": TRACE_EVENT,
            TRACE_EVENT: _signal_governor_decision_payload(item),
        },
    )


def _signal_governor_decision_payload(
    item: SignalGovernorDecision,
) -> dict[str, bool | int | str]:
    return {
        "symbol": item.decision.symbol,
        "passed": item.passed,
        "reason": item.reason,
        "rank": item.rank,
        "final_score": item.final_score,
    }
