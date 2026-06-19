"""Configuration models and YAML loading for crypto-flow-bot-v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass(frozen=True, slots=True)
class TimeframeConfig:
    """Multi-timeframe setup for RFA analysis."""

    entry: str
    context: str
    macro: str


@dataclass(frozen=True, slots=True)
class BinanceDataConfig:
    """Public Binance USDⓈ-M Futures market-data settings."""

    base_url: str
    timeout_seconds: float
    kline_limit: int
    derivatives_data_limit: int


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Telegram settings placeholder.

    Real message sending is intentionally not implemented in PR 2.
    """

    enabled: bool
    bot_token_env: str
    chat_id_env: str


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Logging settings."""

    level: str
    jsonl_path: Path


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Risk-management settings used by later PRs."""

    min_risk_reward: float
    atr_stop_multiplier: float
    atr_tp_multipliers: tuple[float, ...]
    trailing_atr_multiplier: float
    max_position_minutes: int
    cooldown_minutes: int


@dataclass(frozen=True, slots=True)
class RFAEngineConfig:
    """Configuration gates for the future RFA Engine."""

    min_signal_confidence: int
    watch_confidence: int
    strong_signal_confidence: int
    require_context_alignment: bool
    require_macro_alignment: bool


@dataclass(frozen=True, slots=True)
class BotConfig:
    """Top-level application configuration."""

    symbols: tuple[str, ...]
    timeframes: TimeframeConfig
    binance: BinanceDataConfig
    telegram: TelegramConfig
    logging: LoggingConfig
    risk: RiskConfig
    rfa_engine: RFAEngineConfig


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BotConfig:
    """Load and validate bot configuration from YAML."""

    config_path = Path(path)
    if not config_path.exists():
        msg = f"Config file not found: {config_path}"
        raise FileNotFoundError(msg)

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "Config file must contain a YAML mapping at the top level."
        raise ValueError(msg)

    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> BotConfig:
    """Parse a raw mapping into a typed configuration object."""

    symbols = _parse_symbols(raw.get("symbols"))
    timeframes = _parse_timeframes(_require_mapping(raw, "timeframes"))
    binance = _parse_binance(_require_mapping(raw, "binance"))
    telegram = _parse_telegram(_require_mapping(raw, "telegram"))
    logging_config = _parse_logging(_require_mapping(raw, "logging"))
    risk = _parse_risk(_require_mapping(raw, "risk"))
    rfa_engine = _parse_rfa_engine(_require_mapping(raw, "rfa_engine"))

    return BotConfig(
        symbols=symbols,
        timeframes=timeframes,
        binance=binance,
        telegram=telegram,
        logging=logging_config,
        risk=risk,
        rfa_engine=rfa_engine,
    )


def _require_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        msg = f"Config section '{key}' must be a mapping."
        raise ValueError(msg)
    return value


def _parse_symbols(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        msg = "Config field 'symbols' must be a non-empty list."
        raise ValueError(msg)

    symbols = tuple(str(symbol).strip().upper() for symbol in value)
    if any(not symbol for symbol in symbols):
        msg = "Config field 'symbols' cannot contain empty symbols."
        raise ValueError(msg)
    return symbols


def _parse_timeframes(value: dict[str, Any]) -> TimeframeConfig:
    return TimeframeConfig(
        entry=_required_str(value, "entry"),
        context=_required_str(value, "context"),
        macro=_required_str(value, "macro"),
    )


def _parse_binance(value: dict[str, Any]) -> BinanceDataConfig:
    timeout_seconds = _required_float(value, "timeout_seconds")
    kline_limit = _required_int(value, "kline_limit")
    derivatives_data_limit = _required_int(value, "derivatives_data_limit")

    if timeout_seconds <= 0:
        msg = "Binance field 'timeout_seconds' must be positive."
        raise ValueError(msg)
    if not 1 <= kline_limit <= 1500:
        msg = "Binance field 'kline_limit' must be between 1 and 1500."
        raise ValueError(msg)
    if not 1 <= derivatives_data_limit <= 500:
        msg = "Binance field 'derivatives_data_limit' must be between 1 and 500."
        raise ValueError(msg)

    return BinanceDataConfig(
        base_url=_required_str(value, "base_url").rstrip("/"),
        timeout_seconds=timeout_seconds,
        kline_limit=kline_limit,
        derivatives_data_limit=derivatives_data_limit,
    )


def _parse_telegram(value: dict[str, Any]) -> TelegramConfig:
    return TelegramConfig(
        enabled=bool(value.get("enabled", False)),
        bot_token_env=_required_str(value, "bot_token_env"),
        chat_id_env=_required_str(value, "chat_id_env"),
    )


def _parse_logging(value: dict[str, Any]) -> LoggingConfig:
    return LoggingConfig(
        level=_required_str(value, "level").upper(),
        jsonl_path=Path(_required_str(value, "jsonl_path")),
    )


def _parse_risk(value: dict[str, Any]) -> RiskConfig:
    atr_tp_multipliers = value.get("atr_tp_multipliers")
    if not isinstance(atr_tp_multipliers, list) or not atr_tp_multipliers:
        msg = "Risk field 'atr_tp_multipliers' must be a non-empty list."
        raise ValueError(msg)

    return RiskConfig(
        min_risk_reward=_required_float(value, "min_risk_reward"),
        atr_stop_multiplier=_required_float(value, "atr_stop_multiplier"),
        atr_tp_multipliers=tuple(float(item) for item in atr_tp_multipliers),
        trailing_atr_multiplier=_required_float(value, "trailing_atr_multiplier"),
        max_position_minutes=_required_int(value, "max_position_minutes"),
        cooldown_minutes=_required_int(value, "cooldown_minutes"),
    )


def _parse_rfa_engine(value: dict[str, Any]) -> RFAEngineConfig:
    return RFAEngineConfig(
        min_signal_confidence=_required_int(value, "min_signal_confidence"),
        watch_confidence=_required_int(value, "watch_confidence"),
        strong_signal_confidence=_required_int(value, "strong_signal_confidence"),
        require_context_alignment=bool(value.get("require_context_alignment", True)),
        require_macro_alignment=bool(value.get("require_macro_alignment", True)),
    )


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        msg = f"Config value '{key}' must be a non-empty string."
        raise ValueError(msg)
    return item.strip()


def _required_float(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, int | float):
        msg = f"Config value '{key}' must be numeric."
        raise ValueError(msg)
    return float(item)


def _required_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int):
        msg = f"Config value '{key}' must be an integer."
        raise ValueError(msg)
    return item
