import json
import logging
from pathlib import Path

from crypto_flow_bot_v2.config import LoggingConfig
from crypto_flow_bot_v2.logging import configure_logging, get_logger


def test_configure_logging_writes_jsonl_file(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "logs" / "events.jsonl"

    configure_logging(LoggingConfig(level="INFO", jsonl_path=jsonl_path))
    get_logger("crypto_flow_bot_v2.tests").info("hello %s", "world")
    for handler in logging.getLogger().handlers:
        handler.flush()

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    assert payload["level"] == "INFO"
    assert payload["logger"] == "crypto_flow_bot_v2.tests"
    assert payload["message"] == "hello world"
