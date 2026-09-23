"""Provider interface for crypto market data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..exceptions import ProviderError
from ..models import CryptoBar, CryptoMarket, CryptoTicker, FundingRate, MarketType, Timeframe


class CryptoDataProvider(ABC):
    """Abstract crypto data source. Symbols are canonical ``BASE/QUOTE``."""

    #: Human-readable source name, used in cache keys and logs.
    name: str = "base"

    #: Expected data delay in minutes (None = unknown).
    delay_minutes: int | None = None

    @abstractmethod
    def get_markets(
        self,
        quote: str | None = None,
        market_type: MarketType | None = None,
    ) -> list[CryptoMarket]:
        """Listed markets, optionally filtered by quote currency and type."""
        raise NotImplementedError

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[CryptoBar]:
        """Bars for a canonical pair over ``[start, end)``."""
        raise NotImplementedError

    def get_ticker(self, symbol: str) -> CryptoTicker:
        """Latest quote + 24h stats. Default: derive from recent bars."""
        raise ProviderError(f"{self.name} does not provide tickers")

    def get_funding_rates(
        self, symbol: str, start: date, end: date
    ) -> list[FundingRate]:
        """Funding-rate history for a perpetual. Default: unsupported."""
        raise ProviderError(f"{self.name} does not provide funding rates")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(name={self.name!r})"
