"""Run three cost scenarios or write an explicit data-blocked status report."""
from pathlib import Path
from datetime import date, datetime, timezone
import argparse
import csv
import hashlib
import json
import subprocess
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import preservation
import reporting

TRADE_FIELDS = "symbol,side,entry_timestamp,entry_price,exit_timestamp,exit_price,quantity,entry_reason,exit_reason,gross_pnl,commissions,slippage_cost,spread_cost,net_pnl,duration_seconds".split(",")


def epoch(value):
    return int(datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc).timestamp())


def blocked(out, reasons, config):
    out.mkdir(parents=True, exist_ok=True)
    result = {"status": "BLOCKED_NO_HISTORICAL_EXECUTION", "requested_start": config["start"], "requested_end_inclusive": config["requested_end_inclusive"], "reasons": reasons, "initial_capital_default": config["initial_capital_usd"], "historical_performance": None, "historical_trades": None, "break_even_source": "absent_in_supplied_source", "synthetic_results_are_not_historical": True}
    (out / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    with (out / "trades.csv").open("w", newline="") as f:
        csv.writer(f).writerow(TRADE_FIELDS)
    (out / "report.md").write_text("# Historical backtest status\n\n**No historical backtest result is available.**\n\nRequested period: October 11, 2025 through October 11, 2026.\n\n" + "\n".join("- " + reason for reason in reasons) + "\n\nHistorical return, final equity, trade count, win rate, profit factor, drawdown, expectancy, Sharpe, monthly performance, and cost sensitivity are **N/A**, not zero. The header-only trades.csv records no executions and must not be interpreted as a zero-trade strategy result. No historical equity or returns charts are generated without market observations.\n\nThe supplied source has no implemented break-even or stop-loss management. Its only exit predicate is an SMA10 crossing. The isolated adapter reuses that supplied source and cannot validate the user's described break-even strategy.\n\nSee ../../README.md for reproducible build, tests, data acquisition and replay commands; ../../STRATEGY_AUDIT.md for source behavior; ../../DATA_FEASIBILITY.md for data limitations.\n", encoding="utf-8")
    print("Historical execution blocked: " + "; ".join(reasons))
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=BASE / "config.json")
    parser.add_argument("--data", type=Path, default=BASE / "data" / "ibkr" / "bars.csv")
    parser.add_argument("--manifest", type=Path, default=BASE / "data" / "ibkr" / "manifest.json")
    parser.add_argument("--sessions", type=Path, default=BASE / "data" / "ibkr" / "sessions.csv")
    parser.add_argument("--out", type=Path, default=BASE / "results" / "historical")
    parser.add_argument("--start", help="UTC start date; must match a separately acquired subset and its warm-up")
    parser.add_argument("--end", help="Exclusive UTC end date; must match the input's acquisition window")
    parser.add_argument("--synthetic", action="store_true", help="Unit-test fixtures only; labels all reports synthetic")
    args = parser.parse_args()
    args.out = args.out.resolve()
    if not args.out.is_relative_to(BASE):
        parser.error("All output must remain under backtesting/")
    cfg = json.loads(args.config.read_text())
    start = epoch(args.start or cfg["start"])
    end = epoch(args.end or cfg["end_exclusive"])
    if start >= end or cfg["initial_capital_usd"] <= 0:
        parser.error("Invalid dates or capital")
    if args.synthetic and args.out == BASE / "results" / "historical":
        parser.error("Select a separate --out directory for synthetic fixtures")
    if not preservation.verify():
        raise RuntimeError("Original files changed; stopping")
    reasons = []
    if not args.data.is_file():
        reasons.append("Required actual five-second intraday data and warm-up are unavailable: " + str(args.data))
    if not (BASE / "build" / "replay.exe").is_file():
        reasons.append("Replay executable is missing; run backtesting\\build.cmd")
    if reasons:
        return blocked(args.out, reasons, cfg)
    args.out.mkdir(parents=True, exist_ok=True)
    session_dates = None
    if not args.synthetic:
        if not args.manifest.is_file() or not args.sessions.is_file():
            return blocked(args.out, ["Historical input requires its source manifest and actual exchange-session calendar."], cfg)
        import validate_data
        coverage = validate_data.validate(args.data, args.sessions, args.manifest, start, end, cfg["symbols"])
        (args.out / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        if coverage["errors"]:
            return blocked(args.out, coverage["errors"], cfg)
        session_dates = {row["session"][:4]+"-"+row["session"][4:6]+"-"+row["session"][6:8] if "-" not in row["session"] else row["session"] for row in coverage["session_coverage"]}
    (args.out / "status.json").write_text(json.dumps({"status": "RUNNING", "synthetic": args.synthetic, "note": "Existing scenario files are not results of this run until status is COMPLETE."}, indent=2)+"\n")
    comparison = []
    for name, scenario in cfg["scenarios"].items():
        destination = args.out / name
        destination.mkdir(parents=True, exist_ok=True)
        cmd = [str(BASE / "build" / "replay.exe"), "--data", str(args.data.resolve()), "--out", str(destination), "--start", str(start), "--end", str(end), "--capital", str(cfg["initial_capital_usd"]), "--leverage", str(cfg["max_leverage"])]
        for key, value in scenario.items():
            cmd += ["--" + key.replace("_", "-"), str(value)]
        if args.synthetic:
            cmd.append("--synthetic-test")
        result = subprocess.run(cmd, cwd=BASE, text=True, capture_output=True)
        (destination / "run.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            (args.out / "status.json").write_text(json.dumps({"status": "FAILED", "scenario": name, "error": "See scenario run.log", "synthetic": args.synthetic}, indent=2)+"\n")
            raise RuntimeError(f"Replay failed ({result.returncode}): {destination / 'run.log'}")
        try:
            perf = reporting.generate(destination, cfg["initial_capital_usd"], args.synthetic, session_dates)
        except Exception as exc:
            (args.out / "status.json").write_text(json.dumps({"status": "FAILED", "scenario": name, "error": str(exc), "synthetic": args.synthetic}, indent=2)+"\n")
            raise
        comparison.append({"scenario": name, "net_pnl": perf["net_pnl"], "net_return_percent": perf["net_return_percent"], "closed_trades": perf["total_closed_trades"], "max_drawdown_usd": perf["max_drawdown_usd"], "commissions": perf["total_commissions"], "estimated_execution_costs": perf["estimated_execution_costs"]})
    with (args.out / "cost_sensitivity.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(comparison)
    with args.data.open("rb") as f:
        data_sha256 = hashlib.file_digest(f, "sha256").hexdigest()
    (args.out / "run_manifest.json").write_text(json.dumps({"config": cfg, "start_epoch": start, "end_epoch": end, "synthetic": args.synthetic, "data_sha256": data_sha256, "adapter_manifest": json.loads((BASE / "build" / "adapter_manifest.json").read_text()), "comparison": comparison}, indent=2) + "\n")
    if not preservation.verify():
        (args.out / "status.json").write_text(json.dumps({"status": "FAILED", "error": "Preservation verification failed", "synthetic": args.synthetic}, indent=2)+"\n")
        raise RuntimeError("Original file preservation verification failed after replay")
    (args.out / "status.json").write_text(json.dumps({"status": "COMPLETE", "synthetic": args.synthetic}, indent=2)+"\n")
    print(json.dumps(comparison, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
