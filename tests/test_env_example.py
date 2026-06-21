from pathlib import Path


def test_env_example_enables_live_runner_by_default() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "LIVE_RUNNER_ENABLED=true" in content
    assert "TELEGRAM_BOT_TOKEN=" in content
    assert "TELEGRAM_CHAT_ID=" in content
    assert "Without TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID" in content
    assert "Telegram messages will not be sent" in content
