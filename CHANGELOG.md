# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
