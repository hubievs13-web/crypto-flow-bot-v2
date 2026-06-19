"""MarketSnapshot builder for normalized RFA engine inputs.

This module prepares market state only. It does not calculate trade signals, confidence scores,
entries, exits, Telegram alerts, or real exchange actions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

from crypto_flow_bot_v2.binance.models import (
    Candlestick,
    FundingRate,
    LiquidationOrder,
    LongShortRatioPoint,
    OpenInterest,
    TakerBuySellVolumePoint,
)
from crypto_flow_bot_v2.config import BotConfig
from crypto_flow_bot_v2.models import MarketRegime, MarketSnapshot


T = TypeVar("T")


class SnapshotBuildError(RuntimeError):
    """Raised when a complete MarketSnapshot cannot be built from market data."""


class MarketDataClient(Protocol):
    """Read-only market-data client required by the snapshot builder."""

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[Candlestick, ...]:
        """Fetch kline/candlestick bars."""

    def get_open_interest(self, symbol: str) -> OpenInterest:
        """Fetch present open interest."""

    def get_funding_rates(
        self,
        symbol: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[FundingRate, ...]:
        """Fetch funding-rate history."""

    def get_long_short_ratio(
        self,
        symbol: str,
        period: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[LongShortRatioPoint, ...]:
        """Fetch global long/short account ratio points."""

    def get_taker_buy_sell_volume(
        self,
        symbol: str,
        period: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[TakerBuySellVolumePoint, ...]:
        """Fetch taker buy/sell volume points."""

    def get_liquidation_orders(
        self,
        symbol: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[LiquidationOrder, ...]:
        """Fetch public forced liquidation orders."""


class MarketSnapshotBuilder:
    """Build normalized MarketSnapshot objects from read-only market data."""

    def __init__(self, data_client: MarketDataClient, config: BotConfig) -> None:
        self._data_client = data_client
        self._config = config

    def build(self, symbol: str) -> MarketSnapshot:
        """Build one normalized snapshot for a symbol."""

        normalized_symbol = _normalize_symbol(symbol)
        entry_bars = self._data_client.get_klines(
            normalized_symbol,
            self._config.timeframes.entry,
            limit=self._config.binance.kline_limit,
        )
        context_bars = self._data_client.get_klines(
            normalized_symbol,
            self._config.timeframes.context,
            limit=self._config.binance.kline_limit,
        )
        macro_bars = self._data_client.get_klines(
            normalized_symbol,
            self._config.timeframes.macro,
            limit=self._config.binance.kline_limit,
        )

        _require_minimum_bars(entry_bars, "entry klines")
        _require_minimum_bars(context_bars, "context klines")
        _require_minimum_bars(macro_bars, "macro klines")

        derivatives_limit = self._config.binance.derivatives_data_limit
        open_interest = self._data_client.get_open_interest(normalized_symbol)
        funding_rates = self._data_client.get_funding_rates(
            normalized_symbol,
            limit=derivatives_limit,
        )
        long_short_points = self._data_client.get_long_short_ratio(
            normalized_symbol,
            period=self._config.timeframes.entry,
            limit=derivatives_limit,
        )
        taker_points = self._data_client.get_taker_buy_sell_volume(
            normalized_symbol,
            period=self._config.timeframes.entry,
            limit=derivatives_limit,
        )
        liquidation_orders = self._data_client.get_liquidation_orders(
            normalized_symbol,
            limit=derivatives_limit,
        )

        metrics = _build_metrics(
            entry_bars=entry_bars,
            context_bars=context_bars,
            macro_bars=macro_bars,
            open_interest=open_interest,
            funding_rates=funding_rates,
            long_short_points=long_short_points,
            taker_points=taker_points,
            liquidation_orders=liquidation_orders,
        )
        latest_entry = entry_bars[-1]
        return MarketSnapshot(
            symbol=normalized_symbol,
            timestamp=latest_entry.close_time,
            entry_timeframe=self._config.timeframes.entry,
            context_timeframe=self._config.timeframes.context,
            macro_timeframe=self._config.timeframes.macro,
            price=latest_entry.close,
            regime=_classify_regime(metrics),
            metrics=metrics,
        )

    def build_many(self, symbols: Sequence[str] | None = None) -> tuple[MarketSnapshot, ...]:
        """Build snapshots for explicit symbols or all configured symbols."""

        selected_symbols = self._config.symbols if symbols is None else tuple(symbols)
        return tuple(self.build(symbol) for symbol in selected_symbols)


def _build_metrics(
    entry_bars: tuple[Candlestick, ...],
    context_bars: tuple[Candlestick, ...],
    macro_bars: tuple[Candlestick, ...],
    open_interest: OpenInterest,
    funding_rates: tuple[FundingRate, ...],
    long_short_points: tuple[LongShortRatioPoint, ...],
    taker_points: tuple[TakerBuySellVolumePoint, ...],
    liquidation_orders: tuple[LiquidationOrder, ...],
) -> dict[str, float | int | str | bool]:
    latest_entry = entry_bars[-1]
    latest_context = context_bars[-1]
    latest_macro = macro_bars[-1]
    latest_funding = _last_or_none(funding_rates)
    latest_long_short = _last_or_none(long_short_points)
    latest_taker = _last_or_none(taker_points)
    liquidation_metrics = _liquidation_metrics(liquidation_orders)
    entry_atr = _average_true_range(entry_bars)

    metrics: dict[str, float | int | str | bool] = {
        "entry_close": latest_entry.close,
        "context_close": latest_context.close,
        "macro_close": latest_macro.close,
        "entry_volume": latest_entry.volume,
        "entry_quote_volume": latest_entry.quote_volume,
        "entry_trade_count": latest_entry.trade_count,
        "entry_return_pct": _percentage_change(entry_bars[0].close, latest_entry.close),
        "context_return_pct": _percentage_change(context_bars[0].close, latest_context.close),
        "macro_return_pct": _percentage_change(macro_bars[0].close, latest_macro.close),
        "entry_atr": entry_atr,
        "entry_atr_pct": _safe_ratio(entry_atr, latest_entry.close) * 100,
        "entry_taker_buy_quote_volume": latest_entry.taker_buy_quote_volume,
        "entry_taker_buy_quote_ratio": _safe_ratio(
            latest_entry.taker_buy_quote_volume,
            latest_entry.quote_volume,
        ),
        "open_interest": open_interest.open_interest,
    }

    if latest_funding is not None:
        metrics["funding_rate"] = latest_funding.funding_rate
        metrics["funding_mark_price"] = latest_funding.mark_price
    if latest_long_short is not None:
        metrics["long_short_ratio"] = latest_long_short.long_short_ratio
        metrics["long_account"] = latest_long_short.long_account
        metrics["short_account"] = latest_long_short.short_account
    if latest_taker is not None:
        metrics["taker_buy_sell_ratio"] = latest_taker.buy_sell_ratio
        metrics["taker_buy_volume"] = latest_taker.buy_volume
        metrics["taker_sell_volume"] = latest_taker.sell_volume

    metrics.update(liquidation_metrics)
    return metrics


def _classify_regime(metrics: dict[str, float | int | str | bool]) -> MarketRegime:
    entry_return_pct = _metric_float(metrics, "entry_return_pct")
    context_return_pct = _metric_float(metrics, "context_return_pct")
    macro_return_pct = _metric_float(metrics, "macro_return_pct")
    entry_atr_pct = _metric_float(metrics, "entry_atr_pct")

    if entry_atr_pct >= 4.0:
        return MarketRegime.HIGH_VOLATILITY
    if abs(entry_return_pct) <= 0.25 and entry_atr_pct <= 0.5:
        return MarketRegime.SQUEEZE_SETUP
    if context_return_pct > 0 and macro_return_pct >= 0:
        return MarketRegime.TREND_UP
    if context_return_pct < 0 and macro_return_pct <= 0:
        return MarketRegime.TREND_DOWN
    if context_return_pct * macro_return_pct < 0:
        return MarketRegime.EXHAUSTION
    return MarketRegime.RANGE


def _liquidation_metrics(
    liquidation_orders: tuple[LiquidationOrder, ...],
) -> dict[str, float | int | str | bool]:
    buy_notional = 0.0
    sell_notional = 0.0
    buy_count = 0
    sell_count = 0

    for order in liquidation_orders:
        notional = order.average_price * order.executed_quantity
        if order.side == "BUY":
            buy_notional += notional
            buy_count += 1
        elif order.side == "SELL":
            sell_notional += notional
            sell_count += 1

    return {
        "liquidation_count": len(liquidation_orders),
        "liquidation_buy_count": buy_count,
        "liquidation_sell_count": sell_count,
        "liquidation_buy_notional": buy_notional,
        "liquidation_sell_notional": sell_notional,
        "liquidation_total_notional": buy_notional + sell_notional,
    }


def _average_true_range(bars: tuple[Candlestick, ...]) -> float:
    true_ranges = []
    previous_close = bars[0].close
    for bar in bars[1:]:
        true_ranges.append(
            max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
        )
        previous_close = bar.close
    return sum(true_ranges) / len(true_ranges)


def _percentage_change(start: float, end: float) -> float:
    return _safe_ratio(end - start, start) * 100


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _metric_float(metrics: dict[str, float | int | str | bool], key: str) -> float:
    value = metrics[key]
    if not isinstance(value, int | float):
        msg = f"Metric '{key}' must be numeric."
        raise SnapshotBuildError(msg)
    return float(value)


def _last_or_none(values: tuple[T, ...]) -> T | None:
    if not values:
        return None
    return values[-1]


def _require_minimum_bars(bars: tuple[Candlestick, ...], name: str) -> None:
    if len(bars) < 2:
        msg = f"{name} must contain at least two bars."
        raise SnapshotBuildError(msg)


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        msg = "symbol must be a non-empty string."
        raise ValueError(msg)
    return symbol.strip().upper()
