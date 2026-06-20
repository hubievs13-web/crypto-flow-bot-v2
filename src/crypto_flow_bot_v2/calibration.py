"""Offline calibration and optimization for RFA backtest results.

This module tunes configuration values by replaying already-built MarketSnapshot objects. It does
not fetch Binance data, send Telegram messages, or touch any real exchange account.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import product
from math import isfinite

from crypto_flow_bot_v2.backtest import (
    BacktestReplayEngine,
    BacktestSummary,
    HistoricalSnapshotSource,
    ReplayEvent,
    ReplayEventType,
    ReplayResult,
)
from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.models import MarketSnapshot


@dataclass(frozen=True, slots=True)
class CalibrationParameters:
    """One RFA and risk parameter set tested by the optimizer."""

    min_signal_confidence: int
    min_risk_reward: float
    atr_stop_multiplier: float
    trailing_atr_multiplier: float
    cooldown_minutes: int

    def __post_init__(self) -> None:
        if not 0 <= self.min_signal_confidence <= 100:
            msg = "min_signal_confidence must be between 0 and 100."
            raise ValueError(msg)
        _validate_positive_finite(self.min_risk_reward, "min_risk_reward")
        _validate_positive_finite(self.atr_stop_multiplier, "atr_stop_multiplier")
        _validate_positive_finite(self.trailing_atr_multiplier, "trailing_atr_multiplier")
        if self.cooldown_minutes < 0:
            msg = "cooldown_minutes cannot be negative."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CalibrationTrialResult:
    """Backtest result and score for one parameter set."""

    parameters: CalibrationParameters
    replay: ReplayResult
    score: float
    rejected_reason: str | None = None

    @property
    def accepted(self) -> bool:
        """Return whether the trial satisfies configured calibration quality gates."""

        return self.rejected_reason is None


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Full deterministic optimization output."""

    objective: str
    trials: tuple[CalibrationTrialResult, ...]
    best_trial: CalibrationTrialResult | None


class CalibrationOptimizer:
    """Run deterministic grid-search calibration over offline replay data."""

    def __init__(self, config: BotConfig) -> None:
        self._config = config

    def run(
        self,
        snapshot_source: HistoricalSnapshotSource | Iterable[MarketSnapshot],
        symbols: Sequence[str] | None = None,
    ) -> CalibrationResult:
        """Evaluate configured parameter combinations and return the best accepted trial."""

        snapshots = _materialize_snapshots(snapshot_source=snapshot_source, symbols=symbols)
        trials = tuple(
            self._run_trial(parameters, snapshots)
            for parameters in parameter_grid(self._config)
        )
        accepted_trials = tuple(trial for trial in trials if trial.accepted)
        best_trial = max(accepted_trials, key=_trial_sort_key) if accepted_trials else None
        return CalibrationResult(
            objective=self._config.calibration.objective,
            trials=trials,
            best_trial=best_trial,
        )

    def _run_trial(
        self,
        parameters: CalibrationParameters,
        snapshots: tuple[MarketSnapshot, ...],
    ) -> CalibrationTrialResult:
        trial_config = config_with_parameters(self._config, parameters)
        try:
            replay = BacktestReplayEngine(trial_config).run(snapshots)
        except Exception as exc:
            replay = _failed_replay_result(snapshots, exc)
        score = score_summary(
            summary=replay.summary,
            drawdown_penalty=self._config.calibration.drawdown_penalty,
        )
        return CalibrationTrialResult(
            parameters=parameters,
            replay=replay,
            score=score,
            rejected_reason=_rejected_reason(self._config, replay.summary),
        )


def parameter_grid(config: BotConfig) -> tuple[CalibrationParameters, ...]:
    """Build the deterministic parameter grid described by config.calibration."""

    calibration = config.calibration
    grid = (
        CalibrationParameters(
            min_signal_confidence=confidence,
            min_risk_reward=min_risk_reward,
            atr_stop_multiplier=atr_stop_multiplier,
            trailing_atr_multiplier=trailing_atr_multiplier,
            cooldown_minutes=cooldown_minutes,
        )
        for (
            confidence,
            min_risk_reward,
            atr_stop_multiplier,
            trailing_atr_multiplier,
            cooldown_minutes,
        ) in product(
            calibration.min_signal_confidence_values,
            calibration.min_risk_reward_values,
            calibration.atr_stop_multiplier_values,
            calibration.trailing_atr_multiplier_values,
            calibration.cooldown_minutes_values,
        )
    )
    return tuple(grid)[: calibration.max_trials]


