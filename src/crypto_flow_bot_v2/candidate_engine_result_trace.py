"""Candidate Engine structured diagnostics for live symbol decision traces."""

from __future__ import annotations

from typing import Any

from crypto_flow_bot_v2 import live_runner, live_symbol_decision_trace
from crypto_flow_bot_v2.candidate_engine import CandidateEngineResult
from crypto_flow_bot_v2.models import MarketSnapshot, SignalDecision

_ORIGINAL_TRACE_PAYLOAD = live_symbol_decision_trace._symbol_decision_trace_payload  # noqa: SLF001
_LAST_CANDIDATE_ENGINE_RESULTS: dict[str, CandidateEngineResult] = {}


def install_candidate_engine_result_trace() -> None:
    """Install CandidateEngineResult preservation in live symbol decision traces."""

    runner_cls = live_runner.LiveAlertRunner
    if getattr(runner_cls, "_candidate_engine_result_trace_installed", False):
        return

    runner_cls._candidate_engine_decision = _candidate_engine_decision_with_result  # type: ignore[method-assign]
    if hasattr(live_symbol_decision_trace, "_candidate_engine_result"):
        live_symbol_decision_trace._candidate_engine_result = _candidate_engine_result  # type: ignore[attr-defined]
    live_symbol_decision_trace._symbol_decision_trace_payload = _trace_payload_with_candidate_engine
    runner_cls._candidate_engine_result_trace_installed = True


def _candidate_engine_decision_with_result(
    runner: live_runner.LiveAlertRunner,
    snapshot: MarketSnapshot,
    decision: SignalDecision,
) -> SignalDecision | None:
    return _candidate_engine_result(runner, snapshot, decision).decision


def _candidate_engine_result(
    runner: live_runner.LiveAlertRunner,
    snapshot: MarketSnapshot,
    decision: SignalDecision,
) -> CandidateEngineResult:
    if not runner._config.candidate_engine.enabled:  # noqa: SLF001
        result = CandidateEngineResult(
            decision=decision,
            reason="candidate engine disabled",
        )
        _LAST_CANDIDATE_ENGINE_RESULTS[snapshot.symbol] = result
        return result

    try:
        result = runner._candidate_engine.process(snapshot=snapshot, decision=decision)  # noqa: SLF001
    except Exception:
        live_runner.LOGGER.exception("candidate engine failed; fail-open preserving old signal flow")
        result = CandidateEngineResult(
            decision=decision,
            reason="candidate engine failed; fail-open",
        )
        _LAST_CANDIDATE_ENGINE_RESULTS[snapshot.symbol] = result
        return result

    live_runner.LOGGER.info(
        "candidate engine result: symbol=%s decision_emitted=%s reason=%s",
        snapshot.symbol,
        result.decision is not None,
        result.reason,
    )
    _LAST_CANDIDATE_ENGINE_RESULTS[snapshot.symbol] = result
    return result


def _trace_payload_with_candidate_engine(*args: Any, **kwargs: Any) -> dict[str, object]:
    payload = _ORIGINAL_TRACE_PAYLOAD(*args, **kwargs)
    symbol = _trace_symbol(args=args, kwargs=kwargs)
    result = _trace_result(args=args, kwargs=kwargs)
    candidate_result = None
    if symbol is not None and result is not None and result.decision_evaluated:
        candidate_result = _LAST_CANDIDATE_ENGINE_RESULTS.get(symbol)
    payload["candidate_engine"] = _candidate_engine_trace(candidate_result)
    return payload


def _trace_symbol(*, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if "symbol" in kwargs:
        return kwargs["symbol"]
    if args:
        return args[0]
    return None


def _trace_result(*, args: tuple[Any, ...], kwargs: dict[str, Any]) -> object | None:
    if "result" in kwargs:
        return kwargs["result"]
    if len(args) >= 3:
        return args[2]
    return None


def _candidate_engine_trace(
    result: CandidateEngineResult | None,
) -> dict[str, bool | float | int | list[str] | str | None] | None:
    if result is None:
        return None
    candidate = getattr(result, "candidate", None)
    return {
        "reason": result.reason,
        "emitted": result.decision is not None,
        "current_score": None if candidate is None else candidate.current_score,
        "best_score": None if candidate is None else candidate.best_score,
        "maturity_ticks": None if candidate is None else candidate.maturity_ticks,
        "missing_conditions": None if candidate is None else list(candidate.missing_conditions),
        "hard_filters_passed": None if candidate is None else candidate.hard_filters_passed,
    }
