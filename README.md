# crypto-flow-bot-v2

Clean scaffold for a Binance Futures crypto signal bot based on the planned **RFA Engine — Regime-Flow-Alpha Engine**.

This repository is a fresh project. It does **not** copy the old `crypto-flow-bot` strategy logic. The old repository may be used later only as a reference for generic infrastructure patterns such as data access, Telegram alerts, virtual position tracking, JSONL logs, YAML config, and risk-management utilities.

## Current scope

### PR 1 — project scaffold

PR 1 created the foundation:

- Python 3.11+ package with `src/` layout
- typed domain models for snapshots, decisions, exits, and virtual positions
- YAML configuration loader and validation
- logging setup
- runnable package entrypoint
- unit tests for config and models
- ruff and pytest configuration

### PR 2 — Binance data layer

PR 2 adds a read-only Binance USDⓈ-M Futures market-data layer:

- public REST transport with stdlib `urllib`
- dependency-injected transport protocol for tests and later replay/backtest
- typed data models for klines, open interest, funding, global long/short ratio, taker buy/sell volume, and liquidation orders
- config section for Binance public data settings
- tests using fakes with exact production signatures

PR 2 intentionally does **not** implement:

- Binance private account access
- order placement, order cancellation, or account changes
- WebSocket streams
- Telegram API sending
- real trading execution
- full RFA strategy calculation
- backtest or replay

### PR 3 — MarketSnapshot builder

PR 3 adds the normalization layer that converts read-only Binance market data into `MarketSnapshot` objects for the future RFA Engine:

- dependency-injected `MarketDataClient` protocol matching the PR 2 Binance client signatures
- `MarketSnapshotBuilder.build()` for one symbol
- `MarketSnapshotBuilder.build_many()` for configured or explicit symbol sets
- normalized metrics for entry/context/macro price action, ATR volatility, open interest, funding, long/short ratio, taker pressure, and liquidation notional
- coarse market-regime classification for snapshot context only
- unit tests using exact-signature fakes

PR 3 intentionally does **not** implement:

- trade signal generation
- confidence scoring
- SL/TP/trailing/time-stop calculation
- Telegram message sending
- real order execution
- backtest/replay
- old direct-threshold signal logic

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

## Binance public data endpoints prepared in PR 2

- Klines: `/fapi/v1/klines`
- Present open interest: `/fapi/v1/openInterest`
- Funding-rate history: `/fapi/v1/fundingRate`
- Global long/short account ratio: `/futures/data/globalLongShortAccountRatio`
- Taker buy/sell volume: `/futures/data/takerlongshortRatio`
- Public forced liquidation orders: `/fapi/v1/allForceOrders`

These endpoints are read-only market-data sources and use only public requests.

## Snapshot metrics prepared in PR 3

`MarketSnapshot.metrics` currently includes normalized values such as:

- `entry_return_pct`, `context_return_pct`, `macro_return_pct`
- `entry_atr`, `entry_atr_pct`
- `open_interest`
- `funding_rate`, `funding_mark_price`
- `long_short_ratio`, `long_account`, `short_account`
- `taker_buy_sell_ratio`, `taker_buy_volume`, `taker_sell_volume`
- `liquidation_count`, `liquidation_buy_notional`, `liquidation_sell_notional`, `liquidation_total_notional`

These are inputs for later RFA scoring. They are not standalone trading signals.

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
