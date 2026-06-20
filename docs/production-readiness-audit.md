# Production readiness audit notes

This document records the rationale for the production-readiness fixes in `fix/production-readiness-audit`.

## Source, Docker, and config consistency

- Docker builds must install committed source code exactly as tested locally.
- `Dockerfile` must not patch Python source files during image build.
- Committed `config.yaml` keeps Telegram disabled by default.
- Production enablement is explicit through `telegram.enabled: true` plus environment variables.

## Runtime isolation policy

- Snapshot build failures are counted as build errors and do not stop the live loop.
- Position update, signal evaluation, and position open failures are counted as processing errors and logged with `LOGGER.exception`.
- Telegram multi-chat sends continue after per-chat failures and report partial success.
- Telegram `/start` offsets advance only after each update is safely handled.

## Offline tooling policy

Backtest and calibration tooling should not fail an entire offline run because one snapshot or trial has bad runtime data. Bad snapshots produce replay error events; calibration rejects trials with replay errors.

## Logging and persistence policy

- `logging.jsonl_path` writes actual JSONL records.
- Persistent virtual position state is not written during initialization unless state is explicitly restored through `restore_state` or later modified by open/update/close operations.
