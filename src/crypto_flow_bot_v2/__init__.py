"""Clean foundation for crypto-flow-bot-v2."""

from __future__ import annotations

from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertService, TelegramAlertStatus

__all__ = ["__version__"]

__version__ = "0.1.0"


def _suppress_no_trade_diagnostic(_self: TelegramAlertService, _decision: object) -> TelegramAlertResult:
    return TelegramAlertResult(
        status=TelegramAlertStatus.SKIPPED,
        message="NO_TRADE diagnostics are not sent to Telegram",
    )


TelegramAlertService.send_no_trade_diagnostic = _suppress_no_trade_diagnostic  # type: ignore[attr-defined]
