# Binance.US provider

`trade_data_crypto.providers.BinanceUSPublicProvider` fetches spot
market data from Binance.US public REST — the keyless counterpart to
`CoinbasePublicProvider` and `KrakenPublicProvider`. It implements
`CryptoDataProvider` exactly, so the swap is one line and every
downstream engine (backtests, strategies, paper trading) works untouched.

This is the **Binance.US** (US-regulated) API, not Binance.com. No API
key is needed for any endpoint this provider uses.

## Endpoints used

All keyless, base `https://api.binance.us`:

| Call | Wire |
|---|---|
| `get_markets` | `GET /api/v3/exchangeInfo` |
| `get_bars` | `GET /api/v3/klines?symbol=BTCUSD&interval=5m&startTime=<ms>&endTime=<ms>&limit=1000` |
| `get_ticker` | `GET /api/v3/ticker/24hr?symbol=BTCUSD` |

Kline row shape:

```
[openTime, open, high, low, close, volume, closeTime,
 quoteAssetVolume, trades, takerBuyBaseVol, takerBuyQuoteVol, ignore]
```

## Symbol mapping

Binance.US lists **USD pairs, not USDT**, for the majors, so `BTC/USD`
→ `BTCUSD` via `symbols.to_binanceus_symbol` (plain concatenation —
distinct from `to_binance_symbol`, which targets Binance.com USDT
pairs). `get_markets` reads `baseAsset`/`quoteAsset` straight from
`exchangeInfo`, so there is no parsing ambiguity on the listing side.

## Timeframe mapping

| Suite `Timeframe` | Binance.US `interval` |
|---|---|
| `M1` | `1m` |
| `M5` | `5m` |
| `M15` | `15m` |
| `H1` | `1h` |
| `H4` | `4h` |
| `D1` | `1d` |

Exact native intervals — no resampling.

## Pagination

Klines cap at **1000 rows per response**. The provider pages with
`startTime = lastCloseTime + 1` until a short page arrives, then
merges/sorts. `endTime` is **inclusive** on the wire, so the request
window is `[cursor, stop_ms - 1]` against the engine's `[start, end)`
contract. A stuck-cursor guard breaks the loop if the cursor stops
advancing.

## Rate limits and politeness

- `min_interval` (default **0.35 s**): kline request weight scales with
  `limit`, so the provider stays polite by default.
- HTTP 429 **and 418** raise `RateLimitError` immediately (418 is
  Binance's IP auto-ban after repeated 429s — do not retry into it).
- 5xx / network errors retry with backoff (`2^attempt` s); after
  `max_retries` (default 3) the provider raises `ProviderError`.
- API errors arrive as HTTP 4xx with a JSON body
  `{"code": ..., "msg": ...}`: code **-1121** (Invalid symbol) →
  `MarketNotFoundError`, anything else → `ProviderError` (after
  `max_retries`). The mapping is factored into `_map_http_error()` so it
  is unit-testable without HTTP.

## Field compromises

Kline rows map as: `openTime` (ms) → `timestamp` (UTC, bar open),
`open/high/low/close` → OHLC, `volume` → `volume` (base currency),
`quoteAssetVolume` → `quote_volume`, `trades` → `trades`. Taker-buy
splits (`takerBuyBaseVol`, `takerBuyQuoteVol`) have no `CryptoBar`
counterpart and are dropped. Ticker fields map as: `bidPrice` → `bid`,
`askPrice` → `ask`, `lastPrice` → `last`, `highPrice`/`lowPrice` →
`high_24h`/`low_24h`, `volume` → `base_volume_24h`, `quoteVolume` →
`quote_volume_24h`. Markets keep only `status == "TRADING"` with
`"SPOT"` in `permissions`; `PRICE_FILTER.tickSize` → `tick_size`,
`LOT_SIZE.minQty` → `min_size`. Malformed rows are skipped, matching the
Coinbase provider's behavior.

## Fee schedule (spot)

For execution-cost modeling in `trade-backtest` / `trade-risk`. Numbers
retrieved **2026-09-26**:

| Maker | Taker | Volume tiers |
|---|---|---|
| **0%** | **0.02%** | none — flat on all spot pairs |

Per the April 2026 fee overhaul: zero maker fees and a flat 0.02% taker
fee on all spot pairs, with no volume tiers. Sources: crypto-economy.com
(2026-04), tradersunion.com (2026-04), cryptsy.com fee-page screenshot
captured 2026-07-08.

## Honest limitations

- **Cheapest taker fee of the three venues, thinnest order books.**
  Binance.US's 0.02% taker fee is the lowest in this engine, but its
  books are thinner than Kraken/Coinbase on most pairs — the fee saving
  can evaporate into spread/slippage. Model both.
- **`get_markets` is spot-only by filter.** `exchangeInfo` lists
  everything Binance.US offers; the provider keeps `TRADING` +
  `SPOT`-permission symbols only.
- **No derivatives.** Binance.US is spot-only, so `get_funding_rates`
  keeps the base-class "unsupported" default.
- **API surface drift.** Endpoint shapes were verified against public
  docs at build time; the defensive parsing skips malformed rows rather
  than crashing, and the scripted-`_fetch` mock lets you pin a new shape
  in tests before touching production code.
