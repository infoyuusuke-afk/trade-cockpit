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


_ANCHOR_PATCH = None


def setUpModule():
    # Never touch the real %LOCALAPPDATA% registry or spend anchor from tests.
    global _REGISTRY_PATCH, _ANCHOR_PATCH
    _REGISTRY_PATCH = patch.dict(os.environ, {pilot.PAID_LEDGER_REGISTRY_ENV: str(Path(_REGISTRY_DIR.name) / "registry.json")})
    _REGISTRY_PATCH.start()
    _ANCHOR_PATCH = patch.object(pilot, "spend_anchor_path", lambda: Path(_REGISTRY_DIR.name) / "anchor.json")
    _ANCHOR_PATCH.start()
    # The HKCU copy is a temp file here: tests never write the real registry.
    _MIRROR_PATCHES[:] = [patch.object(pilot, "_read_mirror", _fake_read_mirror),
                          patch.object(pilot, "_write_mirror", _fake_write_mirror)]
    for p in _MIRROR_PATCHES:
        p.start()


def _mirror_file():
    return Path(_REGISTRY_DIR.name) / "mirror.json"


def _fake_read_mirror():
    path = _mirror_file()
    if not path.exists():
        return None
    rec = json.loads(path.read_text("utf-8"))
    if not pilot._valid_record(rec):
        raise pilot.Blocked("PAID_SPEND_MIRROR_INVALID_NO_CALL")
    return rec


def _fake_write_mirror(rec):
    _mirror_file().write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")


_MIRROR_PATCHES = []


def tearDownModule():
    for p in _MIRROR_PATCHES:
        p.stop()
    _ANCHOR_PATCH.stop()
    _REGISTRY_PATCH.stop()
    _REGISTRY_DIR.cleanup()


def fresh_registry():
    path = Path(os.environ[pilot.PAID_LEDGER_REGISTRY_ENV])
    if path.exists():
        path.unlink()
    for record in (pilot.spend_anchor_path(), _mirror_file()):
        if record.exists():
            record.unlink()


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
        per, cap = pilot.PAID_RESERVED_CENTS_PER_RUN, pilot.PAID_TOTAL_LEDGER_CENTS
        old_runs = cap // per - 2
        for i in range(old_runs):
            pilot.reserve_billable_attempt(self.ledger, "old_run_%04d" % i, "fp", slot_key="k%d" % i,
                                           now=NOW + timedelta(days=i))
        pilot.retire_paid_ledger(self.ledger_id, "moved to a new disk")
        new = self.dir / "new.sqlite"
        pilot.init_paid_ledger(new)
        carried = pilot.carried_cents(pilot.read_registry())
        self.assertEqual(carried, old_runs * per)
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
        self.assertEqual(row, (pilot.PAID_MODEL, 600, 30, 5, 25))   # OWNER 2026-10-22: 25 cents per run

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


