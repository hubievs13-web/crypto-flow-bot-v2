"""Package entrypoint for crypto-flow-bot-v2."""

from __future__ import annotations

import os
from threading import Event, Thread

from crypto_flow_bot_v2.config import DEFAULT_CONFIG_PATH, BotConfig, load_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.logging import configure_logging, get_logger
from crypto_flow_bot_v2.telegram import TelegramAlertService, TelegramAlertStatus
from crypto_flow_bot_v2.telegram_start import TelegramStartCommandPoller

LOGGER = get_logger(__name__)
TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_LIVE_RUNNER_INTERVAL_SECONDS = 900
LIVE_RUNNER_STARTUP_MESSAGE = "🚀 Crypto Flow Bot started. Live runner enabled."


def main() -> int:
    """Load configuration and either print a safe summary or start the live alert runner."""

    config_path = os.getenv("CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
    config = load_config(config_path)
    configure_logging(config.logging)
    live_runner_enabled = _live_runner_enabled()

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
    _log_startup_diagnostics(config=config, live_runner_enabled=live_runner_enabled)
    LOGGER.info("No Binance private API or real trading execution is active.")

    if not live_runner_enabled:
        LOGGER.info("Live runner disabled. Set LIVE_RUNNER_ENABLED=true to start alerts.")
        return 0

    cycle_interval_seconds = _live_runner_interval_seconds()
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
    _send_live_runner_startup_message(config)
    start_poller = _start_telegram_start_poller(config)
    try:
        stats = runner.run(max_cycles=max_cycles)
    finally:
        _stop_telegram_start_poller(start_poller)
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


def _log_startup_diagnostics(config: BotConfig, live_runner_enabled: bool) -> None:
    token_present = _env_has_value(config.telegram.bot_token_env)
    chat_id_present = _env_has_value(config.telegram.chat_id_env)
    LOGGER.info(
        "startup diagnostics: LIVE_RUNNER_ENABLED=%s telegram.enabled=%s "
        "token present: %s chat_id present: %s",
        live_runner_enabled,
        config.telegram.enabled,
        _yes_no(token_present),
        _yes_no(chat_id_present),
    )
    if config.telegram.enabled and (not token_present or not chat_id_present):
        LOGGER.warning(
            "Telegram is enabled but messages will not be sent because credentials are missing: "
            "token present: %s chat_id present: %s bot_token_env=%s chat_id_env=%s",
            _yes_no(token_present),
            _yes_no(chat_id_present),
            config.telegram.bot_token_env,
            config.telegram.chat_id_env,
        )


def _send_live_runner_startup_message(config: BotConfig) -> None:
    notifier = TelegramAlertService(config)
    try:
        result = notifier._send(LIVE_RUNNER_STARTUP_MESSAGE)  # noqa: SLF001
    except Exception:
        LOGGER.exception("failed to send live runner startup Telegram message")
        return

    if result.status is TelegramAlertStatus.SENT:
        LOGGER.info("live runner startup Telegram message sent")
    else:
        LOGGER.warning("live runner startup Telegram message skipped: %s", result.message)


def _start_telegram_start_poller(config: BotConfig) -> tuple[Event, Thread]:
    stop_event = Event()
    poller = TelegramStartCommandPoller(config)
    thread = Thread(
        target=poller.run_forever,
        args=(stop_event,),
        name="telegram-start-poller",
        daemon=True,
    )
    thread.start()
    LOGGER.info("Telegram /start command poller started.")
    return stop_event, thread


def _stop_telegram_start_poller(start_poller: tuple[Event, Thread]) -> None:
    stop_event, thread = start_poller
    stop_event.set()
    thread.join(timeout=2)


def _live_runner_enabled() -> bool:
    return os.getenv("LIVE_RUNNER_ENABLED", "").strip().lower() in TRUE_VALUES


def _live_runner_interval_seconds() -> int:
    raw = os.getenv("LIVE_RUNNER_INTERVAL_SECONDS")
    if raw is not None and raw.strip():
        value = int(raw)
        if value <= 0:
            msg = "LIVE_RUNNER_INTERVAL_SECONDS must be positive."
            raise ValueError(msg)
        return value
    return _env_int("LIVE_CYCLE_INTERVAL_SECONDS", default=DEFAULT_LIVE_RUNNER_INTERVAL_SECONDS)


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


def _env_has_value(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
