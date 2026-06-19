"""Public Binance USDⓈ-M Futures market-data client.

The client is read-only. It does not sign requests and cannot place, modify, or cancel orders.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crypto_flow_bot_v2.binance.models import (
    Candlestick,
    FundingRate,
    LiquidationOrder,
    LongShortRatioPoint,
    OpenInterest,
    TakerBuySellVolumePoint,
    datetime_from_millis,
)
from crypto_flow_bot_v2.config import BinanceDataConfig

JsonValue = dict[str, Any] | list[Any]
QueryValue = str | int | float

KLINES_PATH = "/fapi/v1/klines"
OPEN_INTEREST_PATH = "/fapi/v1/openInterest"
FUNDING_RATE_PATH = "/fapi/v1/fundingRate"
LONG_SHORT_RATIO_PATH = "/futures/data/globalLongShortAccountRatio"
TAKER_BUY_SELL_VOLUME_PATH = "/futures/data/takerlongshortRatio"
LIQUIDATION_ORDERS_PATH = "/fapi/v1/allForceOrders"


class BinanceDataError(RuntimeError):
    """Raised when Binance market data cannot be fetched or parsed."""


class HttpTransport(Protocol):
    """Minimal transport protocol used by the Binance data client."""

    def get_json(self, path: str, params: Mapping[str, QueryValue]) -> JsonValue:
        """Return decoded JSON for a GET request."""


class UrlLibTransport:
    """Small stdlib HTTP transport for public Binance data endpoints."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: BinanceDataConfig) -> UrlLibTransport:
        """Build a transport from application config."""

        return cls(base_url=config.base_url, timeout_seconds=config.timeout_seconds)

    def get_json(self, path: str, params: Mapping[str, QueryValue]) -> JsonValue:
        """Fetch and decode JSON from Binance."""

        query_string = urlencode(params)
        url = f"{self._base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        request = Request(url, headers={"User-Agent": "crypto-flow-bot-v2/0.1.0"})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                raw_body = response.read().decode(charset)
        except HTTPError as exc:
            msg = f"Binance HTTP error {exc.code} for {path}."
            raise BinanceDataError(msg) from exc
        except URLError as exc:
            msg = f"Binance request failed for {path}: {exc.reason}"
            raise BinanceDataError(msg) from exc
        except TimeoutError as exc:
            msg = f"Binance request timed out for {path}."
            raise BinanceDataError(msg) from exc

        try:
            decoded = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            msg = f"Binance returned invalid JSON for {path}."
            raise BinanceDataError(msg) from exc

        if not isinstance(decoded, dict | list):
            msg = f"Binance returned unsupported JSON payload for {path}."
            raise BinanceDataError(msg)
        return decoded


