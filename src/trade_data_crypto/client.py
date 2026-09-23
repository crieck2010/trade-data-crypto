"""High-level client: markets, bars, tickers, funding.

:class:`CryptoDataClient` is the primary entry point:

* :meth:`get_markets` -- listed markets, cached.
* :meth:`get_bars` -- OHLCV bars per canonical pair, cached, deduplicated.
* :meth:`get_ticker` -- latest quote + 24h stats (never cached).
* :meth:`get_funding_rates` -- perpetual funding history (pass-through;
  provider-dependent).
* :meth:`stream_bars` -- chunked iteration for long histories.

For interop: ``CryptoBar`` shares the OHLCV shape of the equities
(``Bar``) and futures (``FuturesBar``) engines, so ``trade-backtest``
and ``trade-strategies`` can consume all three uniformly. ``FundingRate``
feeds ``trade-risk`` carry accounting for perp positions.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

from .cache import DiskCache
from .exceptions import MarketNotFoundError
from .models import CryptoBar, CryptoMarket, CryptoTicker, FundingRate, MarketType, Timeframe
from .providers.base import CryptoDataProvider
from .symbols import canonical


class CryptoDataClient:
    """Fetch and cache crypto market data."""

    def __init__(
        self,
        provider: CryptoDataProvider,
        cache: DiskCache | None = None,
    ) -> None:
        self.provider = provider
        self.cache = cache if cache is not None else DiskCache()

    # -- markets ------------------------------------------------------------
    def get_markets(
        self,
        quote: str | None = None,
        market_type: MarketType | None = None,
        *,
        use_cache: bool = True,
    ) -> list[CryptoMarket]:
        if use_cache and self.cache is not None:
            hit = self.cache.get_markets(self.provider.name, quote)
            if hit is not None:
                return self._filter_markets(hit, market_type)
        markets = self.provider.get_markets(quote=quote, market_type=market_type)
        if use_cache and self.cache is not None:
            self.cache.put_markets(self.provider.name, quote, markets)
        return markets

    @staticmethod
    def _filter_markets(
        markets: list[CryptoMarket], market_type: MarketType | None
    ) -> list[CryptoMarket]:
        if market_type is None:
            return markets
        return [m for m in markets if m.market_type is market_type]

    def require_market(self, symbol: str) -> CryptoMarket:
        """Return the market for a pair or raise :class:`MarketNotFoundError`."""
        pair = canonical(symbol)
        for market in self.get_markets():
            if market.symbol == pair:
                return market
        raise MarketNotFoundError(f"no market listed for {pair}")

    # -- bars -----------------------------------------------------------------
    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        use_cache: bool = True,
    ) -> list[CryptoBar]:
        """Bars for a canonical pair over ``[start, end)``."""
        pair = canonical(symbol)
        if use_cache and self.cache is not None:
            hit = self.cache.get_bars(self.provider.name, pair, timeframe, start, end)
            if hit is not None:
                return hit
        bars = self._dedup(self.provider.get_bars(pair, timeframe, start, end))
        if use_cache and self.cache is not None:
            self.cache.put_bars(self.provider.name, pair, timeframe, start, end, bars)
        return bars

    @staticmethod
    def _dedup(bars: list[CryptoBar]) -> list[CryptoBar]:
        seen: dict = {}
        for bar in bars:
            seen[bar.timestamp] = bar
        return [seen[k] for k in sorted(seen)]

    def stream_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        chunk_days: int = 90,
        use_cache: bool = True,
    ) -> Iterator[CryptoBar]:
        """Yield bars in date chunks (bounded memory for long histories)."""
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            yield from self.get_bars(symbol, timeframe, cursor, chunk_end, use_cache=use_cache)
            cursor = chunk_end

    # -- ticker & funding (real-time; never cached) -----------------------------
    def get_ticker(self, symbol: str) -> CryptoTicker:
        return self.provider.get_ticker(canonical(symbol))

    def get_funding_rates(
        self, symbol: str, start: date, end: date
    ) -> list[FundingRate]:
        return self.provider.get_funding_rates(canonical(symbol), start, end)
