from datetime import UTC, datetime, timedelta

from crypto_flow_bot_v2.binance.models import Candlestick, OpenInterest
from crypto_flow_bot_v2.snapshot_builder import _build_metrics

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_entry_return_pct_uses_latest_entry_bar_not_full_kline_history() -> None:
    metrics = _build_metrics(
        entry_bars=(
            _bar(100.0, 101.0, 99.0, 100.0, 0, "15m"),
            _bar(100.0, 201.0, 99.0, 200.0, 15, "15m"),
            _bar(200.0, 212.0, 198.0, 210.0, 30, "15m"),
        ),
        context_bars=(
            _bar(100.0, 101.0, 99.0, 100.0, 0, "1h"),
            _bar(100.0, 111.0, 99.0, 110.0, 60, "1h"),
        ),
        macro_bars=(
            _bar(100.0, 101.0, 99.0, 100.0, 0, "4h"),
            _bar(100.0, 121.0, 99.0, 120.0, 240, "4h"),
        ),
        open_interest=OpenInterest(symbol="BTCUSDT", timestamp=NOW, open_interest=12_500.0),
        funding_rates=(),
        long_short_points=(),
        taker_points=(),
        liquidation_orders=(),
    )

    assert metrics["entry_return_pct"] == 5.0
    assert metrics["context_return_pct"] == 10.0
    assert metrics["macro_return_pct"] == 20.0


def _bar(
    open_price: float,
    high: float,
    low: float,
    close: float,
    offset_minutes: int,
    interval: str,
) -> Candlestick:
    open_time = NOW + timedelta(minutes=offset_minutes)
    return Candlestick(
        symbol="BTCUSDT",
        interval=interval,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
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
