# PR 8 — calibration and optimization

PR 8 adds deterministic offline calibration on top of PR 7 replay.

## Included

- `CalibrationOptimizer` for grid-search evaluation over replay-ready `MarketSnapshot` data.
- `CalibrationParameters`, `CalibrationTrialResult`, and `CalibrationResult` outputs.
- Config-driven grids for:
  - `rfa_engine.min_signal_confidence`
  - `risk.min_risk_reward`
  - `risk.atr_stop_multiplier`
  - `risk.trailing_atr_multiplier`
  - `risk.cooldown_minutes`
- `risk_adjusted_pnl` scoring:

```text
score = total_pnl_pct - (max_drawdown_pct * drawdown_penalty)
```

- Minimum closed-trade gate through `calibration.min_trades`.
- Tests for grid generation, best-trial selection, symbol filtering, parameter application, scoring validation, and parameter validation.

## Intentional exclusions

- No automatic live parameter changes.
- No Binance historical download jobs.
- No Binance private account access.
- No real order placement, modification, cancellation, or execution.
- No Telegram sending from calibration runs.
- No WebSocket execution loops.
- No old direct-threshold signal logic.
