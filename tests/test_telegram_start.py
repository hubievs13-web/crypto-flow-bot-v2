from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.telegram import TelegramSendResult
from crypto_flow_bot_v2.telegram_start import TelegramCommandUpdate, TelegramStartCommandPoller


class FakeTelegramTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def send_message(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        parse_mode: str,
    ) -> TelegramSendResult:
        self.calls.append((bot_token, chat_id, text, parse_mode))
        return TelegramSendResult(ok=True, message_id=42)


def test_start_poller_replies_to_inbound_start_command(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ENV", "TOKEN")
    transport = FakeTelegramTransport()
    poller = TelegramStartCommandPoller(_config(), transport=transport)
    poller._get_updates = lambda bot_token: (  # noqa: SLF001
        TelegramCommandUpdate(update_id=10, chat_id="START_CHAT", text="/start"),
        TelegramCommandUpdate(update_id=11, chat_id="OTHER_CHAT", text="hello"),
    )

    handled = poller.run_once()

    assert handled == 1
    assert len(transport.calls) == 1
    bot_token, chat_id, text, parse_mode = transport.calls[0]
    assert bot_token == "TOKEN"
    assert chat_id == "START_CHAT"
    assert "Привет" in text
    assert "Реальные сделки не открываю" in text
    assert parse_mode == "HTML"


def test_start_poller_skips_when_bot_token_missing(monkeypatch) -> None:
    monkeypatch.delenv("BOT_ENV", raising=False)
    transport = FakeTelegramTransport()
    poller = TelegramStartCommandPoller(_config(), transport=transport)

    handled = poller.run_once()

    assert handled == 0
    assert transport.calls == []


def _config(enabled: bool = True) -> BotConfig:
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
