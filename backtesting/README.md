# Isolated backtest of the selected original SMA10 strategy

This directory contains an offline C++ replay executable, source adapter, IBKR historical-data downloader, coverage validator, focused tests, performance reports and cost scenarios. All new code, generated files, caches and output are under `backtesting/`. The replay executable has no broker connection/order API.

**No one-year historical performance result is available yet.** The completed executions use explicit synthetic fixtures to test correctness. Required actual intraday data and warm-up are not available locally. See [historical status](results/historical/report.md) and [data feasibility](DATA_FEASIBILITY.md). A header-only historical trades CSV means execution was blocked, not that the strategy made zero trades.

## Selected source and preservation

The user selected **the earlier source with active SMA10 exits** on October 13, 2026. During the interruption, the production `traderBot/main.cpp` acquired two comment delimiters disabling that exit block. We left the current production file untouched and reconstructed the original only in [source_snapshot/main.cpp](source_snapshot/main.cpp). Its SHA-256 exactly matches the initial baseline. See [source selection](source_selection.json), [drift evidence](SOURCE_DRIFT.md), and the before/after preservation JSON files.

The selected source contains **no break-even activation, protective stop, or stop update**. Its exit is the strict SMA10 crossing. The unused `OrderInstructions.stopLoss` field and unimplemented `DataFetcher.getStopLoss()` declaration do not create stop management. No missing break-even rule was invented. [Strategy audit](STRATEGY_AUDIT.md) documents every active condition.

The adapter compiles the untouched production `DataFetcher.cpp` and copies exact entry, sizing, exit and time-predicate bytes from the selected source into the isolated build. Four source hashes and fragment hashes are pinned. Source drift fails closed. Only the replay clock, data availability, event scheduling and broker execution boundary are adapted; their limitations are detailed in [replay model](REPLAY_MODEL.md).

This folder is **not a Git checkout**. `git status` and `git diff` were attempted before and after; both failed. We cannot claim verification of originally tracked files. SHA-256 and Git blob hashes cover all 20 original source/project/configuration files. Nineteen still match the initial baseline; the production `main.cpp` change is explicitly recorded. The source-selection guard verifies that it has not changed again and that the earlier snapshot matches the original baseline. No initial baseline was overwritten or replaced with a newly initialized repository.

## Build and verify

Run these commands from `C:\Users\yahav\source\repos\traderBot` in PowerShell:

```powershell
cmd /c backtesting\build.cmd
python backtesting\verify.py
python backtesting\test_reporting_validation.py
python backtesting\fetch_ibkr.py --self-test
python backtesting\preservation.py
```

The build uses installed Visual Studio 2022 C++, TWS API headers/`Decimal.cpp`, and Intel `libbid.lib`. It does not build or launch the live application. Override `VCVARS64_PATH`, `TWS_API_INCLUDE`, `LIBBID_PATH`, or `PYTHON_EXE` if the installed paths differ. All compiler outputs go to `backtesting/build/`.

`verify.py` runs the C++ adapter checks and controlled replay scenarios, writes [verification.json](results/verification/verification.json), and produces synthetic CSV/JSON/Markdown/SVG examples. It covers deterministic reruns, both trade directions, accounting, execution costs, future-data isolation, simultaneous symbol priority/cash limits, rejected-entry behavior, duplicate inputs, and warm-up validation. These are intentionally invented test inputs, not market observations.

The historical Python client reads the existing official API source without installing or changing it. It explicitly disables order mutation methods. Its self-test imports the API offline and verifies aggregation, pagination, duplicates, schedules and order guards. An installed protobuf generation/runtime-version warning may appear; it is not a successful broker connectivity test.

## Acquire actual data

Use an authenticated TWS/Gateway API session with historical-data permissions. The script defaults to the original local port 7497 and a separate client ID 71. It never uses live client ID 0 or launches the live trading engine.

```powershell
python backtesting\fetch_ibkr.py --probe --start 2025-10-11 --end 2026-10-12
python backtesting\fetch_ibkr.py --start 2025-10-11 --end 2026-10-12 --allow-tick-reconstruction
```

