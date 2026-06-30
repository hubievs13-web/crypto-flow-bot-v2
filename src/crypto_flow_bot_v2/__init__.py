"""Clean foundation for crypto-flow-bot-v2."""

from __future__ import annotations

from crypto_flow_bot_v2.candidate_engine_result_trace import install_candidate_engine_result_trace
from crypto_flow_bot_v2.live_cycle_decision_summary import install_live_cycle_decision_summary
from crypto_flow_bot_v2.live_symbol_decision_trace import install_live_symbol_decision_trace
from crypto_flow_bot_v2.signal_governor_decision_trace import (
    install_signal_governor_decision_trace,
)
from crypto_flow_bot_v2.telegram import (
    TelegramAlertResult,
    TelegramAlertService,
    TelegramAlertStatus,
)
from crypto_flow_bot_v2.telegram_send_trace import install_telegram_send_trace

__all__ = ["__version__"]
__version__ = "0.1.0"


def _suppress_no_trade_diagnostic(
    _self: TelegramAlertService,
    _decision: object,
) -> TelegramAlertResult:
    return TelegramAlertResult(
        status=TelegramAlertStatus.SKIPPED,
        message="NO_TRADE diagnostics are not sent to Telegram",
    )


setattr(TelegramAlertService, "send_no_trade_diagnostic", _suppress_no_trade_diagnostic)
install_live_symbol_decision_trace()
install_candidate_engine_result_trace()
install_live_cycle_decision_summary()
install_signal_governor_decision_trace()
install_telegram_send_trace()
