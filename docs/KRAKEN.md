# Kraken provider

`trade_data_crypto.providers.KrakenPublicProvider` fetches spot market
data from Kraken's public REST API — the keyless counterpart to
`CoinbasePublicProvider`. It implements `CryptoDataProvider` exactly, so
the swap is one line and every downstream engine (backtests, strategies,
paper trading) works untouched.

## Endpoints used

All keyless, base `https://api.kraken.com`:

| Call | Wire |
|---|---|
| `get_markets` | `GET /0/public/AssetPairs` |
| `get_bars` | `GET /0/public/OHLC?pair=<krakenpair>&interval=<minutes>&since=<unixtime>` |
| `get_ticker` | `GET /0/public/Ticker?pair=<krakenpair>` |

OHLC response shape:

```json
{"error": [], "result": {"XXBTZUSD": [[time, open, high, low, close, vwap, volume, count], ...], "last": 1234567890}}
```

## Pair / symbology mapping

Kraken uses legacy asset codes: BTC is **XBT** (`XXBT` in pair keys),
ETH is `XETH`, USD is `ZUSD`. The provider maps through
`symbols.to_kraken_pair`:

| Canonical | Kraken pair |
|---|---|
| `BTC/USD` | `XXBTZUSD` |
| `ETH/USD` | `XETHZUSD` |

`to_kraken_pair` handles the majors only. Exotic pairs (SOL, DOGE, ...)
use Kraken's per-asset legacy naming (`SOLUSD`, `XXDGZUSD`, ...) which is
not fully rule-based — resolve the exact pair key via `get_markets`
(AssetPairs) instead of guessing. `get_markets` normalizes asset codes
back to canonical form (`XXBT` → `BTC`, `XETH` → `ETH`, `ZUSD` → `USD`)
best-effort; if an exotic base looks wrong, check the pair's `wsname` in
the raw AssetPairs payload.

## Timeframe mapping

| Suite `Timeframe` | Kraken `interval` (minutes) |
|---|---|
| `M1` | 1 |
| `M5` | 5 |
| `M15` | 15 |
| `H1` | 60 |
| `H4` | 240 |
| `D1` | 1440 |

These are Kraken's allowed OHLC intervals — the mapping is exact, no
resampling.

## Pagination

Kraken caps OHLC at **720 candles per response**. The provider pages with
`since=<last>` (the `last` id from the previous response) until a short
page arrives, then merges/sorts/dedupes. Note `since` is **inclusive**:
the boundary candle repeats on the next page and is deduped by timestamp,
so page boundaries never double-count a candle. A stuck-cursor guard
breaks the loop if `last` stops advancing.

## Rate limits and politeness

- `min_interval` (default 0.6 s) throttles between calls.
- HTTP 429 raises `RateLimitError` immediately (no retry — the caller
  backs off).
- 5xx / network errors retry with backoff (`2^attempt` s); after
  `max_retries` (default 3) the provider raises `ProviderError`.
- Kraken returns most API errors as **HTTP 200 with a non-empty `error`
  array**: `EAPI:Rate limit exceeded` → `RateLimitError`,
  `EQuery:Unknown asset pair` → `MarketNotFoundError`, anything else →
  `ProviderError`. The `error`-array check is factored into `_checked()`
  so the mapping is unit-testable without HTTP.

## Field compromises

OHLC rows map as: `time` → `timestamp` (UTC, bar open), `open/high/low/
close` → OHLC, `volume` → `volume` (base currency), `count` → `trades`.
Row `vwap` has no `CryptoBar` counterpart and is dropped. Ticker fields
map as: `b[0]` → `bid`, `a[0]` → `ask`, `c[0]` → `last` (`a`/`b`/`c` are
`[price, whole_lot_vol, lot_vol]` arrays — index 0 is taken), `v[1]` →
`base_volume_24h` (last-24h). Markets map `pair_decimals` →
`tick_size` (`10^-pair_decimals`), `ordermin` → `min_size`, `status ==
"online"` → `active`. Malformed rows are skipped, matching the Coinbase
provider's behavior.

## Fee schedule (spot, Kraken Pro)

For execution-cost modeling in `trade-backtest` / `trade-risk`. Numbers
retrieved **2026-09-26**:

| Tier (30d volume) | Maker | Taker |
|---|---|---|
| Tier 1 (entry) | **0.40%** | **0.80%** |
| Tier 3 ($10k+) | 0.22% | 0.38% |

Effective 2026-07-09. Sources: Kraken official blog, "Kraken Pro fee
tiers now reward what you hold" (blog.kraken.com, 2026-07-09), and the
Kraken fee schedule.

## Honest limitations

- **Data delay is zero-ish, fees are not.** The provider reports
  `delay_minutes = 0`, but the fee schedule above is what actually moves
  backtest P&L — Kraken's 0.80% entry taker fee is 40× Binance.US's
  0.02%, which is exactly why this engine exists: venue choice is an
  execution-cost decision, not a data decision.
- **Pair-key guessing is majors-only.** Anything beyond BTC/ETH vs USD
  should be resolved through `get_markets`; `to_kraken_pair` will produce
  a wrong key for exotic assets and the API will answer with
  `EQuery:Unknown asset pair` → `MarketNotFoundError`.
- **Asset-code normalization is best-effort.** Codes like `XAUT` strip to
  `AUT` incorrectly; the map covers the majors and common fiats.
- **API surface drift.** Endpoint shapes were verified against public
  docs at build time; the defensive parsing skips malformed rows rather
  than crashing, and the scripted-`_fetch` mock lets you pin a new shape
  in tests before touching production code.
