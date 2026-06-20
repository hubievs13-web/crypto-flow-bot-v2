"""Application logging setup."""

from __future__ import annotations

import json
import logging as std_logging
from datetime import UTC, datetime
from pathlib import Path

from crypto_flow_bot_v2.config import LoggingConfig

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class JsonLineFormatter(std_logging.Formatter):
    """Format LogRecord objects as one JSON object per line."""

    def format(self, record: std_logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(config: LoggingConfig) -> None:
    """Configure console logging and the configured JSONL log file."""

    level = getattr(std_logging, config.level.upper(), std_logging.INFO)
    _ensure_parent_directory(config.jsonl_path)

    console_handler = std_logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(std_logging.Formatter(LOG_FORMAT))

    jsonl_handler = std_logging.FileHandler(config.jsonl_path, encoding="utf-8")
    jsonl_handler.setLevel(level)
    jsonl_handler.setFormatter(JsonLineFormatter())

    root_logger = std_logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(jsonl_handler)


def get_logger(name: str) -> std_logging.Logger:
    """Return an application logger."""

    return std_logging.getLogger(name)


def _ensure_parent_directory(path: Path) -> None:
    parent = path.parent
    if str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)
