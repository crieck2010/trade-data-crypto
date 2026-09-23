"""Tests for crypto symbology, models, and pure stats."""

from datetime import datetime, timezone

import pytest

from trade_data_crypto.exceptions import SymbolParseError
from trade_data_crypto.models import (
    CryptoBar,
    CryptoMarket,
    CryptoTicker,
    FundingRate,
    MarketType,
)
from trade_data_crypto.stats import funding_apr, vwap
from trade_data_crypto.symbols import (
    canonical,
    parse_pair,
    to_binance_symbol,
    to_coinbase_id,
    to_yahoo_symbol,
)


def test_parse_pair_forms():
    assert parse_pair("BTC/USD") == ("BTC", "USD")
    assert parse_pair("BTC-USD") == ("BTC", "USD")
    assert parse_pair("btc/usd") == ("BTC", "USD")
    assert canonical("eth-usd") == "ETH/USD"


def test_parse_pair_rejects_malformed():
    for bad in ["BTC", "BTC/USD/ETH", "/USD", "", "BTC-"]:
        with pytest.raises(SymbolParseError):
            parse_pair(bad)


def test_exchange_symbol_forms():
    assert to_coinbase_id("BTC/USD") == "BTC-USD"
    assert to_yahoo_symbol("BTC/USD") == "BTC-USD"
    assert to_binance_symbol("BTC/USDT") == "BTCUSDT"


def _bar(close, volume, day=1, symbol="BTC/USD"):
    return CryptoBar(
        symbol=symbol,
        timestamp=datetime(2024, 1, day, tzinfo=timezone.utc),
        open=close, high=close + 1, low=close - 1, close=close,
        volume=volume, quote_volume=close * volume, trades=10,
    )


def test_bar_validation():
    b = _bar(100.0, 5.0)
    assert b.symbol == "BTC/USD"
    with pytest.raises(ValueError):
        _bar(100.0, 5.0, symbol="BTCUSD")  # not canonical
    with pytest.raises(ValueError):
        CryptoBar(symbol="BTC/USD", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                  open=200, high=100, low=50, close=90)  # open > high
    with pytest.raises(ValueError):
        _bar(100.0, -1.0)  # negative volume


def test_market_symbol():
    m = CryptoMarket(exchange="coinbase", base="btc", quote="usd")
    assert m.symbol == "BTC/USD"
    assert str(m) == "COINBASE:BTC/USD"
    assert m.market_type is MarketType.SPOT


def test_ticker_spread():
    t = CryptoTicker(
        symbol="BTC/USD", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        last=100.0, bid=99.9, ask=100.1,
    )
    assert t.spread_bps == pytest.approx(20.0)
    t2 = CryptoTicker(symbol="BTC/USD", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc), last=100.0)
    assert t2.spread_bps is None


def test_vwap():
    bars = [_bar(100.0, 10.0), _bar(110.0, 10.0), _bar(90.0, 20.0)]
    # (100*10 + 110*10 + 90*20) / 40 = 97.5
    assert vwap(bars) == pytest.approx(97.5)
    assert vwap([]) is None
    assert vwap([_bar(100.0, 0.0)]) is None


def test_funding_apr():
    # 0.01% per 8h -> (1.0001)^(1095) - 1 ~= 11.57%
    assert funding_apr(0.0001, 8.0) == pytest.approx(0.1157, abs=0.001)
    assert funding_apr(0.0) == pytest.approx(0.0)
    assert funding_apr(-0.0001, 8.0) < 0
    with pytest.raises(ValueError):
        funding_apr(0.0001, 0)


def test_funding_rate_model():
    f = FundingRate(symbol="BTC/USD", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    rate=0.0001, predicted_next=0.0002)
    assert f.interval_hours == 8.0
