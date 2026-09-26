"""Tests for the Kraken provider. Everything runs offline against a
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
from trade_data_crypto.providers.kraken import (
    _INTERVAL_MINUTES,
    _MAX_CANDLES,
    _checked,
    _normalize_asset,
    KrakenPublicProvider,
)
from trade_data_crypto.symbols import to_kraken_pair


class MockKraken(KrakenPublicProvider):
    """Kraken provider with scripted ``_fetch`` responses."""

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


def _ohlc_payload(rows, pair="XXBTZUSD", last=None):
    return {
        "error": [],
        "result": {
            pair: rows,
            "last": last if last is not None else (rows[-1][0] if rows else 0),
        },
    }


def _row(ts, o, h, l, c, v=10.0, n=5, vwap=None):
    # Kraken sends prices as strings; fields are
    # [time, open, high, low, close, vwap, volume, count].
    return [ts, str(o), str(h), str(l), str(c), str(vwap if vwap is not None else (o + c) / 2), str(v), n]


def _five_min_rows(n, start_ts, base=100.0):
    rows = []
    for i in range(n):
        ts = start_ts + i * 300
        c = base + i
        rows.append(_row(ts, c - 1, c + 1, c - 2, c, v=10.0 + i, n=5 + i))
    return rows


START = date(2024, 1, 1)
START_TS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


# -- symbology ----------------------------------------------------------

def test_to_kraken_pair_majors():
    assert to_kraken_pair("BTC/USD") == "XXBTZUSD"
    assert to_kraken_pair("ETH/USD") == "XETHZUSD"


def test_normalize_asset():
    assert _normalize_asset("XXBT") == "BTC"
    assert _normalize_asset("XETH") == "ETH"
    assert _normalize_asset("ZUSD") == "USD"
    assert _normalize_asset("SOL") == "SOL"


# -- mapping ------------------------------------------------------------

def test_timeframe_mapping_covers_every_timeframe():
    assert set(_INTERVAL_MINUTES) == set(Timeframe)
    assert _INTERVAL_MINUTES[Timeframe.M1] == 1
    assert _INTERVAL_MINUTES[Timeframe.M5] == 5
    assert _INTERVAL_MINUTES[Timeframe.M15] == 15
    assert _INTERVAL_MINUTES[Timeframe.H1] == 60
    assert _INTERVAL_MINUTES[Timeframe.H4] == 240
    assert _INTERVAL_MINUTES[Timeframe.D1] == 1440


def test_url_construction():
    mock = MockKraken([_ohlc_payload(_five_min_rows(2, START_TS))])
    bars = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 2))
    assert len(bars) == 2
    path, params = mock.calls[0]
    assert path == "/0/public/OHLC"
    assert params["pair"] == "XXBTZUSD"
    assert params["interval"] == 5
    assert params["since"] == START_TS


# -- bar parsing / parity ------------------------------------------------

def test_bar_parsing_parity():
    rows = [_row(START_TS, 100.0, 102.0, 99.0, 101.0, v=12.5, n=7)]
    mock = MockKraken([_ohlc_payload(rows)])
    (bar,) = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 2))
    assert isinstance(bar, CryptoBar)
    assert bar.symbol == "BTC/USD"  # canonical, not XXBTZUSD
    assert bar.timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)  # bar OPEN
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 102.0, 99.0, 101.0)
    assert bar.volume == pytest.approx(12.5)  # base currency
    assert bar.trades == 7  # Kraken `count`
    assert bar.quote_volume is None  # Kraken vwap has no CryptoBar field


def test_bars_sorted_ascending_and_windowed():
    rows = _five_min_rows(10, START_TS) + _five_min_rows(3, START_TS - 3 * 300)
    mock = MockKraken([_ohlc_payload(rows, last=START_TS + 9 * 300)])
    bars = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 2))
    assert len(bars) == 10  # pre-window rows dropped
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


# -- pagination ----------------------------------------------------------

def test_pagination_across_page_boundary():
    page1 = _five_min_rows(_MAX_CANDLES, START_TS)
    last1 = page1[-1][0]
    # Kraken's `since` is inclusive: the boundary candle repeats on page 2.
    page2 = _five_min_rows(3, last1)
    mock = MockKraken([
        _ohlc_payload(page1, last=last1),
        _ohlc_payload(page2, last=page2[-1][0]),
    ])
    bars = mock.get_bars("BTC/USD", Timeframe.M5, START, date(2024, 1, 10))
    assert len(bars) == _MAX_CANDLES + 2  # boundary candle deduped
    assert len(mock.calls) == 2
    _, params2 = mock.calls[1]
    assert params2["since"] == last1  # paginate with since=last
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


# -- error mapping -------------------------------------------------------

def test_checked_unknown_pair():
    with pytest.raises(MarketNotFoundError):
        _checked({"error": ["EQuery:Unknown asset pair"], "result": {}}, "OHLC BTC/USD")


def test_checked_rate_limit():
    with pytest.raises(RateLimitError):
        _checked({"error": ["EAPI:Rate limit exceeded"], "result": {}}, "OHLC BTC/USD")


def test_checked_generic_error():
    with pytest.raises(ProviderError):
        _checked({"error": ["EGeneral:Some failure"], "result": {}}, "OHLC BTC/USD")


def test_unknown_pair_end_to_end():
    mock = MockKraken([{"error": ["EQuery:Unknown asset pair"], "result": {}}])
    with pytest.raises(MarketNotFoundError):
        mock.get_bars("DOGE/USD", Timeframe.M5, START, date(2024, 1, 2))


def test_http_429_maps_to_rate_limit(monkeypatch):
    def boom(request, timeout=30):
        raise urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    provider = KrakenPublicProvider(min_interval=0.0, max_retries=1)
    with pytest.raises(RateLimitError):
        provider._fetch("/0/public/OHLC", {"pair": "XXBTZUSD"})


# -- ticker --------------------------------------------------------------

def test_ticker_parsing():
    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": {
                # b/a/c are [price, whole_lot_vol, lot_vol]; index 0 taken.
                "a": ["101.5", "1", "1.0"],
                "b": ["101.0", "2", "2.0"],
                "c": ["101.2", "0.5"],
                "v": ["100.0", "1234.5"],
            }
        },
    }
    mock = MockKraken([payload])
    ticker = mock.get_ticker("BTC/USD")
    assert ticker.symbol == "BTC/USD"
    assert ticker.last == pytest.approx(101.2)
    assert ticker.bid == pytest.approx(101.0)
    assert ticker.ask == pytest.approx(101.5)
    assert ticker.base_volume_24h == pytest.approx(1234.5)
    path, params = mock.calls[0]
    assert path == "/0/public/Ticker"
    assert params["pair"] == "XXBTZUSD"


# -- markets -------------------------------------------------------------

def _assetpairs_payload():
    return {
        "error": [],
        "result": {
            "XXBTZUSD": {
                "base": "XXBT", "quote": "ZUSD", "status": "online",
                "pair_decimals": 1, "ordermin": "0.0001",
            },
            "XETHZUSD": {
                "base": "XETH", "quote": "ZUSD", "status": "online",
                "pair_decimals": 2, "ordermin": "0.002",
            },
            "XXBTZEUR": {
                "base": "XXBT", "quote": "ZEUR", "status": "online",
                "pair_decimals": 1, "ordermin": "0.0001",
            },
        },
    }


def test_get_markets():
    mock = MockKraken([_assetpairs_payload()])
    markets = mock.get_markets()
    by_symbol = {m.symbol: m for m in markets}
    assert by_symbol["BTC/USD"].exchange == "KRAKEN"
    assert by_symbol["BTC/USD"].market_type is MarketType.SPOT
    assert by_symbol["BTC/USD"].tick_size == pytest.approx(0.1)
    assert by_symbol["BTC/USD"].min_size == pytest.approx(0.0001)
    assert by_symbol["ETH/USD"].tick_size == pytest.approx(0.01)
    assert by_symbol["BTC/EUR"].active is True


def test_get_markets_quote_filter_and_type_guard():
    mock = MockKraken([_assetpairs_payload(), _assetpairs_payload()])
    usd = mock.get_markets(quote="USD")
    assert {m.symbol for m in usd} == {"BTC/USD", "ETH/USD"}
    assert mock.get_markets(market_type=MarketType.PERP) == []
