from datetime import UTC, datetime, timedelta

import pytest

from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.live_runner import LiveAlertRunner
from crypto_flow_bot_v2.models import MarketRegime, MarketSnapshot, SignalDecision
from crypto_flow_bot_v2.models import SignalDirection, SignalType
from crypto_flow_bot_v2.position_manager import (
    PositionEvent,
    PositionEventType,
    VirtualPositionManager,
)
from crypto_flow_bot_v2.telegram import (
    TelegramAlertResult,
    TelegramAlertStatus,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeSnapshotBuilder:
    def __init__(
        self,
        snapshots: dict[str, MarketSnapshot],
        failures: set[str] | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.failures = failures or set()
        self.calls: list[str] = []

    def build(self, symbol: str) -> MarketSnapshot:
        self.calls.append(symbol)
        if symbol in self.failures:
            raise RuntimeError(f"snapshot failed for {symbol}")
        return self.snapshots[symbol]


class FakeSignalEngine:
    def __init__(
        self,
        decisions: dict[str, SignalDecision],
        failures: set[str] | None = None,
    ) -> None:
        self.decisions = decisions
        self.failures = failures or set()
        self.calls: list[MarketSnapshot] = []

    def evaluate(self, snapshot: MarketSnapshot) -> SignalDecision:
        self.calls.append(snapshot)
        if snapshot.symbol in self.failures:
            raise RuntimeError(f"signal failed for {snapshot.symbol}")
        return self.decisions[snapshot.symbol]


class FakeTelegramAlerts:
    def __init__(self, status: TelegramAlertStatus = TelegramAlertStatus.SENT) -> None:
        self.status = status
        self.signal_calls: list[SignalDecision] = []
        self.position_event_calls: list[PositionEvent] = []

    def send_signal(self, decision: SignalDecision) -> TelegramAlertResult:
        self.signal_calls.append(decision)
        return TelegramAlertResult(status=self.status, message=self.status.value)

    def send_position_event(self, event: PositionEvent) -> TelegramAlertResult:
        self.position_event_calls.append(event)
        return TelegramAlertResult(status=self.status, message=self.status.value)


class FailingPositionManager:
    def __init__(
        self,
        config: BotConfig,
        fail_update: bool = False,
        fail_open: bool = False,
    ) -> None:
        self._manager = VirtualPositionManager(config)
        self.fail_update = fail_update
        self.fail_open = fail_open

    def active_positions(self):
        return self._manager.active_positions()

    def update_price(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        invalidation_reason: str | None = None,
    ) -> PositionEvent:
        if self.fail_update:
            raise RuntimeError(f"update failed for {symbol}")
        return self._manager.update_price(
            symbol=symbol,
            price=price,
            timestamp=timestamp,
            invalidation_reason=invalidation_reason,
        )

    def open_from_decision(self, decision: SignalDecision) -> PositionEvent:
        if self.fail_open:
            raise RuntimeError(f"open failed for {decision.symbol}")
        return self._manager.open_from_decision(decision)


def test_run_once_alerts_only_after_position_open() -> None:
    config = _config(symbols=("BTCUSDT",))
    builder = FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")})
    decision = _trade_decision("BTCUSDT")
    engine = FakeSignalEngine({"BTCUSDT": decision})
    alerts = FakeTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=VirtualPositionManager(config),
        telegram_alerts=alerts,
    )

    report = runner.run_once()

    assert report.snapshots_built == 1
    assert report.processing_errors == 0
    assert report.decisions_evaluated == 1
    assert report.positions_opened == 1
    assert report.telegram_alerts_sent == 2
    assert alerts.signal_calls == [decision]
    assert len(alerts.position_event_calls) == 1
    assert alerts.position_event_calls[0].event_type is PositionEventType.OPENED


def test_run_once_does_not_duplicate_signal_when_position_is_active() -> None:
    config = _config(symbols=("BTCUSDT",))
    builder = FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")})
    engine = FakeSignalEngine({"BTCUSDT": _trade_decision("BTCUSDT")})
    alerts = FakeTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=VirtualPositionManager(config),
        telegram_alerts=alerts,
    )

    first_report = runner.run_once()
    second_report = runner.run_once()

    assert first_report.positions_opened == 1
    assert second_report.positions_opened == 0
    assert second_report.telegram_alerts_sent == 0
    assert len(alerts.signal_calls) == 1
    assert len(alerts.position_event_calls) == 1


