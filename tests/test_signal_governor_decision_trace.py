from datetime import UTC, datetime

import pytest

from crypto_flow_bot_v2.models import SignalDecision, SignalDirection, SignalType
from crypto_flow_bot_v2.signal_governor import SignalGovernorDecision
from crypto_flow_bot_v2.signal_governor_decision_trace import (
    _log_signal_governor_decision,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_signal_governor_decision_trace_logs_structured_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    item = SignalGovernorDecision(
        decision=_decision("BTCUSDT"),
        passed=True,
        reason="ranked first",
        rank=1,
        final_score=90,
    )

    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        _log_signal_governor_decision(item)

    assert _governor_decisions(caplog) == [
        {
            "symbol": "BTCUSDT",
            "passed": True,
            "reason": "ranked first",
            "rank": 1,
            "final_score": 90,
        }
    ]


def test_signal_governor_decision_trace_does_not_log_empty_governor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="crypto_flow_bot_v2.live_runner"):
        pass

    assert _governor_decisions(caplog) == []


def _governor_decisions(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        record.signal_governor_decision
        for record in caplog.records
        if hasattr(record, "signal_governor_decision")
    ]


def _decision(symbol: str) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=90,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence",),
    )
