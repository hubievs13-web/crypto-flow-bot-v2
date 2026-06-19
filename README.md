# crypto-flow-bot-v2

Clean Binance Futures crypto signal bot based on the planned **RFA Engine — Regime-Flow-Alpha Engine**.

This repository is a fresh project. It does **not** copy the old `crypto-flow-bot` strategy logic. The old repository may be used only as a reference for generic infrastructure patterns such as public Binance Futures data, Telegram alerts, virtual position tracking, JSONL logs, YAML config, and risk-management utilities.

The bot is designed for Telegram alerts and virtual positions only. It must not open or close real trades.

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

PR 3 adds the normalization layer that converts read-only Binance market data into `MarketSnapshot` objects for the RFA Engine:

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

### PR 4 — RFA signal engine

PR 4 adds a pure RFA decision layer on top of `MarketSnapshot`:

- `RFAEngine.evaluate()` for one snapshot
- `RFAEngine.evaluate_many()` for batches of snapshots
- multi-component Regime-Flow-Alpha confluence scoring
- `LONG_CONTINUATION`, `SHORT_CONTINUATION`, `LONG_REVERSAL`, `SHORT_REVERSAL`, and `NO_TRADE` decisions
- confidence scoring from `0` to `100`
- context and macro alignment gates from config
- ATR-based `stop_loss` and `take_profit_levels`
- risk/reward gate using the configured minimum
- unit tests for long, short, blocked, low-confidence, and missing-metric cases

PR 4 intentionally does **not** implement:

- Binance API calls inside the engine
- Telegram API sending
- active-position checks
- cooldown checks
- virtual position lifecycle management
- trailing stop mutation after entry
- time stop execution
- backtest/replay
- real order execution
- old direct-threshold signal logic

### PR 5 — virtual position manager

PR 5 adds an in-memory lifecycle layer for simulated positions:

- `VirtualPositionManager.open_from_decision()` for tradeable RFA decisions
- one active virtual position per symbol
- post-close cooldown checks using `risk.cooldown_minutes`
- adaptive trailing-stop updates derived from the RFA ATR-based stop distance
- final take-profit closure
- stop-loss and trailing-stop closure
- time-stop closure using `risk.max_position_minutes`
- reason-invalidation closure
- virtual PnL percentage calculation
- unit tests for open, duplicate block, ignored `NO_TRADE`, cooldown, trailing, TP, time stop, short PnL, and invalidation paths

PR 5 intentionally does **not** implement:

- Binance private account access
- real order placement, modification, or cancellation
- Telegram API sending
- persistent storage of positions
- WebSocket execution loops
- backtest/replay
- old direct-threshold signal logic

### PR 6 — Telegram alerts

PR 6 adds a Telegram alert layer for RFA decisions and virtual position events:

- `TelegramAlertService` for signal and virtual-position alerts
- `UrlLibTelegramTransport` for Telegram Bot API `sendMessage`
- HTML-safe formatters for RFA signals and virtual position opened/closed events
- environment-based bot token and chat ID lookup
- disabled/missing-environment safe skips
- unit tests with exact-signature fake Telegram transport

PR 6 intentionally does **not** implement:

- Binance private account access
- real order placement, modification, cancellation, or execution
- WebSocket execution loops
- persistent position storage
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

These are inputs for RFA scoring. They are not standalone trading signals.

## RFA Engine scoring in PR 4

The engine scores a snapshot only through multi-factor confluence. It checks regime, 15m entry momentum, 1h context structure, 4h macro direction, taker flow, taker buy/sell pressure, funding, global long/short ratio, liquidation notional, volatility, open interest availability, and risk/reward.

A single threshold crossing is insufficient. A full trade decision requires enough aligned RFA components, context/macro confirmation, valid ATR exits, and configured minimum confidence.

## Virtual position lifecycle in PR 5

`VirtualPositionManager` consumes `SignalDecision` objects and tracks only virtual state. It blocks duplicate active positions by symbol and blocks new entries until the configured cooldown expires after a virtual close.

Position updates are driven by supplied prices and timestamps. The manager can close a virtual position through stop loss, trailing stop, final take profit, time stop, manual close, or reason invalidation.

## Telegram alerts in PR 6

Telegram alerts are disabled by default. To enable them, set `telegram.enabled: true` in `config.yaml` and provide the environment variables named by `bot_token_env` and `chat_id_env` in the environment.

`TelegramAlertService.send_signal()` sends only fully alertable RFA decisions. `TelegramAlertService.send_position_event()` sends only opened or closed virtual position events.

The package entrypoint loads and validates configuration only. It does not fetch market data, open positions, or send Telegram messages by itself.

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

A full Telegram signal should be sent only when confidence, risk/reward, multi-timeframe alignment, active-position checks, and cooldown checks all pass.

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
