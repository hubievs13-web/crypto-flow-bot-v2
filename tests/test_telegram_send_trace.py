import pytest

from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertStatus
from crypto_flow_bot_v2.telegram_send_trace import (
    _log_telegram_result,
    _log_telegram_send_failed,
)


def test_telegram_send_skipped_logs_structured_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = TelegramAlertResult(
        status=TelegramAlertStatus.SKIPPED,
        message="telegram credentials are not configured in environment",
    )

    with caplog.at_level("WARNING", logger="crypto_flow_bot_v2.live_runner"):
        _log_telegram_result(symbol="BTCUSDT", alert_type="signal", result=result)

    assert _skipped_events(caplog) == [
        {
            "symbol": "BTCUSDT",
            "alert_type": "signal",
            "reason": "telegram credentials are not configured in environment",
        }
    ]
    assert _failed_events(caplog) == []


def test_telegram_send_failed_logs_structured_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR", logger="crypto_flow_bot_v2.live_runner"):
        _log_telegram_send_failed(
            symbol="ETHUSDT",
            alert_type="position_event",
            error="Telegram request timed out while sending alert.",
        )

    assert _failed_events(caplog) == [
        {
            "symbol": "ETHUSDT",
            "alert_type": "position_event",
            "error": "Telegram request timed out while sending alert.",
        }
    ]
    assert _skipped_events(caplog) == []


def test_telegram_send_sent_does_not_log_noise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = TelegramAlertResult(
        status=TelegramAlertStatus.SENT,
        message="telegram alert sent",
    )

    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        _log_telegram_result(symbol="SOLUSDT", alert_type="signal", result=result)

    assert _skipped_events(caplog) == []
    assert _failed_events(caplog) == []


def _skipped_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, str]]:
    return [
        record.telegram_send_skipped
        for record in caplog.records
        if hasattr(record, "telegram_send_skipped")
    ]


def _failed_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, str]]:
    return [
        record.telegram_send_failed
        for record in caplog.records
        if hasattr(record, "telegram_send_failed")
    ]
