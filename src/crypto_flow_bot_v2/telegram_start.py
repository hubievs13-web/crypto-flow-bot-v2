"""Telegram /start command polling.

This module replies to inbound Telegram /start commands only. It does not place, modify,
or close exchange orders.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.logging import get_logger
from crypto_flow_bot_v2.start_message import format_start_message
from crypto_flow_bot_v2.telegram import TelegramAlertError, TelegramTransport, UrlLibTelegramTransport

LOGGER = get_logger(__name__)
START_COMMAND = "/start"
USER_AGENT = "crypto-flow-bot-v2/0.1.0"


@dataclass(frozen=True, slots=True)
class TelegramCommandUpdate:
    """Minimal inbound Telegram message needed to handle /start."""

    update_id: int
    chat_id: str
    text: str


class TelegramStartCommandPoller:
    """Poll Telegram updates and reply to /start commands with a Russian welcome message."""

    def __init__(
        self,
        config: BotConfig,
        transport: TelegramTransport | None = None,
        poll_interval_seconds: float = 3.0,
    ) -> None:
        self._config = config
        self._transport = transport or UrlLibTelegramTransport.from_config(config.telegram)
        self._poll_interval_seconds = poll_interval_seconds
        self._update_offset: int | None = None

    def run_forever(self, stop_event: Event) -> None:
        """Poll until stop_event is set."""

        while not stop_event.is_set():
            try:
                handled = self.run_once()
            except Exception:
                LOGGER.exception("failed to process Telegram /start updates")
            else:
                if handled:
                    LOGGER.info("Telegram /start commands handled: %s", handled)
            stop_event.wait(self._poll_interval_seconds)

    def run_once(self) -> int:
        """Poll Telegram once and return the number of /start replies sent."""

        telegram = self._config.telegram
        if not telegram.enabled:
            return 0

        bot_token = os.getenv(telegram.bot_token_env, "").strip()
        if not bot_token:
            return 0

        updates = self._get_updates(bot_token)
        if updates:
            self._update_offset = max(update.update_id for update in updates) + 1

        handled = 0
        for update in updates:
            if not _is_start_command(update.text):
                continue
            self._transport.send_message(
                bot_token=bot_token,
                chat_id=update.chat_id,
                text=format_start_message(),
                parse_mode=telegram.parse_mode,
            )
            handled += 1
        return handled

    def _get_updates(self, bot_token: str) -> tuple[TelegramCommandUpdate, ...]:
        payload = {"timeout": "0"}
        if self._update_offset is not None:
            payload["offset"] = str(self._update_offset)
        url = f"{self._config.telegram.base_url.rstrip('/')}/bot{bot_token}/getUpdates?{urlencode(payload)}"
        request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")

        try:
            with urlopen(request, timeout=self._config.telegram.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                raw_body = response.read().decode(charset)
        except HTTPError as exc:
            msg = f"Telegram HTTP error {exc.code} while fetching updates."
            raise TelegramAlertError(msg) from exc
        except URLError as exc:
            msg = f"Telegram request failed while fetching updates: {exc.reason}"
            raise TelegramAlertError(msg) from exc
        except TimeoutError as exc:
            msg = "Telegram request timed out while fetching updates."
            raise TelegramAlertError(msg) from exc

        try:
            decoded = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            msg = "Telegram returned invalid JSON."
            raise TelegramAlertError(msg) from exc
        if not isinstance(decoded, dict) or not decoded.get("ok", False):
            msg = "Telegram API rejected getUpdates request."
            raise TelegramAlertError(msg)

        raw_updates = decoded.get("result", [])
        if not isinstance(raw_updates, list):
            msg = "Telegram returned unsupported updates payload."
            raise TelegramAlertError(msg)
        return tuple(
            update
            for raw_update in raw_updates
            if (update := _parse_update(raw_update)) is not None
        )


def _is_start_command(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    command = stripped.split(maxsplit=1)[0].split("@", maxsplit=1)[0]
    return command == START_COMMAND


def _parse_update(raw_update: object) -> TelegramCommandUpdate | None:
    if not isinstance(raw_update, dict):
        return None
    update_id = raw_update.get("update_id")
    if not isinstance(update_id, int):
        return None
    message = raw_update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int | str):
        return None
    return TelegramCommandUpdate(update_id=update_id, chat_id=str(chat_id), text=text)
