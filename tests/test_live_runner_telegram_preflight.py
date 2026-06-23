import pytest

from crypto_flow_bot_v2 import main as app_main
from crypto_flow_bot_v2.config import BotConfig, parse_config


def test_live_runner_telegram_preflight_requires_both_credentials(monkeypatch) -> None:
    config = _config(enabled=True)
    monkeypatch.delenv("BOT_ENV", raising=False)
    monkeypatch.delenv("CHAT_ENV", raising=False)

    with pytest.raises(app_main.LiveRunnerTelegramCredentialsError) as exc_info:
        app_main._validate_live_runner_telegram_config(config=config, live_runner_enabled=True)

    message = str(exc_info.value)
    assert "Telegram is enabled for live runner" in message
    assert "BOT_ENV" in message
    assert "CHAT_ENV" in message


def test_live_runner_telegram_preflight_reports_missing_bot_token(monkeypatch) -> None:
    config = _config(enabled=True)
    monkeypatch.delenv("BOT_ENV", raising=False)
    monkeypatch.setenv("CHAT_ENV", "present")

    with pytest.raises(app_main.LiveRunnerTelegramCredentialsError) as exc_info:
        app_main._validate_live_runner_telegram_config(config=config, live_runner_enabled=True)

    message = str(exc_info.value)
    assert "BOT_ENV" in message
    assert "CHAT_ENV" not in message


def test_live_runner_telegram_preflight_reports_missing_chat_id(monkeypatch) -> None:
    config = _config(enabled=True)
    monkeypatch.setenv("BOT_ENV", "present")
    monkeypatch.delenv("CHAT_ENV", raising=False)

    with pytest.raises(app_main.LiveRunnerTelegramCredentialsError) as exc_info:
        app_main._validate_live_runner_telegram_config(config=config, live_runner_enabled=True)

    message = str(exc_info.value)
    assert "CHAT_ENV" in message
    assert "BOT_ENV" not in message


def test_live_runner_telegram_preflight_allows_telegram_disabled(monkeypatch) -> None:
    config = _config(enabled=False)
    monkeypatch.delenv("BOT_ENV", raising=False)
    monkeypatch.delenv("CHAT_ENV", raising=False)

    app_main._validate_live_runner_telegram_config(config=config, live_runner_enabled=True)


def test_live_runner_telegram_preflight_allows_live_runner_disabled(monkeypatch) -> None:
    config = _config(enabled=True)
    monkeypatch.delenv("BOT_ENV", raising=False)
    monkeypatch.delenv("CHAT_ENV", raising=False)

    app_main._validate_live_runner_telegram_config(config=config, live_runner_enabled=False)


def test_live_runner_telegram_preflight_passes_when_credentials_exist(monkeypatch) -> None:
    config = _config(enabled=True)
    monkeypatch.setenv("BOT_ENV", "present")
    monkeypatch.setenv("CHAT_ENV", "present")

    app_main._validate_live_runner_telegram_config(config=config, live_runner_enabled=True)


def _config(enabled: bool) -> BotConfig:
    return parse_config(
        {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
            "binance": {
                "base_url": "https://fapi.binance.com",
                "timeout_seconds": 10.0,
                "kline_limit": 300,
                "derivatives_data_limit": 100,
            },
            "telegram": {
                "enabled": enabled,
                "bot_token_env": "BOT_ENV",
                "chat_id_env": "CHAT_ENV",
                "base_url": "https://api.telegram.org",
                "timeout_seconds": 10.0,
                "parse_mode": "HTML",
            },
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
    )
