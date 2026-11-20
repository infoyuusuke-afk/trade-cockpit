"""Paid-run controls (no API call is ever made here).

One fixed private ledger (path and id from the OWNER's environment), a new or
swapped ledger refused, explicit per-run approval, audit columns, settings
marked APPROVED vs PROVISIONAL, and Usage reconciliation flags.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
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
_REGISTRY_DIR = tempfile.TemporaryDirectory(prefix="v10-ledger-registry-")
_REGISTRY_PATCH = None


def setUpModule():
    # Never touch the real %LOCALAPPDATA% registry from tests.
    global _REGISTRY_PATCH
    _REGISTRY_PATCH = patch.dict(os.environ, {pilot.PAID_LEDGER_REGISTRY_ENV: str(Path(_REGISTRY_DIR.name) / "registry.json")})
    _REGISTRY_PATCH.start()


def tearDownModule():
    _REGISTRY_PATCH.stop()
    _REGISTRY_DIR.cleanup()


def fresh_registry():
    path = Path(os.environ[pilot.PAID_LEDGER_REGISTRY_ENV])
    if path.exists():
        path.unlink()


class FixedLedger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.ledger = self.dir / "paid_attempts.sqlite"
        fresh_registry()
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
        with self.assertRaisesRegex(pilot.Blocked, "NOT_THE_FIXED_LOCATION"):
            self.check(path=self.dir / "other.sqlite")

    def test_a_second_ledger_cannot_be_started_while_one_is_active(self):
        with self.assertRaisesRegex(pilot.Blocked, "ALREADY_ACTIVE"):
            pilot.init_paid_ledger(self.dir / "second.sqlite")

    def test_swapped_ledger_file_is_refused(self):
        self.ledger.unlink()
        fresh_registry()
        pilot.init_paid_ledger(self.ledger)  # same path, new identity: counts would restart
        with self.assertRaisesRegex(pilot.Blocked, "IDENTITY_MISMATCH"):
            self.check()

    def test_env_pointing_at_an_unregistered_ledger_is_refused(self):
        other = self.dir / "other.sqlite"
        pilot.retire_paid_ledger(self.ledger_id, "test")
        other_id = pilot.init_paid_ledger(other)
        with self.assertRaisesRegex(pilot.Blocked, "NOT_THE_REGISTERED_ACTIVE_LEDGER"):
            self.check()  # env still names the retired ledger
        self.check(path=other, **{pilot.PAID_LEDGER_PATH_ENV: str(other), pilot.PAID_LEDGER_ID_ENV: other_id})

    def test_retired_reservations_keep_counting(self):
        for i in range(6):
            pilot.reserve_billable_attempt(self.ledger, "old_run_%04d" % i, "fp", slot_key="k%d" % i,
                                           now=NOW + timedelta(days=i))
        pilot.retire_paid_ledger(self.ledger_id, "moved to a new disk")
        new = self.dir / "new.sqlite"
        pilot.init_paid_ledger(new)
        carried = pilot.carried_cents(pilot.read_registry())
        self.assertEqual(carried, 600)
        pilot.reserve_billable_attempt(new, "new_run_0001", "fp", slot_key="n1", now=NOW, carried=carried)
        pilot.reserve_billable_attempt(new, "new_run_0002", "fp", slot_key="n2", now=NOW + timedelta(days=1), carried=carried)
        with self.assertRaisesRegex(pilot.Blocked, "LOCAL_BUDGET_RESERVATION_EXHAUSTED"):
            pilot.reserve_billable_attempt(new, "new_run_0003", "fp", slot_key="n3", now=NOW + timedelta(days=2), carried=carried)

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
                              "--synthetic-paid-trial", "--paid-budget-db", str(self.ledger)],
                             env=env, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("PAID_RUN_NOT_APPROVED_FOR_THIS_RUN_ID_NO_CALL", out.stdout)
        with closing(sqlite3.connect(self.ledger)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("paid_attempts", tables)


class BillableSourceGate(unittest.TestCase):
    def doc(self, *types):
        rows = []
        for i, t in enumerate(types):
            rows.append({"source_type": t, "source_id": "s%d" % i})
        return {"sources": rows}

    def test_statistics_figures_need_the_owner_decision(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(pilot.PAID_ALLOW_STATISTICS_ENV, None)
            with self.assertRaisesRegex(pilot.Blocked, "OFFICIAL_STATISTICS_FIGURES_NEED_OWNER_DECISION"):
                pilot.check_billable_sources(self.doc("OFFICIAL_STATISTICS_FILE"), synthetic_trial=False)
        with patch.dict(os.environ, {pilot.PAID_ALLOW_STATISTICS_ENV: pilot.PAID_ALLOW_STATISTICS_VALUE}):
            pilot.check_billable_sources(self.doc("OFFICIAL_STATISTICS_FILE", "OFFICIAL_RSS_HEADLINE"), synthetic_trial=False)
        pilot.check_billable_sources(self.doc("OFFICIAL_RSS_HEADLINE"), synthetic_trial=False)

    def test_synthetic_evidence_only_in_an_explicit_synthetic_trial(self):
        with self.assertRaisesRegex(pilot.Blocked, "SYNTHETIC_EVIDENCE_NEEDS_SYNTHETIC_PAID_TRIAL_ONLY"):
            pilot.check_billable_sources(self.doc("SYNTHETIC_TEST"), synthetic_trial=False)
        with self.assertRaisesRegex(pilot.Blocked, "SYNTHETIC_EVIDENCE_NEEDS_SYNTHETIC_PAID_TRIAL_ONLY"):
            pilot.check_billable_sources(self.doc("SYNTHETIC_TEST", "OFFICIAL_RSS_HEADLINE"), synthetic_trial=True)
        with self.assertRaisesRegex(pilot.Blocked, "SYNTHETIC_PAID_TRIAL_WITH_REAL_EVIDENCE"):
            pilot.check_billable_sources(self.doc("OFFICIAL_RSS_HEADLINE"), synthetic_trial=True)
        pilot.check_billable_sources(self.doc("SYNTHETIC_TEST"), synthetic_trial=True)


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
            fresh_registry()
            ledger_id = pilot.init_paid_ledger(ledger)
            pilot.reserve_billable_attempt(ledger, "usage_run_0001", "fp", slot_key="k", now=NOW)
            usage = Path(td) / "usage.csv"
            usage.write_text("date,cost_usd\n2026-10-21,0.04\n", encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_paid_ledger_report.py"), "--ledger",
                                  str(ledger), "--usage-csv", str(usage)], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            got = json.loads(out.stdout)
            self.assertEqual((got["reserved_cents_total"], got["usage_cents_total"], got["flags"]), (100, 4, []))
            self.assertEqual((got["ledger_id"], got["usage_dates"]), (ledger_id, "UTC"))

    def test_usage_dates_in_utc_are_compared_with_the_utc_day_of_each_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "paid.sqlite"
            fresh_registry()
            pilot.init_paid_ledger(ledger)
            # 08:00 JST on 10/21 = 23:00 UTC on 10/20: JST day 10/21, UTC day 10/20
            pilot.reserve_billable_attempt(ledger, "tz_run_0001", "fp", slot_key="k",
                                           now=datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc))
            self.assertEqual(report.reconcile(report.ledger_days(ledger, usage_dates="UTC"), {"2026-10-20": 5})["flags"], [])
            self.assertEqual(report.reconcile(report.ledger_days(ledger, usage_dates="JST"), {"2026-10-21": 5})["flags"], [])
            self.assertEqual(report.reconcile(report.ledger_days(ledger, usage_dates="JST"), {"2026-10-20": 5})["flags"],
                             ["USAGE_WITHOUT_RESERVATION:2026-10-20"])

    def test_report_flags_a_ledger_without_identity(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "bare.sqlite"
            pilot.reserve_billable_attempt(ledger, "bare_run_0001", "fp", slot_key="k", now=NOW)
            self.assertIsNone(report.ledger_identity(ledger))


if __name__ == "__main__":
    unittest.main()
