# VPS deployment guide

This guide runs `crypto-flow-bot-v2` as a Telegram-only Binance Futures public-data alert bot. It does not enable real exchange trading.

## Clone and configure

```bash
git clone https://github.com/hubievs13-web/crypto-flow-bot-v2.git
cd crypto-flow-bot-v2
cp .env.example .env
mkdir -p data logs
```

Default `config.yaml` is safe: Telegram is disabled. Default `.env.example` keeps `LIVE_RUNNER_ENABLED=false`, so the package entrypoint loads config and logging, then exits.

For production alerts, enable the live runner in `.env`, provide Telegram credentials through environment variables, and set `telegram.enabled: true` in `config.yaml`. Keep real credentials out of git.

Use this mounted position-state path in Docker:

```bash
POSITION_STATE_PATH=/app/data/positions.json
```

## Smoke tests

Build the image:

```bash
docker compose build
```

Safe config/logging startup:

```bash
docker compose run --rm \
  -e LIVE_RUNNER_ENABLED=false \
  crypto-flow-bot-v2
```

One finite live cycle:

```bash
docker compose run --rm \
  -e LIVE_RUNNER_ENABLED=true \
  -e LIVE_RUNNER_MAX_CYCLES=1 \
  crypto-flow-bot-v2
```

The live smoke test uses public Binance endpoints only and stops after one cycle. If Telegram remains disabled in `config.yaml`, Telegram sends and the `/start` poller are skipped safely.

## Production run

Remove or empty `LIVE_RUNNER_MAX_CYCLES` in `.env`, then run:

```bash
docker compose up -d --build
```

## Logs

```bash
docker compose logs -f --tail=200
```

The configured JSONL log file is mounted under `./logs` through the `/app/logs` container path.

## Persistent virtual positions

Virtual positions are saved to `/app/data/positions.json`, which compose maps to `./data/positions.json` on the host. This file is runtime state. Do not delete it unless you intentionally want to reset virtual state.

## Safety boundary

This deployment has no real trading execution:

- no Binance private API access
- no Binance API key usage
- no order placement
- no order cancellation
- no account mutation
