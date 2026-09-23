# trade-data-crypto

Crypto market-data engine: spot markets, OHLCV bars, tickers, and
funding-rate models across exchanges. Fourth data module of the
algorithmic/agentic trading system — a sibling of `trade-data-equities`,
`trade-data-options`, and `trade-data-futures`, sharing their
provider/client/cache design language.

Free data today (Coinbase public REST with no API key, yfinance
convenience feed), pluggable keyed exchange feeds tomorrow. Built for
**research, backtesting, and paper trading** — not for live execution.

## Features

- **Canonical symbology** — `BASE/QUOTE` everywhere (`BTC/USD`), with
  conversion to Coinbase/Yahoo (`BTC-USD`) and Binance (`BTCUSDT`) forms.
- **Market models** — spot, perpetual, and dated-future markets with tick
  size, min size, and active status.
- **Bars** — OHLCV plus quote volume and trade count where the venue
  publishes them; crypto trades 24/7, so no session-gap handling needed.
- **Tickers** — last, bid/ask, 24h high/low/volume, spread in bps.
- **Funding rates** — model + APR annualization for perpetual carry
  accounting.
- **Two free providers** — `CoinbasePublicProvider` (keyless public REST:
  full market listings, auto-paginated candles, tickers; stdlib `urllib`
  only) and `YFinanceCryptoProvider` (15 liquid majors, optional extra).
- **Disk cache** — bars (60 min TTL) and market listings (24 h TTL);
  tickers are real-time and never cached.
- **Bounded-memory streaming** — `stream_bars` walks long histories in
  date chunks.
- **Pure analytics** — VWAP and funding-APR helpers with no provider
  coupling.

## Installation

```bash
pip install trade-data-crypto              # core + Coinbase provider, stdlib only
pip install "trade-data-crypto[yfinance]"  # + yfinance convenience feed
```

Requires Python 3.10+. No API keys needed for either bundled provider.

## Quickstart

```python
from datetime import date, timedelta
from trade_data_crypto import (
    CoinbasePublicProvider, CryptoDataClient, Timeframe, vwap,
)

client = CryptoDataClient(CoinbasePublicProvider())
end = date.today()

markets = client.get_markets(quote="USD")
print(f"{len(markets)} USD spot markets")

bars = client.get_bars("BTC/USD", Timeframe.D1, end - timedelta(days=90), end)
print(f"{len(bars)} bars, last {bars[-1].close:,.2f}, VWAP {vwap(bars):,.2f}")

ticker = client.get_ticker("BTC/USD")
print(f"spread {ticker.spread_bps:.1f} bps")
```

## Architecture

```
                        ┌──────────────────────┐
                        │   CryptoDataClient   │  markets · bars · ticker · funding
                        └──────────┬───────────┘
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
   ┌──────────────────┐  ┌─────────────────┐  ┌────────────────────┐
   │CryptoDataProvi-  │  │    DiskCache    │  │ stats (vwap,       │
   │der (ABC)         │  │  JSON on disk   │  │ funding_apr)       │
   └────────┬─────────┘  └─────────────────┘  │ symbols            │
            ├─────────────────┐               └────────────────────┘
            ▼                 ▼
   ┌────────────────┐ ┌───────────────────┐
   │CoinbasePublic- │ │YFinanceCrypto-    │  ← keyless
   │Provider        │ │Provider           │
   └────────────────┘ └───────────────────┘
   ┌────────────────┐
   │ YourExchange   │  ← implement 4 methods for a keyed feed
   └────────────────┘

models: CryptoMarket · CryptoBar · CryptoTicker · FundingRate · Timeframe · MarketType
```

**Coinbase pagination.** The public candles endpoint returns max 300
candles per request; the provider pages `[start, end)` automatically in
`300 × granularity` windows and merges/sorts/dedupes. Public rate limit
is ~10 req/s; the provider throttles (default 0.15 s) and retries with
backoff.

**yfinance scope.** 15 liquid majors vs USD, daily + intraday; `H4` is
resampled from 1h bars. It's a convenience feed — Coinbase is the
primary free source.

