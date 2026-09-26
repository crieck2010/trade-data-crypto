"""trade-data-crypto: crypto market-data engine.

Spot markets, OHLCV bars, tickers, and funding-rate models across
exchanges, with free providers (Coinbase public REST, yfinance) and a
two-method interface for keyed exchange feeds. See README.md.
"""

from .cache import DiskCache
from .client import CryptoDataClient
from .exceptions import (
    CryptoDataError,
    MarketNotFoundError,
    ProviderError,
    RateLimitError,
    SymbolParseError,
)
from .models import (
    CryptoBar,
    CryptoMarket,
    CryptoTicker,
    FundingRate,
    MarketType,
    Timeframe,
    ensure_utc,
)
from .providers import (
    BinanceUSPublicProvider,
    CoinbasePublicProvider,
    CryptoDataProvider,
    KrakenPublicProvider,
    YFinanceCryptoProvider,
)
from .stats import funding_apr, vwap
from .symbols import (
    canonical,
    parse_pair,
    to_binance_symbol,
    to_binanceus_symbol,
    to_coinbase_id,
    to_kraken_pair,
    to_yahoo_symbol,
)

__version__ = "0.2.0"

__all__ = [
    "BinanceUSPublicProvider",
    "CoinbasePublicProvider",
    "CryptoBar",
    "CryptoDataClient",
    "CryptoDataError",
    "CryptoDataProvider",
    "CryptoMarket",
    "CryptoTicker",
    "DiskCache",
    "FundingRate",
    "KrakenPublicProvider",
    "MarketNotFoundError",
    "MarketType",
    "ProviderError",
    "RateLimitError",
    "SymbolParseError",
    "Timeframe",
    "YFinanceCryptoProvider",
    "__version__",
    "canonical",
    "ensure_utc",
    "funding_apr",
    "parse_pair",
    "to_binance_symbol",
    "to_binanceus_symbol",
    "to_coinbase_id",
    "to_kraken_pair",
    "to_yahoo_symbol",
    "vwap",
]
