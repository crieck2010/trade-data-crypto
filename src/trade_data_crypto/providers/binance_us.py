"""Crypto provider backed by Binance.US public REST (free, no key).

Endpoints used (all keyless)::

    GET https://api.binance.us/api/v3/exchangeInfo
    GET https://api.binance.us/api/v3/klines?symbol=BTCUSD&interval=5m&startTime=<ms>&endTime=<ms>&limit=1000
    GET https://api.binance.us/api/v3/ticker/24hr?symbol=BTCUSD

Kline rows come back as::

    [openTime, open, high, low, close, volume, closeTime,
     quoteAssetVolume, trades, takerBuyBaseVol, takerBuyQuoteVol, ignore]

max 1000 rows per request -- this provider pages automatically with
``startTime = lastCloseTime + 1``. Timestamps are bar-open milliseconds;
volume is in base currency; ``trades`` and ``quoteAssetVolume`` map to
the bar's trade count and quote volume. Taker-buy splits have no
``CryptoBar`` counterpart and are dropped.

Symbol mapping: Binance.US lists USD pairs (not USDT) for the majors, so
``BTC/USD`` -> ``BTCUSD``. See :func:`symbols.to_binanceus_symbol`.

Binance.US returns API errors as HTTP 4xx with a JSON body
``{"code": ..., "msg": ...}``; the provider maps code ``-1121``
(Invalid symbol) to ``MarketNotFoundError`` and HTTP 429/418 (rate
limit / IP auto-ban) to ``RateLimitError``. Kline weight scales with
``limit``, so the provider throttles politely (default 0.35 s).

HTTP is stdlib ``urllib`` only: no extra dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from ..exceptions import MarketNotFoundError, ProviderError, RateLimitError
from ..models import CryptoBar, CryptoMarket, CryptoTicker, MarketType, Timeframe
from ..symbols import canonical, to_binanceus_symbol
from .base import CryptoDataProvider

_BASE_URL = "https://api.binance.us"

_INTERVAL = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
}

_MAX_ROWS = 1000  # Binance.US klines page size


def _map_http_error(exc: urllib.error.HTTPError, what: str) -> Exception:
    """Map a Binance.US HTTP error to the engine's exception hierarchy.

    Factored out of ``_fetch`` so the mapping is unit-testable without
    HTTP.
    """
    if exc.code in (429, 418):
        return RateLimitError(f"Binance.US rate limit hit ({what})")
    try:
        body = exc.read().decode("utf-8")
        payload = json.loads(body)
    except Exception:  # noqa: BLE001 - body may not be JSON
        payload = {}
    code = payload.get("code")
    msg = payload.get("msg", "")
    if code == -1121:
        return MarketNotFoundError(f"Binance.US has no market for {what}: {msg}")
    return ProviderError(f"Binance.US HTTP {exc.code} for {what}: {msg or exc.reason}")


class BinanceUSPublicProvider(CryptoDataProvider):
    """Free spot market data from Binance.US public REST (no API key)."""

    name = "binance_us"
    delay_minutes = 0

    def __init__(self, min_interval: float = 0.35, max_retries: int = 3) -> None:
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
        request = urllib.request.Request(url, headers={"User-Agent": "trade-data-crypto/0.2.0"})
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                mapped = _map_http_error(exc, path)
                if isinstance(mapped, (RateLimitError, MarketNotFoundError)):
                    raise mapped from exc
                last = mapped
            except Exception as exc:  # noqa: BLE001 - network errors vary
                last = exc
            time.sleep(2**attempt)
        raise ProviderError(f"Binance.US request failed after {self.max_retries} attempts: {last}")

    @staticmethod
    def _filters(symbol_info: dict) -> tuple[float | None, float | None]:
        """(tick_size, min_size) from exchangeInfo filters, best-effort."""
        tick = min_qty = None
        for f in symbol_info.get("filters", []):
            ftype = f.get("filterType")
            try:
                if ftype == "PRICE_FILTER" and f.get("tickSize"):
                    tick = float(f["tickSize"])
                elif ftype == "LOT_SIZE" and f.get("minQty"):
                    min_qty = float(f["minQty"])
            except (TypeError, ValueError):
                continue
        return tick, min_qty

    # -- CryptoDataProvider -----------------------------------------------
    def get_markets(
        self,
        quote: str | None = None,
        market_type: MarketType | None = None,
    ) -> list[CryptoMarket]:
        if market_type is not None and market_type is not MarketType.SPOT:
            return []  # public API lists spot only
        data = self._fetch("/api/v3/exchangeInfo")
        markets: list[CryptoMarket] = []
        for s in data.get("symbols", []):
            try:
                if s.get("status") != "TRADING":
                    continue
                if "SPOT" not in (s.get("permissions") or []):
                    continue
                tick, min_qty = self._filters(s)
                market = CryptoMarket(
                    exchange="BINANCEUS",
                    base=str(s["baseAsset"]),
                    quote=str(s["quoteAsset"]),
                    market_type=MarketType.SPOT,
                    tick_size=tick,
                    min_size=min_qty,
                    active=True,
                )
            except (KeyError, ValueError, TypeError):
                continue
            markets.append(market)
        if quote is not None:
            wanted = quote.strip().upper()
            markets = [m for m in markets if m.quote == wanted]
        return sorted(markets, key=lambda m: m.symbol)

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[CryptoBar]:
        pair = canonical(symbol)
        venue_symbol = to_binanceus_symbol(pair)
        interval = _INTERVAL[timeframe]
        start_ms = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp() * 1000)
        stop_ms = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000)
        bars: list[CryptoBar] = []
        # Page in windows of <= 1000 klines; endTime is inclusive on the
        # wire, so the window is [cursor, stop_ms - 1].
        cursor = start_ms
        prev_cursor = -1
        while cursor < stop_ms and cursor > prev_cursor:
            prev_cursor = cursor
            rows = self._fetch(
                "/api/v3/klines",
                {
                    "symbol": venue_symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": stop_ms - 1,
                    "limit": _MAX_ROWS,
                },
            )
            if not rows:
                break
            for row in rows:
                try:
                    open_ms = int(row[0])
                    if not (cursor <= open_ms < stop_ms):
                        continue
                    stamp = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)
                    quote_vol = float(row[7])
                    bars.append(
                        CryptoBar(
                            symbol=pair,
                            timestamp=stamp,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[5]),
                            quote_volume=quote_vol if quote_vol else None,
                            trades=int(row[8]),
                        )
                    )
                except (IndexError, TypeError, ValueError):
                    continue  # defensive: skip malformed rows
            try:
                cursor = int(rows[-1][6]) + 1  # lastCloseTime + 1
            except (IndexError, TypeError, ValueError):
                break
            if len(rows) < _MAX_ROWS:
                break
        return sorted(bars, key=lambda b: b.timestamp)

    def get_ticker(self, symbol: str) -> CryptoTicker:
        pair = canonical(symbol)
        venue_symbol = to_binanceus_symbol(pair)
        data = self._fetch("/api/v3/ticker/24hr", {"symbol": venue_symbol})
        try:
            last = float(data["lastPrice"])
            bid = float(data["bidPrice"])
            ask = float(data["askPrice"])
            high = float(data.get("highPrice") or 0) or None
            low = float(data.get("lowPrice") or 0) or None
            base_vol = float(data.get("volume") or 0) or None
            quote_vol = float(data.get("quoteVolume") or 0) or None
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"bad ticker payload for {pair}: {exc}") from exc
        stamp = datetime.now(timezone.utc)
        return CryptoTicker(
            symbol=pair,
            timestamp=stamp,
            last=last,
            bid=bid,
            ask=ask,
            high_24h=high,
            low_24h=low,
            base_volume_24h=base_vol,
            quote_volume_24h=quote_vol,
        )
