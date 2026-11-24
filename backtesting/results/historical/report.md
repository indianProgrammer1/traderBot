# Historical backtest status

**No historical backtest result is available.**

Requested period: October 11, 2025 through October 11, 2026.

- Required actual five-second intraday data and warm-up are unavailable: C:\Users\yahav\source\repos\traderBot\backtesting\data\ibkr\bars.csv

Historical return, final equity, trade count, win rate, profit factor, drawdown, expectancy, Sharpe, monthly performance, and cost sensitivity are **N/A**, not zero. The header-only trades.csv records no executions and must not be interpreted as a zero-trade strategy result. No historical equity or returns charts are generated without market observations.

The supplied source has no implemented break-even or stop-loss management. Its only exit predicate is an SMA10 crossing. The isolated adapter reuses that supplied source and cannot validate the user's described break-even strategy.

See ../../README.md for reproducible build, tests, data acquisition and replay commands; ../../STRATEGY_AUDIT.md for source behavior; ../../DATA_FEASIBILITY.md for data limitations.
