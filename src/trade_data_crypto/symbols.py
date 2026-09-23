"""Crypto pair symbology.

The canonical form is CCXT-style ``BASE/QUOTE`` (``BTC/USD``). Exchanges
each spell it differently; these helpers convert:

* Coinbase / Yahoo: ``BTC-USD``
* Binance: ``BTCUSDT``
"""

from __future__ import annotations

from .exceptions import SymbolParseError


def parse_pair(symbol: str) -> tuple[str, str]:
    """``"BTC/USD"`` or ``"BTC-USD"`` -> ``("BTC", "USD")``."""
    text = symbol.strip().upper().replace("-", "/")
    parts = text.split("/")
    if len(parts) != 2 or not all(parts):
        raise SymbolParseError(f"not a crypto pair: {symbol!r} (expected BASE/QUOTE)")
    return parts[0], parts[1]


def canonical(symbol: str) -> str:
    """Any accepted form -> ``BASE/QUOTE``."""
    base, quote = parse_pair(symbol)
    return f"{base}/{quote}"


def to_coinbase_id(symbol: str) -> str:
    """``BTC/USD`` -> ``BTC-USD``."""
    base, quote = parse_pair(symbol)
    return f"{base}-{quote}"


def to_yahoo_symbol(symbol: str) -> str:
    """``BTC/USD`` -> ``BTC-USD`` (yahoo quotes crypto vs fiat this way)."""
    return to_coinbase_id(symbol)


def to_binance_symbol(symbol: str) -> str:
    """``BTC/USDT`` -> ``BTCUSDT``."""
    base, quote = parse_pair(symbol)
    return f"{base}{quote}"
