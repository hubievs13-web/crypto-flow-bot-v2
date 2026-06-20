# Deployment smoke checklist

Run before production deployment:

```bash
pytest
ruff check .
python -m crypto_flow_bot_v2
```

Docker checks:

```bash
docker compose build
docker compose run --rm -e LIVE_RUNNER_ENABLED=false crypto-flow-bot-v2
docker compose run --rm -e LIVE_RUNNER_ENABLED=true -e LIVE_RUNNER_MAX_CYCLES=1 crypto-flow-bot-v2
```

Notes:

- The default config keeps Telegram disabled.
- For production Telegram alerts, set `telegram.enabled: true` and provide `TELEGRAM_BOT_TOKEN` plus `TELEGRAM_CHAT_ID` outside git.
- `POSITION_STATE_PATH=/app/data/positions.json` matches the compose volume mapping.
- `logging.jsonl_path` writes to the mounted `/app/logs` path when the default config is used in Docker.
