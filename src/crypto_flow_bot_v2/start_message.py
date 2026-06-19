"""Telegram /start welcome message."""

from __future__ import annotations


def format_start_message() -> str:
    """Return the Russian Telegram welcome message."""

    return "\n".join(
        [
            "<b>Привет! Я Crypto Flow Bot.</b>",
            "Я отслеживаю крипторынок и отправляю Telegram-сигналы по RFA-модели.",
            "Реальные сделки не открываю: это только уведомления и виртуальные позиции.",
        ]
    )
