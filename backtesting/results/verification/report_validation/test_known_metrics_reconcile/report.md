# SYNTHETIC VERIFICATION — performance

**Synthetic fixtures are invented unit-test inputs. They are not historical market observations.**

| Metric | Value |
|---|---:|
| initial capital | 1000 |
| final equity | 1050.000000 |
| net pnl | 50.000000 |
| net return percent | 5.000000 |
| total closed trades | 3 |
| winning trades | 1 |
| losing trades | 1 |
| flat trades | 1 |
| win rate percent | 33.333333 |
| average winning trade | 100.000000 |
| average losing trade | -50.000000 |
| profit factor | 2.000000 |
| max drawdown usd | 50.000000 |
| max drawdown percent | 4.545455 |
| average pnl per trade | 16.666667 |
| expectancy per trade | 16.666667 |
| total commissions | 0.000000 |
| estimated execution costs | 0.000000 |
| sharpe ratio | N/A |
| sharpe observations | 4 |

Portfolio P&L includes marked open positions; trade statistics include closed trades only. Monthly P&L is change in marked portfolio equity, not a sum of exits. Slippage/spread already affect execution prices and are not deducted twice. Open positions are not forcibly liquidated.

252 annualization; zero risk-free rate; last observation of each validated NY session. A verified exchange-session calendar and at least20 session returns are required. Otherwise N/A. Artificial weekend/holiday boundary observations are excluded when a calendar is supplied.

![Equity](equity.svg)

![Drawdown](drawdown.svg)

![Monthly returns](monthly_returns.svg)

| Month | Trades | Wins | Losses | Net P&L | Return % | Max DD USD | Max DD % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-01 | 3 | 1 | 1 | 50.0000 | 5.0000 | 50.0000 | 4.5455 |