## Adding a provider

```python
from trade_data_crypto import CryptoDataProvider

class MyExchange(CryptoDataProvider):
    name = "myexchange"
    delay_minutes = 0

    def get_markets(self, quote=None, market_type=None) -> list[CryptoMarket]: ...
    def get_bars(self, symbol, timeframe, start, end) -> list[CryptoBar]: ...
    def get_ticker(self, symbol) -> CryptoTicker: ...          # optional
    def get_funding_rates(self, symbol, start, end) -> list[FundingRate]: ...  # optional
```

`get_ticker` / `get_funding_rates` already default to "unsupported", so a
spot-only feed implements two methods. Normalize every symbol to
`BASE/QUOTE` with `canonical()` before building models.

## Interop with the other data engines

The engines are decoupled — this package imports no sibling — but they
compose by shape:

```python
from trade_data_crypto import CryptoDataClient, CoinbasePublicProvider, Timeframe, vwap

bars = CryptoDataClient(CoinbasePublicProvider()).get_bars(
    "BTC/USD", Timeframe.D1, start, end)

# CryptoBar mirrors the equity Bar and futures FuturesBar shapes
# (timestamp, OHLC, volume), so trade-backtest and trade-strategies
# consume all three asset classes through one code path. Crypto-only
# extras (quote_volume, trades) ride along as optional fields.
closes = [b.close for b in bars]

# FundingRate feeds trade-risk carry accounting for perp positions:
#   daily_cost = funding_apr(rate, interval_hours) / 365 * notional
```

## Scaling notes

- **Coinbase paging is O(windows)** — one HTTP call per 300-candle page;
  per-page results cache under the full-range key, so re-requests are free.
- **Per-symbol caching** keeps multi-symbol scans (top-50 universes) to
  one fetch per symbol per hour; share one `DiskCache` root across
  workers via `TRADE_CRYPTO_CACHE`.
- **Bars are immutable dataclasses** — safe to share across threads;
  `stream_bars` keeps memory flat over multi-year 1m histories.
- Timeframes are exchange-native granularities; no resampling except
  yfinance `H4`.

## API reference (essentials)

| Name | Kind | Purpose |
|---|---|---|
| `CryptoDataClient(provider, cache)` | class | Main entry point |
| `client.get_markets(quote, market_type)` | method | Listed markets (cached) |
| `client.require_market(symbol)` | method | Market or `MarketNotFoundError` |
| `client.get_bars(symbol, timeframe, start, end)` | method | OHLCV bars `[start, end)` |
| `client.get_ticker(symbol)` | method | Real-time quote (never cached) |
| `client.get_funding_rates(symbol, start, end)` | method | Perp funding (provider-dependent) |
| `client.stream_bars(...)` | method | Chunked iteration |
| `canonical` / `parse_pair` | functions | `BASE/QUOTE` symbology |
| `to_coinbase_id` / `to_binance_symbol` | functions | Exchange symbol forms |
| `vwap` / `funding_apr` | functions | Pure analytics |

## Testing

```bash
pip install "trade-data-crypto[dev]"
pytest -q
```

Fully offline: providers are faked, Coinbase pagination is tested
against stubbed HTTP, and calendars/math are hand-computed.
`examples/quickstart.py` is the live smoke test (network; yfinance leg
needs the extra).

## Roadmap

Sibling repositories:

- `trade-data-equities` — stock/ETF bars (done)
- `trade-data-options` — chains, Greeks, IV surfaces (done)
- `trade-data-futures` — specs, continuous contracts, term structure (done)
- `trade-data-crypto` — this repo
- `trade-backtest` — event-driven backtesting
- `trade-strategies` — strategy framework + starters
- `trade-risk` — position sizing, limits, drawdown guards
- `trade-agents` — hedge-fund desk: idea agents → portfolio-manager → risk-manager
- `trade-dashboard-web` / `trade-dashboard-desktop` — dashboards
- `trade-suite` — meta-package tying it all together

## License

MIT — see [LICENSE](LICENSE).