def test_run_once_alerts_position_close_before_new_signal_gate() -> None:
    config = _config(symbols=("BTCUSDT",))
    first_snapshot = _snapshot("BTCUSDT", price=100.0, timestamp=NOW)
    second_snapshot = _snapshot("BTCUSDT", price=105.0, timestamp=NOW + timedelta(minutes=15))
    builder = FakeSnapshotBuilder({"BTCUSDT": first_snapshot})
    engine = FakeSignalEngine({"BTCUSDT": _trade_decision("BTCUSDT")})
    alerts = FakeTelegramAlerts()
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=VirtualPositionManager(config),
        telegram_alerts=alerts,
    )

    open_report = runner.run_once()
    builder.snapshots["BTCUSDT"] = second_snapshot
    close_report = runner.run_once()

    assert open_report.positions_opened == 1
    assert close_report.positions_closed == 1
    assert close_report.positions_opened == 0
    assert close_report.telegram_alerts_sent == 1
    assert alerts.position_event_calls[-1].event_type is PositionEventType.CLOSED


def test_run_once_continues_when_one_symbol_snapshot_fails() -> None:
    config = _config(symbols=("BTCUSDT", "ETHUSDT"))
    builder = FakeSnapshotBuilder(
        {"BTCUSDT": _snapshot("BTCUSDT")},
        failures={"ETHUSDT"},
    )
    engine = FakeSignalEngine({"BTCUSDT": _trade_decision("BTCUSDT")})
    alerts = FakeTelegramAlerts(status=TelegramAlertStatus.SKIPPED)
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=VirtualPositionManager(config),
        telegram_alerts=alerts,
    )

    report = runner.run_once()

    assert report.snapshots_built == 1
    assert report.build_errors == 1
    assert report.processing_errors == 0
    assert report.decisions_evaluated == 1
    assert report.positions_opened == 1
    assert report.telegram_alerts_skipped == 2
    assert builder.calls == ["BTCUSDT", "ETHUSDT"]


def test_run_once_continues_when_signal_engine_fails() -> None:
    config = _config(symbols=("BTCUSDT", "ETHUSDT"))
    builder = FakeSnapshotBuilder(
        {
            "BTCUSDT": _snapshot("BTCUSDT"),
            "ETHUSDT": _snapshot("ETHUSDT"),
        }
    )
    engine = FakeSignalEngine(
        {"BTCUSDT": _trade_decision("BTCUSDT")},
        failures={"ETHUSDT"},
    )
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=VirtualPositionManager(config),
        telegram_alerts=FakeTelegramAlerts(status=TelegramAlertStatus.SKIPPED),
    )

    report = runner.run_once()

    assert report.snapshots_built == 2
    assert report.processing_errors == 1
    assert report.decisions_evaluated == 1
    assert report.positions_opened == 1


def test_run_once_continues_when_position_update_fails() -> None:
    config = _config(symbols=("BTCUSDT", "ETHUSDT"))
    builder = FakeSnapshotBuilder(
        {
            "BTCUSDT": _snapshot("BTCUSDT"),
            "ETHUSDT": _snapshot("ETHUSDT"),
        }
    )
    engine = FakeSignalEngine({"BTCUSDT": _trade_decision("BTCUSDT")})
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=FailingPositionManager(config, fail_update=True),
        telegram_alerts=FakeTelegramAlerts(),
    )

    report = runner.run_once()

    assert report.snapshots_built == 2
    assert report.processing_errors == 2
    assert report.decisions_evaluated == 0
    assert report.positions_opened == 0