class SpendAnchor(unittest.TestCase):
    """D-041 (1)(2), audit item 5: two copies, never a fresh start, no reset by files or env."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        fresh_registry()
        self.ledger = self.dir / "paid.sqlite"
        self.ledger_id = pilot.init_paid_ledger(self.ledger)

    def adopt_after_first_run(self):
        # the OWNER PC already had paid runs: a reservation exists, then the record is adopted
        pilot.reserve_billable_attempt(self.ledger, "anchor_run_0000", "fp", slot_key="s0", now=NOW)
        pilot.adopt_spend_anchor()

    def reserve(self, ledger, i):
        carried = pilot.spend_anchor_carried(pilot.read_registry())
        pilot.reserve_billable_attempt(ledger, "anchor_run_%04d" % i, "fp", slot_key="s%d" % i,
                                       now=NOW + timedelta(days=i), carried=carried)
        pilot.record_spend_anchor(pilot.read_registry())

    def test_no_automatic_first_use(self):
        with self.assertRaisesRegex(pilot.Blocked, "PAID_SPEND_ANCHOR_MISSING_NO_CALL"):
            pilot.spend_anchor_carried(pilot.read_registry())
        with self.assertRaisesRegex(pilot.Blocked, "ADOPT_NEEDS_EXISTING_RESERVATIONS"):
            pilot.adopt_spend_anchor()
        self.assertIsNone(pilot.read_spend_anchor())

    def test_adopt_then_each_reservation_raises_both_copies(self):
        self.adopt_after_first_run()
        per = pilot.PAID_RESERVED_CENTS_PER_RUN
        self.assertEqual(pilot.read_spend_anchor()["high_water_cents"], per)
        self.reserve(self.ledger, 1)
        rec = pilot.read_spend_anchor()
        self.assertEqual((rec["high_water_cents"], rec["revision"]), (2 * per, 2))
        self.assertEqual(json.loads(_mirror_file().read_text("utf-8")), rec)
        with self.assertRaisesRegex(pilot.Blocked, "ALREADY_EXISTS"):
            pilot.adopt_spend_anchor()

    def test_one_copy_deleted_or_changed_stops(self):
        self.adopt_after_first_run()
        _mirror_file().unlink()
        with self.assertRaisesRegex(pilot.Blocked, "ONE_COPY_MISSING"):
            pilot.spend_anchor_carried(pilot.read_registry())
        with self.assertRaisesRegex(pilot.Blocked, "ALREADY_EXISTS"):
            pilot.adopt_spend_anchor()                 # cannot be rebuilt over one remaining copy
        rec = json.loads(pilot.spend_anchor_path().read_text("utf-8"))
        _fake_write_mirror(dict(rec, high_water_cents=0))   # lowered in one copy
        with self.assertRaisesRegex(pilot.Blocked, "COPIES_DIFFER"):
            pilot.spend_anchor_carried(pilot.read_registry())

    def test_both_copies_deleted_after_runs_stop_not_a_first_use(self):
        self.adopt_after_first_run()
        pilot.spend_anchor_path().unlink()
        _mirror_file().unlink()
        with self.assertRaisesRegex(pilot.Blocked, "PAID_SPEND_ANCHOR_MISSING_NO_CALL"):
            pilot.spend_anchor_carried(pilot.read_registry())

    def test_new_registry_and_recreated_ledger_stop_instead_of_resetting(self):
        self.adopt_after_first_run()
        high = pilot.read_spend_anchor()["high_water_cents"]
        Path(os.environ[pilot.PAID_LEDGER_REGISTRY_ENV]).unlink()   # registry deleted (or env points elsewhere)
        self.ledger.unlink()                                        # ledger deleted
        new_id = pilot.init_paid_ledger(self.ledger)                # and re-created
        rec = pilot.read_spend_anchor()
        self.assertIn(new_id, rec["ledger_ids"])
        self.assertEqual(rec["high_water_cents"], high)             # the total is kept
        with self.assertRaisesRegex(pilot.Blocked, "PAID_LEDGER_ROLLBACK_DETECTED_NO_CALL"):
            pilot.spend_anchor_carried(pilot.read_registry())       # fail-closed, no reset

    def test_a_properly_retired_ledger_carries_its_total(self):
        self.adopt_after_first_run()
        pilot.retire_paid_ledger(self.ledger_id, "new disk")
        pilot.init_paid_ledger(self.dir / "next.sqlite")
        self.assertEqual(pilot.spend_anchor_carried(pilot.read_registry()), pilot.PAID_RESERVED_CENTS_PER_RUN)

    def test_rollback_and_unknown_ledger_stop(self):
        self.adopt_after_first_run()
        with closing(sqlite3.connect(self.ledger)) as conn, conn:
            conn.execute("DELETE FROM paid_attempts")
        with self.assertRaisesRegex(pilot.Blocked, "PAID_LEDGER_ROLLBACK_DETECTED_NO_CALL"):
            pilot.spend_anchor_carried(pilot.read_registry())
        rec = pilot.read_spend_anchor()
        pilot._write_spend_anchor([], rec["high_water_cents"], rec["revision"] + 1)
        with self.assertRaisesRegex(pilot.Blocked, "PAID_LEDGER_NOT_IN_SPEND_ANCHOR_NO_CALL"):
            pilot.spend_anchor_carried(pilot.read_registry())

    def test_unreadable_or_invalid_file_stops(self):
        self.adopt_after_first_run()
        path = pilot.spend_anchor_path()
        for body, reason in (("{not json", "UNREADABLE"), ('{"schema": "x"}', "INVALID")):
            path.write_text(body, encoding="utf-8")
            with self.subTest(body=body), self.assertRaisesRegex(pilot.Blocked, "PAID_SPEND_ANCHOR_" + reason):
                pilot.spend_anchor_carried(pilot.read_registry())

    def test_record_locations_are_not_taken_from_the_environment(self):
        source = SCRIPT.read_text(encoding="utf-8")
        body = source[source.index("def _known_local_appdata"):source.index("def spend_anchor_path")]
        self.assertNotIn("os.environ", body)
        self.assertIn("SHGetKnownFolderPath", body)
        self.assertIn('SPEND_MIRROR_KEY = r"Software\\100B_AGENT\\PaidSpend"', source)
        self.assertIn("winreg.HKEY_CURRENT_USER", source)
        self.assertIn("RESIDUAL RISK", source)

    def test_cli_main_uses_the_record(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("carried=spend_anchor_carried(read_registry()))", source)
        self.assertIn("record_spend_anchor(read_registry())", source)


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
            self.assertEqual((got["reserved_cents_total"], got["usage_cents_total"], got["flags"]), (pilot.PAID_RESERVED_CENTS_PER_RUN, 4, []))
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
