# Audit of the provided C++ strategy

On October 13, 2026 the user selected the earlier audited version **with SMA10 exits** after the current production file was externally changed to comment out its exit block. The exact earlier `main.cpp` is preserved under `source_snapshot/main.cpp`; its SHA-256 matches the initial audit pin. Current production source remains untouched. `SOURCE_DRIFT.md`, `source_drift.json`, and `source_selection.json` record the difference and explicit selection. References below describe that selected earlier version.

The inspected source contains **no break-even mechanism, stop-loss order, or stop-level update**. A one-year result described as reproducing the requested break-even strategy cannot be certified from these files. The adapter preserves the available strategy; it does not invent missing behavior.

All references below are relative to the original project root. Original source and build files are read only. The separate backtesting build compiles `traderBot/DataFetcher.cpp` directly, without edits, and extracts exact source bytes from the selected `main.cpp` snapshot into `backtesting/build/strategy_adapter.generated.cpp`. Source hashes, actual source paths, selection metadata and fragment hashes appear in `backtesting/build/adapter_manifest.json`. Generation fails if the selected snapshot, any other pinned source, or the observed current production main file changes. This is source identity verification, not a replacement for Git verification.

## Active rules

| Rule | Exact behavior | Original source |
|---|---|---|
| Time | Asia/Jerusalem local time, inclusive 16:35:10 and exclusive 17:01:00 | `DataFetcher.cpp:32-48` |
| Candle | Second-last supplied five-minute bar; body >= 70% of high-low range; close > open is green, close < open is red | `DataFetcher.cpp:5-31` |
| Distance | `abs(lastPrice-yesterdayClose) < ATR*0.40`, strictly less | `main.cpp:320-322` |
| Long | SMA20 > SMA200, green candle, price > SMA20 | `main.cpp:324-327` |
| Short | SMA20 < SMA200, red candle, price < SMA20 | `main.cpp:329-332` |
| Indicators | SMA10/20/200 include the last supplied close; insufficient history returns zero | `DataFetcher.cpp:103-156` |
| ATR | Fourteen true ranges averaged for the seed, then EMA with alpha `2/15`; not Wilder smoothing | `DataFetcher.cpp:63-101` |
| Risk | Fixed $30 | `DataFetcher.h:47` |
| Quantity | Long `floor(abs(30/(price-candleLow)))`; short `floor(abs(30/(candleHigh-price)))`; candle extremes from second-last supplied bar | `main.cpp:168-173`; `DataFetcher.cpp:176-205` |
| Entry | Market order; outside regular trading hours allowed; GTC | `main.cpp:163-193` |
| Exit | Market exit when long price < SMA10 or short price > SMA10; equality does not exit | `main.cpp:203-224` |

Gap status, QQQ trend, volume, open price, SMA10 and price optimization are passed/logged but do not filter entries. QQQ trend is explicitly unimplemented (`DataFetcher.cpp:220-223`). `OrderInstructions.stopLoss` is unused (`OrderInstructions.h:6`); `DataFetcher.getStopLoss()` has only a declaration (`DataFetcher.h:48`). Candle extremes determine quantity but do not create a protective stop.

## Reused bytes and adapted boundaries

The generator copies `main.cpp:289-337` (the complete `analyzeData` function), `main.cpp:172-173` (quantity statements), `main.cpp:209-210` (exit condition), and `DataFetcher.cpp:47-48` (time predicate) without changing any fragment byte. Wrapper functions provide the same variables around these fragments. The signal function invokes original `DataFetcher` methods and supplies historical Jerusalem time instead of wall-clock time. Display color constants are empty in the offline adapter. These do not participate in decisions.

The build uses installed TWS API types, `Decimal.cpp`, and Intel `libbid.lib`. It does not link the broker client, `IbApi.cpp`, or the live `main()` function. It creates no broker connection and cannot submit broker orders. All object files, generated files and executables are placed under `backtesting/build/`.

The live quantity code converts to `int` before testing invalid results. The adapter explicitly rejects zero/nonfinite divisors and values outside integer range before conversion, returning zero and assigning no simulated fill. It also preserves the source's `lastPrice == candleLow` rejection for either side. This defensive treatment makes undefined arithmetic auditable; it is not a claim about how a particular live compiler might handle undefined conversion.

## Replay fidelity limits that must remain explicit

- Historical requests are regular-hours TRADES: daily ATR uses six months; yesterday-close/open data uses one week; five-minute SMA10/20 use two days and SMA200 four days (`IbApi.cpp:70-156`). Current daily and five-minute snapshots can contain partial bars. Only information available at each snapshot time may enter indicators; complete future daily/5-minute bars would introduce lookahead.
- The historical refresh deadline is the next five-minute boundary plus nine seconds. Within each snapshot, analysis runs roughly every two seconds, using the most recently received five-second trade-bar close (`main.cpp:78,93,140,231`). Network completion and polling phase are not recoverable from OHLC alone.
- The fixed Jerusalem entry window must remain fixed in that timezone. US/Israel DST mismatch weeks change its relationship to the New York market open.
- Open/closed flags are initialized once per symbol worker and never reset (`main.cpp:86-87,160,197,223`). Literal process behavior allows at most one entry per symbol over its lifetime. Daily restart is an explicitly different deployment assumption.
- Shared integer buying power starts at $10,500 (`main.cpp:37`), is decremented on entry (`194`), and is never replenished on exit. The compound decrement converts trade notional to integer. Both long and short entries consume this balance.
- Invalid quantity, excessive notional, or insufficient buying power causes the symbol worker to return permanently (`main.cpp:174-186`). There is no automatic end-of-day liquidation.
- Concurrent symbol workers make balance checks and submissions nondeterministic. A replay must disclose its deterministic order among simultaneous symbols.
- Source records positions on order submission, without waiting for fills. Historical bid/ask, latency, commissions, slippage, rejected orders and partial fills are absent from the strategy. They belong to a separately labeled execution model.
- The source has no take-profit or break-even trigger, initial protective stop, trailing stop, or updated stop level to reproduce. Stop and break-even output fields must say unavailable, rather than fabricate zero-dollar stop trades or invent a risk multiple.

## Validation and preservation

`build.cmd --adapter-only` builds the adapter checks. `build/adapter_tests.exe` checks historical time boundaries including DST mismatch, ATR seed and EMA recurrence, SMA windows, second-last candle selection, sizing and invalid arithmetic, complete long/short signal paths, and strict SMA10 exit comparisons. These synthetic fixtures validate implementation; they are not market-performance observations.

At initial audit, `git` returned `fatal: not a git repository` in the requested project. Consequently an assertion that originally tracked files are unchanged using Git cannot currently be made. The parent workflow records original-file SHA-256 values before and after new work and records the Git limitation separately. Do not initialize a new Git repository and present that as historical preservation verification.

Read-only inspection of the nearby `trading_engine_project` and `BuyHighSellLow` projects did not find the requested break-even implementation or a Git checkout. They are different applications and are not used as replacement strategy code.
