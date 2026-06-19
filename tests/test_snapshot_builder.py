from datetime import UTC, datetime, timedelta

import pytest

from crypto_flow_bot_v2.binance.models import (
    Candlestick,
    FundingRate,
    LiquidationOrder,
    LongShortRatioPoint,
    OpenInterest,
    TakerBuySellVolumePoint,
)
from crypto_flow_bot_v2.config import BotConfig, parse_config
from crypto_flow_bot_v2.models import MarketRegime
from crypto_flow_bot_v2.snapshot_builder import MarketSnapshotBuilder, SnapshotBuildError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeMarketDataClient:
    def __init__(
        self,
        klines_by_interval: dict[str, tuple[Candlestick, ...]],
        open_interest: OpenInterest,
        funding_rates: tuple[FundingRate, ...],
        long_short_points: tuple[LongShortRatioPoint, ...],
        taker_points: tuple[TakerBuySellVolumePoint, ...],
        liquidation_orders: tuple[LiquidationOrder, ...],
    ) -> None:
        self.klines_by_interval = klines_by_interval
        self.open_interest = open_interest
        self.funding_rates = funding_rates
        self.long_short_points = long_short_points
        self.taker_points = taker_points
        self.liquidation_orders = liquidation_orders
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[Candlestick, ...]:
        self.calls.append(("get_klines", (symbol, interval, limit, start_time, end_time)))
        return self.klines_by_interval[interval]

    def get_open_interest(self, symbol: str) -> OpenInterest:
        self.calls.append(("get_open_interest", (symbol,)))
        return self.open_interest

    def get_funding_rates(
        self,
        symbol: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[FundingRate, ...]:
        self.calls.append(("get_funding_rates", (symbol, limit, start_time, end_time)))
        return self.funding_rates

    def get_long_short_ratio(
        self,
        symbol: str,
        period: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[LongShortRatioPoint, ...]:
        self.calls.append(("get_long_short_ratio", (symbol, period, limit, start_time, end_time)))
        return self.long_short_points

    def get_taker_buy_sell_volume(
        self,
        symbol: str,
        period: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[TakerBuySellVolumePoint, ...]:
        self.calls.append(
            ("get_taker_buy_sell_volume", (symbol, period, limit, start_time, end_time))
        )
        return self.taker_points

    def get_liquidation_orders(
        self,
        symbol: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[LiquidationOrder, ...]:
        self.calls.append(("get_liquidation_orders", (symbol, limit, start_time, end_time)))
        return self.liquidation_orders


def test_market_snapshot_builder_normalizes_multisource_data() -> None:
    config = _config()
    client = _fake_client()
    builder = MarketSnapshotBuilder(data_client=client, config=config)

    snapshot = builder.build("btcusdt")

    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.entry_timeframe == "15m"
    assert snapshot.context_timeframe == "1h"
    assert snapshot.macro_timeframe == "4h"
    assert snapshot.price == 106.0
    assert snapshot.timestamp == NOW + timedelta(minutes=45)
    assert snapshot.regime is MarketRegime.TREND_UP
    assert snapshot.metrics["open_interest"] == 12_500.0
    assert snapshot.metrics["funding_rate"] == 0.0002
    assert snapshot.metrics["long_short_ratio"] == 1.4
    assert snapshot.metrics["taker_buy_sell_ratio"] == 1.6
    assert snapshot.metrics["liquidation_count"] == 2
    assert snapshot.metrics["liquidation_buy_notional"] == 0.5 * 108.0
    assert snapshot.metrics["liquidation_sell_notional"] == 0.25 * 105.0
    assert client.calls == [
        ("get_klines", ("BTCUSDT", "15m", 300, None, None)),
        ("get_klines", ("BTCUSDT", "1h", 300, None, None)),
        ("get_klines", ("BTCUSDT", "4h", 300, None, None)),
        ("get_open_interest", ("BTCUSDT",)),
        ("get_funding_rates", ("BTCUSDT", 100, None, None)),
        ("get_long_short_ratio", ("BTCUSDT", "15m", 100, None, None)),
        ("get_taker_buy_sell_volume", ("BTCUSDT", "15m", 100, None, None)),
        ("get_liquidation_orders", ("BTCUSDT", 100, None, None)),
    ]


def test_market_snapshot_builder_build_many_uses_configured_symbols() -> None:
    builder = MarketSnapshotBuilder(data_client=_fake_client(), config=_config())

    snapshots = builder.build_many()

    assert tuple(snapshot.symbol for snapshot in snapshots) == ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def test_market_snapshot_builder_rejects_missing_entry_history() -> None:
    client = _fake_client()
    client.klines_by_interval["15m"] = (_bar(100.0, 101.0, 99.0, 100.0, 0, "15m"),)
    builder = MarketSnapshotBuilder(data_client=client, config=_config())

    with pytest.raises(SnapshotBuildError, match="entry klines"):
        builder.build("BTCUSDT")


def _fake_client() -> FakeMarketDataClient:
    return FakeMarketDataClient(
        klines_by_interval={
            "15m": (
                _bar(100.0, 101.0, 99.0, 100.0, 0, "15m"),
                _bar(100.0, 103.0, 100.0, 102.0, 15, "15m"),
                _bar(102.0, 106.5, 102.0, 106.0, 30, "15m"),
            ),
            "1h": (
                _bar(100.0, 102.0, 99.0, 100.0, 0, "1h"),
                _bar(100.0, 107.0, 99.0, 105.0, 60, "1h"),
                _bar(105.0, 111.0, 104.0, 110.0, 120, "1h"),
            ),
            "4h": (
                _bar(100.0, 103.0, 99.0, 100.0, 0, "4h"),
                _bar(100.0, 109.0, 99.0, 108.0, 240, "4h"),
                _bar(108.0, 116.0, 107.0, 115.0, 480, "4h"),
            ),
        },
        open_interest=OpenInterest(symbol="BTCUSDT", timestamp=NOW, open_interest=12_500.0),
        funding_rates=(
            FundingRate(
                symbol="BTCUSDT",
                funding_time=NOW,
                funding_rate=0.0002,
                mark_price=106.0,
            ),
        ),
        long_short_points=(
            LongShortRatioPoint(
                symbol="BTCUSDT",
                timestamp=NOW,
                long_short_ratio=1.4,
                long_account=0.58,
                short_account=0.42,
            ),
        ),
        taker_points=(
            TakerBuySellVolumePoint(
                symbol="BTCUSDT",
                timestamp=NOW,
                buy_sell_ratio=1.6,
                buy_volume=160.0,
                sell_volume=100.0,
            ),
        ),
        liquidation_orders=(
            LiquidationOrder(
                symbol="BTCUSDT",
                timestamp=NOW,
                side="BUY",
                price=108.0,
                average_price=108.0,
                original_quantity=0.5,
                executed_quantity=0.5,
                status="FILLED",
            ),
            LiquidationOrder(
                symbol="BTCUSDT",
                timestamp=NOW,
                side="SELL",
                price=105.0,
                average_price=105.0,
                original_quantity=0.25,
                executed_quantity=0.25,
                status="FILLED",
            ),
        ),
    )


def _bar(
    open_price: float,
    high: float,
    low: float,
    close: float,
    offset_minutes: int,
    interval: str,
) -> Candlestick:
    open_time = NOW + timedelta(minutes=offset_minutes)
    close_time = open_time + timedelta(minutes=15)
    return Candlestick(
        symbol="BTCUSDT",
        interval=interval,
        open_time=open_time,
        close_time=close_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=10.0,
        quote_volume=1_000.0,
        trade_count=100,
        taker_buy_base_volume=6.0,
        taker_buy_quote_volume=600.0,
    )


def _config() -> BotConfig:
    return parse_config(
        {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframes": {"entry": "15m", "context": "1h", "macro": "4h"},
            "binance": {
                "base_url": "https://fapi.binance.com",
                "timeout_seconds": 10.0,
                "kline_limit": 300,
                "derivatives_data_limit": 100,
            },
            "telegram": {"enabled": False, "bot_token_env": "A", "chat_id_env": "B"},
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
