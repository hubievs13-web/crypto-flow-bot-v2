"""Application logging setup."""

from __future__ import annotations

import logging as std_logging
from pathlib import Path

from crypto_flow_bot_v2.config import LoggingConfig

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(config: LoggingConfig) -> None:
    """Configure standard library logging for the application."""

    level = getattr(std_logging, config.level.upper(), std_logging.INFO)
    _ensure_parent_directory(config.jsonl_path)
    std_logging.basicConfig(level=level, format=LOG_FORMAT)


def get_logger(name: str) -> std_logging.Logger:
    """Return an application logger."""

    return std_logging.getLogger(name)


def _ensure_parent_directory(path: Path) -> None:
    parent = path.parent
    if str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)
