# Release checklist

Before merge:

- Review PR diff for source, tests, Docker, docs, and config consistency.
- Confirm CI passes: `ruff check .`, `pytest`, and safe entrypoint smoke test.
- Build Docker image.
- Run safe Docker startup with `LIVE_RUNNER_ENABLED=false`.
- Run one-cycle Docker live smoke test with `LIVE_RUNNER_ENABLED=true` and `LIVE_RUNNER_MAX_CYCLES=1`.

Before production:

- Set `telegram.enabled: true` only in the deployment config that should send alerts.
- Provide Telegram environment variables through the deployment secret store or `.env` outside git.
- Mount `/app/data` for virtual position state.
- Mount `/app/logs` for JSONL logs.
- Verify public Binance endpoint availability from the target host.
