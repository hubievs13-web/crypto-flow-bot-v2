from pathlib import Path

from crypto_flow_bot_v2.config import load_config


def test_project_config_uses_requested_lite_candidate_engine_settings() -> None:
    config = load_config(Path("config.yaml"))

    candidate_engine = config.candidate_engine
    assert candidate_engine.enabled is True
    assert candidate_engine.min_candidate_score == 0.60
    assert candidate_engine.signal_threshold == 0.70
    assert candidate_engine.candidate_ttl_minutes == 180
    assert candidate_engine.min_maturity_ticks == 2
    assert candidate_engine.max_maturity_bonus == 0.03
    assert candidate_engine.max_candidates_total == 100
    assert candidate_engine.max_candidates_per_symbol == 2
    assert candidate_engine.hard_filters_required is True

    assert config.rfa_engine.min_signal_confidence == 70
    assert config.rfa_engine.require_context_alignment is True
    assert config.rfa_engine.require_macro_alignment is True
