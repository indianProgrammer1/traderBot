#!/usr/bin/env python3
"""Read-only IBKR historical acquisition. All generated files stay in backtesting/.

No order, position, or account mutation API is used. --probe needs no IB API package.
Native history older than six months is clipped explicitly; --allow-tick-reconstruction
opts into a different historical tick aggregation source for the older portion.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import errno
import hashlib
import json
import math
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
SYMBOLS = "TSLA,NFLX,CRWD,MRNA,AMD,NVDA,AAPL,ROKU,PDD,MSFT"
FIELDS = "symbol,start_epoch,end_epoch,open,high,low,close,volume,is_rth,kind".split(",")
UTC = timezone.utc


def subtract_months(day: date, count: int) -> date:
    index = day.year * 12 + day.month - 1 - count
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def epoch(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), UTC).timestamp())


def ib_datetime(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y%m%d-%H:%M:%S")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def local_stamp(value: str, zone: str) -> int:
    # IB schedules return an explicit exchange time-zone plus local date/time.
    value = value.strip().replace("-", " ", 1)
    return int(datetime.strptime(value, "%Y%m%d %H:%M:%S").replace(tzinfo=ZoneInfo(zone)).timestamp())


def probe(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
        return {"host": host, "port": port, "tcp_reachable": True,
                "note": "TCP only; authentication and historical entitlement not verified."}
    except OSError as exc:
        permission_denied = exc.errno in (errno.EACCES, errno.EPERM) or getattr(exc, "winerror", None) == 10013
        return {"host": host, "port": port, "tcp_reachable": False,
                "status": "socket_permission_denied" if permission_denied else "tcp_connection_failed",
                "error": str(exc), "note": "No historical data request or order was submitted."}


def make_client(api_source: Path):
    if api_source.exists():
        sys.path.insert(0, str(api_source))
    try:
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
        from ibapi.contract import Contract
    except ImportError as exc:
        raise RuntimeError("Official ibapi unavailable; pass --api-source to its pythonclient directory.") from exc

    class HistoryClient(EWrapper, EClient):
        def __init__(self):
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.pending = {}
            self.sequence = 50000

        def nextValidId(self, orderId):
            self.ready.set()  # Connection handshake only; this ID is never used.

        def placeOrder(self, *args, **kwargs):
            raise RuntimeError("Order submission is disabled in the historical downloader")

        def cancelOrder(self, *args, **kwargs):
            raise RuntimeError("Order cancellation is disabled in the historical downloader")

        def reqGlobalCancel(self, *args, **kwargs):
            raise RuntimeError("Order cancellation is disabled in the historical downloader")

        def error(self, reqId, *args):
            # Current API adds errorTime before errorCode; support both signatures.
            if len(args) >= 3 and isinstance(args[1], int):
                code, message = args[1], args[2]
            else:
                code, message = args[0], args[1]
            state = self.pending.get(reqId)
            if state is not None and code not in (2104, 2106, 2107, 2108, 2158, 2176):
                state["error"] = f"IBKR {code}: {message}"
                state["event"].set()

        def historicalData(self, reqId, bar):
            state = self.pending.get(reqId)
            if state is not None:
                state["rows"].append({key: str(getattr(bar, key)) for key in
                                      ("date", "open", "high", "low", "close", "volume")})

        def historicalDataEnd(self, reqId, start, end):
            state = self.pending.get(reqId)
            if state is not None:
                state["event"].set()

        def historicalSchedule(self, reqId, startDateTime, endDateTime, timeZone, sessions):
            state = self.pending.get(reqId)
            if state is not None:
                state["rows"] = [{"date": s.refDate, "start": s.startDateTime,
                                   "end": s.endDateTime, "zone": timeZone} for s in sessions]
                state["event"].set()

        def historicalTicksLast(self, reqId, ticks, done):
            state = self.pending.get(reqId)
            if state is not None:
                state["rows"].extend({"time": int(t.time), "price": float(t.price),
                                       "size": str(t.size), "exchange": t.exchange,
                                       "conditions": t.specialConditions,
                                       "past_limit": bool(t.tickAttribLast.pastLimit),
                                       "unreported": bool(t.tickAttribLast.unreported)} for t in ticks)
                if done:
                    state["event"].set()

        def request(self, spec, timeout):
            self.sequence += 1
            req_id = self.sequence
            state = {"event": threading.Event(), "rows": [], "error": None}
            self.pending[req_id] = state
            contract = Contract()
            contract.symbol = spec["symbol"]
            contract.secType, contract.exchange, contract.currency = "STK", "SMART", "USD"
            try:
                if spec["type"] == "ticks":
                    self.reqHistoricalTicks(req_id, contract, ib_datetime(spec["start"]), "",
                                            1000, "TRADES", 0, False, [])
                else:
                    self.reqHistoricalData(req_id, contract, ib_datetime(spec["end"]),
                                           spec["duration"], spec["bar_size"], spec["show"],
                                           spec["rth"], 2, False, [])
                if not state["event"].wait(timeout):
                    if spec["type"] != "ticks":
                        self.cancelHistoricalData(req_id)
                    raise TimeoutError(f"Historical request timed out for {spec['symbol']}")
                if state["error"]:
                    raise RuntimeError(state["error"])
                return state["rows"]
            finally:
                self.pending.pop(req_id, None)

    return HistoryClient()


class Downloader:
    def __init__(self, client, args, output):
        self.client, self.args, self.output = client, args, output
        self.raw = output / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.last_request = 0.0
        self.last_identical = {}
        self.requests = {}

    def get(self, spec):
        key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        path = self.raw / (key + ".json")
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["request"] != spec:
                raise RuntimeError("Raw cache key mismatch")
        else:
            for attempt in range(self.args.retries + 1):
                now = time.monotonic()
                wait = max(0, self.last_request + 10.1 - now,
                           self.last_identical.get(key, 0) + 15.1 - now)
                if wait:
                    time.sleep(wait)
                self.last_request = self.last_identical[key] = time.monotonic()
                try:
                    rows = self.client.request(spec, self.args.timeout)
                    payload = {"request": spec, "rows": rows,
                               "retrieved_utc": datetime.now(UTC).isoformat()}
                    atomic_json(path, payload)
                    break
                except (RuntimeError, TimeoutError):
                    if attempt == self.args.retries:
                        raise
                    time.sleep(30 * (attempt + 1))
        self.requests[key] = {"file": str(path.relative_to(self.output)), "request": spec,
                              "rows": len(payload["rows"]),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return payload["rows"]

    def bars(self, symbol, end, duration, size, rth, show="TRADES"):
        return self.get({"type": "bars", "symbol": symbol, "end": end,
                         "duration": duration, "bar_size": size, "rth": rth, "show": show})

    def schedule(self, symbol, start, end):
        merged = {}
        duplicate_records = 0
        request_ranges = []
        for rth in (1, 0):
            cursor = start
            while cursor < end:
                boundary = min(end, cursor + 180 * 86400)
                duration = f"{math.ceil((boundary - cursor) / 86400) + 1} D"
                records = self.bars(symbol, boundary, duration, "1 day", rth, "SCHEDULE")
                request_ranges.append({"start_epoch": cursor, "end_epoch": boundary,
                                       "rth": rth, "raw_rows": len(records)})
                for record in records:
                    opened = local_stamp(record["start"], record["zone"])
                    closed = local_stamp(record["end"], record["zone"])
                    if closed <= start or opened >= end:
                        continue
                    field = "rth" if rth else "all"
                    session = merged.setdefault(record["date"], {"symbol": symbol, "date": record["date"]})
                    if field + "_open" in session:
                        if (opened, closed) != (session[field + "_open"], session[field + "_close"]):
                            raise RuntimeError(f"Conflicting or split-session schedule for {symbol} {record['date']}; do not merge unobserved intervals")
                        duplicate_records += 1
                    session[field + "_open"] = opened
                    session[field + "_close"] = closed
                cursor = boundary
        for session in merged.values():
            if not all(key in session for key in ("rth_open", "rth_close", "all_open", "all_close")):
                raise RuntimeError(f"Incomplete RTH/all-hours schedule for {symbol} {session['date']}")
        if not merged:
            raise RuntimeError(f"Empty IBKR schedule for {symbol}; no holiday calendar is guessed")
        self.schedule_audit = getattr(self, "schedule_audit", {})
        self.schedule_audit[symbol] = {"query_start_epoch": start, "query_end_epoch": end,
                                       "normalized_sessions": len(merged), "duplicate_sessions": 0,
                                       "identical_raw_duplicates_removed": duplicate_records,
                                       "requests": request_ranges}
        return sorted(merged.values(), key=lambda row: row["rth_open"])


def insert_bar(db, symbol, start, end, raw, rth, kind):
    if end <= start or (kind == "realtime5s" and (start % 5 or end - start != 5)):
        raise ValueError(f"Invalid bar interval for {symbol} at {start}")
    numbers = tuple(float(raw[key]) for key in ("open", "high", "low", "close", "volume"))
    opened, high, low, close, volume = numbers
    if not all(math.isfinite(n) for n in numbers) or min(opened, high, low, close) <= 0 or volume < 0:
        raise ValueError(f"Nonfinite/invalid bar for {symbol} at {start}")
    if high < max(opened, low, close) or low > min(opened, close):
        raise ValueError(f"Invalid OHLC ordering for {symbol} at {start}")
    row = (symbol, int(start), int(end), *numbers, int(rth), kind)
    old = db.execute("SELECT * FROM bars WHERE symbol=? AND start_epoch=? AND kind=?",
                     (symbol, start, kind)).fetchone()
    if old is not None and old != row:
        raise ValueError(f"Conflicting duplicate bar for {symbol} at {start} ({kind})")
    db.execute("INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)", row)


def reconstructed_ticks(download, db, symbol, start, end, rth_open, rth_close):
    cursor, bucket = start, None
    aggregate = None
    # IBKR completes the final second of a page. Advancing by one second therefore
    # avoids duplicated seconds without discarding same-second trades in that page.
    while cursor < end:
        ticks = download.get({"type": "ticks", "symbol": symbol, "start": cursor})
        if not ticks:
            break
        if any(ticks[i]["time"] > ticks[i + 1]["time"] for i in range(len(ticks) - 1)):
            raise ValueError("Historical tick page is not chronological")
        for tick in ticks:
            stamp = tick["time"]
            if stamp < cursor or stamp >= end:
                continue
            # Retain the original flags/conditions in the raw cache. IB's TRADES
            # service defines included trades; do not invent extra trade filters.
            price, size = float(tick["price"]), float(tick["size"])
            if not math.isfinite(price) or price <= 0 or not math.isfinite(size) or size < 0:
                raise ValueError("Invalid historical trade")
            next_bucket = stamp - stamp % 5
            if next_bucket != bucket:
                if aggregate is not None:
                    insert_bar(db, symbol, bucket, bucket + 5, aggregate,
                               rth_open <= bucket < rth_close, "realtime5s")
                bucket = next_bucket
                aggregate = {"open": price, "high": price, "low": price, "close": price, "volume": size}
            else:
                aggregate["high"] = max(aggregate["high"], price)
                aggregate["low"] = min(aggregate["low"], price)
                aggregate["close"] = price
                aggregate["volume"] += size
        next_cursor = ticks[-1]["time"] + 1
        if next_cursor <= cursor:
            raise ValueError("Historical tick pagination made no progress")
        cursor = next_cursor
    if aggregate is not None:
        insert_bar(db, symbol, bucket, bucket + 5, aggregate,
                   rth_open <= bucket < rth_close, "realtime5s")


def acquire(download, db, args, manifest):
    start, end = manifest["effective_start_epoch"], epoch(args.end)
    warmup_start = epoch(subtract_months(datetime.fromtimestamp(start, UTC).date(), 6) - timedelta(days=7))
    manifest["calendar_start_epoch"] = warmup_start
    manifest["calendar_end_epoch"] = end
    all_sessions = []
    for symbol in args.symbols:
        print(f"Acquiring {symbol}; cached requests are reused.", flush=True)
        sessions = download.schedule(symbol, warmup_start, end)
        manifest["calendar_coverage"] = download.schedule_audit
        all_sessions.extend(sessions)
        by_day = {s["date"]: s for s in sessions}
        for raw in download.bars(symbol, start, "7 M", "1 day", 1):
            day = raw["date"].replace("-", "")
            session = by_day.get(day)
            if session is not None and session["rth_close"] <= start:
                insert_bar(db, symbol, session["rth_open"], session["rth_close"], raw, True, "history1d")
        cursor = start - 14 * 86400
        while cursor < start:
            boundary = min(start, cursor + 86400)
            for raw in download.bars(symbol, boundary, "1 D", "5 mins", 1):
                stamp = int(raw["date"])
                if cursor <= stamp and stamp + 300 <= start:
                    insert_bar(db, symbol, stamp, stamp + 300, raw, True, "history5m")
            cursor = boundary
        for session in sessions:
            opened = max(start, session["all_open"])
            closed = min(end, session["all_close"])
            if opened >= closed:
                continue
            if opened < manifest["native_retention_start_epoch"]:
                reconstructed_ticks(download, db, symbol, opened, closed,
                                    session["rth_open"], session["rth_close"])
            else:
                cursor = opened
                while cursor < closed:
                    boundary = min(closed, cursor + 3600)
                    for raw in download.bars(symbol, boundary, f"{boundary - cursor} S", "5 secs", 0):
                        stamp = int(raw["date"])
                        if cursor <= stamp and stamp + 5 <= boundary:
                            insert_bar(db, symbol, stamp, stamp + 5, raw,
                                       session["rth_open"] <= stamp < session["rth_close"], "realtime5s")
                    cursor = boundary
            db.commit()
        manifest["symbols_completed"].append(symbol)
        manifest["requests"] = list(download.requests.values())
        atomic_json(download.output / "manifest.json", manifest)
    with (download.output / "sessions.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["symbol", "date", "rth_open", "rth_close", "all_open", "all_close"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(all_sessions, key=lambda row: (row["rth_open"], row["symbol"])))
    with (download.output / "sessions.csv").open("rb") as handle:
        manifest["sessions_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--self-test", action="store_true", help="Run focused offline acquisition tests")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=71)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 10, 11))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 12), help="Exclusive UTC date; 2026-10-12 includes the requested October 11")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Jerusalem")).date(),
                        help="Date used for six-month retention preflight; update for later acquisition")
    parser.add_argument("--symbols", default=SYMBOLS)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "ibkr")
    parser.add_argument("--api-source", type=Path, default=Path(r"C:\TWS API\source\pythonclient"))
    parser.add_argument("--allow-tick-reconstruction", action="store_true")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    args.symbols = args.symbols.split(",")
    if not args.symbols or any(s not in SYMBOLS.split(",") for s in args.symbols) or len(set(args.symbols)) != len(args.symbols):
        parser.error("Symbols must be a unique subset of the source universe")
    if args.start >= args.end or args.end > args.as_of:
        parser.error("Require start < end <= as-of")
    if args.client_id <= 0:
        parser.error("Use a dedicated positive client ID; never the live engine's ID 0")
    if args.timeout <= 0 or args.retries < 0:
        parser.error("Invalid timeout/retry setting")
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT):
        parser.error("Output must be inside backtesting/")
    return args


def main():
    args = arguments()
    if args.self_test:
        return self_test(args.api_source)
    args.output.mkdir(parents=True, exist_ok=True)
    retention_start = subtract_months(args.as_of, 6)
    effective_start = args.start if args.allow_tick_reconstruction else max(args.start, retention_start)
    manifest = {"requested_start": str(args.start), "requested_end_exclusive": str(args.end),
                "effective_start": str(effective_start), "effective_start_epoch": epoch(effective_start),
                "native_retention_start_epoch": epoch(retention_start), "as_of": str(args.as_of),
                "symbols": args.symbols, "symbols_completed": [], "requests": [],
                "tick_reconstruction_enabled": args.allow_tick_reconstruction,
                "source": "IBKR historical TRADES; native 5s and optional historical tick aggregation",
                "price_adjustment": "IBKR historical defaults; corporate-action consistency requires review",
                "price_basis_verified": False,
                "synthetic_empty_bars": False, "status": "not_started",
                "limitations": ["Historical filtering and adjustments can differ from the live feed.",
                                "Missing five-second intervals remain missing; no invented prices.",
                                "Historical ticks and native bars are not certified to share a split-adjusted price basis.",
                                "Coverage must be reviewed before treating the download as a complete backtest."]}
    if effective_start > args.start:
        manifest["missing_requested_interval"] = [str(args.start), str(effective_start)]
    manifest["connectivity"] = probe(args.host, args.port)
    if args.probe or not manifest["connectivity"]["tcp_reachable"]:
        manifest["status"] = ("probe_only" if manifest["connectivity"]["tcp_reachable"]
                              else "blocked_" + manifest["connectivity"]["status"])
        atomic_json(args.output / "probe.json", manifest)
        print(json.dumps(manifest, indent=2))
        return 0 if manifest["connectivity"]["tcp_reachable"] else 2
    if effective_start >= args.end:
        raise RuntimeError("No native five-second coverage in the requested range; tick reconstruction must be explicitly enabled")
    client = download = db = None
    try:
        client = make_client(args.api_source)
        client.connect(args.host, args.port, args.client_id)
        thread = threading.Thread(target=client.run, daemon=True)
        thread.start()
        if not client.ready.wait(10):
            raise RuntimeError("IBKR API handshake not received; check API permissions and unique client ID")
        download = Downloader(client, args, args.output)
        # Rebuild normalized rows from immutable raw cache each run to prevent stale
        # bars from a different requested date range being mistaken for new coverage.
        db = sqlite3.connect(args.output / "normalized.sqlite")
        db.execute("DROP TABLE IF EXISTS bars")
        db.execute("CREATE TABLE bars(symbol TEXT,start_epoch INTEGER,end_epoch INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL,is_rth INTEGER,kind TEXT,PRIMARY KEY(symbol,start_epoch,kind))")
        manifest["status"] = "downloading"
        atomic_json(args.output / "manifest.json", manifest)
        acquire(download, db, args, manifest)
        db.commit()
        counts = db.execute("SELECT symbol,kind,COUNT(*),MIN(start_epoch),MAX(end_epoch) FROM bars GROUP BY symbol,kind ORDER BY symbol,kind").fetchall()
        manifest["coverage"] = [dict(zip(("symbol", "kind", "rows", "first_start_epoch", "last_end_epoch"), row)) for row in counts]
        with (args.output / "bars.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            writer.writerows(db.execute("SELECT * FROM bars ORDER BY end_epoch,symbol,kind,start_epoch"))
        with (args.output / "bars.csv").open("rb") as handle:
            manifest["bars_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        manifest["status"] = "download_complete_requires_coverage_review"
        print(f"Saved {args.output / 'bars.csv'}; effective start {effective_start}; review manifest.json.")
        return 0
    except Exception as exc:
        manifest["status"], manifest["error"] = "failed", str(exc)
        print(f"Historical download failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if download is not None:
            manifest["requests"] = list(download.requests.values())
        atomic_json(args.output / "manifest.json", manifest)
        if db is not None:
            db.close()
        if client is not None:
            client.disconnect()


def self_test(api_source):
    assert subtract_months(date(2024, 8, 31), 6) == date(2024, 2, 29)
    assert subtract_months(date(2026, 10, 12), 6) == date(2026, 4, 12)
    assert ib_datetime(epoch(date(2026, 10, 11))) == "20261011-00:00:00"
    assert local_stamp("20260306-09:30:00", "America/New_York") % 86400 == 14 * 3600 + 30 * 60
    assert local_stamp("20260309-09:30:00", "America/New_York") % 86400 == 13 * 3600 + 30 * 60

    class SchedulePages:
        def bars(self, symbol, end, duration, size, rth, show):
            row = {"date": "20261001", "start": "20261001-09:30:00" if rth else "20261001-04:00:00",
                   "end": "20261001-16:00:00" if rth else "20261001-20:00:00", "zone": "America/New_York"}
            return [row, row.copy()]

    schedules = SchedulePages()
    normalized = Downloader.schedule(schedules, "AAPL", epoch(date(2026, 10, 1)), epoch(date(2026, 10, 2)))
    assert len(normalized) == 1 and schedules.schedule_audit["AAPL"]["duplicate_sessions"] == 0
    assert schedules.schedule_audit["AAPL"]["identical_raw_duplicates_removed"] == 2
    assert normalized[0]["rth_open"] == local_stamp("20261001-09:30:00", "America/New_York")
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE bars(symbol TEXT,start_epoch INTEGER,end_epoch INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL,is_rth INTEGER,kind TEXT,PRIMARY KEY(symbol,start_epoch,kind))")
    start = epoch(date(2026, 10, 1))

    class TickPages:
        def __init__(self):
            self.starts = []

        def get(self, spec):
            self.starts.append(spec["start"])
            if spec["start"] == start:
                return [{"time": start, "price": 100, "size": 2},
                        {"time": start, "price": 101, "size": 3},
                        {"time": start + 1, "price": 99, "size": 1}]
            if spec["start"] == start + 2:
                return [{"time": start + 6, "price": 102, "size": 4}]
            return [{"time": start + 21, "price": 200, "size": 7}]

    pages = TickPages()
    reconstructed_ticks(pages, db, "AAPL", start, start + 15, start, start + 10)
    rows = db.execute("SELECT * FROM bars ORDER BY start_epoch").fetchall()
    assert len(rows) == 2, "Empty 10..15-second bucket must not be fabricated"
    assert rows[0] == ("AAPL", start, start + 5, 100, 101, 99, 99, 6, 1, "realtime5s")
    assert rows[1] == ("AAPL", start + 5, start + 10, 102, 102, 102, 102, 4, 1, "realtime5s")
    assert pages.starts == [start, start + 2, start + 7], "Pages must advance beyond completed final seconds"
    valid = {"open": 100, "high": 101, "low": 99, "close": 99, "volume": 6}
    insert_bar(db, "AAPL", start, start + 5, valid, True, "realtime5s")
    assert db.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 2
    try:
        insert_bar(db, "AAPL", start, start + 5, dict(valid, close=100), True, "realtime5s")
        raise AssertionError("Conflicting duplicates must be rejected")
    except ValueError:
        pass
    for invalid in (dict(valid, high=98), dict(valid, volume=-1), dict(valid, open=float("nan"))):
        try:
            insert_bar(db, "AAPL", start + 30, start + 35, invalid, True, "realtime5s")
            raise AssertionError("Invalid OHLCV must be rejected")
        except ValueError:
            pass
    db.close()
    api_status = "source_not_present"
    if api_source.exists():
        client = make_client(api_source)
        for name in ("placeOrder", "cancelOrder", "reqGlobalCancel"):
            try:
                getattr(client, name)()
                raise AssertionError("Order mutation must be disabled")
            except RuntimeError:
                pass
        api_status = "imported_offline_order_guards_passed"
    print(json.dumps({"status": "passed", "api": api_status,
                      "checks": ["calendar_month_lookback", "UTC_and_DST", "tick_pagination",
                                 "OHLCV_aggregation", "no_synthetic_gap_fill", "duplicate_conflicts",
                                 "invalid_prices_and_volume", "schedule_deduplication", "orders_disabled"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