def test_run_once_continues_when_position_open_fails() -> None:
    config = _config(symbols=("BTCUSDT", "ETHUSDT"))
    builder = FakeSnapshotBuilder(
        {
            "BTCUSDT": _snapshot("BTCUSDT"),
            "ETHUSDT": _snapshot("ETHUSDT"),
        }
    )
    engine = FakeSignalEngine(
        {
            "BTCUSDT": _trade_decision("BTCUSDT"),
            "ETHUSDT": _trade_decision("ETHUSDT"),
        }
    )
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=FailingPositionManager(config, fail_open=True),
        telegram_alerts=FakeTelegramAlerts(),
    )

    report = runner.run_once()

    assert report.snapshots_built == 2
    assert report.processing_errors == 2
    assert report.decisions_evaluated == 2
    assert report.positions_opened == 0


def test_run_sleeps_between_finite_cycles() -> None:
    config = _config(symbols=("BTCUSDT",))
    builder = FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")})
    engine = FakeSignalEngine({"BTCUSDT": _no_trade_decision("BTCUSDT")})
    alerts = FakeTelegramAlerts()
    sleep_calls: list[float] = []
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=builder,
        signal_engine=engine,
        position_manager=VirtualPositionManager(config),
        telegram_alerts=alerts,
        cycle_interval_seconds=30,
        sleeper=sleep_calls.append,
    )

    stats = runner.run(max_cycles=2)

    assert stats.cycles == 2
    assert stats.snapshots_built == 2
    assert stats.processing_errors == 0
    assert stats.decisions_evaluated == 2
    assert sleep_calls == [30]


def test_run_rejects_non_positive_max_cycles() -> None:
    config = _config(symbols=("BTCUSDT",))
    runner = LiveAlertRunner(
        config=config,
        snapshot_builder=FakeSnapshotBuilder({"BTCUSDT": _snapshot("BTCUSDT")}),
        signal_engine=FakeSignalEngine({"BTCUSDT": _no_trade_decision("BTCUSDT")}),
        position_manager=VirtualPositionManager(config),
        telegram_alerts=FakeTelegramAlerts(),
    )

    with pytest.raises(ValueError, match="max_cycles"):
        runner.run(max_cycles=0)


def _snapshot(symbol: str, price: float = 100.0, timestamp: datetime = NOW) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        timestamp=timestamp,
        entry_timeframe="15m",
        context_timeframe="1h",
        macro_timeframe="4h",
        price=price,
        regime=MarketRegime.TREND_UP,
        metrics={},
    )


def _trade_decision(symbol: str) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.LONG_CONTINUATION,
        direction=SignalDirection.LONG,
        confidence=80,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit_levels=(103.0, 105.0),
        reasons=("rfa confluence", "risk/reward=1.67"),
    )


def _no_trade_decision(symbol: str) -> SignalDecision:
    return SignalDecision(
        symbol=symbol,
        timestamp=NOW,
        signal_type=SignalType.NO_TRADE,
        direction=SignalDirection.NONE,
        confidence=50,
        entry_price=None,
        stop_loss=None,
        take_profit_levels=(),
        reasons=("not enough evidence",),
        blocked_reason="confidence_below_signal_minimum",
    )


def _config(symbols: tuple[str, ...]) -> BotConfig:
    return parse_config(
        {
            "symbols": list(symbols),
            "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
            "binance": {
                "base_url": "https://fapi.binance.com",
                "timeout_seconds": 10.0,
                "kline_limit": 300,
                "derivatives_data_limit": 100,
            },
            "telegram": {
                "enabled": True,
                "bot_token_env": "BOT_ENV",
                "chat_id_env": "CHAT_ENV",
                "base_url": "https://api.telegram.org",
                "timeout_seconds": 10.0,
                "parse_mode": "HTML",
            },
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
        }
    )
