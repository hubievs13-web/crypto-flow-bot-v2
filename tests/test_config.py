from pathlib import Path

import pytest

from crypto_flow_bot_v2.config import BotConfig, load_config, parse_config


VALID_CONFIG = """
symbols:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT

timeframes:
  entry: 15m
  context: 1h
  macro: 4h

binance:
  base_url: https://fapi.binance.com
  timeout_seconds: 10.0
  kline_limit: 300
  derivatives_data_limit: 100

telegram:
  enabled: false
  bot_token_env: BOT_ENV
  chat_id_env: CHAT_ENV

logging:
  level: INFO
  jsonl_path: logs/rfa-events.jsonl

risk:
  min_risk_reward: 1.5
  atr_stop_multiplier: 1.5
  atr_tp_multipliers: [1.5, 2.5, 4.0]
  trailing_atr_multiplier: 1.0
  max_position_minutes: 240
  cooldown_minutes: 60

rfa_engine:
  min_signal_confidence: 70
  watch_confidence: 60
  strong_signal_confidence: 85
  require_context_alignment: true
  require_macro_alignment: true
"""


def test_load_config_from_yaml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    config = load_config(config_path)

    assert isinstance(config, BotConfig)
    assert config.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert config.timeframes.entry == "15m"
    assert config.timeframes.context == "1h"
    assert config.timeframes.macro == "4h"
    assert config.binance.base_url == "https://fapi.binance.com"
    assert config.binance.timeout_seconds == 10.0
    assert config.binance.kline_limit == 300
    assert config.binance.derivatives_data_limit == 100
    assert config.telegram.enabled is False
    assert config.risk.min_risk_reward == 1.5
    assert config.rfa_engine.min_signal_confidence == 70


def test_parse_config_defaults_missing_telegram_enabled_to_true() -> None:
    raw = _valid_raw_config()
    del raw["telegram"]["enabled"]

    config = parse_config(raw)

    assert config.telegram.enabled is True


def test_parse_config_rejects_empty_symbols() -> None:
    raw = _valid_raw_config()
    raw["symbols"] = []

    with pytest.raises(ValueError, match="symbols"):
        parse_config(raw)


def test_parse_config_rejects_invalid_binance_limit() -> None:
    raw = _valid_raw_config()
    raw["binance"]["kline_limit"] = 1501

    with pytest.raises(ValueError, match="kline_limit"):
        parse_config(raw)


def _valid_raw_config() -> dict[str, object]:
    return {
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
        "binance": {
            "base_url": "https://fapi.binance.com",
            "timeout_seconds": 10.0,
            "kline_limit": 300,
            "derivatives_data_limit": 100,
        },
        "telegram": {"enabled": False, "bot_" "token_env": "A", "chat_" "id_env": "B"},
        "logging": {"level": "INFO", "jsonl_path": "logs/events.jsonl"},
        "risk": {
            "min_risk_reward": 1.5,
            "atr_stop_multiplier": 1.5,
            "atr_tp_multipliers": [1.5, 2.5, 4.0],
            "trailing_atr_multiplier": 1.0,
            "max_position_minutes": 240,
            "cooldown_minutes": 60,
        },
        "rfa_engine": {
            "min_signal_confidence": 70,
            "watch_confidence": 60,
            "strong_signal_confidence": 85,
            "require_context_alignment": True,
            "require_macro_alignment": True,
        },
    }