def config_with_parameters(config: BotConfig, parameters: CalibrationParameters) -> BotConfig:
    """Return a copy of the bot config with one calibration parameter set applied."""

    return replace(
        config,
        risk=replace(
            config.risk,
            min_risk_reward=parameters.min_risk_reward,
            atr_stop_multiplier=parameters.atr_stop_multiplier,
            trailing_atr_multiplier=parameters.trailing_atr_multiplier,
            cooldown_minutes=parameters.cooldown_minutes,
        ),
        rfa_engine=replace(
            config.rfa_engine,
            min_signal_confidence=parameters.min_signal_confidence,
        ),
    )


def score_summary(summary: BacktestSummary, drawdown_penalty: float) -> float:
    """Score a backtest summary using the PR 8 risk-adjusted PnL objective."""

    if drawdown_penalty < 0:
        msg = "drawdown_penalty cannot be negative."
        raise ValueError(msg)
    return round(summary.total_pnl_pct - (summary.max_drawdown_pct * drawdown_penalty), 10)


def _failed_replay_result(snapshots: tuple[MarketSnapshot, ...], exc: Exception) -> ReplayResult:
    error = f"{type(exc).__name__}: {exc}"
    events: tuple[ReplayEvent, ...] = ()
    if snapshots:
        first_snapshot = snapshots[0]
        events = (
            ReplayEvent(
                timestamp=first_snapshot.timestamp,
                symbol=_normalize_symbol(first_snapshot.symbol),
                event_type=ReplayEventType.ERROR,
                error=error,
            ),
        )
    return ReplayResult(
        events=events,
        summary=BacktestSummary(
            symbols=_summary_symbols(snapshots),
            started_at=snapshots[0].timestamp if snapshots else None,
            ended_at=snapshots[-1].timestamp if snapshots else None,
            snapshots_processed=len(snapshots),
            signals_seen=0,
            positions_opened=0,
            positions_closed=0,
            wins=0,
            losses=0,
            total_pnl_pct=0.0,
            average_pnl_pct=0.0,
            max_drawdown_pct=0.0,
            open_positions=0,
            errors=1,
        ),
    )


def _summary_symbols(snapshots: tuple[MarketSnapshot, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_normalize_symbol(snapshot.symbol) for snapshot in snapshots))


def _rejected_reason(config: BotConfig, summary: BacktestSummary) -> str | None:
    if summary.errors:
        return f"runtime_errors:{summary.errors}"
    if summary.positions_closed < config.calibration.min_trades:
        return f"insufficient_closed_trades:{summary.positions_closed}"
    return None


def _trial_sort_key(trial: CalibrationTrialResult) -> tuple[float, int, float]:
    return (
        trial.score,
        trial.replay.summary.positions_closed,
        trial.replay.summary.average_pnl_pct,
    )


def _materialize_snapshots(
    snapshot_source: HistoricalSnapshotSource | Iterable[MarketSnapshot],
    symbols: Sequence[str] | None,
) -> tuple[MarketSnapshot, ...]:
    if hasattr(snapshot_source, "snapshots"):
        raw_snapshots = snapshot_source.snapshots(symbols)
        snapshots = tuple(raw_snapshots)
    else:
        snapshots = tuple(snapshot_source)
        if symbols is not None:
            selected_symbols = {_normalize_symbol(symbol) for symbol in symbols}
            snapshots = tuple(
                snapshot
                for snapshot in snapshots
                if _normalize_symbol(snapshot.symbol) in selected_symbols
            )
    return tuple(sorted(snapshots, key=lambda snapshot: (snapshot.timestamp, snapshot.symbol)))


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        msg = "symbol must be a non-empty string."
        raise ValueError(msg)
    return symbol.strip().upper()


def _validate_positive_finite(value: float, name: str) -> None:
    if value <= 0 or not isfinite(value):
        msg = f"{name} must be positive and finite."
        raise ValueError(msg)
