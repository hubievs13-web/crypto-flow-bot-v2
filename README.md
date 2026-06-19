# crypto-flow-bot-v2

Clean scaffold for a Binance Futures crypto signal bot based on the planned **RFA Engine — Regime-Flow-Alpha Engine**.

This repository is a fresh project. It does **not** copy the old `crypto-flow-bot` strategy logic. The old repository may be used later only as a reference for generic infrastructure patterns such as data access, Telegram alerts, virtual position tracking, JSONL logs, YAML config, and risk-management utilities.

## PR 1 scope

PR 1 creates only the foundation:

- Python 3.11+ package with `src/` layout
- typed domain models for snapshots, decisions, exits, and virtual positions
- YAML configuration loader and validation
- logging setup
- runnable package entrypoint
- unit tests for config and models
- ruff and pytest configuration

PR 1 intentionally does **not** implement:

- Binance REST or WebSocket integration
- Telegram API sending
- real order execution
- automated trading
- full RFA strategy calculation
- backtest or replay

## Planned architecture

Development order:

1. Project scaffold
2. Binance data layer
3. `MarketSnapshot` builder
4. RFA signal engine
5. Virtual position manager
6. Telegram alerts
7. Backtest/replay
8. Calibration and optimization

The bot is designed for Telegram alerts and virtual positions only. It must not open or close real trades.

## Default market setup

- Market: crypto futures
- Exchange: Binance Futures
- Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`
- Entry timeframe: `15m`
- Context timeframe: `1h`
- Macro timeframe: `4h`

## Signal types

- `LONG_CONTINUATION`
- `SHORT_CONTINUATION`
- `LONG_REVERSAL`
- `SHORT_REVERSAL`
- `NO_TRADE`

Confidence bands:

- `0–59`: ignore
- `60–69`: watch only
- `70–84`: normal signal
- `85–100`: strong signal

A full Telegram signal should be sent in later PRs only when confidence, risk/reward, multi-timeframe alignment, cooldown, and active-position checks all pass.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Run

```bash
python -m crypto_flow_bot_v2
```

Optional config path:

```bash
CONFIG_PATH=config.yaml python -m crypto_flow_bot_v2
```

## Checks

```bash
pytest
ruff check .
```
