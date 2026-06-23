# crypto-flow-bot-v2

Alert-only Binance Futures monitoring project using the RFA Engine architecture.

## Safety boundary

The application is alert-only. It uses public/read-only Binance Futures market-data endpoints, does not require Binance private credentials, does not submit exchange orders, and keeps project positions as virtual positions inside local state.

## Default 24/7 startup

```bash
python -m crypto_flow_bot_v2
```

The live runner is enabled by default. If `LIVE_RUNNER_ENABLED` is missing, empty, or contains an unrecognized value, the entrypoint keeps the live loop enabled and logs a warning for unrecognized values. Only explicit false values (`0`, `false`, `no`, `off`) disable the live runner.

## Config-only startup

```bash
LIVE_RUNNER_ENABLED=false python -m crypto_flow_bot_v2
```

This mode loads and validates `config.yaml`, configures logging, writes the configured JSONL log file, prints a startup summary, logs Telegram credential diagnostics, and exits without starting the live loop.

## Live runner startup

```bash
python -m crypto_flow_bot_v2
# or explicitly:
LIVE_RUNNER_ENABLED=true python -m crypto_flow_bot_v2
```

This starts the Telegram-only live runner. It fetches public market data, builds snapshots, evaluates RFA decisions, updates virtual positions, and sends Telegram alerts when Telegram is enabled and credentials are configured.

When the live runner initializes successfully and Telegram credentials exist, the bot sends this startup alert once:

```text
🚀 Crypto Flow Bot started. Live runner enabled.
```

If the live runner is enabled and Telegram is enabled but the required Telegram credentials are missing, startup fails fast before the live loop starts. The error lists the missing environment variables and does not print secret values.

A Telegram `/start` poller runs with the live runner. It performs no work when `telegram.enabled: false` or the configured bot token environment variable is empty.

## Telegram

Telegram is enabled by default:

```yaml
telegram:
  enabled: true
  bot_token_env: TELEGRAM_BOT_TOKEN
  chat_id_env: TELEGRAM_CHAT_ID
```

For production alerts:

1. Keep `telegram.enabled: true` in `config.yaml`, or omit `telegram.enabled` to use the code default.
2. Set `TELEGRAM_BOT_TOKEN`.
3. Set `TELEGRAM_CHAT_ID` to one ID or a comma-separated list.
4. Leave `LIVE_RUNNER_ENABLED` unset or set it to `true`. Set it to `false` only for a deliberate config-only run.

To use `TELEGRAM_CHAT_IDS`, set `telegram.chat_id_env: TELEGRAM_CHAT_IDS` in `config.yaml` and provide that environment variable instead.

## Live runner variables

```env
LIVE_RUNNER_ENABLED=true
LIVE_RUNNER_INTERVAL_SECONDS=900
LIVE_RUNNER_MAX_CYCLES=
POSITION_STATE_PATH=data/positions.json
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`LIVE_RUNNER_ENABLED` defaults to enabled in code. Use `false`, `0`, `no`, or `off` only when you intentionally want to suppress the 24/7 live loop.

`LIVE_RUNNER_INTERVAL_SECONDS` is preferred. `LIVE_CYCLE_INTERVAL_SECONDS` is still accepted for older deployments.

`POSITION_STATE_PATH` stores virtual positions as JSON. The default path is `data/positions.json`.

## Logging

Console logging remains enabled. When `logging.jsonl_path` is set, every file log line is a valid JSON object and the parent directory is created automatically:

```yaml
logging:
  level: INFO
  jsonl_path: logs/rfa-events.jsonl
```

With Docker Compose, `./logs` is mounted to `/app/logs`, so the default JSONL file appears under `logs/` on the host.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Smoke tests

Config-only smoke test:

```bash
LIVE_RUNNER_ENABLED=false python -m crypto_flow_bot_v2
```

One-cycle live smoke test, only after Telegram/config are ready:

```bash
LIVE_RUNNER_MAX_CYCLES=1 python -m crypto_flow_bot_v2
```

Docker config-only startup:

```bash
docker compose run --rm -e LIVE_RUNNER_ENABLED=false crypto-flow-bot-v2
```

Docker one-cycle live runner, only after Telegram/config are ready:

```bash
docker compose run --rm \
  -e LIVE_RUNNER_MAX_CYCLES=1 \
  crypto-flow-bot-v2
```

## Checks

```bash
pytest
ruff check .
python -m crypto_flow_bot_v2
```
