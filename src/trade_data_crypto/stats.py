"""Pure crypto analytics: VWAP and funding-rate annualization.

Provider-agnostic functions over bars and funding observations -- the
kind of math every downstream engine (backtest, strategies, risk)
reaches for.
"""

from __future__ import annotations

from .models import CryptoBar


def vwap(bars: list[CryptoBar]) -> float | None:
    """Volume-weighted average price over ``bars``; None when volume is zero."""
    notional = sum(b.close * b.volume for b in bars)
    volume = sum(b.volume for b in bars)
    if volume <= 0:
        return None
    return notional / volume


def funding_apr(rate: float, interval_hours: float = 8.0) -> float:
    """Annualized funding cost of holding a perpetual.

    ``(1 + rate) ** (8760 / interval_hours) - 1``. Positive means longs
    pay this annualized rate to shorts.
    """
    if interval_hours <= 0:
        raise ValueError(f"interval_hours must be positive, got {interval_hours!r}")
    return (1.0 + rate) ** (8760.0 / interval_hours) - 1.0
