from collections.abc import Mapping
from typing import Any

import pytest

from crypto_flow_bot_v2.binance.client import (
    FUNDING_RATE_PATH,
    KLINES_PATH,
    LIQUIDATION_ORDERS_PATH,
    LONG_SHORT_RATIO_PATH,
    OPEN_INTEREST_PATH,
    TAKER_BUY_SELL_VOLUME_PATH,
    BinanceDataError,
    BinanceFuturesClient,
    QueryValue,
)


class FakeTransport:
    def __init__(self, payloads: Mapping[str, object]) -> None:
        self.payloads = dict(payloads)
        self.calls: list[tuple[str, dict[str, QueryValue]]] = []

    def get_json(self, path: str, params: Mapping[str, QueryValue]) -> dict[str, Any] | list[Any]:
        self.calls.append((path, dict(params)))
        payload = self.payloads[path]
        if isinstance(payload, dict | list):
            return payload
        raise TypeError("Fake payload must be dict or list.")


def test_get_klines_parses_candlesticks() -> None:
    transport = FakeTransport(
        {
            KLINES_PATH: [
                [
                    1_704_067_200_000,
                    "100.0",
                    "110.0",
                    "95.0",
                    "105.0",
                    "10.5",
                    1_704_068_099_999,
                    "1075.0",
                    42,
                    "6.0",
                    "615.0",
                    "0",
                ]
            ]
        }
    )
    client = BinanceFuturesClient(transport=transport)

    klines = client.get_klines("btcusdt", "15m", limit=1)

    assert len(klines) == 1
    assert klines[0].symbol == "BTCUSDT"
    assert klines[0].interval == "15m"
    assert klines[0].close == 105.0
    assert klines[0].trade_count == 42
    assert transport.calls == [(KLINES_PATH, {"symbol": "BTCUSDT", "interval": "15m", "limit": 1})]


def test_get_open_interest_parses_response() -> None:
    transport = FakeTransport(
        {
            OPEN_INTEREST_PATH: {
                "openInterest": "10659.509",
                "symbol": "BTCUSDT",
                "time": 1589437530011,
            }
        }
    )
    client = BinanceFuturesClient(transport=transport)

    result = client.get_open_interest("BTCUSDT")

    assert result.symbol == "BTCUSDT"
    assert result.open_interest == 10659.509
    assert result.timestamp.year == 2020


def test_get_funding_rates_parses_response() -> None:
    transport = FakeTransport(
        {
            FUNDING_RATE_PATH: [
                {
                    "symbol": "BTCUSDT",
                    "fundingRate": "0.00010000",
                    "fundingTime": 1570636800000,
                    "markPrice": "34287.54619963",
                }
            ]
        }
    )
    client = BinanceFuturesClient(transport=transport)

    rates = client.get_funding_rates("BTCUSDT", limit=1)

    assert rates[0].funding_rate == 0.0001
    assert rates[0].mark_price == 34287.54619963


def test_get_long_short_ratio_parses_response() -> None:
    transport = FakeTransport(
        {
            LONG_SHORT_RATIO_PATH: [
                {
                    "symbol": "BTCUSDT",
                    "longShortRatio": "1.9559",
                    "longAccount": "0.6617",
                    "shortAccount": "0.3382",
                    "timestamp": "1583139900000",
                }
            ]
        }
    )
    client = BinanceFuturesClient(transport=transport)

    points = client.get_long_short_ratio("BTCUSDT", period="15m", limit=1)

    assert points[0].long_short_ratio == 1.9559
    assert points[0].long_account == 0.6617
    assert points[0].short_account == 0.3382


def test_get_taker_buy_sell_volume_parses_response() -> None:
    transport = FakeTransport(
        {
            TAKER_BUY_SELL_VOLUME_PATH: [
                {
                    "buySellRatio": "1.5586",
                    "buyVol": "387.3300",
                    "sellVol": "248.5030",
                    "timestamp": "1585614900000",
                }
            ]
        }
    )
    client = BinanceFuturesClient(transport=transport)

    points = client.get_taker_buy_sell_volume("BTCUSDT", period="15m", limit=1)

    assert points[0].symbol == "BTCUSDT"
    assert points[0].buy_sell_ratio == 1.5586
    assert points[0].buy_volume == 387.33
    assert points[0].sell_volume == 248.503


def test_get_liquidation_orders_parses_response() -> None:
    transport = FakeTransport(
        {
            LIQUIDATION_ORDERS_PATH: [
                {
                    "symbol": "BTCUSDT",
                    "side": "SELL",
                    "price": "27500.0",
                    "avgPrice": "27490.0",
                    "origQty": "0.25",
                    "executedQty": "0.25",
                    "status": "FILLED",
                    "time": 1704067200000,
                }
            ]
        }
    )
    client = BinanceFuturesClient(transport=transport)

    orders = client.get_liquidation_orders("BTCUSDT", limit=1)

    assert orders[0].symbol == "BTCUSDT"
    assert orders[0].side == "SELL"
    assert orders[0].average_price == 27490.0
    assert orders[0].executed_quantity == 0.25


def test_rejects_invalid_limit_before_transport_call() -> None:
    transport = FakeTransport({KLINES_PATH: []})
    client = BinanceFuturesClient(transport=transport)

    with pytest.raises(ValueError, match="limit"):
        client.get_klines("BTCUSDT", "15m", limit=0)

    assert transport.calls == []


def test_raises_data_error_on_unexpected_payload_shape() -> None:
    transport = FakeTransport({KLINES_PATH: {"unexpected": "mapping"}})
    client = BinanceFuturesClient(transport=transport)

    with pytest.raises(BinanceDataError, match="list payload"):
        client.get_klines("BTCUSDT", "15m", limit=1)
