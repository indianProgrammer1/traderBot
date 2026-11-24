"""Synthetic unit fixtures for reporting and coverage validation; no market data.

Run: python backtesting/test_reporting_validation.py
All fixture files remain under backtesting/results/verification/report_validation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import reporting
import validate_data

FIXTURES = BASE / "results" / "verification" / "report_validation"
NY = ZoneInfo("America/New_York")
BAR_FIELDS = "symbol,start_epoch,end_epoch,open,high,low,close,volume,is_rth,kind".split(",")
SESSION_FIELDS = "symbol,date,all_open,all_close,rth_open,rth_close".split(",")


def epoch(day: str, hour: int = 12) -> int:
    return int(datetime.fromisoformat(day).replace(hour=hour, tzinfo=NY).timestamp())


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.output = FIXTURES / self.id().split(".")[-1]
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "SYNTHETIC_FIXTURE.txt").write_text(
            "Invented unit-test inputs only. Not historical observations or performance.\n",
            encoding="utf-8",
        )

    def report_fixture(self, points: list[tuple[str, float]], pnls=()) -> Path:
        (self.output / "summary.json").write_text(
            json.dumps({"synthetic_data": True, "status": "synthetic_test_only"}) + "\n"
        )
        equity = [{"timestamp": epoch(day), "equity": value,
                   "commissions": 0, "execution_costs": 0} for day, value in points]
        trades = [{"exit_timestamp": epoch(points[min(i + 1, len(points) - 1)][0]),
                   "net_pnl": pnl} for i, pnl in enumerate(pnls)]
        write_csv(self.output / "equity.csv", list(equity[0]), equity)
        write_csv(self.output / "trades.csv", ["exit_timestamp", "net_pnl"], trades)
        return self.output


class CoverageValidationTests(FixtureCase):
    def coverage_fixture(self, rows=None):
        self.start = int(datetime(2026, 1, 20, tzinfo=timezone.utc).timestamp())
        self.end = self.start + 86400
        # Deliberately abbreviated, invented ten-second session, not a calendar.
        opened = epoch("2026-01-20", 10)
        self.rows = rows if rows is not None else [
            dict(zip(BAR_FIELDS, ["TSLA", opened + i * 5, opened + (i + 1) * 5,
                                 100, 101, 99, 100, 20, 1, "realtime5s"]))
            for i in range(2)
        ]
        self.bars = self.output / "SYNTHETIC_bars.csv"
        self.calendar = self.output / "SYNTHETIC_sessions.csv"
        self.manifest = self.output / "SYNTHETIC_manifest.json"
        write_csv(self.bars, BAR_FIELDS, self.rows)
        write_csv(self.calendar, SESSION_FIELDS, [dict(zip(SESSION_FIELDS, [
            "TSLA", "2026-01-20", opened, opened + 10, opened, opened + 10]))])
        self.provenance = {
            "status": "download_complete_requires_coverage_review",
            "bars_sha256": digest(self.bars), "sessions_sha256": digest(self.calendar),
            "effective_start_epoch": self.start, "requested_end_exclusive": "2026-01-21",
            "symbols_completed": ["TSLA"], "synthetic_test_fixture": True,
            "source": "INVENTED UNIT FIXTURE; NOT MARKET DATA",
        }
        self.save_manifest()

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.provenance) + "\n", encoding="utf-8")

    def validate(self):
        return validate_data.validate(self.bars, self.calendar, self.manifest,
                                      self.start, self.end, ["TSLA"])

    def test_complete_synthetic_coverage(self):
        self.coverage_fixture()
        result = self.validate()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["missing_5s_intervals"], 0)
        self.assertEqual(result["session_coverage"][0]["observed"], 2)

    def test_missing_bar_is_rejected_without_invention(self):
        self.coverage_fixture()
        write_csv(self.bars, BAR_FIELDS, self.rows[:1])
        self.provenance["bars_sha256"] = digest(self.bars)
        self.save_manifest()
        result = self.validate()
        self.assertEqual(result["missing_5s_intervals"], 1)
        self.assertTrue(any("unverified gaps" in error for error in result["errors"]))

    def test_empty_session_is_rejected(self):
        self.coverage_fixture(rows=[])
        result = self.validate()
        self.assertEqual(result["missing_5s_intervals"], 2)
        self.assertTrue(any("No intraday observations" in error for error in result["errors"]))

    def test_calendar_hash_mismatch_is_rejected(self):
        self.coverage_fixture()
        with self.calendar.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        result = self.validate()
        self.assertTrue(any("Session calendar SHA-256" in error for error in result["errors"]))

    def test_bar_hash_mismatch_is_rejected(self):
        self.coverage_fixture()
        self.provenance["bars_sha256"] = "0" * 64
        self.save_manifest()
        self.assertTrue(any("Historical data SHA-256" in error for error in self.validate()["errors"]))

    def test_malformed_ohlc_is_rejected_even_with_matching_hash(self):
        self.coverage_fixture()
        self.rows[0]["high"] = 98
        write_csv(self.bars, BAR_FIELDS, self.rows)
        self.provenance["bars_sha256"] = digest(self.bars)
        self.save_manifest()
        self.assertTrue(any("invalid OHLC or volume" in error for error in self.validate()["errors"]))

    def test_nonfinite_price_is_rejected(self):
        self.coverage_fixture()
        self.rows[0]["close"] = "nan"
        write_csv(self.bars, BAR_FIELDS, self.rows)
        self.provenance["bars_sha256"] = digest(self.bars)
        self.save_manifest()
        self.assertTrue(any("invalid OHLC or volume" in error for error in self.validate()["errors"]))

    def test_missing_symbol_completion_is_rejected(self):
        self.coverage_fixture()
        self.provenance["symbols_completed"] = []
        self.save_manifest()
        self.assertTrue(any("completion for every production symbol" in error
                            for error in self.validate()["errors"]))


class ReportingTests(FixtureCase):
    def test_known_metrics_reconcile(self):
        self.report_fixture([("2026-01-20", 1000), ("2026-01-21", 1100),
                             ("2026-01-22", 1050), ("2026-01-23", 1050)], [100, -50, 0])
        result = reporting.generate(self.output, 1000)
        self.assertEqual(result["total_closed_trades"], 3)
        self.assertEqual((result["winning_trades"], result["losing_trades"], result["flat_trades"]), (1, 1, 1))
        self.assertAlmostEqual(result["win_rate_percent"], 100 / 3)
        self.assertAlmostEqual(result["profit_factor"], 2)
        self.assertAlmostEqual(result["expectancy_per_trade"], 50 / 3)
        self.assertAlmostEqual(result["net_pnl"], 50)
        self.assertAlmostEqual(result["net_return_percent"], 5)
        self.assertAlmostEqual(result["max_drawdown_usd"], 50)
        self.assertAlmostEqual(result["max_drawdown_percent"], 50 / 1100 * 100)
        self.assertAlmostEqual(result["monthly"][0]["net_pnl"], 50)

    def test_zero_equity_month_has_undefined_return_without_crash(self):
        self.report_fixture([("2026-01-20", 1000), ("2026-01-30", 0),
                             ("2026-02-02", 0), ("2026-02-03", 10)])
        result = reporting.generate(self.output, 1000)
        self.assertEqual(result["monthly"][0]["return_percent"], -100)
        self.assertIsNone(result["monthly"][1]["return_percent"])
        self.assertIn("N/A", (self.output / "report.md").read_text(encoding="utf-8"))
        json.loads((self.output / "performance.json").read_text())

    def test_sharpe_unavailable_without_verified_calendar(self):
        points = [((datetime(2026, 1, 1) + timedelta(days=i)).date().isoformat(),
                   1000 + i * 3 + (i % 2) * 2) for i in range(25)]
        self.report_fixture(points)
        result = reporting.generate(self.output, 1000)
        self.assertGreaterEqual(result["sharpe_observations"], 20)
        self.assertIsNone(result["sharpe_ratio"])

    def test_synthetic_summary_cannot_be_relabelled_historical(self):
        self.report_fixture([("2026-01-20", 1000), ("2026-01-21", 1001)])
        result = reporting.generate(self.output, 1000, synthetic=False)
        self.assertEqual(result["status"], "SYNTHETIC_VERIFICATION_ONLY")
        self.assertIn("SYNTHETIC VERIFICATION", (self.output / "report.md").read_text(encoding="utf-8"))
        self.assertIn("SYNTHETIC VERIFICATION", (self.output / "equity.svg").read_text(encoding="utf-8"))

    def test_verified_session_filter_and_sharpe_known_example(self):
        points = [("2025-12-31", 1000)]
        value, expected_returns = 1000.0, []
        dates = set()
        for i in range(20):
            day = (datetime(2026, 1, 1) + timedelta(days=i)).date().isoformat()
            change = .01 if i % 2 == 0 else -.005
            value *= 1 + change
            points.append((day, value))
            dates.add(day)
            expected_returns.append(change)
        points.append(("2026-01-21", value))  # Artificial excluded end marker.
        self.report_fixture(points)
        result = reporting.generate(self.output, 1000, session_dates=dates)
        self.assertEqual(result["sharpe_observations"], 20)
        expected = statistics.mean(expected_returns) / statistics.stdev(expected_returns) * math.sqrt(252)
        self.assertAlmostEqual(result["sharpe_ratio"], expected)
        self.assertEqual([m["month"] for m in result["monthly"]], ["2026-01"])


if __name__ == "__main__":
    FIXTURES.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    record = {"status": "PASS" if result.wasSuccessful() else "FAIL",
              "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "historical_market_data_used": False,
              "fixture_scope": "SYNTHETIC UNIT TESTS ONLY"}
    (FIXTURES / "test_results.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
