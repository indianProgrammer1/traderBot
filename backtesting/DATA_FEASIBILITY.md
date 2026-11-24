# Historical data feasibility — updated 2026-10-13

No eligible historical replay dataset was available at inspection. This is a data-access finding, not a zero-trade performance result.

## Inputs required by the source

The fixed source universe is TSLA, NFLX, CRWD, MRNA, AMD, NVDA, AAPL, ROKU, PDD, MSFT (`traderBot/main.cpp:245`). There is no historical screener to reconstruct. The universe still has selection bias: the source contains today's chosen symbols, not evidence that they were chosen before the backtest period.

| Input | Live request | Purpose |
| --- | --- | --- |
| Five-second trade bars | `reqRealTimeBars(..., 5, "TRADES", false, ...)` | Latest completed bar close; extended-hours enabled |
| Five-minute RTH bars, two-day request | `getSma20bars` | SMA10, SMA20, penultimate signal candle |
| Five-minute RTH bars, four-day request | `getSma200bars` | SMA200 |
| Daily RTH bars, six-month request | `getATRbars` | 14-period true range seeded as arithmetic mean, then EMA with alpha 2/15 |
| Daily RTH bars, one-week request | `getYesderdayClose` | Penultimate close and latest bar open |

The entry clock is **Asia/Jerusalem, 16:35:10 inclusive to 17:01 exclusive**, not a fixed US exchange opening offset (`DataFetcher.cpp:47`). Israel and US daylight saving changes do not coincide. The strategy checks on an approximately two-second timer and refreshes historical snapshots on five-minute boundaries plus nine seconds (`main.cpp:93,231`). Historical requests end at the request time; recreating a currently forming daily/five-minute bar from the final full bar would leak future information. Those partial bars must be reconstructed only from observations available at that event.

## Local evidence

- No `.csv`, `.parquet`, `.json`, `.db`, or `.sqlite` price dataset was found in the trading repository before implementation.
- Broker connectivity is unverified. The sandbox denied the socket probe (`WinError 10013`) and the TCP listener inventory (CIM resource access denied). Earlier empty output with suppressed errors did **not** prove that TWS was absent. The production connection targets 127.0.0.1:7497. The live engine was not launched; no broker request or order was sent by the blocked probe.
- The attempted escalated listener inventory ultimately returned **aborted by user**. No escalated socket/listener check completed and no historical acquisition occurred. [Connectivity evidence](data/ibkr/connectivity_status.json) records these outcomes without inferring whether TWS is running.
- Official Python API source exists at `C:\TWS API\source\pythonclient\ibapi`, but `ibapi` is not installed on the default Python import path. The adapter can read this source without changing it.
- Sibling project `C:\Users\yahav\source\repos\stocksData` contains a CSV reader referencing `C:\Users\yahav\PyCharmMiscProject\AAPL.csv`. That file contains daily AAPL data from 2025-05-30 through 2025-06-13. It is outside the requested period, lacks the required intraday resolution, and is too short for the full warm-up. It cannot supply a valid subset of this backtest.
- Standard Alpaca/Databento API-key environment variables were absent. No secret values were printed or copied.

## IBKR feasibility and limits

IBKR's current documentation says native bars of 30 seconds or less are unavailable more than six months back. A direct five-second-bar download therefore cannot cover 2025-10-11 through 2026-10-11. However, **historical Time & Sales is retained up to three years**. Historical `TRADES` ticks offer a possible full-period source, subject to the user's market-data entitlement and actual contract coverage. The API returns up to 1,000 requested ticks per page (possibly more to complete a second); pagination and archival are necessary. Aggregating historical ticks to five-second bars is a documented reconstruction, not proof of an exact match to the original real-time feed.

Sources: [Unavailable Historical Data](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/unavailable-historical-data), [Requesting Time and Sales data](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-time-sales/requesting-time-and-sales-data).

For small bars, requests must avoid identical requests within 15 seconds, six or more same-contract/exchange/tick-type requests within two seconds, and more than 60 requests in ten minutes. A single sequential queue with conservative spacing and retry backoff is appropriate. A full-year, ten-symbol tick download can be substantial and is not a single API request.

Source: [Pacing Violations for Small Bars](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/pacing-violations-for-small-bars-30-secs-or-less).

IBKR also documents filtering, compression, and adjustment differences between current historical data and historical live observations. In particular, corporate actions and historical revisions require consistent pricing bases across daily warm-up and intraday data. Native historical bars are evidence of historical prices, not an archive of exactly what this application saw live.

Source: [Historical Data Filtering](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/historical-data-filtering).

## Alternatives investigated

- **Alpaca historical SIP trades:** The official FAQ says SIP history ending at least 15 minutes ago is accessible without a paid subscription. Historical trade pagination can supply subminute input, but valid API credentials are required. No credentials are available here. Feed and sale-condition handling must be declared; an IEX-only feed must not silently replace the full-market data source. [Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), [Historical trades endpoint](https://docs.alpaca.markets/us/reference/stocktradesingle-1).
- **Databento:** Provides historical tick data, requires an API key, and uses metered or subscription pricing. No request, account creation, or purchase was made. [Official getting-started documentation](https://databento.com/docs/getting-started/build-first-app?historical=http&live=http).
- Daily or one-minute data cannot recover this strategy's sequence of five-second closes. No coarser series is promoted to a valid five-second backtest, and no price bars are fabricated to fill unavailable history.

## What is needed to continue

Enable the TWS/Gateway API in an authenticated session with historical market-data permission, or provide a licensed historical trade/five-second archive with daily and five-minute warm-up. Preserve raw inputs, record their source, validate all ten symbols and session coverage, and verify corporate-action consistency before interpreting performance. A full-year numerical result is unavailable until those requirements are satisfied. There is currently no scientifically valid local subset of the requested period.
