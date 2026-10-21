"""Paid-run controls (no API call is ever made here).

One fixed private ledger (path and id from the OWNER's environment), a new or
swapped ledger refused, explicit per-run approval, audit columns, settings
marked APPROVED vs PROVISIONAL, and Usage reconciliation flags.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import agent_paid_ledger_report as report
from scripts import agent_sdk_coordination_pilot as pilot

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_sdk_coordination_pilot.py"
NOW = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)


class FixedLedger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.ledger = self.dir / "paid_attempts.sqlite"
        self.ledger_id = pilot.init_paid_ledger(self.ledger)
        self.env = {pilot.PAID_LEDGER_PATH_ENV: str(self.ledger), pilot.PAID_LEDGER_ID_ENV: self.ledger_id,
                    pilot.PAID_RUN_APPROVAL_ENV: "approved_run_0001"}

    def check(self, path=None, run_id="approved_run_0001", **env):
        merged = {**self.env, **env}
        with patch.dict(os.environ, {k: v for k, v in merged.items() if v is not None}, clear=False):
            for k, v in merged.items():
                if v is None:
                    os.environ.pop(k, None)
            pilot.check_paid_ledger(path or self.ledger, run_id)

    def test_configured_ledger_and_approved_run_pass(self):
        self.check()

    def test_init_refuses_an_existing_file(self):
        with self.assertRaisesRegex(pilot.Blocked, "INIT_PATH_INVALID_OR_EXISTS"):
            pilot.init_paid_ledger(self.ledger)

    def test_other_location_is_refused(self):
        other = self.dir / "other.sqlite"
        pilot.init_paid_ledger(other)
        with self.assertRaisesRegex(pilot.Blocked, "NOT_THE_FIXED_LOCATION"):
            self.check(path=other)

    def test_swapped_ledger_file_is_refused(self):
        self.ledger.unlink()
        pilot.init_paid_ledger(self.ledger)  # same path, new identity: counts would restart
        with self.assertRaisesRegex(pilot.Blocked, "IDENTITY_MISMATCH"):
            self.check()

    def test_missing_configuration_is_refused(self):
        for key, reason in ((pilot.PAID_LEDGER_PATH_ENV, "LOCATION_NOT_CONFIGURED"),
                            (pilot.PAID_LEDGER_ID_ENV, "ID_NOT_CONFIGURED")):
            with self.subTest(key=key), self.assertRaisesRegex(pilot.Blocked, reason):
                self.check(**{key: None})

    def test_run_must_be_explicitly_approved(self):
        with self.assertRaisesRegex(pilot.Blocked, "NOT_APPROVED_FOR_THIS_RUN_ID"):
            self.check(run_id="another_run_0002")
        with self.assertRaisesRegex(pilot.Blocked, "NOT_APPROVED_FOR_THIS_RUN_ID"):
            self.check(**{pilot.PAID_RUN_APPROVAL_ENV: None})

    def test_reservation_records_the_audited_limits(self):
        pilot.reserve_billable_attempt(self.ledger, "approved_run_0001", "fp", slot_key="2026-10-21:premarket_0830", now=NOW)
        with closing(sqlite3.connect(self.ledger)) as conn:
            row = conn.execute("SELECT model, max_output_tokens, timeout_seconds, max_model_calls, reserved_cents"
                               " FROM paid_attempts").fetchone()
        self.assertEqual(row, (pilot.PAID_MODEL, 600, 30, 5, 100))

    def test_cli_billable_run_without_approval_stops_before_any_reservation(self):
        fixture = self.dir / "evidence.json"
        fixture.write_text((ROOT / "examples" / "agent_sdk_public_synthetic_20261021.json").read_text("utf-8"), encoding="utf-8")
        env = dict(os.environ, **self.env, OPENAI_API_KEY="sk-fake-unit-test-not-real")
        env.pop(pilot.PAID_RUN_APPROVAL_ENV)
        env.pop("OPENAI_AGENT_MODEL", None)
        env.pop("OPENAI_BASE_URL", None)
        out = subprocess.run([sys.executable, str(SCRIPT), "--input", str(fixture), "--enable-billable-api",
                              "--paid-budget-db", str(self.ledger)], env=env, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("PAID_RUN_NOT_APPROVED_FOR_THIS_RUN_ID_NO_CALL", out.stdout)
        with closing(sqlite3.connect(self.ledger)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("paid_attempts", tables)


class Settings(unittest.TestCase):
    def test_owner_decisions_and_provisional_values_are_marked(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--print-settings"], cwd=ROOT, text=True, capture_output=True)
        got = json.loads(out.stdout)
        self.assertTrue(got["model"]["status"].startswith("APPROVED"))
        self.assertTrue(got["lifetime_reserved_cents"]["status"].startswith("APPROVED"))
        for key in ("max_paid_runs_per_jst_day", "role_validity_hours", "role_source_window_hours"):
            self.assertEqual(got[key]["status"], "PROVISIONAL")
        self.assertEqual(got["run_frequency"]["status"], "UNDECIDED")


class UsageReconciliation(unittest.TestCase):
    def test_flags(self):
        ledger = {"2026-10-21": {"runs": 1, "reserved_cents": 100}}
        self.assertEqual(report.reconcile(ledger, {"2026-10-21": 3})["flags"], [])
        got = report.reconcile(ledger, {"2026-10-20": 50, "2026-10-21": 150})
        self.assertEqual(got["flags"], ["USAGE_WITHOUT_RESERVATION:2026-10-20", "USAGE_OVER_RESERVATION:2026-10-21"])
        self.assertIn("TOTAL_OVER_PREPAID_CREDIT", report.reconcile(ledger, {"2026-10-21": 1200})["flags"])
        self.assertEqual(report.reconcile(ledger, None)["usage"], "NOT_PROVIDED")

    def test_cli_reads_ledger_and_usage_export(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "paid.sqlite"
            pilot.init_paid_ledger(ledger)
            pilot.reserve_billable_attempt(ledger, "usage_run_0001", "fp", slot_key="k", now=NOW)
            usage = Path(td) / "usage.csv"
            usage.write_text("date,cost_usd\n2026-10-21,0.04\n", encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_paid_ledger_report.py"), "--ledger",
                                  str(ledger), "--usage-csv", str(usage)], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            got = json.loads(out.stdout)
            self.assertEqual((got["reserved_cents_total"], got["usage_cents_total"], got["flags"]), (100, 4, []))


if __name__ == "__main__":
    unittest.main()
