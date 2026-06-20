# Test double notes

The test suite uses fakes for market data, Telegram delivery, snapshots, signal decisions, position management, and persistence storage.

The fakes used in the production-readiness tests are expected to keep method names and call arguments aligned with the production protocols. They also simulate failures at explicit stages so live-runner and Telegram error handling can be tested deterministically.
