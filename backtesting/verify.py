"""Controlled synthetic integration tests. No fixture is historical market data."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import csv
import hashlib
import json
import math
import subprocess
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import reporting

NY = ZoneInfo("America/New_York")
FIELDS = "symbol,start_epoch,end_epoch,open,high,low,close,volume,is_rth,kind".split(",")


def epoch(day, hour=9, minute=30, second=0):
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=NY).timestamp())


def write(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["end_epoch"], r["symbol"], r["kind"], r["start_epoch"])))


def fixture(path, side="BUY", unknown_future_low=88):
    day = datetime(2026, 1, 20).date()
    start = epoch(day)
    rows = []
    def add(t, duration, o, h, low, c, kind, volume=10000):
        rows.append(dict(zip(FIELDS, ["TSLA", t, t+duration, o, h, low, c, volume, 1, kind])))
    previous = day - timedelta(days=210)
    while previous < day:
        if previous.weekday() < 5:
            add(epoch(previous), 23400, 100, 110, 90, 100, "history1d")
        previous += timedelta(days=1)
    # Five complete synthetic sessions provide the requested 200-bar warm-up.
    warm_days = []
    previous = day - timedelta(days=1)
    while len(warm_days) < 5:
        if previous.weekday() < 5:
            warm_days.append(previous)
        previous -= timedelta(days=1)
    opens = [epoch(d) + i*300 for d in sorted(warm_days) for i in range(78)]
    for i, t in enumerate(opens):
        c = 100 if i >= len(opens)-20 else (90 if side == "BUY" else 110)
        add(t, 300, c-.1, c+.2, c-.2, c, "history5m")
    for offset in range(0, 420, 5):
        if offset < 300:
            o = 100 + (2 if side == "BUY" else -2) * offset/300
            c = 100 + (2 if side == "BUY" else -2) * (offset+5)/300
        elif offset < 320:
            # Source rejects lastPrice==candleLow even for a short; preserve it.
            o = c = 102 if side == "BUY" else 98.2
        else:
            o = c = 90 if side == "BUY" else 110
        h, low = max(o,c), min(o,c)
        if offset == 315:
            # Future high/low in an order's fill bar must not affect its OPEN fill.
            low = min(low, unknown_future_low)
        add(start + offset, 5, o, h, low, c, "realtime5s")
    write(path, rows)
    return start, start + 420, rows


def csvrows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def run(data, out, start, end, costs=True, expect_ok=True):
    cmd = [str(BASE / "build" / "replay.exe"), "--data", str(data), "--out", str(out), "--start", str(start), "--end", str(end), "--capital", "4200", "--leverage", "2.5", "--commission-per-share", ".005" if costs else "0", "--min-commission", "1" if costs else "0", "--slippage-bps", "1" if costs else "0", "--half-spread-bps", "1" if costs else "0", "--synthetic-test"]
    result = subprocess.run(cmd, cwd=BASE, text=True, capture_output=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "test.log").write_text(result.stdout + result.stderr)
    if expect_ok and result.returncode:
        raise AssertionError(f"Replay failed: {result.stdout}\n{result.stderr}")
    if not expect_ok and result.returncode == 0:
        raise AssertionError("Invalid input was accepted")
    return result


def close(a, b, message):
    if not math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6):
        raise AssertionError(f"{message}: {a} != {b}")


def main():
    output = BASE / "results" / "verification"
    output.mkdir(parents=True, exist_ok=True)
    checked = []
    adapter = subprocess.run([str(BASE / "build" / "adapter_tests.exe")], cwd=BASE, capture_output=True, text=True)
    (output / "adapter_tests.log").write_text(adapter.stdout + adapter.stderr)
    if adapter.returncode:
        raise AssertionError(adapter.stdout + adapter.stderr)
    checked.append("Original adapter indicator/signal/time/sizing/exit tests pass")
    data = output / "SYNTHETIC_LONG.csv"
    start, end, rows = fixture(data)
    run(data, output / "long_a", start, end)
    run(data, output / "long_b", start, end)
    for name in ("trades.csv", "equity.csv", "orders.csv", "summary.json"):
        if (output / "long_a" / name).read_bytes() != (output / "long_b" / name).read_bytes():
            raise AssertionError("Nondeterministic output: " + name)
    checked.append("Identical inputs produce byte-identical trades/equity/orders/summary")
    trades = csvrows(output / "long_a" / "trades.csv")
    if len(trades) != 1 or trades[0]["side"] != "BUY":
        raise AssertionError(f"Expected one closed original-strategy long trade, got {trades}")
    t = trades[0]
    if int(t["entry_timestamp"]) < start+315:
        raise AssertionError("Entry used an open from before the signal could be known")
    if int(t["exit_timestamp"]) <= int(t["entry_timestamp"]):
        raise AssertionError("Invalid trade chronology")
    close(t["gross_pnl"], (float(t["exit_price"])-float(t["entry_price"]))*int(t["quantity"]), "Long gross P&L")
    close(t["net_pnl"], float(t["gross_pnl"])-float(t["commissions"]), "Costs not double-counted")
    equity = csvrows(output / "long_a" / "equity.csv")
    close(equity[-1]["equity"], 4200 + float(t["net_pnl"]), "Closed-position portfolio reconciliation")
    checked.append("Original long signal submits/fills/exits once; causal fills and net accounting reconcile")
    run(data, output / "zero_cost", start, end, costs=False)
    zero = csvrows(output / "zero_cost" / "trades.csv")[0]
    if float(t["net_pnl"]) >= float(zero["net_pnl"]):
        raise AssertionError("Execution friction did not reduce P&L")
    checked.append("Commissions/spread/slippage reduce controlled-trade P&L")
    variant = output / "SYNTHETIC_FUTURE_LOW.csv"
    fixture(variant, unknown_future_low=1)
    run(variant, output / "future_variant", start, end)
    vt = csvrows(output / "future_variant" / "trades.csv")[0]
    for key in ("entry_timestamp", "entry_price", "quantity"):
        close(t[key], vt[key], "Future fill-bar low changed earlier entry " + key)
    checked.append("Changing unobserved fill-bar low cannot affect earlier signal, quantity or open fill")
    shortdata = output / "SYNTHETIC_SHORT.csv"
    fixture(shortdata, side="SELL")
    run(shortdata, output / "short", start, end)
    short = csvrows(output / "short" / "trades.csv")
    if len(short) != 1 or short[0]["side"] != "SELL":
        raise AssertionError("Expected one closed short trade")
    st = short[0]
    close(st["gross_pnl"], (float(st["entry_price"])-float(st["exit_price"]))*int(st["quantity"]), "Short gross P&L")
    close(csvrows(output / "short" / "equity.csv")[-1]["equity"], 4200+float(st["net_pnl"]), "Short account reconciliation")
    checked.append("Original short signal, exit and cash/liability accounting reconcile")
    summary = json.loads((output / "long_a" / "summary.json").read_text())
    close(summary["producer_cash_remaining"], 10500-int(float(t["quantity"])*102), "Source cash allowance stays spent after exit")
    orphan_rows = [dict(r) for r in rows]
    for r in orphan_rows:
        if r["kind"] == "realtime5s" and r["start_epoch"] == start+310:
            r["volume"] = 1
    orphan_file = output / "SYNTHETIC_ORPHAN.csv"
    write(orphan_file, orphan_rows)
    run(orphan_file, output / "orphan", start, end)
    orphan = json.loads((output / "orphan" / "summary.json").read_text())
    if orphan["closed_trades"] != 0 or orphan["open_positions"] != 1 or orphan["coverage"][0]["open_entry_reason"] != "orphan_exit_after_rejected_entry":
        raise AssertionError("Rejected entry's later opposite market order must preserve source orphan-position behavior")
    checked.append("Unreplenished source cash and opposite order after rejected entry preserve production behavior")
    multi_rows = []
    universe = ["TSLA", "NFLX", "CRWD", "MRNA", "AMD", "NVDA", "AAPL", "ROKU", "PDD", "MSFT"]
    for symbol in universe:
        multi_rows.extend(dict(r, symbol=symbol) for r in rows)
    multi_file = output / "SYNTHETIC_MULTI.csv"
    write(multi_file, multi_rows)
    run(multi_file, output / "multi", start, end)
    multi = json.loads((output / "multi" / "summary.json").read_text())
    mt = csvrows(output / "multi" / "trades.csv")
    if [r["symbol"] for r in mt] != universe[:6] or multi["terminated_symbols"] != 4:
        raise AssertionError("Deterministic source launch order/shared buying-power selection differs")
    for row in csvrows(output / "multi" / "equity.csv"):
        close(float(row["equity"]), 4200+float(row["realized_pnl"])+float(row["unrealized_pnl"])-float(row["commissions"]), "Every-event portfolio reconciliation")
    checked.append("Ten simultaneous symbols obey stable launch order and shared cash; every equity event reconciles")
    duplicate = output / "INVALID_DUPLICATE.csv"
    write(duplicate, rows + [rows[-1]])
    run(duplicate, output / "rejected_duplicate", start, end, expect_ok=False)
    bad = output / "INVALID_FUTURE_WARMUP.csv"
    badrows = [dict(r) for r in rows]
    badrows[0]["start_epoch"], badrows[0]["end_epoch"] = start, start+23400
    write(bad, badrows)
    run(bad, output / "rejected_future", start, end, expect_ok=False)
    checked.append("Duplicate bars and warm-up data from the future are rejected")
    missing = output / "MISSING_WARMUP.csv"
    write(missing, [r for r in rows if r["kind"] != "history1d"])
    run(missing, output / "rejected_warmup", start, end, expect_ok=False)
    checked.append("Missing daily warm-up is rejected")
    performance = reporting.generate(output / "long_a", 4200, synthetic=True)
    if performance["total_closed_trades"] != 1 or performance["status"] != "SYNTHETIC_VERIFICATION_ONLY":
        raise AssertionError("Report failed synthetic labeling or trade count")
    close(performance["net_pnl"], t["net_pnl"], "Report P&L reconciliation")
    checked.append("Synthetic CSV/JSON/Markdown/charts are explicitly labeled and reconcile to accounting")
    auto_label = reporting.generate(output / "long_a", 4200)
    if auto_label["status"] != "SYNTHETIC_VERIFICATION_ONLY":
        raise AssertionError("Synthetic report must not be relabeled historical by omitting a flag")
    result = {"status": "PASS", "historical_market_data_used": False, "checks": checked}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
