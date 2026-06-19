from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from crypto_flow_bot_v2.calibration import (
    CalibrationOptimizer,
    CalibrationParameters,
    config_with_parameters,
    parameter_grid,
    score_summary,
)
from crypto_flow_bot_v2.config import CalibrationConfig, load_config
from crypto_flow_bot_v2.models import MarketRegime, MarketSnapshot

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def test_parameter_grid_honors_configured_order_and_max_trials() -> None:
    config = replace(
        load_config(),
        calibration=_calibration_config(
            max_trials=3,
            min_signal_confidence_values=(70, 80),
            min_risk_reward_values=(1.5, 2.0),
            atr_stop_multiplier_values=(1.0,),
            trailing_atr_multiplier_values=(0.8,),
            cooldown_minutes_values=(30, 60),
        ),
    )

    grid = parameter_grid(config)

    assert len(grid) == 3
    assert grid[0] == CalibrationParameters(
        min_signal_confidence=70,
        min_risk_reward=1.5,
        atr_stop_multiplier=1.0,
        trailing_atr_multiplier=0.8,
        cooldown_minutes=30,
    )
    assert grid[1].cooldown_minutes == 60
    assert grid[2].min_risk_reward == 2.0


def test_calibration_optimizer_selects_best_accepted_trial() -> None:
    config = replace(
        load_config(),
        calibration=_calibration_config(
            min_trades=1,
            min_signal_confidence_values=(70,),
            min_risk_reward_values=(1.5, 3.0),
        ),
    )
    snapshots = (
        _long_snapshot(price=100.0, timestamp=BASE_TIME),
        _long_snapshot(price=109.0, timestamp=BASE_TIME + timedelta(minutes=15)),
    )

    result = CalibrationOptimizer(config).run(snapshots)

    assert len(result.trials) == 2
    assert result.objective == "risk_adjusted_pnl"
    assert result.best_trial is not None
    assert result.best_trial.parameters.min_risk_reward == 1.5
    assert result.best_trial.score == 9.0

    rejected_trials = tuple(trial for trial in result.trials if not trial.accepted)
    assert len(rejected_trials) == 1
    assert rejected_trials[0].parameters.min_risk_reward == 3.0
    assert rejected_trials[0].rejected_reason == "insufficient_closed_trades:0"


def test_calibration_optimizer_filters_symbols_for_plain_iterables() -> None:
    config = replace(
        load_config(),
        calibration=_calibration_config(min_trades=1, min_risk_reward_values=(1.5,)),
    )
    snapshots = (
        _long_snapshot(symbol="ETHUSDT", price=2000.0, timestamp=BASE_TIME),
        _long_snapshot(symbol="BTCUSDT", price=100.0, timestamp=BASE_TIME),
        _long_snapshot(
            symbol="BTCUSDT",
            price=109.0,
            timestamp=BASE_TIME + timedelta(minutes=15),
        ),
    )

    result = CalibrationOptimizer(config).run(snapshots, symbols=("btcusdt",))

    assert result.best_trial is not None
    assert result.best_trial.replay.summary.symbols == ("BTCUSDT",)
    assert result.best_trial.replay.summary.snapshots_processed == 2


def test_config_with_parameters_updates_only_tuned_fields() -> None:
    config = load_config()
    parameters = CalibrationParameters(
        min_signal_confidence=85,
        min_risk_reward=2.0,
        atr_stop_multiplier=2.5,
        trailing_atr_multiplier=1.25,
        cooldown_minutes=120,
    )

    tuned_config = config_with_parameters(config, parameters)

    assert tuned_config.rfa_engine.min_signal_confidence == 85
    assert tuned_config.risk.min_risk_reward == 2.0
    assert tuned_config.risk.atr_stop_multiplier == 2.5
    assert tuned_config.risk.trailing_atr_multiplier == 1.25
    assert tuned_config.risk.cooldown_minutes == 120
    assert tuned_config.risk.max_position_minutes == config.risk.max_position_minutes
    assert tuned_config.risk.atr_tp_multipliers == config.risk.atr_tp_multipliers


def test_score_summary_rejects_negative_drawdown_penalty() -> None:
    config = replace(
        load_config(),
        calibration=_calibration_config(min_trades=0, min_risk_reward_values=(3.0,)),
    )
    result = CalibrationOptimizer(config).run((_long_snapshot(),))

    with pytest.raises(ValueError, match="drawdown_penalty"):
        score_summary(result.trials[0].replay.summary, drawdown_penalty=-1.0)


def test_calibration_parameters_validate_confidence() -> None:
    with pytest.raises(ValueError, match="min_signal_confidence"):
        CalibrationParameters(
            min_signal_confidence=101,
            min_risk_reward=1.5,
            atr_stop_multiplier=1.5,
            trailing_atr_multiplier=1.0,
            cooldown_minutes=60,
        )


def _calibration_config(
    enabled: bool = True,
    objective: str = "risk_adjusted_pnl",
    min_trades: int = 1,
    drawdown_penalty: float = 1.0,
    max_trials: int = 100,
    min_signal_confidence_values: tuple[int, ...] = (70,),
    min_risk_reward_values: tuple[float, ...] = (1.5,),
    atr_stop_multiplier_values: tuple[float, ...] = (1.5,),
    trailing_atr_multiplier_values: tuple[float, ...] = (1.0,),
    cooldown_minutes_values: tuple[int, ...] = (60,),
) -> CalibrationConfig:
    return CalibrationConfig(
        enabled=enabled,
        objective=objective,
        min_trades=min_trades,
        drawdown_penalty=drawdown_penalty,
        max_trials=max_trials,
        min_signal_confidence_values=min_signal_confidence_values,
        min_risk_reward_values=min_risk_reward_values,
        atr_stop_multiplier_values=atr_stop_multiplier_values,
        trailing_atr_multiplier_values=trailing_atr_multiplier_values,
        cooldown_minutes_values=cooldown_minutes_values,
    )


def _long_snapshot(
    symbol: str = "BTCUSDT",
    price: float = 100.0,
    timestamp: datetime = BASE_TIME,
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        timestamp=timestamp,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=price,
        regime=MarketRegime.TREND_UP,
        metrics={
            "entry_return_pct": 1.25,
            "context_return_pct": 1.1,
            "macro_return_pct": 1.0,
            "entry_atr": 2.0,
            "entry_atr_pct": 2.0,
            "entry_taker_buy_quote_ratio": 0.66,
            "open_interest": 1_000_000.0,
            "funding_rate": 0.0002,
            "long_short_ratio": 1.2,
            "taker_buy_sell_ratio": 1.4,
            "liquidation_buy_notional": 100_000.0,
            "liquidation_sell_notional": 10_000.0,
        },
    )
