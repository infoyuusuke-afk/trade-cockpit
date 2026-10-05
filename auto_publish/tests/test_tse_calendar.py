"""TSE trading-day calendar: JPX-sourced closures, fail-closed outside coverage."""
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from auto_publish.app.errors import ValidationError
from auto_publish.app.export.cockpit_export import build_export
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.marketcal.tse import DEFAULT_PATH, CalendarError, load_calendar
from auto_publish.tests.helpers import TESTS_DIR, PipelineCase

REAL = TESTS_DIR / "fixtures" / "cockpit_export" / "2026-09-25"


class TestCalendarData(unittest.TestCase):
    def setUp(self):
        self.cal = load_calendar()

    def test_jpx_2026_closures(self):
        closed = ["2026-01-01", "2026-01-02", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20", "2026-04-29",
                  "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22",
                  "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31"]
        for d in closed:
            st = self.cal.status(d)
            self.assertFalse(st.trading, d)
            self.assertTrue(st.reason.startswith("closure:"), (d, st.reason))

    def test_silver_week_2026_and_2027_substitute_holiday(self):
        self.assertEqual(self.cal.status("2026-09-22").reason, "closure:休日（国民の休日）")
        self.assertFalse(self.cal.is_trading_day("2027-03-22"))   # 振替休日
        self.assertTrue(self.cal.is_trading_day("2027-03-23"))

    def test_ordinary_sessions_and_close_time(self):
        for d in ("2026-09-24", "2026-09-25", "2026-12-30", "2027-01-04", "2026-01-05"):
            st = self.cal.status(d)
            self.assertTrue(st.trading, d)
            self.assertEqual(st.close_jst, "15:30")

    def test_weekends(self):
        self.assertEqual(self.cal.status("2026-09-26").reason, "weekend")
        self.assertEqual(self.cal.status("2026-09-27").reason, "weekend")

    def test_uncovered_year_is_fail_closed(self):
        for d in ("2025-12-30", "2028-01-04"):
            with self.assertRaises(CalendarError) as cm:
                self.cal.status(d)
            self.assertEqual(cm.exception.code, "CALENDAR_UNAVAILABLE")

    def test_next_and_previous_trading_day_skip_holidays(self):
        self.assertEqual(self.cal.next_trading_day("2026-09-18"), date(2026, 9, 24))   # Fri -> after silver week
        self.assertEqual(self.cal.previous_trading_day("2026-09-24"), date(2026, 9, 18))
        self.assertEqual(self.cal.next_trading_day("2026-12-30"), date(2027, 1, 4))

    def test_every_covered_year_has_year_end_and_new_year(self):
        raw = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        for y in raw["covered_years"]:
            for mmdd in ("12-31", "01-01", "01-02", "01-03"):
                d = f"{y}-{mmdd}"
                self.assertFalse(self.cal.is_trading_day(d), d)

    def test_sources_are_recorded(self):
        self.assertTrue(any("jpx.co.jp" in s for s in self.cal.sources))
        self.assertEqual(len(self.cal.sha256), 64)


class TestCalendarFileValidation(unittest.TestCase):
    def write(self, mutate):
        doc = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        mutate(doc)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "cal.json"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return p

    def expect_invalid(self, mutate, code="CALENDAR_INVALID"):
        with self.assertRaises(CalendarError) as cm:
            load_calendar(self.write(mutate))
        self.assertEqual(cm.exception.code, code)

    def test_missing_year_end_closure_rejected(self):
        self.expect_invalid(lambda d: d["closures"].pop("2026-12-31"))

    def test_date_outside_covered_years_rejected(self):
        self.expect_invalid(lambda d: d["closures"].update({"2028-01-01": "x"}))

    def test_malformed_date_rejected(self):
        self.expect_invalid(lambda d: d["closures"].update({"2026-9-1": "x"}))

    def test_bad_schema_rejected(self):
        self.expect_invalid(lambda d: d.update(schema="v0"))

    def test_missing_file_is_unavailable(self):
        with self.assertRaises(CalendarError) as cm:
            load_calendar(Path(tempfile.gettempdir()) / "no_such_calendar.json")
        self.assertEqual(cm.exception.code, "CALENDAR_UNAVAILABLE")

    def test_extra_closure_and_session_override(self):
        def mut(d):
            d["extra_closures"]["2026-10-01"] = "system outage (example)"
            d["session_overrides"]["2026-10-02"] = {"close_jst": "13:00", "reason": "example"}
        cal = load_calendar(self.write(mut))
        self.assertEqual(cal.status("2026-10-01").reason, "extra_closure:system outage (example)")
        self.assertEqual(cal.status("2026-10-02").close_jst, "13:00")
        self.expect_invalid(lambda d: d["session_overrides"].update({"2026-10-02": {"close_jst": "1pm"}}))


class TestCalendarInPipeline(PipelineCase):
    def relabel(self, new_date, generated_at):
        new = self.drop.parent / new_date
        self.drop.rename(new)
        p = new / "daily_summary.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc.update(session_date=new_date, generated_at=generated_at)
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return new

    def test_validate_rejects_jpx_holiday(self):
        new = self.relabel("2026-09-22", "2026-09-22T15:45:00+09:00")   # Tuesday, market holiday
        self.ctx.clock.set(self.ctx.clock.now().replace(day=22))
        ingest(self.ctx, new)
        with self.assertRaises(ValidationError) as cm:
            validate(self.ctx, "2026-09-22")
        self.assertEqual(cm.exception.code, "NOT_TRADING_DAY")
        self.assertIn("休日", cm.exception.details["reason"])
        state = self.ctx.conn.execute("SELECT state FROM sessions").fetchone()[0]
        self.assertEqual(state, "FAILED")

    def test_validate_records_calendar_hash(self):
        self.ingest_validate()
        detail = self.ctx.conn.execute(
            "SELECT detail_json FROM audit_log WHERE to_state='VALIDATED'").fetchone()[0]
        self.assertEqual(json.loads(detail)["tse_calendar_sha256"], load_calendar().sha256)

    def test_session_override_changes_close_used_for_freshness(self):
        # A shortened session (close 13:00) makes a 14:00 summary valid instead of premature.
        doc = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        doc["session_overrides"]["2026-09-24"] = {"close_jst": "13:00", "reason": "test"}
        p = self.root / "cal.json"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.ctx.cfg["tse_calendar_path"] = str(p)
        s = self.drop / "daily_summary.json"
        d = json.loads(s.read_text(encoding="utf-8"))
        d["generated_at"] = "2026-09-24T14:00:00+09:00"
        s.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        ingest(self.ctx, self.drop)
        self.assertEqual(validate(self.ctx, "2026-09-24")["state"], "VALIDATED")


class TestCalendarInExporter(unittest.TestCase):
    def test_export_rejects_holiday_and_uncovered_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            for d, code in (("2026-09-23", "NOT_TRADING_DAY"), ("2028-09-25", "CALENDAR_UNAVAILABLE")):
                with self.assertRaises(ValidationError) as cm:
                    build_export(d, REAL / "data.json", REAL / "paper_trade_history.json")
                self.assertEqual(cm.exception.code, code, d)


if __name__ == "__main__":
    unittest.main()
