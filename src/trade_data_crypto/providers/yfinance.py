"""Crypto provider backed by yfinance (free).

Yahoo quotes crypto as ``BTC-USD`` with daily and intraday history; data
is near-real-time for majors. Markets come from a built-in list of
liquid pairs -- this is a convenience feed, not an exchange listing.

yfinance is an *optional* dependency, imported lazily::

    pip install trade-data-crypto[yfinance]
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone

from ..exceptions import MarketNotFoundError, ProviderError, RateLimitError
from ..models import CryptoBar, CryptoMarket, CryptoTicker, MarketType, Timeframe
from ..symbols import canonical, to_yahoo_symbol
from .base import CryptoDataProvider

_INTERVALS = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "1h",  # resampled below
    Timeframe.D1: "1d",
}

#: Liquid majors quoted by Yahoo (vs USD).
_YAHOO_PAIRS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", "ADA/USD",
    "AVAX/USD", "LINK/USD", "LTC/USD", "BCH/USD", "DOT/USD", "MATIC/USD",
    "ATOM/USD", "NEAR/USD", "ARB/USD",
]


class YFinanceCryptoProvider(CryptoDataProvider):
    """Free crypto bars/tickers via the yfinance package."""

    name = "yfinance"
    delay_minutes = 0  # effectively real-time for majors

    def __init__(self, min_interval: float = 0.5, max_retries: int = 3) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_call = 0.0

    # -- internals ----------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _ticker(self, yahoo_symbol: str):
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError(
                "yfinance is not installed; run `pip install trade-data-crypto[yfinance]`"
            ) from exc
        return yf.Ticker(yahoo_symbol)

    def _call(self, func, *args, **kwargs):
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - vendor errors vary
                last = exc
                if "429" in str(exc) or "rate" in str(exc).lower():
                    raise RateLimitError(f"yfinance rate limit hit: {exc}") from exc
                time.sleep(2**attempt)
        raise ProviderError(
            f"yfinance request failed after {self.max_retries} attempts: {last}"
        ) from last

    # -- CryptoDataProvider -------------------------------------------
    def get_markets(
        self,
        quote: str | None = None,
        market_type: MarketType | None = None,
    ) -> list[CryptoMarket]:
        markets = [
            CryptoMarket(exchange="YAHOO", base=b, quote=q, market_type=MarketType.SPOT)
            for b, q in (p.split("/") for p in _YAHOO_PAIRS)
        ]
        if quote is not None:
            markets = [m for m in markets if m.quote == quote.strip().upper()]
        if market_type is not None:
            markets = [m for m in markets if m.market_type is market_type]
        return markets

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[CryptoBar]:
        pair = canonical(symbol)
        if pair not in _YAHOO_PAIRS:
            raise MarketNotFoundError(f"yfinance feed has no market for {pair}")
        ticker = self._ticker(to_yahoo_symbol(pair))
        frame = self._call(
            ticker.history,
            start=start.isoformat(),
            end=end.isoformat(),
            interval=_INTERVALS[timeframe],
            auto_adjust=False,
            actions=False,
        )
        bars: list[CryptoBar] = []
        for ts, row in frame.iterrows():
            try:
                stamp = ts.to_pydatetime()
            except (AttributeError, TypeError, ValueError):
                continue
            if stamp != stamp:  # NaT guard
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            vals = {k: _num(row.get(k)) for k in ("Open", "High", "Low", "Close", "Volume")}
            if vals["Open"] is None or vals["Close"] is None:
                continue
            bars.append(
                CryptoBar(
                    symbol=pair, timestamp=stamp,
                    open=vals["Open"],
                    high=vals["High"] if vals["High"] is not None else vals["Open"],
                    low=vals["Low"] if vals["Low"] is not None else vals["Open"],
                    close=vals["Close"], volume=vals["Volume"] or 0.0,
                )
            )
        bars = sorted(bars, key=lambda b: b.timestamp)
        if timeframe is Timeframe.H4:
            bars = _resample_4h(bars)
        return bars

    def get_ticker(self, symbol: str) -> CryptoTicker:
        pair = canonical(symbol)
        if pair not in _YAHOO_PAIRS:
            raise MarketNotFoundError(f"yfinance feed has no market for {pair}")
        ticker = self._ticker(to_yahoo_symbol(pair))
        frame = self._call(ticker.history, period="5d", interval="1d", auto_adjust=False, actions=False)
        if len(frame) == 0:
            raise ProviderError(f"no ticker data for {pair}")
        last_row, prev_row = frame.iloc[-1], frame.iloc[-2] if len(frame) > 1 else frame.iloc[-1]
        last = _num(last_row.get("Close"))
        if last is None:
            raise ProviderError(f"no last price for {pair}")
        stamp = frame.index[-1].to_pydatetime()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return CryptoTicker(
            symbol=pair, timestamp=stamp, last=last,
            high_24h=_num(last_row.get("High")), low_24h=_num(last_row.get("Low")),
            base_volume_24h=_num(last_row.get("Volume")),
        )


def _resample_4h(bars: list[CryptoBar]) -> list[CryptoBar]:
    """Group 1h bars into 4h bars anchored at 00/04/08/... UTC."""
    out: list[CryptoBar] = []
    bucket: list[CryptoBar] = []
    key = None
    for bar in bars:
        k = bar.timestamp.replace(minute=0, second=0, microsecond=0)
        k = k.replace(hour=(k.hour // 4) * 4)
        if k != key and bucket:
            out.append(_merge(bucket))
            bucket = []
        key = k
        bucket.append(bar)
    if bucket:
        out.append(_merge(bucket))
    return out


def _merge(bucket: list[CryptoBar]) -> CryptoBar:
    first, last = bucket[0], bucket[-1]
    return CryptoBar(
        symbol=first.symbol, timestamp=first.timestamp,
        open=first.open, high=max(b.high for b in bucket),
        low=min(b.low for b in bucket), close=last.close,
        volume=sum(b.volume for b in bucket),
    )


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
