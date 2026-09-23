"""End-to-end smoke test: Coinbase spot data + yfinance cross-check.

Coinbase public endpoints need no API key. The yfinance leg needs:
    pip install "trade-data-crypto[yfinance]"
"""

from datetime import date, timedelta

from trade_data_crypto import (
    CoinbasePublicProvider,
    CryptoDataClient,
    Timeframe,
    YFinanceCryptoProvider,
    funding_apr,
    vwap,
)


def main() -> None:
    cb = CryptoDataClient(CoinbasePublicProvider())
    end = date.today()
    start = end - timedelta(days=30)

    markets = cb.get_markets(quote="USD")
    print(f"Coinbase USD spot markets: {len(markets)}")

    bars = cb.get_bars("BTC/USD", Timeframe.D1, start, end)
    print(f"BTC/USD: {len(bars)} daily bars, "
          f"{bars[0].timestamp.date()} -> {bars[-1].timestamp.date()}, "
          f"last {bars[-1].close:,.2f}, 30d VWAP {vwap(bars):,.2f}")

    ticker = cb.get_ticker("BTC/USD")
    print(f"Ticker: last {ticker.last:,.2f}, spread {ticker.spread_bps:.1f} bps, "
          f"24h vol {ticker.base_volume_24h:,.1f} BTC")

    # yfinance cross-check on ETH.
    try:
        yf = CryptoDataClient(YFinanceCryptoProvider())
        eth = yf.get_bars("ETH/USD", Timeframe.D1, start, end)
        print(f"yfinance ETH/USD: {len(eth)} daily bars, last {eth[-1].close:,.2f}")
    except Exception as exc:  # noqa: BLE001 - optional leg
        print(f"yfinance leg skipped: {exc}")

    # Funding math demo (perps need a keyed exchange feed).
    print(f"0.01%/8h funding ~= {funding_apr(0.0001):.2%} APR for longs")


if __name__ == "__main__":
    main()
