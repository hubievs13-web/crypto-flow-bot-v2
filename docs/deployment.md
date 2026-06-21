# Deployment guide

Alert-only deployment notes for `crypto-flow-bot-v2`.

## Safety boundary

The application is alert-only. It uses public/read-only Binance Futures market-data endpoints, does not require Binance private credentials, does not submit exchange orders, and keeps project positions as virtual positions inside local state.

## Configure

```bash
git clone https://github.com/hubievs13-web/crypto-flow-bot-v2.git
cd crypto-flow-bot-v2
cp .env.example .env
mkdir -p data logs
```

## Safe/default startup

```bash
python -m crypto_flow_bot_v2
```

Without `LIVE_RUNNER_ENABLED=true`, this loads and validates `config.yaml`, configures logging, writes the configured JSONL log file, prints a startup summary, and exits without starting the live loop.

## Live runner startup

```bash
LIVE_RUNNER_ENABLED=true python -m crypto_flow_bot_v2
```

This starts the Telegram-only live runner. It fetches public market data, builds snapshots, evaluates RFA decisions, updates virtual positions, and sends Telegram alerts only when Telegram is enabled and credentials are configured.

## Telegram

Telegram is disabled by default:

```yaml
telegram:
  enabled: false
  bot_token_env: TELEGRAM_BOT_TOKEN
  chat_id_env: TELEGRAM_CHAT_ID
```

For production alerts, set `telegram.enabled: true`, provide `TELEGRAM_BOT_TOKEN`, provide `TELEGRAM_CHAT_ID` or configure `telegram.chat_id_env: TELEGRAM_CHAT_IDS`, and set `LIVE_RUNNER_ENABLED=true`.

## Smoke tests

Minimal safe smoke test:

```bash
python -m crypto_flow_bot_v2
```

One-cycle live smoke test, only after Telegram/config are ready:

```bash
LIVE_RUNNER_ENABLED=true LIVE_RUNNER_MAX_CYCLES=1 python -m crypto_flow_bot_v2
```

Docker safe startup:

```bash
docker compose run --rm -e LIVE_RUNNER_ENABLED=false crypto-flow-bot-v2
```

Docker one-cycle live runner, only after Telegram/config are ready:

```bash
docker compose run --rm \
  -e LIVE_RUNNER_ENABLED=true \
  -e LIVE_RUNNER_MAX_CYCLES=1 \
  crypto-flow-bot-v2
```

## Variables and runtime files

`LIVE_RUNNER_INTERVAL_SECONDS` is preferred. `LIVE_CYCLE_INTERVAL_SECONDS` is still accepted for older deployments.

`POSITION_STATE_PATH=data/positions.json` stores virtual positions. Docker Compose mounts `./data` to `/app/data`.

`logging.jsonl_path: logs/rfa-events.jsonl` writes one JSON object per line. Docker Compose mounts `./logs` to `/app/logs`.

Console logs:

```bash
docker compose logs -f --tail=200
```
