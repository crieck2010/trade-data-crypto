"""Crypto provider backed by Kraken's public REST API (free, no key).

Endpoints used (all keyless)::

    GET https://api.kraken.com/0/public/AssetPairs
    GET https://api.kraken.com/0/public/OHLC?pair=<krakenpair>&interval=<minutes>&since=<unixtime>
    GET https://api.kraken.com/0/public/Ticker?pair=<krakenpair>

OHLC rows come back as
``[time, open, high, low, close, vwap, volume, count]`` (note the order),
max 720 candles per request -- this provider pages automatically with
``since=<last>`` and dedupes the repeated boundary candle. Timestamps are
bar-open unixtime; volume is in base currency; ``count`` maps to the
bar's trade count. Row ``vwap`` has no ``CryptoBar`` counterpart and is
dropped.

Pair mapping: Kraken's legacy asset codes rename BTC to XBT (``XXBT`` in
pair keys) and USD to ZUSD, so ``BTC/USD`` -> ``XXBTZUSD`` and
``ETH/USD`` -> ``XETHZUSD``. See :func:`symbols.to_kraken_pair`. Exotic
pairs should be resolved via ``get_markets`` (AssetPairs) rather than
guessed.

Kraken returns most API errors as HTTP 200 with a non-empty ``error``
array; the provider maps ``EAPI:Rate limit exceeded`` to
``RateLimitError``, ``EQuery:Unknown asset pair`` to
``MarketNotFoundError``, and anything else to ``ProviderError``.

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
from ..symbols import canonical, to_kraken_pair
from .base import CryptoDataProvider

_BASE_URL = "https://api.kraken.com"

_INTERVAL_MINUTES = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
}

_MAX_CANDLES = 720  # Kraken OHLC page size


def _normalize_asset(code: str) -> str:
    """Kraken asset code (``XXBT``) -> canonical base (``BTC``).

    Best-effort: strips one leading X/Z from long codes (Kraken's
    legacy convention) and maps XBT -> BTC. Exotic codes pass through
    as-is; resolve them via ``get_markets`` if the result looks wrong.
    """
    code = code.strip().upper()
    if len(code) > 3 and code[0] in "XZ" and code[1:].isalpha():
        code = code[1:]
    return {"XBT": "BTC"}.get(code, code)


def _checked(data: dict, what: str) -> dict:
    """Raise the mapped error for a Kraken ``error`` array; else ``result``.

    Factored out of ``_fetch`` so the mapping is unit-testable without
    HTTP.
    """
    errors = data.get("error") or []
    if errors:
        joined = "; ".join(str(e) for e in errors)
        if any("Rate limit" in str(e) for e in errors):
            raise RateLimitError(f"Kraken rate limit hit ({what}): {joined}")
        if any("Unknown asset pair" in str(e) for e in errors):
            raise MarketNotFoundError(f"Kraken has no market for {what}: {joined}")
        raise ProviderError(f"Kraken error for {what}: {joined}")
    result = data.get("result")
    if not isinstance(result, dict):
        raise ProviderError(f"Kraken returned no result for {what}")
    return result


class KrakenPublicProvider(CryptoDataProvider):
    """Free spot market data from Kraken's public API (no API key)."""

    name = "kraken"
    delay_minutes = 0

    def __init__(self, min_interval: float = 0.6, max_retries: int = 3) -> None:
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
                if exc.code == 429:
                    raise RateLimitError("Kraken rate limit hit") from exc
                last = exc
            except Exception as exc:  # noqa: BLE001 - network errors vary
                last = exc
            time.sleep(2**attempt)
        raise ProviderError(f"Kraken request failed after {self.max_retries} attempts: {last}")

    # -- CryptoDataProvider -----------------------------------------------
    def get_markets(
        self,
        quote: str | None = None,
        market_type: MarketType | None = None,
    ) -> list[CryptoMarket]:
        if market_type is not None and market_type is not MarketType.SPOT:
            return []  # AssetPairs lists spot only
        result = _checked(self._fetch("/0/public/AssetPairs"), "AssetPairs")
        markets: list[CryptoMarket] = []
        for _key, p in result.items():
            if not isinstance(p, dict):
                continue
            try:
                base = _normalize_asset(str(p.get("base", "")))
                q = _normalize_asset(str(p.get("quote", "")))
                if not base or not q:
                    continue
                pair_decimals = p.get("pair_decimals")
                tick = 10.0 ** -int(pair_decimals) if pair_decimals is not None else None
                ordermin = p.get("ordermin")
                market = CryptoMarket(
                    exchange="KRAKEN",
                    base=base,
                    quote=q,
                    market_type=MarketType.SPOT,
                    tick_size=tick,
                    min_size=float(ordermin) if ordermin is not None else None,
                    active=p.get("status") == "online",
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
        kraken_pair = to_kraken_pair(pair)
        interval = _INTERVAL_MINUTES[timeframe]
        start_ts = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
        stop_ts = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
        bars: list[CryptoBar] = []
        seen: set[int] = set()
        # Page in windows of <= 720 candles; Kraken's `since` is inclusive,
        # so the boundary candle repeats and is deduped via `seen`.
        since = start_ts
        while since < stop_ts:
            result = _checked(
                self._fetch(
                    "/0/public/OHLC",
                    {"pair": kraken_pair, "interval": interval, "since": since},
                ),
                f"OHLC {pair}",
            )
            keys = [k for k in result if k != "last"]
            rows = result[keys[0]] if keys else []
            last = result.get("last", since)
            for row in rows:
                try:
                    ts = int(row[0])
                    if not (start_ts <= ts < stop_ts) or ts in seen:
                        continue
                    stamp = datetime.fromtimestamp(ts, tz=timezone.utc)
                    bars.append(
                        CryptoBar(
                            symbol=pair,
                            timestamp=stamp,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[6]),
                            trades=int(row[7]),
                        )
                    )
                    seen.add(ts)
                except (IndexError, TypeError, ValueError):
                    continue  # defensive: skip malformed rows
            if len(rows) < _MAX_CANDLES or int(last) <= since:
                break  # short page means no more data; guard against a stuck cursor
            since = int(last)
        return sorted(bars, key=lambda b: b.timestamp)

    def get_ticker(self, symbol: str) -> CryptoTicker:
        pair = canonical(symbol)
        kraken_pair = to_kraken_pair(pair)
        result = _checked(
            self._fetch("/0/public/Ticker", {"pair": kraken_pair}),
            f"Ticker {pair}",
        )
        keys = list(result.keys())
        if not keys:
            raise ProviderError(f"Kraken returned no ticker for {pair}")
        data = result[keys[0]]
        try:
            bid = float(data["b"][0])
            ask = float(data["a"][0])
            last = float(data["c"][0])
            volumes = data.get("v") or []
            base_volume_24h = float(volumes[1]) if len(volumes) > 1 else None
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ProviderError(f"bad ticker payload for {pair}: {exc}") from exc
        stamp = datetime.now(timezone.utc)
        return CryptoTicker(
            symbol=pair,
            timestamp=stamp,
            last=last,
            bid=bid,
            ask=ask,
            base_volume_24h=base_volume_24h,
        )
