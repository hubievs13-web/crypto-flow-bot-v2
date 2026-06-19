# PR 8 validation notes

Local validation available in this execution environment:

```bash
python -m compileall -q \
  src/crypto_flow_bot_v2/config.py \
  src/crypto_flow_bot_v2/calibration.py \
  tests/test_calibration.py
```

Result: passed on the edited PR 8 files before pushing.

Additional static check performed locally:

- Python line-length scan for edited PR 8 Python files: 0 lines over 100 characters.

Not completed in this execution environment:

- Full repository `pytest`, because the environment cannot clone/fetch GitHub over the network.
- `ruff check .`, because `ruff` is not installed in the execution environment.

The PR keeps calibration offline and uses already-built `MarketSnapshot` data only.
