"""Exception hierarchy for the crypto market-data engine."""


class CryptoDataError(Exception):
    """Base class for all engine errors."""


class MarketNotFoundError(CryptoDataError):
    """No market is listed for the requested symbol."""


class ProviderError(CryptoDataError):
    """The provider failed after retries (network, parsing, API errors)."""


class RateLimitError(ProviderError):
    """The provider rate-limited the request; back off and retry later."""


class SymbolParseError(CryptoDataError):
    """A crypto pair string could not be parsed."""
