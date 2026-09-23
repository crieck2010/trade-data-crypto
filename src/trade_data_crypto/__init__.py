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
    CoinbasePublicProvider,
    CryptoDataProvider,
    YFinanceCryptoProvider,
)
from .stats import funding_apr, vwap
from .symbols import (
    canonical,
    parse_pair,
    to_binance_symbol,
    to_coinbase_id,
    to_yahoo_symbol,
)

__version__ = "0.1.0"

__all__ = [
    "CoinbasePublicProvider",
    "CryptoBar",
    "CryptoDataClient",
    "CryptoDataError",
    "CryptoDataProvider",
    "CryptoMarket",
    "CryptoTicker",
    "DiskCache",
    "FundingRate",
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
    "to_coinbase_id",
    "to_yahoo_symbol",
    "vwap",
]
