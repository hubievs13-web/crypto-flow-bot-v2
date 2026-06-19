"""Package entrypoint for crypto-flow-bot-v2."""

from __future__ import annotations

import os

from crypto_flow_bot_v2.config import DEFAULT_CONFIG_PATH, load_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.logging import configure_logging, get_logger

LOGGER = get_logger(__name__)
TRUE_VALUES = {"1", "true", "yes", "on"}


def main() -> int:
    """Load configuration and either print a safe summary or start the live alert runner."""

    config_path = os.getenv("CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
    config = load_config(config_path)
    configure_logging(config.logging)

    LOGGER.info(
        "crypto-flow-bot-v2 loaded: symbols=%s entry=%s context=%s macro=%s",
        ",".join(config.symbols),
        config.timeframes.entry,
        config.timeframes.context,
        config.timeframes.macro,
    )
    LOGGER.info(
        "Binance data layer configured for public USDⓈ-M Futures REST data: base_url=%s",
        config.binance.base_url,
    )
    LOGGER.info(
        "Telegram alert layer configured: enabled=%s bot_token_env=%s chat_id_env=%s",
        config.telegram.enabled,
        config.telegram.bot_token_env,
        config.telegram.chat_id_env,
    )
    LOGGER.info("No Binance private API or real trading execution is active.")

    if not _live_runner_enabled():
        LOGGER.info("Live runner disabled. Set LIVE_RUNNER_ENABLED=true to start alerts.")
        return 0

    cycle_interval_seconds = _env_int("LIVE_CYCLE_INTERVAL_SECONDS", default=900)
    max_cycles = _env_optional_int("LIVE_RUNNER_MAX_CYCLES")
    position_state_path = _env_optional_str("POSITION_STATE_PATH")
    LOGGER.info(
        "Starting live Telegram-only runner: interval_seconds=%s max_cycles=%s "
        "position_state_path=%s",
        cycle_interval_seconds,
        max_cycles,
        position_state_path,
    )
    runner = LiveAlertRunner.from_config(
        config=config,
        cycle_interval_seconds=cycle_interval_seconds,
        position_state_path=position_state_path,
    )
    stats = runner.run(max_cycles=max_cycles)
    LOGGER.info(
        "Live runner stopped: cycles=%s snapshots=%s decisions=%s opened=%s closed=%s "
        "alerts_sent=%s alert_errors=%s",
        stats.cycles,
        stats.snapshots_built,
        stats.decisions_evaluated,
        stats.positions_opened,
        stats.positions_closed,
        stats.telegram_alerts_sent,
        stats.telegram_alert_errors,
    )
    return 0


def _live_runner_enabled() -> bool:
    return os.getenv("LIVE_RUNNER_ENABLED", "").strip().lower() in TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value <= 0:
        msg = f"{name} must be positive."
        raise ValueError(msg)
    return value


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    value = int(raw)
    if value <= 0:
        msg = f"{name} must be positive when provided."
        raise ValueError(msg)
    return value


def _env_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


if __name__ == "__main__":
    raise SystemExit(main())
