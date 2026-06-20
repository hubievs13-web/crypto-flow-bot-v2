# Runtime error policy

## Live runner

The live runner isolates errors by symbol and stage. A failure in one symbol must not stop the whole cycle.

Stages:

- `snapshot_build`
- `position_update`
- `signal_evaluation`
- `position_open`

Each stage logs with `LOGGER.exception` and increments either `build_errors` or `processing_errors`.

## Telegram delivery

Telegram sends to multiple chat IDs are independent. One failed chat ID does not block the rest. Results report sent and failed counts through `TelegramAlertResult`.

## Telegram `/start`

The `/start` poller advances the update offset only after an update is safely handled. Failed sends can be retried without repeatedly replying to already successful later updates.

## Offline replay

Backtest replay records per-snapshot runtime failures as `ReplayEventType.ERROR`. Calibration rejects trials whose replay summary contains runtime errors.
