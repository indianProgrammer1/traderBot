"""Validate source identity, bar invariants and actual exchange-session coverage."""
from pathlib import Path
from collections import defaultdict
import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone


def validate(data, sessions_file, manifest_file, start, end, symbols):
    manifest = json.loads(Path(manifest_file).read_text())
    errors, warnings = [], []
    if manifest.get("status") != "download_complete_requires_coverage_review":
        errors.append("Historical data acquisition is not marked complete in the source manifest.")
    with Path(data).open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if manifest.get("bars_sha256") != digest:
        errors.append("Historical data SHA-256 does not match its provenance manifest.")
    with Path(sessions_file).open("rb") as f:
        calendar_digest = hashlib.file_digest(f, "sha256").hexdigest()
    if manifest.get("sessions_sha256") != calendar_digest:
        errors.append("Session calendar SHA-256 does not match its source manifest.")
    if manifest.get("effective_start_epoch") != start:
        errors.append("Replay start must equal the dataset's effective acquisition start. Acquire a separate subset with matching warm-up, or pass --start for the already acquired window.")
    try:
        manifest_end = int(datetime.fromisoformat(manifest["requested_end_exclusive"]).replace(tzinfo=timezone.utc).timestamp())
        if manifest_end != end:
            errors.append("Replay end must equal the dataset's exclusive acquisition end; use a separately acquired/cache-generated window.")
    except (KeyError, ValueError):
        errors.append("Missing or invalid acquisition end date in source manifest.")
    if set(manifest.get("symbols_completed", [])) != set(symbols):
        errors.append("Source manifest does not confirm completion for every production symbol.")
    sessions = defaultdict(list)
    with Path(sessions_file).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["symbol"] in symbols and start <= int(row["rth_open"]) < end:
                sessions[row["symbol"]].append({k: (row[k] if k in ("symbol", "date") else int(row[k])) for k in row})
    for symbol in symbols:
        sessions[symbol].sort(key=lambda r: r["all_open"])
        if not sessions[symbol]:
            errors.append(f"No exchange sessions provided for {symbol} in the requested period.")
        if len({s["date"] for s in sessions[symbol]}) != len(sessions[symbol]):
            errors.append(f"Duplicate exchange sessions for {symbol}.")
        for s in sessions[symbol]:
            if not (s["all_open"] <= s["rth_open"] < s["rth_close"] <= s["all_close"]):
                errors.append(f"Invalid exchange session bounds for {symbol} on {s['date']}.")
    counts = defaultdict(int)
    span = {}
    previous = None
    previous_key = {}
    coverage = defaultdict(lambda: {"observed": 0, "first": None, "last": None, "rth_observed": 0})
    session_index = defaultdict(int)
    with Path(data).open(newline="", encoding="utf-8") as f:
        for line, row in enumerate(csv.DictReader(f), 2):
            try:
                symbol, kind = row["symbol"], row["kind"]
                opened, closed = int(row["start_epoch"]), int(row["end_epoch"])
                nums = [float(row[k]) for k in ("open", "high", "low", "close", "volume")]
                o, h, low, close, volume = nums
                key = (closed, symbol, kind, opened)
                if previous is not None and key < previous:
                    raise ValueError("rows not globally ordered by end_epoch,symbol,kind,start_epoch")
                previous = key
                if previous_key.get((symbol, kind), -1) >= opened:
                    raise ValueError("duplicate or reversed bar timestamp")
                previous_key[(symbol, kind)] = opened
                if symbol not in symbols or kind not in ("history1d", "history5m", "realtime5s"):
                    raise ValueError("unexpected symbol or bar kind")
                if not all(math.isfinite(x) for x in nums) or min(o, h, low, close) <= 0 or volume < 0 or low > min(o, close) or h < max(o, close) or h < low:
                    raise ValueError("invalid OHLC or volume")
                if closed <= opened or (kind == "realtime5s" and (closed - opened != 5 or opened % 5)) or (kind == "history5m" and closed - opened != 300):
                    raise ValueError("invalid bar duration/alignment")
                if row["is_rth"] not in ("0", "1"):
                    raise ValueError("invalid RTH indicator")
                counts[f"{symbol}:{kind}"] += 1
                sk = f"{symbol}:{kind}"
                span.setdefault(sk, {"first_start": opened, "last_end": closed})["last_end"] = closed
                if kind != "realtime5s" or opened < start or closed > end:
                    continue
                symbol_sessions = sessions[symbol]
                idx = session_index[symbol]
                while idx < len(symbol_sessions) and opened >= symbol_sessions[idx]["all_close"]:
                    idx += 1
                session_index[symbol] = idx
                if idx == len(symbol_sessions) or opened < symbol_sessions[idx]["all_open"]:
                    raise ValueError("bar lies outside supplied exchange trading sessions")
                session = symbol_sessions[idx]
                actual_rth = session["rth_open"] <= opened < session["rth_close"]
                if actual_rth != (row["is_rth"] == "1"):
                    raise ValueError("RTH flag conflicts with exchange schedule")
                c = coverage[(symbol, session["date"])]
                c["observed"] += 1
                c["rth_observed"] += int(actual_rth)
                c["first"] = opened if c["first"] is None else c["first"]
                c["last"] = closed
            except (ValueError, KeyError) as exc:
                errors.append(f"Invalid data at line {line}: {exc}")
                break
    daily = []
    gaps = 0
    for symbol in symbols:
        for session in sessions[symbol]:
            c = coverage[(symbol, session["date"])]
            expected = (min(end, session["all_close"]) - max(start, session["all_open"])) // 5
            rth_expected = (session["rth_close"] - session["rth_open"]) // 5
            missing = max(0, expected - c["observed"])
            gaps += missing
            daily.append({"symbol": symbol, "session": session["date"], **c, "expected_5s_intervals": expected, "missing_5s_intervals": missing, "missing_rth_intervals": max(0, rth_expected - c["rth_observed"])})
            if not c["observed"]:
                errors.append(f"No intraday observations for {symbol} on session {session['date']}.")
    if gaps:
        warnings.append(f"{gaps} exchange-session five-second intervals have no observation. Historical trade aggregation may omit intervals without trades; missing records alone cannot distinguish that from lost data.")
        if not manifest.get("missing_intervals_verified_no_trades", False):
            errors.append("Five-second coverage has unverified gaps. Validate against the raw provider archive or select a complete subset; do not fill invented bars.")
    if manifest.get("tick_reconstruction_enabled"):
        warnings.append("Historical ticks were aggregated to five-second OHLC. The result is a reconstruction and can differ from the production real-time feed.")
    warnings.extend(["Corporate actions, historical filtering and raw-vs-adjusted price consistency must be checked against the provider manifest.", "A session calendar returned by the provider determines holidays/early closes; this validator does not invent weekday sessions."])
    return {"errors": errors, "warnings": warnings, "counts": dict(counts), "span": span, "session_coverage": daily, "data_sha256": digest, "start_epoch": start, "end_epoch": end, "missing_5s_intervals": gaps}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=Path)
    p.add_argument("sessions", type=Path)
    p.add_argument("manifest", type=Path)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--symbols", default="TSLA,NFLX,CRWD,MRNA,AMD,NVDA,AAPL,ROKU,PDD,MSFT")
    a = p.parse_args()
    result = validate(a.data, a.sessions, a.manifest, a.start, a.end, a.symbols.split(","))
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["errors"] else 0)
