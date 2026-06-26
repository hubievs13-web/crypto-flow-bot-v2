from datetime import UTC, datetime

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.models import MarketRegime, MarketSnapshot, SignalDecision
from crypto_flow_bot_v2.models import SignalDirection, SignalType
from crypto_flow_bot_v2.position_manager import PositionEvent, PositionEventType
from crypto_flow_bot_v2.telegram import TelegramAlertResult, TelegramAlertStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeSnapshotBuilder:
    def __init__(self, snapshots: dict[str, MarketSnapshot]) -> None:
        self.snapshots = snapshots

    def build(self, symbol: str) -> MarketSnapshot:
        return self.snapshots[symbol]


class FakeSignalEngine:
    def __init__(self, decisions: dict[str, SignalDecision]) -> None:
        self.decisions = decisions

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        return self.decisions[snapshot.symbol]


class FailingSignalEngine:
    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        raise RuntimeError("new layer failed")


class FakePositionManager:
    def __init__(self) -> None:
        self.open_calls: list[SignalDecision] = []

    def active_positions(self) -> tuple[object, ...]:
        return ()

    def update_price(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        invalidation_reason: str | None = None,
    ) -> PositionEvent:
        return PositionEvent(
            event_type=PositionEventType.IGNORED,
            symbol=symbol,
            timestamp=timestamp,
            message="no active position for symbol",
        )

    def open_from_decision(self, decision: SignalDecision) -> PositionEvent:
        self.open_calls.append(decision)
        if decision.signal_type is SignalType.NO_TRADE:
            return PositionEvent(
                event_type=PositionEventType.IGNORED,
                symbol=decision.symbol,
                timestamp=decision.timestamp,
                message="decision ignored",
            )
        return PositionEvent(
            event_type=PositionEventType.OPENED,
            symbol=decision.symbol,
            timestamp=decision.timestamp,
            message="virtual position opened",
        )


class FakeTelegramAlerts:
    def __init__(self) -> None:
        self.signal_calls: list[SignalDecision] = []
        self.position_event_calls: list[PositionEvent] = []

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        self.signal_calls.append(decision)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        self.position_event_calls.append(event)
        return TelegramAlertResult(status=TelegramAlertStatus.SENT, message="sent")


def test_governor_enabled_sends_only_best_ranked_signals() -> None:
    config = _config(governor_enabled=True, max_signals_per_scan=2)
    position_manager = FakePositionManager()
    alerts = FakeTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(_snapshots(config.symbols)),
        signal_engine=FakeSignalEngine(
            {
                "BTCUSDT": _trade_decision("BTCUSDT", 74),
                "ETHUSDT": _trade_decision("ETHUSDT", 80),
                "SOLUSDT": _trade_decision("SOLUSDT", 78),
            }
        ),
        position_manager=position_manager,
        telegram_alerts=alerts,
    )

    report = runner.run_once()

    assert report.positions_opened == 2
    assert report.telegram_alerts_sent == 4
    assert report.telegram_alerts_skipped == 1
    assert [decision.symbol for decision in alerts.signal_calls] == ["ETHUSDT", "SOLUSDT"]
    assert all("governor: passed" in " | ".join(call.reasons) for call in alerts.signal_calls)


def test_governor_disabled_keeps_old_send_flow() -> None:
    config = _config(governor_enabled=False, max_signals_per_scan=1)
    alerts = FakeTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(_snapshots(config.symbols)),
        signal_engine=FakeSignalEngine(
            {
                "BTCUSDT": _trade_decision("BTCUSDT", 74),
                "ETHUSDT": _trade_decision("ETHUSDT", 80),
            }
        ),
        position_manager=FakePositionManager(),
        telegram_alerts=alerts,
    )

    report = runner.run_once()

    assert report.positions_opened == 2
    assert [decision.symbol for decision in alerts.signal_calls] == ["BTCUSDT", "ETHUSDT"]


def test_live_runner_does_not_crash_when_signal_layer_fails() -> None:
    config = _config(governor_enabled=True, max_signals_per_scan=2)
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder(_snapshots(("BTCUSDT",))),
        signal_engine=FailingSignalEngine(),
        position_manager=FakePositionManager(),
        telegram_alerts=FakeTelegramAlerts(),
    )

    report = runner.run_once()

    assert report.symbol_errors == 1
    assert report.positions_opened == 0


def _snapshots(symbols: tuple[str, ...]) -> dict[str, MarketSnapshot]:
    return {symbol: _snapshot(symbol) for symbol in symbols}


def _snapshot(symbol: str) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        timestamp=NOW,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=100.0,
        regime=MarketRegime.TREND_UP,
        metrics={
            "entry_return_pct": 1.0,
            "context_return_pct": 2.0,
            "macro_return_pct": 3.0,
            "entry_atr_pct": 1.0,
        },
    )


def _trade_decision(symbol: str, confidence: int) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=confidence,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence", "risk/reward=1.67"),
    )


def _config(governor_enabled: bool, max_signals_per_scan: int) -> BotConfig:
    raw = {
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
        "binance": {
            "base_url": "https://fapi.binance.com",
            "timeout_seconds": 10.0,
            "kline_limit": 300,
            "derivatives_data_limit": 100,
        },
        "telegram": {"enabled": True, "bot_token_env": "A", "chat_id_env": "B"},
        "logging": {"level": "INFO", "jsonl_path": "logs/events.jsonl"},
        "risk": {
            "min_risk_reward": 1.5,
            "atr_stop_multiplier": 1.5,
            "atr_tp_multipliers": [1.5, 2.5, 4.0],
            "trailing_atr_multiplier": 1.0,
            "max_position_minutes": 240,
            "cooldown_minutes": 60,
        },
        "rfa_engine": {
            "min_signal_confidence": 70,
            "watch_confidence": 60,
            "strong_signal_confidence": 85,
            "require_context_alignment": True,
            "require_macro_alignment": True,
        },
        "signal_governor": {
            "enabled": governor_enabled,
            "max_signals_per_scan": max_signals_per_scan,
            "max_signals_per_hour": 4,
            "per_symbol_cooldown_minutes": 90,
            "same_direction_cluster_limit": 3,
            "ranking": {
                "primary": "final_score",
                "secondary": "risk_reward",
                "tertiary": "volume_confirmation",
            },
        },
    }
    return parse_config(raw)
