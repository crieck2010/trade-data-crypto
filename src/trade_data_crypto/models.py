"""Core models for crypto market data.

Crypto trades 24/7, so there are no session gaps to handle -- but there
are exchange-specific symbol formats, spot vs. derivative markets, and
funding rates on perpetuals. Models are immutable, stdlib-only
dataclasses. ``CryptoBar`` mirrors the OHLCV shape of the equities and
futures engines (plus crypto-native fields) so downstream engines can
treat all three uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite


class Timeframe(Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class MarketType(Enum):
    SPOT = "spot"
    PERP = "perpetual"
    FUTURE = "future"


def ensure_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _nonneg(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative number, got {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class CryptoMarket:
    """One tradable market on an exchange, in canonical ``BASE/QUOTE`` form."""

    exchange: str
    base: str
    quote: str
    market_type: MarketType = MarketType.SPOT
    tick_size: float | None = None   # minimum price increment
    min_size: float | None = None    # minimum order size in base currency
    active: bool = True

    def __post_init__(self) -> None:
        for field in ("exchange", "base", "quote"):
            value = getattr(self, field).strip().upper()
            if not value:
                raise ValueError(f"{field} must be a non-empty string")
            object.__setattr__(self, field, value)

    @property
    def symbol(self) -> str:
        """Canonical pair: ``BTC/USD``."""
        return f"{self.base}/{self.quote}"

    def __str__(self) -> str:
        return f"{self.exchange}:{self.symbol}"


@dataclass(frozen=True, slots=True)
class CryptoBar:
    """One OHLCV bar for a canonical pair (``BTC/USD``).

    ``quote_volume`` (volume in quote currency) and ``trades`` are
    exchange-dependent; None when the venue doesn't publish them.
    """

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0  # base-currency volume
    quote_volume: float | None = None
    trades: int | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if "/" not in symbol:
            raise ValueError(f"symbol must be canonical BASE/QUOTE, got {self.symbol!r}")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        for name in ("open", "high", "low", "close"):
            _finite(name, getattr(self, name))
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                f"bar violates low <= open/close <= high: {self.low}, {self.open}, {self.close}, {self.high}"
            )
        _nonneg("volume", self.volume)
        object.__setattr__(self, "quote_volume", _nonneg("quote_volume", self.quote_volume))
        if self.trades is not None and (not isinstance(self.trades, int) or self.trades < 0):
            raise ValueError(f"trades must be a non-negative int, got {self.trades!r}")


@dataclass(frozen=True, slots=True)
class CryptoTicker:
    """Latest quote + 24h stats for a pair."""

    symbol: str
    timestamp: datetime
    last: float
    bid: float | None = None
    ask: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    base_volume_24h: float | None = None
    quote_volume_24h: float | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if "/" not in symbol:
            raise ValueError(f"symbol must be canonical BASE/QUOTE, got {self.symbol!r}")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        _finite("last", self.last)
        for name in ("bid", "ask", "high_24h", "low_24h"):
            value = getattr(self, name)
            if value is not None:
                _finite(name, value)
        object.__setattr__(self, "base_volume_24h", _nonneg("base_volume_24h", self.base_volume_24h))
        object.__setattr__(self, "quote_volume_24h", _nonneg("quote_volume_24h", self.quote_volume_24h))

    @property
    def spread_bps(self) -> float | None:
        """Bid/ask spread in basis points, None when bid/ask missing."""
        if self.bid is None or self.ask is None or self.last == 0:
            return None
        return (self.ask - self.bid) / self.last * 10_000


@dataclass(frozen=True, slots=True)
class FundingRate:
    """One funding-rate observation for a perpetual contract.

    ``rate`` is the decimal funding paid per ``interval_hours``
    (positive = longs pay shorts).
    """

    symbol: str
    timestamp: datetime
    rate: float
    interval_hours: float = 8.0
    predicted_next: float | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if "/" not in symbol:
            raise ValueError(f"symbol must be canonical BASE/QUOTE, got {self.symbol!r}")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        _finite("rate", self.rate)
        if not isfinite(self.interval_hours) or self.interval_hours <= 0:
            raise ValueError(f"interval_hours must be positive, got {self.interval_hours!r}")