`--end` is exclusive UTC midnight, so October 12 includes the requested October 11. The default `--as-of` uses the current date in Asia/Jerusalem to assess retention. Pass another host/port only for your intended data session. Raw responses are cached, hashed and reused. Downloaded bars and actual exchange schedules are normalized under `data/ibkr/`, with request provenance and coverage manifests. Sequential requests, pacing delays and retries are implemented.

IBKR native five-second bars older than six months are unavailable. The explicit reconstruction option permits historical trade ticks for the older interval, then aggregates only observed trades. This may take substantial time for ten liquid symbols. It is not an exact archive of the application's historical real-time feed. The default without this option clips to available native retention and clearly records the missing period. For that subset, use `run.py --start` equal to the manifest's `effective_start`; do not claim it covers the full year.

Native historical bars and historical ticks can have different filtering/adjustment bases. Review corporate-action consistency before interpreting results. Missing intervals remain absent; prices are never filled synthetically. The validator rejects unverified five-second gaps and absent sessions. Only mark `missing_intervals_verified_no_trades` true in the manifest after independent raw-source evidence establishes that interpretation; it is not a switch for ignoring missing data. A calendar hash protects against accidentally omitting a holiday/early-close/session record after acquisition. The provider's schedule determines sessions, not an invented weekday calendar.

CSV format:

```text
symbol,start_epoch,end_epoch,open,high,low,close,volume,is_rth,kind
```

Rows are globally ordered by `end_epoch,symbol,kind,start_epoch`. Warm-up kinds are `history1d` and `history5m`, completed before replay start. Replay kind is `realtime5s`, with actual five-second intervals. Historical warm-up needs six months of RTH daily history plus at least 200 RTH five-minute bars. The downloader requests additional context. Begin on a day boundary, not in the middle of an RTH session. A different replay window requires a separately acquired/cache-generated dataset with matching warm-up; the engine does not silently splice a wider file.

## Run and inspect performance

```powershell
python backtesting\run.py
```

Configuration is in [config.json](config.json): requested dates, source symbols, capital, leverage and three cost scenarios. The $4,200 capital and 2.5 leverage defaults are inferred from the production `4200*2.5` buying-power expression, not an account statement. They remain configurable. Source risk stays $30 and its $10,500 restrictions remain unchanged.

`run.py` verifies original-file preservation and input provenance/coverage, then runs baseline, moderate and conservative execution friction without changing strategy parameters. It writes status, provenance, per-scenario trades/orders/equity/monthly CSVs, all requested performance metrics, Markdown reports, SVG equity/drawdown/monthly-return charts and `cost_sensitivity.csv`. Annual equity is processed as a stream; metrics use every event and chart samples retain half-hour extrema. Sharpe is omitted without enough verified session returns. Always check `status.json` before interpreting scenario folders from an earlier attempt.

The supplied process allows at most one entry per symbol over its lifetime, never restores its internal integer cash counter after exits, and has no daily restart or forced liquidation. We retain those behaviors. Actual filled positions and equity are accounted separately. Open positions remain marked, so portfolio P&L can differ from the sum of closed trades. Full details and material limitations—including unknown borrow/financing/dividends, estimated spread/slippage, a prior-volume liquidity proxy, asynchronous timing and reconstructed snapshot differences—are in [REPLAY_MODEL.md](REPLAY_MODEL.md).

To reproduce the cost-scenario plumbing with the synthetic test data after verification:

```powershell
python backtesting\run.py --synthetic --data backtesting\results\verification\SYNTHETIC_LONG.csv --start 2026-01-20 --end 2026-01-21 --out backtesting\results\synthetic_cost_sensitivity
```

Those scenario outputs test infrastructure only. They cannot establish historical return, favorable market conditions, annual consistency, drawdowns in actual markets, or whether the strategy remains profitable after costs. Those conclusions remain unavailable until an eligible, validated market dataset is replayed. Historical profitability, if later observed, would not establish future profitability.
