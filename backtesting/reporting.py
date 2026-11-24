"""Reports from offline replay output; synthetic reports stay explicitly labeled."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import argparse
import csv
import json
import math
import statistics
import html

NY = ZoneInfo("America/New_York")


def read_csv(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def stamp(value):
    return datetime.fromtimestamp(int(float(value)), NY)


def number(row, key):
    return float(row.get(key, 0) or 0)


def drawdown(values, initial):
    peak = initial
    usd = percent = 0.0
    for value in values:
        peak = max(peak, value)
        usd = max(usd, peak - value)
        if peak > 0:
            percent = max(percent, (peak - value) / peak * 100)
    return usd, percent


def svg_line(path, values, title, percent=False):
    if not values:
        return
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    pts = " ".join(f"{60 + i * 800 / max(1, len(values)-1):.2f},{260 - (v-lo)*200/(hi-lo):.2f}" for i, v in enumerate(values))
    unit = "%" if percent else " USD"
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="920" height="320" viewBox="0 0 920 320">
<rect width="920" height="320" fill="#fff"/><g font-family="sans-serif" fill="#182c42">
<text x="30" y="30" font-size="18">{html.escape(title)}</text><path d="M60 60V260H860" fill="none" stroke="#9ba6b2"/>
<text x="62" y="55">{hi:.2f}{unit}</text><text x="62" y="280">{lo:.2f}{unit}</text>
<text x="620" y="300">Chronological replay observations</text></g><polyline points="{pts}" fill="none" stroke="#2357c6" stroke-width="2"/></svg>'''
    path.write_text(content, encoding="utf-8")


def svg_months(path, monthly, title):
    monthly = [m for m in monthly if m["return_percent"] is not None]
    if not monthly:
        return
    width = max(600, 100 * len(monthly))
    scale = max([abs(m["return_percent"]) for m in monthly] + [0.001])
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="330"><rect width="100%" height="100%" fill="white"/><g font-family="sans-serif"><text x="20" y="30">{html.escape(title)}</text><path d="M20 170H{width-20}" stroke="#999"/>']
    for i, m in enumerate(monthly):
        x = 30 + i * (width - 60) / len(monthly)
        v = m["return_percent"]
        height = abs(v) * 110 / scale
        y = 170 - height if v >= 0 else 170
        pieces.append(f'<rect x="{x}" y="{y}" width="35" height="{height}" fill="{"#227854" if v >= 0 else "#b83245"}"/><text x="{x}" y="300" font-size="11">{m["month"]}</text><text x="{x}" y="{y-6 if v>=0 else y+height+16}" font-size="11">{v:.3f}%</text>')
    path.write_text("".join(pieces) + "</g></svg>", encoding="utf-8")


def generate(out, initial, synthetic=False, session_dates=None):
    out = Path(out)
    engine_summary = json.loads((out / "summary.json").read_text())
    synthetic = synthetic or bool(engine_summary.get("synthetic_data"))
    trades = read_csv(out / "trades.csv")
    pnls = [number(r, "net_pnl") for r in trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    # Stream annual logs: metrics use every observation, charts retain extrema
    # within each half-hour bucket, bounded to about 70k points per year.
    days, months = {}, {}
    peak, mdd_usd, mdd_pct, last_value = initial, 0.0, 0.0, initial
    last_row = None
    buckets = {}
    with (out / "equity.csv").open(newline="") as f:
        for sequence, row in enumerate(csv.DictReader(f)):
            dt = stamp(row["timestamp"])
            value = number(row, "equity")
            peak = max(peak, value)
            current_dd = (value / peak - 1) * 100 if peak > 0 else 0
            mdd_usd, mdd_pct = max(mdd_usd, peak-value), max(mdd_pct, -current_dd)
            bucket = int(float(row["timestamp"])) // 1800
            point = (sequence, value, current_dd)
            if bucket not in buckets:
                buckets[bucket] = [point, point, point, point, point]
            b = buckets[bucket]
            if value < b[1][1]: b[1] = point
            if value > b[2][1]: b[2] = point
            b[3] = point
            if current_dd < b[4][2]: b[4] = point
            if session_dates is None or dt.date().isoformat() in session_dates:
                days[dt.date().isoformat()] = value
                month = dt.strftime("%Y-%m")
                if month not in months:
                    months[month] = {"initial": last_value, "peak": last_value, "dd": 0.0, "dd_pct": 0.0}
                m = months[month]
                m["peak"] = max(m["peak"], value)
                m["dd"] = max(m["dd"], m["peak"]-value)
                if m["peak"] > 0: m["dd_pct"] = max(m["dd_pct"], (1-value/m["peak"])*100)
                m["last"] = value
            last_row, last_value = row, value
    if last_row is None:
        raise ValueError("No replay equity observations: this is not a performance result")
    final = number(last_row, "equity")
    chart_points = [p for b in buckets.values() for p in sorted(set(b))]
    values, dd = [p[1] for p in chart_points], [p[2] for p in chart_points]
    month_trades = defaultdict(list)
    for trade in trades:
        month_trades[stamp(trade["exit_timestamp"]).strftime("%Y-%m")].append(number(trade, "net_pnl"))
    previous = initial
    monthly = []
    for month, m in sorted(months.items()):
        results = month_trades[month]
        monthly.append({"month": month, "trades": len(results), "wins": sum(p > 0 for p in results), "losses": sum(p < 0 for p in results), "net_pnl": m["last"] - previous, "return_percent": (m["last"] / previous - 1) * 100 if previous else None, "max_drawdown_usd": m["dd"], "max_drawdown_percent": m["dd_pct"]})
        previous = m["last"]
    returns = []
    previous = initial
    for value in days.values():
        if previous > 0:
            returns.append(value / previous - 1)
        previous = value
    sharpe = None
    if session_dates is not None and len(returns) >= 20 and statistics.stdev(returns) > 0:
        sharpe = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(252)
    performance = {
        "status": "SYNTHETIC_VERIFICATION_ONLY" if synthetic else "HISTORICAL_REPLAY_WITH_DECLARED_EXECUTION_ASSUMPTIONS",
        "initial_capital": initial, "final_equity": final, "net_pnl": final - initial,
        "net_return_percent": (final / initial - 1) * 100, "total_closed_trades": len(trades),
        "winning_trades": len(wins), "losing_trades": len(losses), "flat_trades": sum(p == 0 for p in pnls),
        "win_rate_percent": 100 * len(wins) / len(trades) if trades else None,
        "average_winning_trade": statistics.mean(wins) if wins else None,
        "average_losing_trade": statistics.mean(losses) if losses else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "max_drawdown_usd": mdd_usd, "max_drawdown_percent": mdd_pct,
        "average_pnl_per_trade": statistics.mean(pnls) if pnls else None,
        "expectancy_per_trade": statistics.mean(pnls) if pnls else None,
        "total_commissions": number(last_row, "commissions"),
        "estimated_execution_costs": number(last_row, "execution_costs"),
        "sharpe_ratio": sharpe, "sharpe_observations": len(returns),
        "sharpe_assumption": "252 annualization; zero risk-free rate; last observation of each validated NY session. A verified exchange-session calendar and at least20 session returns are required. Otherwise N/A. Artificial weekend/holiday boundary observations are excluded when a calendar is supplied.",
        "monthly": monthly,
        "accounting": "Portfolio P&L includes marked open positions; trade statistics include closed trades only. Monthly P&L is change in marked portfolio equity, not a sum of exits. Slippage/spread already affect execution prices and are not deducted twice. Open positions are not forcibly liquidated.",
    }
    (out / "performance.json").write_text(json.dumps(performance, indent=2, allow_nan=False) + "\n")
    with (out / "monthly.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(monthly[0]) if monthly else ["month"])
        writer.writeheader()
        writer.writerows(monthly)
    label = "SYNTHETIC VERIFICATION — " if synthetic else "Historical replay — "
    svg_line(out / "equity.svg", values, label + "portfolio equity")
    svg_line(out / "drawdown.svg", dd, label + "drawdown", True)
    svg_months(out / "monthly_returns.svg", monthly, label + "monthly returns")
    lines = ["# " + label + "performance", "", "**Synthetic fixtures are invented unit-test inputs. They are not historical market observations.**" if synthetic else "Results apply only to the supplied data, source version and declared execution assumptions. Review the data provenance/coverage manifest and STRATEGY_AUDIT.md before interpreting these metrics.", "", "| Metric | Value |", "|---|---:|"]
    for key, val in performance.items():
        if key in ("monthly", "accounting", "sharpe_assumption", "status"):
            continue
        lines.append(f"| {key.replace('_', ' ')} | {'N/A' if val is None else (format(val, '.6f') if isinstance(val,float) else val)} |")
    lines.extend(["", performance["accounting"], "", performance["sharpe_assumption"], "", "![Equity](equity.svg)", "", "![Drawdown](drawdown.svg)", "", "![Monthly returns](monthly_returns.svg)", "", "| Month | Trades | Wins | Losses | Net P&L | Return % | Max DD USD | Max DD % |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for m in monthly:
        ret = "N/A" if m['return_percent'] is None else f"{m['return_percent']:.4f}"
        lines.append(f"| {m['month']} | {m['trades']} | {m['wins']} | {m['losses']} | {m['net_pnl']:.4f} | {ret} | {m['max_drawdown_usd']:.4f} | {m['max_drawdown_percent']:.4f} |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return performance


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out", type=Path)
    p.add_argument("--capital", type=float, default=4200)
    p.add_argument("--synthetic", action="store_true")
    args = p.parse_args()
    print(json.dumps(generate(args.out, args.capital, args.synthetic), indent=2))
