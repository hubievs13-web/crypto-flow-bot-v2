"""Typed models returned by the Binance Futures data layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def datetime_from_millis(value: int | str) -> datetime:
    """Convert a Binance millisecond timestamp to an aware UTC datetime."""

    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class Candlestick:
    """USDⓈ-M Futures kline/candlestick data."""

    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_non_empty(self.interval, "interval")
        for field_name in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        ):
            _validate_non_negative(getattr(self, field_name), field_name)
        if self.high < self.low:
            msg = "high must be greater than or equal to low."
            raise ValueError(msg)
        if self.trade_count < 0:
            msg = "trade_count must be non-negative."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class OpenInterest:
    """Present open interest for a symbol."""

    symbol: str
    timestamp: datetime
    open_interest: float

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_non_negative(self.open_interest, "open_interest")


@dataclass(frozen=True, slots=True)
class FundingRate:
    """Historical funding-rate point."""

    symbol: str
    funding_time: datetime
    funding_rate: float
    mark_price: float

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_positive(self.mark_price, "mark_price")


@dataclass(frozen=True, slots=True)
class LongShortRatioPoint:
    """Global long/short account ratio point."""

    symbol: str
    timestamp: datetime
    long_short_ratio: float
    long_account: float
    short_account: float

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_non_negative(self.long_short_ratio, "long_short_ratio")
        _validate_non_negative(self.long_account, "long_account")
        _validate_non_negative(self.short_account, "short_account")


@dataclass(frozen=True, slots=True)
class TakerBuySellVolumePoint:
    """Taker buy/sell volume point."""

    symbol: str
    timestamp: datetime
    buy_sell_ratio: float
    buy_volume: float
    sell_volume: float

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_non_negative(self.buy_sell_ratio, "buy_sell_ratio")
        _validate_non_negative(self.buy_volume, "buy_volume")
        _validate_non_negative(self.sell_volume, "sell_volume")


@dataclass(frozen=True, slots=True)
class LiquidationOrder:
    """Forced liquidation order summary from the public market-data endpoint."""

    symbol: str
    timestamp: datetime
    side: str
    price: float
    average_price: float
    original_quantity: float
    executed_quantity: float
    status: str

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_non_empty(self.side, "side")
        _validate_non_empty(self.status, "status")
        _validate_non_negative(self.price, "price")
        _validate_non_negative(self.average_price, "average_price")
        _validate_non_negative(self.original_quantity, "original_quantity")
        _validate_non_negative(self.executed_quantity, "executed_quantity")


def _validate_symbol(symbol: str) -> None:
    _validate_non_empty(symbol, "symbol")


def _validate_non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-empty string."
        raise ValueError(msg)


def _validate_positive(value: float, name: str) -> None:
    if value <= 0:
        msg = f"{name} must be positive."
        raise ValueError(msg)


def _validate_non_negative(value: float, name: str) -> None:
    if value < 0:
        msg = f"{name} must be non-negative."
        raise ValueError(msg)