class BinanceFuturesClient:
    """Read-only client for public Binance USDⓈ-M Futures market data."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    @classmethod
    def from_config(cls, config: BinanceDataConfig) -> BinanceFuturesClient:
        """Build the client from application config."""

        return cls(transport=UrlLibTransport.from_config(config))

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[Candlestick, ...]:
        """Fetch kline/candlestick bars for a symbol."""

        _validate_limit(limit, max_limit=1500, name="limit")
        params = _clean_params(
            {
                "symbol": _normalize_symbol(symbol),
                "interval": interval,
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            }
        )
        payload = self._transport.get_json(KLINES_PATH, params)
        rows = _expect_list(payload, KLINES_PATH)
        return tuple(
            _parse_candlestick(row, symbol=params["symbol"], interval=interval) for row in rows
        )

    def get_open_interest(self, symbol: str) -> OpenInterest:
        """Fetch present open interest for a symbol."""

        params = {"symbol": _normalize_symbol(symbol)}
        payload = self._transport.get_json(OPEN_INTEREST_PATH, params)
        data = _expect_mapping(payload, OPEN_INTEREST_PATH)
        return OpenInterest(
            symbol=str(data["symbol"]).upper(),
            timestamp=datetime_from_millis(data["time"]),
            open_interest=float(data["openInterest"]),
        )

    def get_funding_rates(
        self,
        symbol: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[FundingRate, ...]:
        """Fetch funding-rate history for a symbol."""

        _validate_limit(limit, max_limit=1000, name="limit")
        params = _clean_params(
            {
                "symbol": _normalize_symbol(symbol),
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            }
        )
        payload = self._transport.get_json(FUNDING_RATE_PATH, params)
        rows = _expect_list(payload, FUNDING_RATE_PATH)
        return tuple(_parse_funding_rate(row) for row in rows)

    def get_long_short_ratio(
        self,
        symbol: str,
        period: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[LongShortRatioPoint, ...]:
        """Fetch global long/short account ratio points."""

        _validate_limit(limit, max_limit=500, name="limit")
        params = _clean_params(
            {
                "symbol": _normalize_symbol(symbol),
                "period": period,
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            }
        )
        payload = self._transport.get_json(LONG_SHORT_RATIO_PATH, params)
        rows = _expect_list(payload, LONG_SHORT_RATIO_PATH)
        return tuple(_parse_long_short_ratio(row, fallback_symbol=params["symbol"]) for row in rows)

    def get_taker_buy_sell_volume(
        self,
        symbol: str,
        period: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[TakerBuySellVolumePoint, ...]:
        """Fetch taker buy/sell volume points."""

        _validate_limit(limit, max_limit=500, name="limit")
        params = _clean_params(
            {
                "symbol": _normalize_symbol(symbol),
                "period": period,
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            }
        )
        payload = self._transport.get_json(TAKER_BUY_SELL_VOLUME_PATH, params)
        rows = _expect_list(payload, TAKER_BUY_SELL_VOLUME_PATH)
        return tuple(_parse_taker_buy_sell(row, fallback_symbol=params["symbol"]) for row in rows)

    def get_liquidation_orders(
        self,
        symbol: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[LiquidationOrder, ...]:
        """Fetch public forced liquidation orders for a symbol."""

        _validate_limit(limit, max_limit=1000, name="limit")
        params = _clean_params(
            {
                "symbol": _normalize_symbol(symbol),
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            }
        )
        payload = self._transport.get_json(LIQUIDATION_ORDERS_PATH, params)
        rows = _expect_list(payload, LIQUIDATION_ORDERS_PATH)
        return tuple(_parse_liquidation_order(row) for row in rows)


def _parse_candlestick(row: Any, symbol: str, interval: str) -> Candlestick:
    if not isinstance(row, list) or len(row) < 11:
        msg = "Binance kline row must be a list with at least 11 values."
        raise BinanceDataError(msg)
    return Candlestick(
        symbol=symbol,
        interval=interval,
        open_time=datetime_from_millis(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=datetime_from_millis(row[6]),
        quote_volume=float(row[7]),
        trade_count=int(row[8]),
        taker_buy_base_volume=float(row[9]),
        taker_buy_quote_volume=float(row[10]),
    )


def _parse_funding_rate(row: Any) -> FundingRate:
    data = _expect_mapping(row, FUNDING_RATE_PATH)
    return FundingRate(
        symbol=str(data["symbol"]).upper(),
        funding_time=datetime_from_millis(data["fundingTime"]),
        funding_rate=float(data["fundingRate"]),
        mark_price=float(data["markPrice"]),
    )


def _parse_long_short_ratio(row: Any, fallback_symbol: str) -> LongShortRatioPoint:
    data = _expect_mapping(row, LONG_SHORT_RATIO_PATH)
    return LongShortRatioPoint(
        symbol=str(data.get("symbol", fallback_symbol)).upper(),
        timestamp=datetime_from_millis(data["timestamp"]),
        long_short_ratio=float(data["longShortRatio"]),
        long_account=float(data["longAccount"]),
        short_account=float(data["shortAccount"]),
    )


def _parse_taker_buy_sell(row: Any, fallback_symbol: str) -> TakerBuySellVolumePoint:
    data = _expect_mapping(row, TAKER_BUY_SELL_VOLUME_PATH)
    return TakerBuySellVolumePoint(
        symbol=str(data.get("symbol", fallback_symbol)).upper(),
        timestamp=datetime_from_millis(data["timestamp"]),
        buy_sell_ratio=float(data["buySellRatio"]),
        buy_volume=float(data["buyVol"]),
        sell_volume=float(data["sellVol"]),
    )


def _parse_liquidation_order(row: Any) -> LiquidationOrder:
    data = _expect_mapping(row, LIQUIDATION_ORDERS_PATH)
    return LiquidationOrder(
        symbol=str(data["symbol"]).upper(),
        timestamp=datetime_from_millis(data["time"]),
        side=str(data["side"]).upper(),
        price=float(data["price"]),
        average_price=float(data.get("avgPrice", data["price"])),
        original_quantity=float(data["origQty"]),
        executed_quantity=float(data["executedQty"]),
        status=str(data["status"]).upper(),
    )


def _expect_list(payload: JsonValue, endpoint: str) -> list[Any]:
    if not isinstance(payload, list):
        msg = f"Expected Binance list payload from {endpoint}."
        raise BinanceDataError(msg)
    return payload


def _expect_mapping(payload: Any, endpoint: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        msg = f"Expected Binance mapping payload from {endpoint}."
        raise BinanceDataError(msg)
    return payload


def _clean_params(params: Mapping[str, QueryValue | None]) -> dict[str, QueryValue]:
    return {key: value for key, value in params.items() if value is not None}


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        msg = "symbol must be a non-empty string."
        raise ValueError(msg)
    return symbol.strip().upper()


def _validate_limit(limit: int, max_limit: int, name: str) -> None:
    if not isinstance(limit, int):
        msg = f"{name} must be an integer."
        raise ValueError(msg)
    if not 1 <= limit <= max_limit:
        msg = f"{name} must be between 1 and {max_limit}."
        raise ValueError(msg)
