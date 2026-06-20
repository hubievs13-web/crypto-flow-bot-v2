# Config defaults

Committed defaults are safe for local startup and CI.

- Telegram is disabled by default in `config.yaml`.
- `LIVE_RUNNER_ENABLED=false` is the default in `.env.example`.
- Numeric config validation rejects booleans for integer and float fields.
