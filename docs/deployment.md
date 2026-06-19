# VPS deployment guide

This guide runs `crypto-flow-bot-v2` as a Telegram-only Binance Futures public-data alert bot.
It does not enable real exchange trading.

## Minimum VPS

A small Ubuntu VPS is enough for the current bot:

- 1 vCPU
- 1 GB RAM
- 10–20 GB SSD
- Ubuntu 22.04 or 24.04

## Install Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl git gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

## Clone and configure

```bash
git clone https://github.com/hubievs13-web/crypto-flow-bot-v2.git
cd crypto-flow-bot-v2
cp .env.example .env
mkdir -p data logs
```

Edit `.env`:

```bash
CONFIG_PATH=config.yaml
TELEGRAM_BOT_TOKEN=<real token>
TELEGRAM_CHAT_ID=<real chat id>
LIVE_RUNNER_ENABLED=true
LIVE_CYCLE_INTERVAL_SECONDS=900
LIVE_RUNNER_MAX_CYCLES=
POSITION_STATE_PATH=data/positions.json
```

Edit `config.yaml` and set Telegram on:

```yaml
telegram:
  enabled: true
  bot_token_env: TELEGRAM_BOT_TOKEN
  chat_id_env: TELEGRAM_CHAT_ID
```

Keep the real token only in `.env`. Do not commit `.env`.

## Smoke test

Build the image first:

```bash
docker compose build
```

Run one finite cycle with a one-off container. This avoids the production restart policy, so the
container stops after the single smoke-test cycle instead of restarting forever:

```bash
docker compose run --rm \
  -e LIVE_RUNNER_ENABLED=true \
  -e LIVE_RUNNER_MAX_CYCLES=1 \
  crypto-flow-bot-v2
```

The bot should start, fetch public market data, and then stop after one cycle.

## Production run

Remove or empty `LIVE_RUNNER_MAX_CYCLES` in `.env`, then run:

```bash
docker compose up -d --build
```

## Logs

```bash
docker compose logs -f --tail=200
```

The configured JSONL log file is mounted under `./logs`.

## Persistent virtual positions

Virtual positions are saved to:

```bash
data/positions.json
```

This file is runtime state. It allows the bot to remember active virtual positions after a container
restart. Do not delete it unless you intentionally want to reset virtual state.

## Stop / restart

```bash
docker compose stop
docker compose restart
```

## Update from GitHub

```bash
git pull
docker compose up -d --build
```

## Safety boundary

This deployment still has no real trading execution:

- no Binance private API access
- no Binance API key usage
- no order placement
- no order cancellation
- no account mutation
