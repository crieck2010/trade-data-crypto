# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-26

### Added
- `KrakenPublicProvider`: free keyless spot data via Kraken public REST --
  AssetPairs market listings, auto-paginated OHLC (720 candles/page,
  `since=<last>` with boundary dedupe), tickers. Stdlib `urllib` only.
  Kraken error arrays mapped: rate-limit -> `RateLimitError`, unknown
  asset pair -> `MarketNotFoundError`.
- `BinanceUSPublicProvider`: free keyless spot data via Binance.US public
  REST -- exchangeInfo market listings (TRADING + SPOT filter), auto-
  paginated klines (1000 rows/page, `startTime = lastCloseTime + 1`), 24h
  tickers. Stdlib `urllib` only. Code -1121 -> `MarketNotFoundError`,
  HTTP 429/418 -> `RateLimitError`.
- `symbols.to_kraken_pair` (`BTC/USD` -> `XXBTZUSD`, `ETH/USD` ->
  `XETHZUSD`) and `symbols.to_binanceus_symbol` (`BTC/USD` -> `BTCUSD`);
  both exported from the package root.
- `docs/KRAKEN.md` and `docs/BINANCE_US.md`: endpoints, symbology,
  pagination, rate limits, field compromises, fee schedules (Kraken Pro
  spot 0.40%/0.80% entry tier; Binance.US spot 0%/0.02% flat), honest
  limitations.
- Offline test suites `tests/test_kraken.py` and `tests/test_binance_us.py`
  (scripted `_fetch` + monkeypatched `urlopen` for HTTP-error mapping).

## [0.1.0] - 2026-09-23

### Added
- Core models: `CryptoMarket` (spot/perp/future), `CryptoBar` (OHLCV +
  quote volume + trade count), `CryptoTicker` (bid/ask, 24h stats, spread
  in bps), `FundingRate`, `Timeframe`, `MarketType`.
- `symbols`: canonical `BASE/QUOTE` parsing and conversion to Coinbase /
  Yahoo (`BTC-USD`) and Binance (`BTCUSDT`) formats.
- `stats`: pure VWAP and funding-rate annualization helpers.
- `CryptoDataProvider` ABC (markets, bars, ticker, funding) with
  unsupported-method defaults.
- `CoinbasePublicProvider`: free keyless spot data via public REST --
  market listings, auto-paginated candles (300/page), tickers. Stdlib
  `urllib` only.
- `YFinanceCryptoProvider`: free bars/tickers for 15 liquid majors via
  the yfinance package (optional extra), with 1h -> 4h resampling.
- `CryptoDataClient`: markets, bars, real-time ticker/funding
  pass-through, chunked `stream_bars`; `DiskCache` (stdlib JSON, 60-minute
  bar TTL, 24-hour market TTL; tickers never cached).
- Offline test suite incl. a stubbed-HTTP pagination test, and a
  comprehensive README.
