from crypto_flow_bot_v2 import main as app_main


def test_live_runner_interval_prefers_primary_env(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_RUNNER_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("LIVE_CYCLE_INTERVAL_SECONDS", "900")

    assert app_main._live_runner_interval_seconds() == 60


def test_live_runner_interval_supports_legacy_env(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_RUNNER_INTERVAL_SECONDS", raising=False)
    monkeypatch.setenv("LIVE_CYCLE_INTERVAL_SECONDS", "120")

    assert app_main._live_runner_interval_seconds() == 120
