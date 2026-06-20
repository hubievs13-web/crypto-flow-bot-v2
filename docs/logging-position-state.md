# Logging and position state

Logging:

- Console logging uses the configured log level.
- `logging.jsonl_path` writes one JSON object per line.
- Docker compose mounts `/app/logs` to `./logs`.

Position state:

- Virtual-position state is loaded on startup.
- Initialization does not write a state file.
- State is saved only after open, update, close, or explicit restore operations.
- Docker compose mounts `/app/data` to `./data`.
