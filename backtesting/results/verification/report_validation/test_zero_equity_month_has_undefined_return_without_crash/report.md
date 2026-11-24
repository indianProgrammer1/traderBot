# SYNTHETIC VERIFICATION — performance

**Synthetic fixtures are invented unit-test inputs. They are not historical market observations.**

| Metric | Value |
|---|---:|
| initial capital | 1000 |
| final equity | 10.000000 |
| net pnl | -990.000000 |
| net return percent | -99.000000 |
| total closed trades | 0 |
| winning trades | 0 |
| losing trades | 0 |
| flat trades | 0 |
| win rate percent | N/A |
| average winning trade | N/A |
| average losing trade | N/A |
| profit factor | N/A |
| max drawdown usd | 1000.000000 |
| max drawdown percent | 100.000000 |
| average pnl per trade | N/A |
| expectancy per trade | N/A |
| total commissions | 0.000000 |
| estimated execution costs | 0.000000 |
| sharpe ratio | N/A |
| sharpe observations | 2 |

Portfolio P&L includes marked open positions; trade statistics include closed trades only. Monthly P&L is change in marked portfolio equity, not a sum of exits. Slippage/spread already affect execution prices and are not deducted twice. Open positions are not forcibly liquidated.

252 annualization; zero risk-free rate; last observation of each validated NY session. A verified exchange-session calendar and at least20 session returns are required. Otherwise N/A. Artificial weekend/holiday boundary observations are excluded when a calendar is supplied.

![Equity](equity.svg)

![Drawdown](drawdown.svg)

![Monthly returns](monthly_returns.svg)

| Month | Trades | Wins | Losses | Net P&L | Return % | Max DD USD | Max DD % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-01 | 0 | 0 | 0 | -1000.0000 | -100.0000 | 1000.0000 | 100.0000 |
| 2026-02 | 0 | 0 | 0 | 10.0000 | N/A | 0.0000 | 0.0000 |
