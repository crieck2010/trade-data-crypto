"""Tests for the Binance.US provider. Everything runs offline against a
scripted ``_fetch`` (or a monkeypatched ``urlopen`` for the HTTP-error
mapping tests).

No test in this file touches the network or needs an API key.
"""

import io
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

import pytest

from trade_data_crypto.exceptions import (
    MarketNotFoundError,
    ProviderError,
    RateLimitError,
)
from trade_data_crypto.models import CryptoBar, MarketType, Timeframe
from trade_data_crypto.providers.binance_us import (
    _INTERVAL,
    _MAX_ROWS,
    _map_http_error,
    BinanceUSPublicProvider,
)
from trade_data_crypto.symbols import to_binanceus_symbol


class MockBinanceUS(BinanceUSPublicProvider):
    """Binance.US provider with scripted ``_fetch`` responses."""

    def __init__(self, script):
        super().__init__(min_interval=0.0, max_retries=1)
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []

    def _fetch(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _kline(open_ms, o, h, l, c, vol=10.0, trades=5, quote_vol=None):
    # [openTime, open, high, low, close, volume, closeTime,
    #  quoteAssetVolume, trades, takerBuyBaseVol, takerBuyQuoteVol, ignore]
    close_ms = open_ms + 299_999
    return [
        open_ms, str(o), str(h), str(l), str(c), str(vol), close_ms,
        str(quote_vol if quote_vol is not None else c * vol),
        trades, "0", "0", "0",
    ]


def _five_min_klines(n, start_ms, base=100.0):
    rows = []
    for i in range(n):
        open_ms = start_ms + i * 300_000
        c = base + i
        rows.append(_kline(open_ms, c - 1, c + 1, c - 2, c, vol=10.0 + i, trades=5 + i))
    return rows


START = date(2024, 1, 1)
START_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


# -- symbology ----------------------------------------------------------

def test_to_binanceus_symbol():
    assert to_binanceus_symbol("BTC/USD") == "BTCUSD"
    assert to_binanceus_symbol("ETH/USD") == "ETHUSD"


# -- mapping ------------------------------------------------------------

def test_timeframe_mapping_covers_every_timeframe():
    assert set(_INTERVAL) == set(Timeframe)
    assert _INTERVAL[Timeframe.M1] == "1m"
    assert _INTERVAL[Timeframe.M5] == "5m"
    assert _INTERVAL[Timeframe.M15] == "15m"
    assert _INTERVAL[Timeframe.H1] == "1h"
    assert _INTERVAL[Timeframe.H4] == "4h"
    assert _INTERVAL[Timeframe.D1] == "1d"


def test_url_construction():
    mock = MockBinanceUS([_five_min_klines(2, START_MS)])
    bars = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 2))
    assert len(bars) == 2
    path, params = mock.calls[0]
    assert path == "/api/v3/klines"
    assert params["symbol"] == "BTCUSD"
    assert params["interval"] == "5m"
    assert params["startTime"] == START_MS
    assert params["endTime"] == START_MS + 86_400_000 - 1  # endTime inclusive
    assert params["limit"] == 1000


# -- bar parsing / parity ------------------------------------------------

def test_bar_parsing_parity():
    rows = [_kline(START_MS, 100.0, 102.0, 99.0, 101.0, vol=12.5, trades=7, quote_vol=1262.5)]
    mock = MockBinanceUS([rows])
    (bar,) = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 2))
    assert isinstance(bar, CryptoBar)
    assert bar.symbol == "BTC/USD"  # canonical, not BTCUSD
    assert bar.timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)  # bar OPEN
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 102.0, 99.0, 101.0)
    assert bar.volume == pytest.approx(12.5)  # base currency
    assert bar.quote_volume == pytest.approx(1262.5)
    assert bar.trades == 7


def test_bars_sorted_ascending_and_windowed():
    rows = _five_min_klines(10, START_MS) + _five_min_klines(3, START_MS - 3 * 300_000)
    mock = MockBinanceUS([rows])
    bars = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 2))
    assert len(bars) == 10  # pre-window rows dropped
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


# -- pagination ----------------------------------------------------------

def test_pagination_across_page_boundary():
    page1 = _five_min_klines(_MAX_ROWS, START_MS)
    last_close1 = page1[-1][6]
    page2 = _five_min_klines(10, last_close1 + 1)
    mock = MockBinanceUS([page1, page2])
    bars = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 10))
    assert len(bars) == _MAX_ROWS + 10
    assert len(mock.calls) == 2
    _, params2 = mock.calls[1]
    assert params2["startTime"] == last_close1 + 1  # lastCloseTime + 1
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


