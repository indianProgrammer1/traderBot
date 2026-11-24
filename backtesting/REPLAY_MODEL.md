# Offline replay model

The executable calls the existing `DataFetcher.cpp` and the verified strategy
adapter. It has no broker connection or broker order API. All output belongs to
the separate `backtesting/` directory. This is a replay of the supplied source,
whose only implemented exit is the SMA10 comparison. The supplied source does
not implement a break-even trigger, stop update, stop order, or take-profit order.
Consequently this executable cannot verify the user's stated break-even behavior
until the corresponding source is supplied.

## Event ordering and observations

The input schema is
`symbol,start_epoch,end_epoch,open,high,low,close,volume,is_rth,kind`.
Timestamps are UTC Unix seconds. `is_rth` must come from historical session
metadata, including holidays and early closes. Rows are sorted by `end_epoch`
then symbol; kinds are `history1d`, `history5m`, and `realtime5s`.

Historical seed bars must end by the requested start. Five-second replay bars
must begin at or after the start and end by the exclusive end of the observation
interval. Five-second bars must have exactly five seconds' duration and lie on
the UTC five-second grid. Historical five-minute bars must have 300 seconds'
duration on that grid. Every price must be positive and finite, the OHLC range
must be internally consistent, and volume must be nonnegative. Duplicate,
overlapping, out-of-order, unknown-symbol, and malformed rows fail the run.

Each symbol requires at least 90 daily bars, daily history extending at least six
calendar months back (with a seven-day session tolerance), and at least 200 RTH
five-minute bars. The latest warmup observations must be within seven calendar
days of the requested start. These numerical checks do not establish that every
expected exchange session or trade is present: acquisition/coverage validation
must also be inspected. A non-synthetic run requires all ten production symbols.

For equal timestamps the engine processes:

1. Five-second bar completions: close/high/low/volume become observable.
2. Pending orders at the newly observed five-second open.
3. A historical snapshot refresh if due.
4. Strategy evaluation if due.

A signal can never fill at an open whose timestamp is equal to, or earlier than,
its submission timestamp. Future bars can be parsed into a small lookahead
buffer, but their highs, lows, closes, and volumes never enter a decision before
completion. At an open only the open price is inspected.

Evaluation initially occurs at `--start` and every two seconds thereafter.
The first refresh is the next five-minute boundary plus nine seconds, matching
the source's initial `floor(now)+5 minutes+9 seconds` expression. Subsequent
refreshes occur every five minutes and restart the two-second evaluation phase.
The original entry gate uses historical `Asia/Jerusalem` civil time, including
its daylight-saving rules. Aggregation uses historical `America/New_York` dates.

Only completed RTH five-second bars update daily and five-minute aggregates.
Snapshots retain the newest, potentially incomplete daily/five-minute aggregate
and freeze it until the next refresh. This preserves the source's penultimate
candle selection and its use of the newest partial close inside moving averages.
Daily history rolls over six calendar months; five-minute history retains the
four most recent observed RTH trading dates. This is an explicit approximation
of an IBKR historical `4 D` response and requires comparison against broker
snapshots before claiming exact historical callback equivalence.

Reconstructed daily/five-minute bars can differ from broker historical bars
because of trade filtering, corrections, adjustments, and missing observations.
Start the ordinary year replay outside an active RTH session: the schema does not
seed the portion of a partially completed daily candle before an intraday start.
Missing five-second bars are never fabricated. Gaps are counted, including
ordinary overnight/weekend gaps, and reported for external session validation.

## Orders, cash, and execution

The source's $30 sizing formula and immutable $10,500 per-order restriction are
preserved. The internal integer cash budget starts at 10,500 and subtracts
`int(quantity * signal_price)` at submission. It is never restored on an exit
or simulated rejection. Invalid quantity/cash ends that symbol's worker. A
symbol receives at most one entry and one exit submission during the entire
run, as in one continuously running instance of the source. There is no daily
reset, forced liquidation, or invented restart policy.

Simultaneous symbols run in the production thread launch order:
TSLA, NFLX, CRWD, MRNA, AMD, NVDA, AAPL, ROKU, PDD, MSFT. The actual operating
system thread race cannot be reconstructed from historical OHLC; this fixed
order is a reproducibility assumption and can affect the shared cash budget.

Market fills use the next strictly later observed five-second open, with adverse
slippage and half-spread in basis points. The open is an observed trade price;
spread and slippage are configurable estimates. A per-order commission is the
greater of minimum commission and per-share commission times quantity.

**Liquidity is a causal proxy:** the entire quantity must fit within the previous
completed five-second bar's observed volume multiplied by `--max-participation`.
This never uses the future volume of the execution bar. It does not prove that
the next opening trade offered sufficient liquidity, and it is not a quote-book
execution model. Multiple orders at the same symbol/open consume this capacity.
Insufficient capacity, including zero prior volume, rejects the order in full;
there are no speculative partial fills or retries. Rejections are audited.

Actual cash, filled positions, and commissions are accounted independently of
the source's internal cash counter. Entry gross exposure is limited by all of:
initial capital times configured leverage, $10,500, and current equity after
estimated execution costs times leverage. This additional simulated broker
control rejects impossible fills. Holding losses can subsequently exceed the
initial entry leverage limit; no margin liquidation is invented. Borrow costs,
short availability, dividends, margin interest, and actual quote spread are not
known from OHLC and are not modeled.

The source toggles its submitted-order flags without waiting for execution
acknowledgments. The replay preserves these flags even after a simulated
rejection. An attempted exit without a filled position can open an unintended
opposite position because the source does not use a reduce-only order. Such a
fill is explicitly labeled `orphan_exit_after_rejected_entry` and receives the
same simulated broker funding/liquidity checks as any opening order. The source
has already set its closed flag, so that position remains unmanaged. Open
positions and pending orders at the end are reported; open positions remain
marked at the last observed price.

## Output interpretation

`orders.csv` records submissions, fills, rejections, and remaining pending
orders. `trades.csv` contains completed round trips. `equity.csv` records cash,
equity, gross exposure, realized gross P&L, unrealized gross P&L, cumulative
commissions, and cumulative estimated execution costs at completions/fills and
interval endpoints. `summary.json` contains replay counters and performance.

Fill prices already include slippage and spread. Thus trade `gross_pnl` is based
on those adverse fill prices, and `net_pnl = gross_pnl - commissions`.
`slippage_cost` and `spread_cost` disclose the embedded costs and must not be
subtracted again. Portfolio identity is
`equity = initial_capital + realized_gross_pnl + unrealized_gross_pnl - commissions`.

`--synthetic-test` labels every summary as synthetic verification and allows a
subset of the production universe. It never converts fabricated prices into a
market performance result. The ordinary replay status confirms execution of
the supplied rows, not exchange-session completeness or matching break-even
source. Real performance conclusions require verified coverage and strategy
identity in addition to an executable returning success.
