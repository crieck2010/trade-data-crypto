"""Crypto provider backed by Coinbase's public REST API (free, no key).

Endpoints used (all keyless)::

    GET https://api.exchange.coinbase.com/products
    GET https://api.exchange.coinbase.com/products/{id}/candles
    GET https://api.exchange.coinbase.com/products/{id}/ticker

Candles come back as ``[time, low, high, open, close, volume]`` (note the
order), max 300 per request -- this provider pages automatically. Public
rate limit is ~10 req/s; the provider throttles to stay under it.

HTTP is stdlib ``urllib`` only: no extra dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from ..exceptions import MarketNotFoundError, ProviderError, RateLimitError
from ..models import CryptoBar, CryptoMarket, CryptoTicker, MarketType, Timeframe
from ..symbols import canonical, to_coinbase_id
from .base import CryptoDataProvider

_BASE_URL = "https://api.exchange.coinbase.com"

_GRANULARITY = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
    Timeframe.H4: 21600,
    Timeframe.D1: 86400,
}

_MAX_CANDLES = 300  # Coinbase page size


class CoinbasePublicProvider(CryptoDataProvider):
    """Free spot market data from Coinbase's public API (no API key)."""

    name = "coinbase"
    delay_minutes = 0

    def __init__(self, min_interval: float = 0.15, max_retries: int = 3) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_call = 0.0

    # -- internals ------------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _fetch(self, path: str, params: dict | None = None):
        """GET ``path``; returns decoded JSON. Split out for testability."""
        url = _BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": "trade-data-crypto/0.1.0"})
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise RateLimitError("Coinbase rate limit hit") from exc
                if exc.code == 404:
                    raise MarketNotFoundError(f"Coinbase has no market at {path}") from exc
                last = exc
            except Exception as exc:  # noqa: BLE001 - network errors vary
                last = exc
            time.sleep(2**attempt)
        raise ProviderError(f"Coinbase request failed after {self.max_retries} attempts: {last}")

    # -- CryptoDataProvider -----------------------------------------------
    def get_markets(
        self,
        quote: str | None = None,
        market_type: MarketType | None = None,
    ) -> list[CryptoMarket]:
        if market_type is not None and market_type is not MarketType.SPOT:
            return []  # public API lists spot only
        products = self._fetch("/products")
        markets: list[CryptoMarket] = []
        for p in products:
            try:
                market = CryptoMarket(
                    exchange="COINBASE",
                    base=p["base_currency"],
                    quote=p["quote_currency"],
                    market_type=MarketType.SPOT,
                    tick_size=float(p.get("quote_increment") or 0) or None,
                    min_size=float(p.get("base_min_size") or 0) or None,
                    active=p.get("status") == "online",
                )
            except (KeyError, ValueError, TypeError):
                continue
            markets.append(market)
        if quote is not None:
            markets = [m for m in markets if m.quote == quote.strip().upper()]
        return sorted(markets, key=lambda m: m.symbol)

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[CryptoBar]:
        pair = canonical(symbol)
        product_id = to_coinbase_id(pair)
        granularity = _GRANULARITY[timeframe]
        bars: list[CryptoBar] = []
        cursor = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        stop = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
        # Page in windows of <= 300 candles.
        while cursor < stop:
            window_end = min(cursor + timedelta(seconds=granularity * _MAX_CANDLES), stop)
            params = {
                "start": cursor.isoformat(),
                "end": window_end.isoformat(),
                "granularity": granularity,
            }
            for candle in self._fetch(f"/products/{product_id}/candles", params):
                ts, low, high, op, close, volume = candle
                stamp = datetime.fromtimestamp(ts, tz=timezone.utc)
                if not (cursor <= stamp < window_end):
                    continue
                bars.append(
                    CryptoBar(
                        symbol=pair, timestamp=stamp,
                        open=op, high=high, low=low, close=close, volume=volume,
                    )
                )
            cursor = window_end
        return sorted(bars, key=lambda b: b.timestamp)

    def get_ticker(self, symbol: str) -> CryptoTicker:
        pair = canonical(symbol)
        product_id = to_coinbase_id(pair)
        data = self._fetch(f"/products/{product_id}/ticker")
        try:
            last = float(data["price"])
            bid = float(data["bid"]) if data.get("bid") else None
            ask = float(data["ask"]) if data.get("ask") else None
            volume = float(data["volume"]) if data.get("volume") else None
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"bad ticker payload for {pair}: {exc}") from exc
        stamp = datetime.now(timezone.utc)
        return CryptoTicker(
            symbol=pair, timestamp=stamp, last=last, bid=bid, ask=ask,
            base_volume_24h=volume,
        )