# -- error mapping -------------------------------------------------------

def _http_error(code, body: bytes):
    return urllib.error.HTTPError(
        "https://api.binance.us/api/v3/klines", code, "err", {}, io.BytesIO(body)
    )


def test_map_http_error_invalid_symbol():
    exc = _http_error(400, b'{"code": -1121, "msg": "Invalid symbol."}')
    mapped = _map_http_error(exc, "/api/v3/klines")
    assert isinstance(mapped, MarketNotFoundError)


def test_map_http_error_rate_limit_and_ban():
    assert isinstance(_map_http_error(_http_error(429, b""), "x"), RateLimitError)
    assert isinstance(_map_http_error(_http_error(418, b""), "x"), RateLimitError)


def test_map_http_error_other_4xx():
    exc = _http_error(400, b'{"code": -1100, "msg": "Illegal characters."}')
    assert isinstance(_map_http_error(exc, "x"), ProviderError)


def test_unknown_symbol_end_to_end():
    mock = MockBinanceUS([MarketNotFoundError("Binance.US has no market for FOO/USD")])
    with pytest.raises(MarketNotFoundError):
        mock.get_bars("FOO/USD", Timeframe.M5, START, date(2024, 1, 2))


def test_http_429_maps_to_rate_limit(monkeypatch):
    def boom(request, timeout=30):
        raise urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    provider = BinanceUSPublicProvider(min_interval=0.0, max_retries=1)
    with pytest.raises(RateLimitError):
        provider._fetch("/api/v3/klines", {"symbol": "BTCUSD"})


# -- ticker --------------------------------------------------------------

def test_ticker_parsing():
    payload = {
        "symbol": "BTCUSD",
        "bidPrice": "101.0",
        "askPrice": "101.5",
        "lastPrice": "101.2",
        "highPrice": "105.0",
        "lowPrice": "99.0",
        "volume": "1234.5",
        "quoteVolume": "125000.0",
    }
    mock = MockBinanceUS([payload])
    ticker = mock.get_ticker("BTC/USD")
    assert ticker.symbol == "BTC/USD"
    assert ticker.last == pytest.approx(101.2)
    assert ticker.bid == pytest.approx(101.0)
    assert ticker.ask == pytest.approx(101.5)
    assert ticker.high_24h == pytest.approx(105.0)
    assert ticker.low_24h == pytest.approx(99.0)
    assert ticker.base_volume_24h == pytest.approx(1234.5)
    assert ticker.quote_volume_24h == pytest.approx(125000.0)
    path, params = mock.calls[0]
    assert path == "/api/v3/ticker/24hr"
    assert params["symbol"] == "BTCUSD"


# -- markets -------------------------------------------------------------

def _exchange_info_payload():
    return {
        "symbols": [
            {
                "symbol": "BTCUSD", "baseAsset": "BTC", "quoteAsset": "USD",
                "status": "TRADING", "permissions": ["SPOT", "MARGIN"],
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {"filterType": "LOT_SIZE", "minQty": "0.00001"},
                ],
            },
            {
                "symbol": "ETHUSD", "baseAsset": "ETH", "quoteAsset": "USD",
                "status": "TRADING", "permissions": ["SPOT"],
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {"filterType": "LOT_SIZE", "minQty": "0.0001"},
                ],
            },
            {
                # halted: filtered out
                "symbol": "FOOUSD", "baseAsset": "FOO", "quoteAsset": "USD",
                "status": "BREAK", "permissions": ["SPOT"], "filters": [],
            },
            {
                # not spot: filtered out
                "symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
                "status": "TRADING", "permissions": ["MARGIN"], "filters": [],
            },
        ]
    }


def test_get_markets():
    mock = MockBinanceUS([_exchange_info_payload()])
    markets = mock.get_markets()
    by_symbol = {m.symbol: m for m in markets}
    assert set(by_symbol) == {"BTC/USD", "ETH/USD"}
    btc = by_symbol["BTC/USD"]
    assert btc.exchange == "BINANCEUS"
    assert btc.market_type is MarketType.SPOT
    assert btc.tick_size == pytest.approx(0.01)
    assert btc.min_size == pytest.approx(0.00001)
    assert btc.active is True


def test_get_markets_quote_filter_and_type_guard():
    mock = MockBinanceUS([_exchange_info_payload(), _exchange_info_payload()])
    assert {m.symbol for m in mock.get_markets(quote="USD")} == {"BTC/USD", "ETH/USD"}
    assert mock.get_markets(market_type=MarketType.PERP) == []
