"""Crypto pair symbology.

The canonical form is CCXT-style ``BASE/QUOTE`` (``BTC/USD``). Exchanges
each spell it differently; these helpers convert:

* Coinbase / Yahoo: ``BTC-USD``
* Binance: ``BTCUSDT``
* Binance.US: ``BTCUSD`` (USD pairs, not USDT)
* Kraken: ``XXBTZUSD`` (BTC is XBT, USD is ZUSD on Kraken)
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


def to_binanceus_symbol(symbol: str) -> str:
    """``BTC/USD`` -> ``BTCUSD``.

    Binance.US lists USD pairs (not USDT) for the majors, so this is a
    plain concatenation of the canonical pair. Distinct from
    :func:`to_binance_symbol`, which targets Binance.com USDT pairs.
    """
    base, quote = parse_pair(symbol)
    return f"{base}{quote}"


# Kraken's legacy asset codes: BTC is XBT (``XXBT`` in AssetPairs keys),
# ETH is XETH, USD is ZUSD. Only the majors map 1:1; exotic pairs should
# be resolved through ``KrakenPublicProvider.get_markets`` (AssetPairs),
# which carries each pair's exact key.
_KRAKEN_BASE = {"BTC": "XXBT", "ETH": "XETH"}
_KRAKEN_QUOTE = {"USD": "ZUSD"}


def to_kraken_pair(symbol: str) -> str:
    """``BTC/USD`` -> ``XXBTZUSD``, ``ETH/USD`` -> ``XETHZUSD``.

    Maps the majors through Kraken's legacy asset codes. For anything
    exotic, resolve the exact pair key via ``get_markets`` instead of
    guessing -- Kraken's per-asset naming (``XXRP``, ``XLTC``...) is not
    fully rule-based.
    """
    base, quote = parse_pair(symbol)
    kraken_base = _KRAKEN_BASE.get(base, base)
    kraken_quote = _KRAKEN_QUOTE.get(quote, quote)
    return f"{kraken_base}{kraken_quote}"
