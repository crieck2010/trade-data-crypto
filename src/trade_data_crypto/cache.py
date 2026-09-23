"""On-disk cache for crypto bars and market listings.

Bars are keyed by ``(provider, symbol, timeframe, start, end)`` with a
60-minute TTL (crypto moves fast; history beyond the last bar rarely
revises). Market listings refresh every 24 hours. Tickers are real-time
and are never cached. Layout::

    <root>/<provider>/bars_<sha1>.json
    <root>/<provider>/markets_<QUOTE>.json

Stdlib-only JSON. ``TRADE_CRYPTO_CACHE`` overrides the default
``~/.cache/trade-data-crypto``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import CryptoBar, CryptoMarket, MarketType, Timeframe, ensure_utc
from .symbols import canonical


def _default_root() -> Path:
    return Path(os.environ.get("TRADE_CRYPTO_CACHE", Path.home() / ".cache" / "trade-data-crypto"))


class DiskCache:
    """JSON file cache for bars (TTL 60m) and markets (TTL 24h)."""

    def __init__(
        self,
        root: str | Path | None = None,
        bars_ttl: timedelta = timedelta(minutes=60),
        markets_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.root = Path(root) if root is not None else _default_root()
        self.bars_ttl = bars_ttl
        self.markets_ttl = markets_ttl

    # -- bars ---------------------------------------------------------------
    @staticmethod
    def _bars_key(provider: str, symbol: str, timeframe: Timeframe, start: date, end: date) -> str:
        return "bars_" + hashlib.sha1(
            f"{provider}|{canonical(symbol)}|{timeframe.value}|{start.isoformat()}|{end.isoformat()}".encode()
        ).hexdigest()

    @staticmethod
    def _bar_to_dict(b: CryptoBar) -> dict[str, Any]:
        return {
            "symbol": b.symbol, "timestamp": b.timestamp.isoformat(),
            "open": b.open, "high": b.high, "low": b.low, "close": b.close,
            "volume": b.volume, "quote_volume": b.quote_volume, "trades": b.trades,
        }

    @staticmethod
    def _bar_from_dict(item: dict[str, Any]) -> CryptoBar:
        return CryptoBar(
            symbol=item["symbol"],
            timestamp=ensure_utc(datetime.fromisoformat(item["timestamp"])),
            open=item["open"], high=item["high"], low=item["low"], close=item["close"],
            volume=item["volume"], quote_volume=item["quote_volume"], trades=item["trades"],
        )

    def get_bars(
        self, provider: str, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> list[CryptoBar] | None:
        raw = self._read(provider, self._bars_key(provider, symbol, timeframe, start, end), self.bars_ttl)
        if raw is None:
            return None
        return [self._bar_from_dict(b) for b in raw]

    def put_bars(
        self, provider: str, symbol: str, timeframe: Timeframe,
        start: date, end: date, bars: list[CryptoBar],
    ) -> None:
        self._write(
            provider,
            self._bars_key(provider, symbol, timeframe, start, end),
            [self._bar_to_dict(b) for b in bars],
        )

    # -- markets --------------------------------------------------------------
    @staticmethod
    def _market_to_dict(m: CryptoMarket) -> dict[str, Any]:
        return {
            "exchange": m.exchange, "base": m.base, "quote": m.quote,
            "market_type": m.market_type.value, "tick_size": m.tick_size,
            "min_size": m.min_size, "active": m.active,
        }

    @staticmethod
    def _market_from_dict(item: dict[str, Any]) -> CryptoMarket:
        return CryptoMarket(
            exchange=item["exchange"], base=item["base"], quote=item["quote"],
            market_type=MarketType(item["market_type"]), tick_size=item["tick_size"],
            min_size=item["min_size"], active=item["active"],
        )

    def get_markets(self, provider: str, quote: str | None) -> list[CryptoMarket] | None:
        raw = self._read(provider, f"markets_{quote or 'ALL'}", self.markets_ttl)
        if raw is None:
            return None
        return [self._market_from_dict(m) for m in raw]

    def put_markets(self, provider: str, quote: str | None, markets: list[CryptoMarket]) -> None:
        self._write(provider, f"markets_{quote or 'ALL'}",
                    [self._market_to_dict(m) for m in markets])

    # -- file io ----------------------------------------------------------------
    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{key}.json"

    def _read(self, namespace: str, key: str, ttl: timedelta) -> Any | None:
        path = self._path(namespace, key)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        fetched = datetime.fromisoformat(doc["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > ttl:
            return None
        return doc["payload"]

    def _write(self, namespace: str, key: str, payload: Any) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"fetched_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        path.write_text(json.dumps(doc), encoding="utf-8")

    def clear(self, namespace: str | None = None) -> int:
        """Delete cached files; returns the number removed."""
        targets = [self.root / namespace] if namespace else [self.root]
        removed = 0
        for target in targets:
            if not target.exists():
                continue
            for path in target.rglob("*.json"):
                path.unlink()
                removed += 1
        return removed
