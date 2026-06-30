"""Configuration models and YAML loading for crypto-flow-bot-v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_TELEGRAM_BASE_URL = "https://api.telegram.org"
DEFAULT_TELEGRAM_TIMEOUT_SECONDS = 10.0
DEFAULT_TELEGRAM_PARSE_MODE = "HTML"
DEFAULT_TELEGRAM_ENABLED = True
DEFAULT_CALIBRATION_OBJECTIVE = "risk_adjusted_pnl"
DEFAULT_MARKET_REGIME_ENABLED = False
DEFAULT_SIGNAL_GOVERNOR_ENABLED = False
DEFAULT_CANDIDATE_ENGINE_ENABLED = False
DEFAULT_RFA_MIN_EVIDENCE_COMPONENTS = 6


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
    """Telegram alert settings.

    Bot tokens and chat IDs are read from environment variables. Config files store only the
    environment variable names and transport settings.
    """

    enabled: bool
    bot_token_env: str
    chat_id_env: str
    base_url: str
    timeout_seconds: float
    parse_mode: str


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
    min_evidence_components: int
    require_context_alignment: bool
    require_macro_alignment: bool


@dataclass(frozen=True, slots=True)
class MarketRegimeScoringConfig:
    """Conservative post-RFA Regime-Lite scoring layer settings."""

    enabled: bool
    mode: str
    fail_open: bool
    low_confidence_behavior: str
    min_confidence_for_adjustment: float
    max_positive_adjustment: int
    max_negative_adjustment: int
    apply_bonus_only_if_base_score_at_least: int


@dataclass(frozen=True, slots=True)
class SignalGovernorRankingConfig:
    """Ranking keys used by SignalGovernor."""

    primary: str
    secondary: str
    tertiary: str


@dataclass(frozen=True, slots=True)
class SignalGovernorConfig:
    """Protective signal throttling and ranking settings."""

    enabled: bool
    max_signals_per_scan: int
    max_signals_per_hour: int
    per_symbol_cooldown_minutes: int
    same_direction_cluster_limit: int
    ranking: SignalGovernorRankingConfig


@dataclass(frozen=True, slots=True)
class CandidateEngineConfig:
    """Lite stateful near-miss candidate tracking settings."""

    enabled: bool
    min_candidate_score: float
    signal_threshold: float
    candidate_ttl_minutes: int
    min_maturity_ticks: int
    max_maturity_bonus: float
    max_candidates_total: int
    max_candidates_per_symbol: int
    hard_filters_required: bool


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    """Offline calibration and optimization settings."""

    enabled: bool
    objective: str
    min_trades: int
    drawdown_penalty: float
    max_trials: int
    min_signal_confidence_values: tuple[int, ...]
    min_risk_reward_values: tuple[float, ...]
    atr_stop_multiplier_values: tuple[float, ...]
    trailing_atr_multiplier_values: tuple[float, ...]
    cooldown_minutes_values: tuple[int, ...]


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
    market_regime: MarketRegimeScoringConfig
    signal_governor: SignalGovernorConfig
    candidate_engine: CandidateEngineConfig
    calibration: CalibrationConfig


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
    market_regime = _parse_market_regime(raw.get("market_regime", {}))
    signal_governor = _parse_signal_governor(raw.get("signal_governor", {}))
    candidate_engine = _parse_candidate_engine(raw.get("candidate_engine", {}))
    calibration = _parse_calibration(raw.get("calibration", {}))

    return BotConfig(
        symbols=symbols,
        timeframes=timeframes,
        binance=binance,
        telegram=telegram,
        logging=logging_config,
        risk=risk,
        rfa_engine=rfa_engine,
        market_regime=market_regime,
        signal_governor=signal_governor,
        candidate_engine=candidate_engine,
        calibration=calibration,
    )


def _require_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        msg = f"Config section '{key}' must be a mapping."
        raise ValueError(msg)
    return value


def _optional_mapping(value: Any, key: str) -> dict[str, Any]:
    if value is None:
        return {}
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
    base_url = str(value.get("base_url", DEFAULT_TELEGRAM_BASE_URL)).strip().rstrip("/")
    timeout_seconds = float(value.get("timeout_seconds", DEFAULT_TELEGRAM_TIMEOUT_SECONDS))
    parse_mode = str(value.get("parse_mode", DEFAULT_TELEGRAM_PARSE_MODE)).strip()

    if not base_url:
        msg = "Telegram field 'base_url' must be non-empty."
        raise ValueError(msg)
    if timeout_seconds <= 0:
        msg = "Telegram field 'timeout_seconds' must be positive."
        raise ValueError(msg)
    if not parse_mode:
        msg = "Telegram field 'parse_mode' must be non-empty."
        raise ValueError(msg)

    return TelegramConfig(
        enabled=bool(value.get("enabled", DEFAULT_TELEGRAM_ENABLED)),
        bot_token_env=_required_str(value, "bot_token_env"),
        chat_id_env=_required_str(value, "chat_id_env"),
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        parse_mode=parse_mode,
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
    min_evidence_components = _optional_int(
        value,
        "min_evidence_components",
        DEFAULT_RFA_MIN_EVIDENCE_COMPONENTS,
    )
    if not 1 <= min_evidence_components <= 10:
        msg = "RFA engine field 'min_evidence_components' must be between 1 and 10."
        raise ValueError(msg)

    return RFAEngineConfig(
        min_signal_confidence=_required_int(value, "min_signal_confidence"),
        watch_confidence=_required_int(value, "watch_confidence"),
        strong_signal_confidence=_required_int(value, "strong_signal_confidence"),
        min_evidence_components=min_evidence_components,
        require_context_alignment=bool(value.get("require_context_alignment", True)),
        require_macro_alignment=bool(value.get("require_macro_alignment", True)),
    )


def _parse_market_regime(value: Any) -> MarketRegimeScoringConfig:
    mapping = _optional_mapping(value, "market_regime")
    config = MarketRegimeScoringConfig(
        enabled=bool(mapping.get("enabled", DEFAULT_MARKET_REGIME_ENABLED)),
        mode=str(mapping.get("mode", "scoring_layer")).strip(),
        fail_open=bool(mapping.get("fail_open", True)),
        low_confidence_behavior=str(
            mapping.get("low_confidence_behavior", "no_adjustment")
        ).strip(),
        min_confidence_for_adjustment=_optional_float(
            mapping,
            "min_confidence_for_adjustment",
            0.65,
        ),
        max_positive_adjustment=_optional_int(mapping, "max_positive_adjustment", 3),
        max_negative_adjustment=_optional_int(mapping, "max_negative_adjustment", 4),
        apply_bonus_only_if_base_score_at_least=_optional_int(
            mapping,
            "apply_bonus_only_if_base_score_at_least",
            68,
        ),
    )
    _validate_market_regime(config)
    return config


def _validate_market_regime(config: MarketRegimeScoringConfig) -> None:
    if config.mode != "scoring_layer":
        msg = "Market regime field 'mode' must be 'scoring_layer'."
        raise ValueError(msg)
    if config.low_confidence_behavior != "no_adjustment":
        msg = "Market regime field 'low_confidence_behavior' must be 'no_adjustment'."
        raise ValueError(msg)
    if not 0.0 <= config.min_confidence_for_adjustment <= 1.0:
        msg = "Market regime field 'min_confidence_for_adjustment' must be between 0 and 1."
        raise ValueError(msg)
    if config.max_positive_adjustment < 0:
        msg = "Market regime field 'max_positive_adjustment' cannot be negative."
        raise ValueError(msg)
    if config.max_negative_adjustment < 0:
        msg = "Market regime field 'max_negative_adjustment' cannot be negative."
        raise ValueError(msg)
    if not 0 <= config.apply_bonus_only_if_base_score_at_least <= 100:
        msg = "Market regime field 'apply_bonus_only_if_base_score_at_least' must be 0-100."
        raise ValueError(msg)


def _parse_signal_governor(value: Any) -> SignalGovernorConfig:
    mapping = _optional_mapping(value, "signal_governor")
    ranking = _optional_mapping(mapping.get("ranking", {}), "signal_governor.ranking")
    config = SignalGovernorConfig(
        enabled=bool(mapping.get("enabled", DEFAULT_SIGNAL_GOVERNOR_ENABLED)),
        max_signals_per_scan=_optional_int(mapping, "max_signals_per_scan", 2),
        max_signals_per_hour=_optional_int(mapping, "max_signals_per_hour", 4),
        per_symbol_cooldown_minutes=_optional_int(mapping, "per_symbol_cooldown_minutes", 90),
        same_direction_cluster_limit=_optional_int(mapping, "same_direction_cluster_limit", 2),
        ranking=SignalGovernorRankingConfig(
            primary=str(ranking.get("primary", "final_score")).strip(),
            secondary=str(ranking.get("secondary", "risk_reward")).strip(),
            tertiary=str(ranking.get("tertiary", "volume_confirmation")).strip(),
        ),
    )
    _validate_signal_governor(config)
    return config


def _validate_signal_governor(config: SignalGovernorConfig) -> None:
    if config.max_signals_per_scan <= 0:
        msg = "Signal governor field 'max_signals_per_scan' must be positive."
        raise ValueError(msg)
    if config.max_signals_per_hour <= 0:
        msg = "Signal governor field 'max_signals_per_hour' must be positive."
        raise ValueError(msg)
    if config.per_symbol_cooldown_minutes < 0:
        msg = "Signal governor field 'per_symbol_cooldown_minutes' cannot be negative."
        raise ValueError(msg)
    if config.same_direction_cluster_limit <= 0:
        msg = "Signal governor field 'same_direction_cluster_limit' must be positive."
        raise ValueError(msg)
    allowed = {"final_score", "base_score", "risk_reward", "volume_confirmation"}
    for key in (
        config.ranking.primary,
        config.ranking.secondary,
        config.ranking.tertiary,
    ):
        if key not in allowed:
            msg = f"Signal governor ranking key '{key}' is not supported."
            raise ValueError(msg)


def _parse_candidate_engine(value: Any) -> CandidateEngineConfig:
    mapping = _optional_mapping(value, "candidate_engine")
    config = CandidateEngineConfig(
        enabled=bool(mapping.get("enabled", DEFAULT_CANDIDATE_ENGINE_ENABLED)),
        min_candidate_score=_optional_float(mapping, "min_candidate_score", 0.65),
        signal_threshold=_optional_float(mapping, "signal_threshold", 0.80),
        candidate_ttl_minutes=_optional_int(mapping, "candidate_ttl_minutes", 120),
        min_maturity_ticks=_optional_int(mapping, "min_maturity_ticks", 2),
        max_maturity_bonus=_optional_float(mapping, "max_maturity_bonus", 0.05),
        max_candidates_total=_optional_int(mapping, "max_candidates_total", 100),
        max_candidates_per_symbol=_optional_int(mapping, "max_candidates_per_symbol", 2),
        hard_filters_required=bool(mapping.get("hard_filters_required", True)),
    )
    _validate_candidate_engine(config)
    return config


def _validate_candidate_engine(config: CandidateEngineConfig) -> None:
    if not 0.0 <= config.min_candidate_score <= 1.0:
        msg = "Candidate engine field 'min_candidate_score' must be between 0 and 1."
        raise ValueError(msg)
    if not 0.0 <= config.signal_threshold <= 1.0:
        msg = "Candidate engine field 'signal_threshold' must be between 0 and 1."
        raise ValueError(msg)
    if config.min_candidate_score >= config.signal_threshold:
        msg = "Candidate engine field 'min_candidate_score' must be below signal_threshold."
        raise ValueError(msg)
    if config.candidate_ttl_minutes <= 0:
        msg = "Candidate engine field 'candidate_ttl_minutes' must be positive."
        raise ValueError(msg)
    if config.min_maturity_ticks <= 0:
        msg = "Candidate engine field 'min_maturity_ticks' must be positive."
        raise ValueError(msg)
    if not 0.0 <= config.max_maturity_bonus <= 1.0:
        msg = "Candidate engine field 'max_maturity_bonus' must be between 0 and 1."
        raise ValueError(msg)
    if config.max_candidates_total <= 0:
        msg = "Candidate engine field 'max_candidates_total' must be positive."
        raise ValueError(msg)
    if config.max_candidates_per_symbol <= 0:
        msg = "Candidate engine field 'max_candidates_per_symbol' must be positive."
        raise ValueError(msg)


def _parse_calibration(value: Any) -> CalibrationConfig:
    if not isinstance(value, dict):
        msg = "Config section 'calibration' must be a mapping."
        raise ValueError(msg)

    config = CalibrationConfig(
        enabled=bool(value.get("enabled", False)),
        objective=str(value.get("objective", DEFAULT_CALIBRATION_OBJECTIVE)).strip(),
        min_trades=_optional_int(value, "min_trades", 1),
        drawdown_penalty=_optional_float(value, "drawdown_penalty", 1.0),
        max_trials=_optional_int(value, "max_trials", 100),
        min_signal_confidence_values=_optional_int_tuple(
            value,
            "min_signal_confidence_values",
            (70,),
        ),
        min_risk_reward_values=_optional_float_tuple(value, "min_risk_reward_values", (1.5,)),
        atr_stop_multiplier_values=_optional_float_tuple(
            value,
            "atr_stop_multiplier_values",
            (1.5,),
        ),
        trailing_atr_multiplier_values=_optional_float_tuple(
            value,
            "trailing_atr_multiplier_values",
            (1.0,),
        ),
        cooldown_minutes_values=_optional_int_tuple(value, "cooldown_minutes_values", (60,)),
    )
    _validate_calibration(config)
    return config


def _validate_calibration(config: CalibrationConfig) -> None:
    if config.objective != DEFAULT_CALIBRATION_OBJECTIVE:
        msg = "Calibration field 'objective' must be 'risk_adjusted_pnl'."
        raise ValueError(msg)
    if config.min_trades < 0:
        msg = "Calibration field 'min_trades' cannot be negative."
        raise ValueError(msg)
    if config.drawdown_penalty < 0:
        msg = "Calibration field 'drawdown_penalty' cannot be negative."
        raise ValueError(msg)
    if config.max_trials <= 0:
        msg = "Calibration field 'max_trials' must be positive."
        raise ValueError(msg)

    for confidence in config.min_signal_confidence_values:
        if not 0 <= confidence <= 100:
            msg = "Calibration confidence values must be between 0 and 100."
            raise ValueError(msg)
    _validate_positive_tuple(config.min_risk_reward_values, "min_risk_reward_values")
    _validate_positive_tuple(config.atr_stop_multiplier_values, "atr_stop_multiplier_values")
    _validate_positive_tuple(
        config.trailing_atr_multiplier_values,
        "trailing_atr_multiplier_values",
    )
    if any(value < 0 for value in config.cooldown_minutes_values):
        msg = "Calibration field 'cooldown_minutes_values' cannot contain negative values."
        raise ValueError(msg)


def _validate_positive_tuple(values: tuple[float, ...], field_name: str) -> None:
    if any(value <= 0 for value in values):
        msg = f"Calibration field '{field_name}' must contain only positive values."
        raise ValueError(msg)


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


def _optional_float(value: dict[str, Any], key: str, default: float) -> float:
    item = value.get(key, default)
    if isinstance(item, bool) or not isinstance(item, int | float):
        msg = f"Config value '{key}' must be numeric."
        raise ValueError(msg)
    return float(item)


def _optional_int(value: dict[str, Any], key: str, default: int) -> int:
    item = value.get(key, default)
    if isinstance(item, bool) or not isinstance(item, int):
        msg = f"Config value '{key}' must be an integer."
        raise ValueError(msg)
    return item


def _optional_float_tuple(
    value: dict[str, Any],
    key: str,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    item = value.get(key, list(default))
    if not isinstance(item, list) or not item:
        msg = f"Config value '{key}' must be a non-empty list."
        raise ValueError(msg)
    if any(isinstance(entry, bool) or not isinstance(entry, int | float) for entry in item):
        msg = f"Config value '{key}' must contain only numeric values."
        raise ValueError(msg)
    return tuple(float(entry) for entry in item)


def _optional_int_tuple(
    value: dict[str, Any],
    key: str,
    default: tuple[int, ...],
) -> tuple[int, ...]:
    item = value.get(key, list(default))
    if not isinstance(item, list) or not item:
        msg = f"Config value '{key}' must be a non-empty list."
        raise ValueError(msg)
    if any(isinstance(entry, bool) or not isinstance(entry, int) for entry in item):
        msg = f"Config value '{key}' must contain only integer values."
        raise ValueError(msg)
    return tuple(item)
