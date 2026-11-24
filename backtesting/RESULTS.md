# Execution assessment — October 13, 2026

**The offline implementation compiles and its controlled tests pass. The requested one-year historical backtest has not executed because no eligible market dataset is available.** Consequently there is no defensible historical profit/loss, return, drawdown, monthly consistency, or profitability conclusion.

## Confirmed work

- Built `build/replay.exe` and `build/adapter_tests.exe` with MSVC, using the original indicator implementation and four verified, byte-identical strategy fragments.
- Executed **40 C++ adapter checks**, **11 integration check groups**, **13 reporting/coverage tests**, and the downloader's **9 offline self-test groups**. All passed. These are synthetic verification results, not historical observations.
- Executed the three configured cost scenarios on a clearly labeled synthetic fixture. Higher execution friction reduced that controlled trade's P&L, confirming the cost plumbing. This says nothing about actual strategy profitability.
- Attempted the ordinary historical runner. It stopped at the missing required `data/ibkr/bars.csv` and produced an explicit blocked status, not fabricated returns or zero-trade performance.
- Recorded source identity, source selection, preservation checks, data-access evidence, repeatable commands, trade/order/equity export formats, metrics and chart generation.

## Strategy identity and preservation

The user selected the **earlier source with active SMA10 exits** on October 13. Between sessions, the production `traderBot/main.cpp` changed: two comment delimiters were added around the exit block. Removing only those four bytes in memory reproduced the original SHA-256 exactly. The selected snapshot is stored under `backtesting/source_snapshot/`; the current production file was left untouched.

The selected source has **no break-even trigger or stop-loss update implementation**. Candle low/high affects sizing only; exit is an SMA10 crossing. Therefore these deliverables cannot substantiate the originally described break-even mechanism. The report analyzes the source version the user explicitly selected.

All implementation writes remain under `backtesting/`. Of the 20 original source/build/configuration files, 19 match the initial baseline; the separately observed `main.cpp` change is recorded rather than hidden. The final guard checks its recorded current hash and the original snapshot hash. Git status/diff were attempted before and after, but this workspace has no `.git` repository, so verification of originally tracked files is unavailable. See [preservation result](preservation_after.json) and [source drift](SOURCE_DRIFT.md).

## Historical results

Requested period: October 11, 2025 through October 11, 2026, inclusive. Source symbols: TSLA, NFLX, CRWD, MRNA, AMD, NVDA, AAPL, ROKU, PDD, MSFT.

| Requested result | Current status |
|---|---|
| Initial capital | Configurable $4,200 default, inferred from source buying-power expression; not an account statement |
| Final equity, USD profit/loss, return | N/A — no historical execution |
| Trades, wins/losses, win rate | N/A — not a zero-trade result |
| Average win/loss, profit factor, expectancy | N/A |
| Maximum drawdown in USD and percent | N/A |
| Historical commissions/execution costs | N/A |
| Sharpe and monthly performance | N/A |
| Historical cost sensitivity | N/A; only synthetic plumbing verified |
| Favorable/unfavorable market conditions | Cannot determine |
| Full-year completeness | No eligible local intraday subset found |

## What is needed next

The downloader needs an accessible authenticated IBKR API session and relevant historical-data permissions, or an eligible licensed five-second/trade archive with daily and five-minute warm-up. The actual exchange calendar, gaps, pricing basis and source provenance must validate before interpretation. [DATA_FEASIBILITY.md](DATA_FEASIBILITY.md) records the latest connectivity evidence and investigates IBKR retention, historical ticks, local datasets and alternatives.

The replay reconstructs daily/five-minute snapshots from completed five-second observations, preserves the Jerusalem clock and source process lifecycle, and uses documented simulated execution. Historical filtering, snapshot arrival timing, concurrent thread ordering, liquidity, corporate actions, borrow and financing remain important limits. The six-month daily lookback and four-date five-minute snapshot are documented approximations of broker responses; exact historical callback equivalence requires archived snapshots. See [REPLAY_MODEL.md](REPLAY_MODEL.md).

[README.md](README.md) contains the exact build, test, acquisition and execution commands. [Verification results](results/verification/verification.json), [synthetic cost scenarios](results/synthetic_cost_sensitivity/cost_sensitivity.csv), and [historical blocked report](results/historical/report.md) keep verified infrastructure behavior separate from unavailable historical conclusions. Historical profitability, if later observed, would not prove future profitability.
