"""Package entrypoint for crypto-flow-bot-v2."""

from __future__ import annotations

import os

from crypto_flow_bot_v2.config import DEFAULT_CONFIG_PATH, load_config
from crypto_flow_bot_v2.logging import configure_logging, get_logger

LOGGER = get_logger(__name__)


def main() -> int:
    """Load configuration and print a safe startup summary."""

    config_path = os.getenv("CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
    config = load_config(config_path)
    configure_logging(config.logging)

    LOGGER.info(
        "crypto-flow-bot-v2 scaffold loaded: symbols=%s entry=%s context=%s macro=%s",
        ",".join(config.symbols),
        config.timeframes.entry,
        config.timeframes.context,
        config.timeframes.macro,
    )
    LOGGER.info("PR 1 contains no Binance API, Telegram sending, or real trading execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
