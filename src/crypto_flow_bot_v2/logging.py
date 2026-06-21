"""Application logging setup."""

from __future__ import annotations

import json
import logging as std_logging
from pathlib import Path
from typing import Any

from crypto_flow_bot_v2.config import LoggingConfig

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_JSONL_HANDLER_MARKER = "_crypto_flow_bot_v2_jsonl_handler"


class JsonLineFormatter(std_logging.Formatter):
    """Format standard-library log records as JSON Lines."""

    def format(self, record: std_logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(config: LoggingConfig) -> None:
    """Configure console and JSONL file logging for the application."""

    level = getattr(std_logging, config.level.upper(), std_logging.INFO)
    _ensure_parent_directory(config.jsonl_path)

    std_logging.basicConfig(level=level, format=LOG_FORMAT)
    root_logger = std_logging.getLogger()
    root_logger.setLevel(level)

    _remove_existing_jsonl_handlers(root_logger)
    jsonl_handler = std_logging.FileHandler(config.jsonl_path, encoding="utf-8")
    setattr(jsonl_handler, _JSONL_HANDLER_MARKER, True)
    jsonl_handler.setLevel(level)
    jsonl_handler.setFormatter(JsonLineFormatter())
    root_logger.addHandler(jsonl_handler)


def get_logger(name: str) -> std_logging.Logger:
    """Return an application logger."""

    return std_logging.getLogger(name)


def _remove_existing_jsonl_handlers(logger: std_logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _JSONL_HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def _ensure_parent_directory(path: Path) -> None:
    parent = path.parent
    if str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)
