"""Tests for the crypto client, cache, and Coinbase pagination."""

from datetime import date, datetime, timedelta, timezone

import pytest

from trade_data_crypto.cache import DiskCache
from trade_data_crypto.client import CryptoDataClient
from trade_data_crypto.exceptions import MarketNotFoundError
from trade_data_crypto.models import CryptoBar, CryptoMarket, MarketType, Timeframe
from trade_data_crypto.providers import CryptoDataProvider
from trade_data_crypto.providers.coinbase import CoinbasePublicProvider


def _bar(symbol, day, close):
    return CryptoBar(
        symbol=symbol,
        timestamp=datetime(2024, 1, day, tzinfo=timezone.utc),
        open=close, high=close, low=close, close=close, volume=10.0,
    )


class FakeCryptoProvider(CryptoDataProvider):
    name = "fake"

    def __init__(self):
        self.bars_calls = 0
        self.markets_calls = 0

    def get_markets(self, quote=None, market_type=None):
        self.markets_calls += 1
        markets = [
            CryptoMarket(exchange="FAKE", base="BTC", quote="USD"),
            CryptoMarket(exchange="FAKE", base="ETH", quote="USD"),
            CryptoMarket(exchange="FAKE", base="BTC", quote="EUR"),
        ]
        if quote is not None:
            markets = [m for m in markets if m.quote == quote]
        return markets

    def get_bars(self, symbol, timeframe, start, end):
        self.bars_calls += 1
        return [_bar(symbol, day, 100.0 + day) for day in (1, 2, 3)]


def _client(provider, tmp_path):
    return CryptoDataClient(provider, cache=DiskCache(root=tmp_path))


def test_markets_cached_and_filtered(tmp_path):
    provider = FakeCryptoProvider()
    client = _client(provider, tmp_path)
    markets = client.get_markets(quote="USD")
    assert [m.symbol for m in markets] == ["BTC/USD", "ETH/USD"]
    client.get_markets(quote="USD")
    assert provider.markets_calls == 1


def test_require_market(tmp_path):
    client = _client(FakeCryptoProvider(), tmp_path)
    assert client.require_market("btc-usd").exchange == "FAKE"
    with pytest.raises(MarketNotFoundError):
        client.require_market("SOL/USD")


def test_bars_cached(tmp_path):
    provider = FakeCryptoProvider()
    client = _client(provider, tmp_path)
    bars = client.get_bars("BTC/USD", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 5))
    assert [b.close for b in bars] == [101.0, 102.0, 103.0]
    client.get_bars("btc-usd", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 5))
    assert provider.bars_calls == 1  # canonicalization hits the same cache key


def test_stream_bars_chunks(tmp_path):
    client = _client(FakeCryptoProvider(), tmp_path)
    bars = list(client.stream_bars("BTC/USD", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 6), chunk_days=2))
    assert len(bars) == 3 * 3


def test_cache_bars_round_trip(tmp_path):
    cache = DiskCache(root=tmp_path)
    bars = [_bar("BTC/USD", 1, 101.0), _bar("BTC/USD", 2, 102.0)]
    assert cache.get_bars("p", "BTC/USD", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 3)) is None
    cache.put_bars("p", "BTC/USD", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 3), bars)
    hit = cache.get_bars("p", "BTC/USD", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 3))
    assert [b.close for b in hit] == [101.0, 102.0]


def test_cache_markets_ttl(tmp_path):
    cache = DiskCache(root=tmp_path, markets_ttl=timedelta(seconds=0))
    markets = [CryptoMarket(exchange="X", base="BTC", quote="USD", tick_size=0.01, min_size=0.001)]
    cache.put_markets("p", "USD", markets)
    assert cache.get_markets("p", "USD") is None
    cache.markets_ttl = timedelta(hours=1)
    cache.put_markets("p", "USD", markets)
    hit = cache.get_markets("p", "USD")
    assert [(m.base, m.tick_size, m.min_size, m.active) for m in hit] == [("BTC", 0.01, 0.001, True)]
    assert cache.clear() == 1


class PagedCoinbase(CoinbasePublicProvider):
    """Coinbase provider with stubbed HTTP to test pagination math."""

    def __init__(self):
        super().__init__(min_interval=0)
        self.requests = []

    def _fetch(self, path, params=None):
        self.requests.append((path, params))
        # One candle per granularity step inside [start, end).
        start = datetime.fromisoformat(params["start"])
        end = datetime.fromisoformat(params["end"])
        gran = params["granularity"]
        out = []
        t = start
        while t < end:
            ts = t.timestamp()
            out.append([ts, 99.0, 101.0, 100.0, 100.5, 10.0])  # [time, low, high, open, close, vol]
            t += timedelta(seconds=gran)
        return out


def test_coinbase_pagination_and_candle_order():
    provider = PagedCoinbase()
    # 1000 hourly candles -> pages of 300, 300, 300, 100.
    start = date(2024, 1, 1)
    end = date(2024, 2, 11)  # 41 days = 984 hours
    bars = provider.get_bars("BTC/USD", Timeframe.H1, start, end)
    assert len(bars) == 984
    assert len(provider.requests) == 4
    assert bars == sorted(bars, key=lambda b: b.timestamp)
    # Coinbase's [time, low, high, open, close, volume] order mapped correctly.
    assert (bars[0].low, bars[0].high, bars[0].open, bars[0].close) == (99.0, 101.0, 100.0, 100.5)
    assert all(b.symbol == "BTC/USD" for b in bars)
