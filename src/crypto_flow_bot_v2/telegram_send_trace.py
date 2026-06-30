"""Structured Telegram send diagnostics for live-runner alerts."""

from __future__ import annotations

from crypto_flow_bot_v2 import live_runner
from crypto_flow_bot_v2.models import SignalDecision
from crypto_flow_bot_v2.position_manager import PositionEvent
from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertStatus

FAILED_EVENT = "telegram_send_failed"
SKIPPED_EVENT = "telegram_send_skipped"


def install_telegram_send_trace() -> None:
    """Install structured Telegram send diagnostics on LiveAlertRunner."""

    runner_cls = live_runner.LiveAlertRunner
    if getattr(runner_cls, "_telegram_send_trace_installed", False):
        return

    runner_cls._send_signal = _send_signal_with_trace  # type: ignore[method-assign]
    runner_cls._send_position_event = (  # type: ignore[method-assign]
        _send_position_event_with_trace
    )
    runner_cls._send_no_trade_diagnostic = (  # type: ignore[method-assign]
        _send_no_trade_diagnostic_with_trace
    )
    runner_cls._telegram_send_trace_installed = True


def _send_signal_with_trace(
    runner: live_runner.LiveAlertRunner,
    decision: SignalDecision,
) -> live_runner._AlertCounter:  # noqa: SLF001
    alert_type = "signal"
    try:
        result = runner._telegram_alerts.send_signal(decision)  # noqa: SLF001
    except Exception as exc:
        _log_telegram_send_failed(
            symbol=decision.symbol,
            alert_type=alert_type,
            error=str(exc),
        )
        live_runner.LOGGER.exception(
            "failed to send signal alert for symbol=%s",
            decision.symbol,
        )
        return live_runner._AlertCounter(errors=1)  # noqa: SLF001

    _log_telegram_result(
        symbol=decision.symbol,
        alert_type=alert_type,
        result=result,
    )
    return live_runner._counter_from_alert_result(result)  # noqa: SLF001


def _send_position_event_with_trace(
    runner: live_runner.LiveAlertRunner,
    event: PositionEvent,
) -> live_runner._AlertCounter:  # noqa: SLF001
    alert_type = "position_event"
    try:
        result = runner._telegram_alerts.send_position_event(event)  # noqa: SLF001
    except Exception as exc:
        _log_telegram_send_failed(
            symbol=event.symbol,
            alert_type=alert_type,
            error=str(exc),
        )
        live_runner.LOGGER.exception(
            "failed to send position alert for symbol=%s",
            event.symbol,
        )
        return live_runner._AlertCounter(errors=1)  # noqa: SLF001

    _log_telegram_result(
        symbol=event.symbol,
        alert_type=alert_type,
        result=result,
    )
    return live_runner._counter_from_alert_result(result)  # noqa: SLF001


def _send_no_trade_diagnostic_with_trace(
    runner: live_runner.LiveAlertRunner,
    decision: SignalDecision,
) -> live_runner._AlertCounter:  # noqa: SLF001
    alert_type = "no_trade_diagnostic"
    try:
        sender = getattr(
            runner._telegram_alerts,  # noqa: SLF001
            "send_no_trade_diagnostic",
            None,
        )
        if callable(sender):
            result = sender(decision)
        else:
            raw_send = getattr(runner._telegram_alerts, "_send", None)  # noqa: SLF001
            if not callable(raw_send):
                reason = "no sender available"
                live_runner.LOGGER.warning(
                    "NO_TRADE Telegram diagnostic skipped: no sender available symbol=%s "
                    "blocked_reason=%s",
                    decision.symbol,
                    decision.blocked_reason or "",
                )
                _log_telegram_send_skipped(
                    symbol=decision.symbol,
                    alert_type=alert_type,
                    reason=reason,
                )
                return live_runner._AlertCounter(skipped=1)  # noqa: SLF001
            result = raw_send(
                live_runner._format_no_trade_diagnostic(decision),  # noqa: SLF001
            )
    except Exception as exc:
        _log_telegram_send_failed(
            symbol=decision.symbol,
            alert_type=alert_type,
            error=str(exc),
        )
        live_runner.LOGGER.exception(
            "failed to send NO_TRADE diagnostic for symbol=%s blocked_reason=%s",
            decision.symbol,
            decision.blocked_reason or "",
        )
        return live_runner._AlertCounter(errors=1)  # noqa: SLF001

    counter = live_runner._counter_from_alert_result(result)  # noqa: SLF001
    _log_telegram_result(
        symbol=decision.symbol,
        alert_type=alert_type,
        result=result,
    )
    if result.status is TelegramAlertStatus.SKIPPED:
        live_runner.LOGGER.warning(
            "NO_TRADE Telegram diagnostic skipped for symbol=%s blocked_reason=%s: %s",
            decision.symbol,
            decision.blocked_reason or "",
            result.message,
        )
    return counter


def _log_telegram_result(
    *,
    symbol: str,
    alert_type: str,
    result: TelegramAlertResult,
) -> None:
    if result.status is TelegramAlertStatus.SENT:
        return
    if result.status is TelegramAlertStatus.SKIPPED:
        _log_telegram_send_skipped(
            symbol=symbol,
            alert_type=alert_type,
            reason=result.message,
        )
        return
    _log_telegram_send_failed(
        symbol=symbol,
        alert_type=alert_type,
        error=result.message,
    )


def _log_telegram_send_skipped(*, symbol: str, alert_type: str, reason: str) -> None:
    live_runner.LOGGER.warning(
        SKIPPED_EVENT,
        extra={
            "event": SKIPPED_EVENT,
            SKIPPED_EVENT: {
                "symbol": symbol,
                "alert_type": alert_type,
                "reason": reason,
            },
        },
    )


def _log_telegram_send_failed(*, symbol: str, alert_type: str, error: str) -> None:
    live_runner.LOGGER.error(
        FAILED_EVENT,
        extra={
            "event": FAILED_EVENT,
            FAILED_EVENT: {
                "symbol": symbol,
                "alert_type": alert_type,
                "error": error,
            },
        },
    )
