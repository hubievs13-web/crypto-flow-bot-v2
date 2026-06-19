"""Domain models for the RFA-based signal bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MarketRegime(StrEnum):
    """Market state classification used by the future RFA Engine."""

    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    SQUEEZE_SETUP = "SQUEEZE_SETUP"
    EXHAUSTION = "EXHAUSTION"


class SignalType(StrEnum):
    """Supported signal classes."""

    LONG_CONTINUATION = "LONG_CONTINUATION"
    SHORT_CONTINUATION = "SHORT_CONTINUATION"
    LONG_REVERSAL = "LONG_REVERSAL"
    SHORT_REVERSAL = "SHORT_REVERSAL"
    NO_TRADE = "NO_TRADE"


class SignalDirection(StrEnum):
    """Directional intent for a signal decision."""

    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Normalized market state consumed by the future signal engine."""

    symbol: str
    timestamp: datetime
    entry_timeframe: str
    context_timeframe: str
    macro_timeframe: str
    price: float
    regime: MarketRegime
    metrics: dict[str, float | int | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_positive_number(self.price, "price")


@dataclass(frozen=True, slots=True)
class ExitPlan:
    """Adaptive exit plan placeholder.

    Later PRs will calculate these values from ATR, volatility, structure, and invalidation rules.
    """

    stop_loss: float
    take_profit_levels: tuple[float, ...]
    trailing_stop: float | None = None
    time_stop_minutes: int | None = None
    invalidation_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_number(self.stop_loss, "stop_loss")
        if not self.take_profit_levels:
            msg = "take_profit_levels must contain at least one target."
            raise ValueError(msg)
        for index, level in enumerate(self.take_profit_levels, start=1):
            _validate_positive_number(level, f"take_profit_levels[{index}]")
        if self.trailing_stop is not None:
            _validate_positive_number(self.trailing_stop, "trailing_stop")
        if self.time_stop_minutes is not None and self.time_stop_minutes <= 0:
            msg = "time_stop_minutes must be positive when provided."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SignalDecision:
    """Output of the future RFA Engine."""

    symbol: str
    timestamp: datetime
    signal_type: SignalType
    direction: SignalDirection
    confidence: int
    entry_price: float | None
    stop_loss: float | None
    take_profit_levels: tuple[float, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        if not 0 <= self.confidence <= 100:
            msg = "confidence must be between 0 and 100."
            raise ValueError(msg)
        if self.signal_type is SignalType.NO_TRADE and self.direction is not SignalDirection.NONE:
            msg = "NO_TRADE decisions must use SignalDirection.NONE."
            raise ValueError(msg)
        if self.signal_type is not SignalType.NO_TRADE and self.direction is SignalDirection.NONE:
            msg = "Trade decisions must use LONG or SHORT direction."
            raise ValueError(msg)
        if self.entry_price is not None:
            _validate_positive_number(self.entry_price, "entry_price")
        if self.stop_loss is not None:
            _validate_positive_number(self.stop_loss, "stop_loss")
        for index, level in enumerate(self.take_profit_levels, start=1):
            _validate_positive_number(level, f"take_profit_levels[{index}]")


@dataclass(frozen=True, slots=True)
class VirtualPosition:
    """Virtual position tracked by the bot without real exchange execution."""

    symbol: str
    direction: SignalDirection
    entry_price: float
    opened_at: datetime
    exit_plan: ExitPlan
    confidence: int
    active: bool = True
    source_signal_type: SignalType | None = None

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        if self.direction is SignalDirection.NONE:
            msg = "VirtualPosition direction must be LONG or SHORT."
            raise ValueError(msg)
        _validate_positive_number(self.entry_price, "entry_price")
        if not 0 <= self.confidence <= 100:
            msg = "confidence must be between 0 and 100."
            raise ValueError(msg)


def _validate_symbol(symbol: str) -> None:
    if not isinstance(symbol, str) or not symbol.strip():
        msg = "symbol must be a non-empty string."
        raise ValueError(msg)


def _validate_positive_number(value: float, name: str) -> None:
    if value <= 0:
        msg = f"{name} must be positive."
        raise ValueError(msg)
