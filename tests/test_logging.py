import json
import logging as std_logging
from pathlib import Path

from crypto_flow_bot_v2.config import LoggingConfig
from crypto_flow_bot_v2.logging import configure_logging, get_logger


def test_configure_logging_writes_jsonl_file(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "events.jsonl"
    root_logger = std_logging.getLogger()
    previous_level = root_logger.level

    try:
        configure_logging(LoggingConfig(level="INFO", jsonl_path=log_path))
        get_logger("crypto_flow_bot_v2.tests.logging").info(
            "jsonl smoke %s",
            "ok",
            extra={
                "event": "live_symbol_decision_trace",
                "live_symbol_decision_trace": {
                    "symbol": "BTCUSDT",
                    "telegram_sent": 1,
                    "telegram_skipped": 0,
                    "telegram_errors": 0,
                },
            },
        )
        for handler in root_logger.handlers:
            handler.flush()

        lines = log_path.read_text(encoding="utf-8").splitlines()
        payload = json.loads(lines[-1])

        assert payload["level"] == "INFO"
        assert payload["logger"] == "crypto_flow_bot_v2.tests.logging"
        assert payload["message"] == "jsonl smoke ok"
        assert payload["event"] == "live_symbol_decision_trace"
        assert payload["live_symbol_decision_trace"] == {
            "symbol": "BTCUSDT",
            "telegram_sent": 1,
            "telegram_skipped": 0,
            "telegram_errors": 0,
        }
    finally:
        for handler in list(root_logger.handlers):
            if getattr(handler, "_crypto_flow_bot_v2_jsonl_handler", False):
                root_logger.removeHandler(handler)
                handler.close()
        root_logger.setLevel(previous_level)
