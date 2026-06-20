"""Telegram alert formatting and delivery.

This module sends Telegram messages only. It never places, modifies, or closes exchange orders.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crypto_flow_bot_v2.config import BotConfig, TelegramConfig
from crypto_flow_bot_v2.models import SignalDecision, SignalDirection, SignalType, VirtualPosition
from crypto_flow_bot_v2.position_manager import PositionEvent, PositionEventType
from crypto_flow_bot_v2.start_message import format_start_message

USER_AGENT = "crypto-flow-bot-v2/0.1.0"


class TelegramAlertError(RuntimeError):
    """Raised when a Telegram alert cannot be delivered."""


class TelegramAlertStatus(StrEnum):
    """Telegram alert delivery result categories."""

    SENT = "SENT"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class TelegramSendResult:
    """Low-level Telegram send result."""

    ok: bool
    message_id: int | None = None


@dataclass(frozen=True, slots=True)
class TelegramAlertResult:
    """High-level alert result emitted by TelegramAlertService."""

    status: TelegramAlertStatus
    message: str
    send_result: TelegramSendResult | None = None


class TelegramTransport(Protocol):
    """Minimal transport for Telegram Bot API messages."""

    def send_message(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        parse_mode: str,
    ) -> TelegramSendResult:
        """Send one Telegram message."""


class UrlLibTelegramTransport:
    """Small stdlib transport for Telegram Bot API sendMessage."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: TelegramConfig) -> UrlLibTelegramTransport:
        """Build the transport from Telegram config."""

        return cls(base_url=config.base_url, timeout_seconds=config.timeout_seconds)

    def send_message(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        parse_mode: str,
    ) -> TelegramSendResult:
        """Send one Telegram message using Telegram Bot API."""

        if not bot_token.strip():
            msg = "Telegram bot token cannot be empty."
            raise TelegramAlertError(msg)
        if not chat_id.strip():
            msg = "Telegram chat id cannot be empty."
            raise TelegramAlertError(msg)

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }
        url = f"{self._base_url}/bot{bot_token}/sendMessage"
        request = Request(
            url,
            data=urlencode(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                raw_body = response.read().decode(charset)
        except HTTPError as exc:
            msg = f"Telegram HTTP error {exc.code} while sending alert."
            raise TelegramAlertError(msg) from exc
        except URLError as exc:
            msg = f"Telegram request failed while sending alert: {exc.reason}"
            raise TelegramAlertError(msg) from exc
        except TimeoutError as exc:
            msg = "Telegram request timed out while sending alert."
            raise TelegramAlertError(msg) from exc

        try:
            decoded = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            msg = "Telegram returned invalid JSON."
            raise TelegramAlertError(msg) from exc
        if not isinstance(decoded, dict):
            msg = "Telegram returned unsupported JSON payload."
            raise TelegramAlertError(msg)
        if not decoded.get("ok", False):
            msg = "Telegram API rejected alert message."
            raise TelegramAlertError(msg)

        result = decoded.get("result", {})
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return TelegramSendResult(
            ok=True,
            message_id=message_id if isinstance(message_id, int) else None,
        )


class TelegramAlertService:
    """Format and send Telegram alerts for RFA decisions and virtual position events."""

    def __init__(self, config: BotConfig, transport: TelegramTransport | None = None) -> None:
        self._config = config
        self._transport = transport or UrlLibTelegramTransport.from_config(config.telegram)

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        """Send a Telegram alert for a fully alertable RFA signal decision."""

        if not _is_alertable_signal(decision, self._config):
            return TelegramAlertResult(
                status=TelegramAlertStatus.SKIPPED,
                message="signal decision is not alertable",
            )
        return self._send(format_signal_decision(decision, self._config))

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        """Send a Telegram alert for opened or closed virtual position events."""

        if event.event_type not in {PositionEventType.OPENED, PositionEventType.CLOSED}:
            return TelegramAlertResult(
                status=TelegramAlertStatus.SKIPPED,
                message=f"position event {event.event_type.value} is not alertable",
            )
        if event.position is None:
            return TelegramAlertResult(
                status=TelegramAlertStatus.SKIPPED,
                message="position event has no position payload",
            )
        return self._send(format_position_event(event))

    def send_start_message(self) -> TelegramAlertResult:
        """Send the Russian welcome message for Telegram /start."""

        return self._send(format_start_message())

    def _send(self, text: str) -> TelegramAlertResult:
        telegram = self._config.telegram
        if not telegram.enabled:
            return TelegramAlertResult(
                status=TelegramAlertStatus.SKIPPED,
                message="telegram alerts are disabled",
            )

        bot_token = os.getenv(telegram.bot_token_env, "").strip()
        chat_ids = _parse_chat_ids(os.getenv(telegram.chat_id_env, ""))
        if not bot_token or not chat_ids:
            return TelegramAlertResult(
                status=TelegramAlertStatus.SKIPPED,
                message="telegram credentials are not configured in environment",
            )

        send_results: list[TelegramSendResult] = []
        for chat_id in chat_ids:
            send_results.append(
                self._transport.send_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    text=text,
                    parse_mode=telegram.parse_mode,
                )
            )
        return TelegramAlertResult(
            status=TelegramAlertStatus.SENT,
            message="telegram alert sent",
            send_result=send_results[-1],
        )


def _parse_chat_ids(raw_chat_ids: str) -> tuple[str, ...]:
    return tuple(
        chat_id
        for chat_id in (part.strip() for part in raw_chat_ids.split(","))
        if chat_id
    )


def format_signal_decision(decision: SignalDecision, config: BotConfig) -> str:
    """Format a full RFA signal decision for Telegram."""

    signal_strength = (
        "STRONG" if decision.confidence >= config.rfa_engine.strong_signal_confidence else "NORMAL"
    )
    lines = [
        f"<b>RFA SIGNAL — {signal_strength}</b>",
        f"Symbol: <b>{escape(decision.symbol)}</b>",
        f"Type: <code>{escape(decision.signal_type.value)}</code>",
        f"Direction: <code>{escape(decision.direction.value)}</code>",
        f"Confidence: <b>{decision.confidence}/100</b>",
        f"Timestamp: <code>{escape(decision.timestamp.isoformat())}</code>",
        "",
        f"Entry: <code>{_format_optional_price(decision.entry_price)}</code>",
        f"Stop loss: <code>{_format_optional_price(decision.stop_loss)}</code>",
        f"Take profit: <code>{_format_targets(decision.take_profit_levels)}</code>",
    ]

    risk_reward = _risk_reward(decision)
    if risk_reward is not None:
        lines.append(f"Risk/reward: <code>{risk_reward:.2f}</code>")
    if decision.reasons:
        lines.extend(("", "<b>Reasons</b>"))
        lines.extend(f"• {escape(reason)}" for reason in decision.reasons[:8])
    return "\n".join(lines)


def format_position_event(event: PositionEvent) -> str:
    """Format a virtual position lifecycle event for Telegram."""

    if event.position is None:
        return _format_generic_position_event(event)
    position = event.position
    if event.event_type is PositionEventType.OPENED:
        return _format_position_opened(position, event)
    if event.event_type is PositionEventType.CLOSED:
        return _format_position_closed(position, event)
    return _format_generic_position_event(event)


def _format_position_opened(position: VirtualPosition, event: PositionEvent) -> str:
    source = (
        position.source_signal_type.value
        if position.source_signal_type is not None
        else "UNKNOWN"
    )
    return "\n".join(
        [
            "<b>VIRTUAL POSITION OPENED</b>",
            f"Symbol: <b>{escape(position.symbol)}</b>",
            f"Direction: <code>{escape(position.direction.value)}</code>",
            f"Source: <code>{escape(source)}</code>",
            f"Confidence: <b>{position.confidence}/100</b>",
            f"Timestamp: <code>{escape(event.timestamp.isoformat())}</code>",
            "",
            f"Entry: <code>{_format_price(position.entry_price)}</code>",
            f"Stop loss: <code>{_format_price(position.exit_plan.stop_loss)}</code>",
            f"Take profit: <code>{_format_targets(position.exit_plan.take_profit_levels)}</code>",
            "Trailing stop: "
            f"<code>{_format_optional_price(position.exit_plan.trailing_stop)}</code>",
            f"Time stop: <code>{position.exit_plan.time_stop_minutes or 'none'} min</code>",
        ]
    )


def _format_position_closed(position: VirtualPosition, event: PositionEvent) -> str:
    exit_reason = event.exit_reason.value if event.exit_reason is not None else "UNKNOWN"
    pnl = "n/a" if event.pnl_pct is None else f"{event.pnl_pct:.2f}%"
    lines = [
        "<b>VIRTUAL POSITION CLOSED</b>",
        f"Symbol: <b>{escape(position.symbol)}</b>",
        f"Direction: <code>{escape(position.direction.value)}</code>",
        f"Exit reason: <code>{escape(exit_reason)}</code>",
        f"Timestamp: <code>{escape(event.timestamp.isoformat())}</code>",
        "",
        f"Entry: <code>{_format_price(position.entry_price)}</code>",
        f"Exit: <code>{_format_optional_price(event.exit_price)}</code>",
        f"PnL: <b>{escape(pnl)}</b>",
    ]
    if event.message:
        lines.append(f"Message: {escape(event.message)}")
    return "\n".join(lines)


def _format_generic_position_event(event: PositionEvent) -> str:
    lines = [
        f"<b>VIRTUAL POSITION {escape(event.event_type.value)}</b>",
        f"Symbol: <b>{escape(event.symbol)}</b>",
        f"Timestamp: <code>{escape(event.timestamp.isoformat())}</code>",
    ]
    if event.message:
        lines.append(f"Message: {escape(event.message)}")
    return "\n".join(lines)


def _is_alertable_signal(decision: SignalDecision, config: BotConfig) -> bool:
    if decision.signal_type is SignalType.NO_TRADE or decision.direction is SignalDirection.NONE:
        return False
    if decision.blocked_reason is not None:
        return False
    if decision.confidence < config.rfa_engine.min_signal_confidence:
        return False
    if _missing_trade_plan(decision):
        return False

    risk_reward = _risk_reward(decision)
    return risk_reward is not None and risk_reward >= config.risk.min_risk_reward


def _missing_trade_plan(decision: SignalDecision) -> bool:
    return (
        decision.entry_price is None
        or decision.stop_loss is None
        or not decision.take_profit_levels
    )


def _risk_reward(decision: SignalDecision) -> float | None:
    if _missing_trade_plan(decision):
        return None
    if decision.direction is SignalDirection.LONG:
        risk = decision.entry_price - decision.stop_loss
        reward = max(decision.take_profit_levels) - decision.entry_price
    elif decision.direction is SignalDirection.SHORT:
        risk = decision.stop_loss - decision.entry_price
        reward = decision.entry_price - min(decision.take_profit_levels)
    else:
        return None

    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _format_targets(levels: tuple[float, ...]) -> str:
    if not levels:
        return "none"
    return " / ".join(_format_price(level) for level in levels)


def _format_optional_price(value: float | None) -> str:
    if value is None:
        return "none"
    return _format_price(value)


def _format_price(value: float) -> str:
    return f"{value:.8g}"
