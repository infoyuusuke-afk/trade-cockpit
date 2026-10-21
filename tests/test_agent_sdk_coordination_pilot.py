"""Synthetic CI for the 100B Agents SDK coordination pilot.

No SDK, API key, external network, Excel, broker or scheduled Task is needed.
"""
import asyncio
from datetime import datetime, timezone
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_sdk_coordination_pilot.py"
spec = importlib.util.spec_from_file_location("agent_sdk_coordination_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)


def sample():
    def src(role, suffix):
        return {
            "source_id": f"public_{suffix}",
            "role": role,
            "source_url": "https://www.jpx.co.jp/markets/",
            "as_of": "2026-10-19T09:00:00+09:00",
            "available_at": "2026-10-19T15:00:00+09:00",
            "summary": "Synthetic public evidence; no actual financial observation",
        }
    return {
        "schema_version": pilot.SCHEMA,
        "run_id": "synthetic_20261020_01",
        "sources": [
            src("pre_next", "alpha"),
            src("supply_sq", "beta"),
            src("revenue_hunter", "gamma"),
        ],
    }


async def fake_provider(role, prompt):
    if role == "progress_coordinator":
        reports = json.loads(prompt)["reports"]
        assert len(reports) == 3
        assert all(r["real_submit_allowed"] is False for r in reports)
        return {
            "summary": "Research-only synthetic comparison",
            "conflicts": ["No real validation yet"],
            "next_checks": ["Verify official source availability"],
        }
    d = json.loads(prompt)
    return {
        "role": role,
        "status": "WATCH",
        "evidence_ids": [x["source_id"] for x in d["sources"]],
        "hypothesis": "Unverified watch-only hypothesis",
        "invalidation": "Missing or stale data",
    }


class Validation(unittest.TestCase):
    def test_accepts_only_immutable_public_safe_timestamps(self):
        got = pilot.validate_snapshot(sample(), NOW)
        self.assertEqual(len(got["sources"]), 3)
        self.assertNotIn("OPENAI_API_KEY", json.dumps(got))

    def test_future_available_at_blocks_even_if_asof_old(self):
        d = sample()
        d["sources"][0]["available_at"] = "2026-10-21T00:00:00+09:00"
        with self.assertRaises(pilot.Blocked):
            pilot.validate_snapshot(d, NOW)

    def test_asof_after_publication_blocks(self):
        d = sample()
        d["sources"][0]["as_of"] = "2026-10-20T05:00:00+09:00"
        with self.assertRaises(pilot.Blocked):
            pilot.validate_snapshot(d, NOW)

    def test_offsetless_timestamp_blocks(self):
        d = sample()
        d["sources"][0]["available_at"] = "2026-10-19T15:00:00"
        with self.assertRaises(pilot.Blocked):
            pilot.validate_snapshot(d, NOW)

    def test_duplicate_source_id_blocks(self):
        d = sample()
        d["sources"][1]["source_id"] = d["sources"][0]["source_id"]
        with self.assertRaises(pilot.Blocked):
            pilot.validate_snapshot(d, NOW)

    def test_sensitive_url_shape_is_not_accepted(self):
        d = sample()
        d["sources"][0]["source_url"] = "https://user:password@example.org/a?token=SECRET"
        with self.assertRaises(pilot.Blocked):
            pilot.validate_snapshot(d, NOW)

    def test_unsupported_role_blocks(self):
        d = sample()
        d["sources"][2]["role"] = "broker_execution"
        with self.assertRaises(pilot.Blocked):
            pilot.validate_snapshot(d, NOW)

    def test_missing_reference_is_rejected_not_fabricated(self):
        with self.assertRaises(pilot.Blocked):
            pilot.validate_specialist("pre_next", {
                "role": "pre_next", "status": "WATCH",
                "evidence_ids": ["fabricated"], "hypothesis": "guess",
                "invalidation": "unknown",
            }, sample()["sources"][:1])

    def test_watch_requires_evidence(self):
        with self.assertRaises(pilot.Blocked):
            pilot.validate_specialist("pre_next", {
                "role": "pre_next", "status": "WATCH",
                "evidence_ids": [], "hypothesis": "guess", "invalidation": "unknown",
            }, sample()["sources"][:1])

    def test_unsafe_coordinator_output_is_rejected(self):
        with self.assertRaises(pilot.Blocked):
            pilot.validate_coordinator({
                "summary": "x", "conflicts": [], "next_checks": [""] * 9
            })


class Orchestration(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_roles_route_without_api_or_broker(self):
        seen = []
        async def track(role, prompt):
            seen.append(role)
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(sample(), track, now=NOW)
        self.assertEqual(seen, [
            "pre_next", "supply_sq", "revenue_hunter", "progress_coordinator"
        ])
        self.assertEqual(result["state"], "RESEARCH_ONLY_NOT_LIVE")
        self.assertIs(result["real_submit_allowed"], False)
        self.assertIs(result["broker_fills_verified"], False)
        self.assertIs(result["promotion_eligible"], False)
        self.assertIsNone(result["actual_profit_yen"])

    async def test_missing_specialist_data_is_explicit_no_data(self):
        d = sample()
        d["sources"] = d["sources"][:1]
        called = []
        async def track(role, prompt):
            called.append(role)
            if role == "progress_coordinator":
                self.assertEqual(
                    [r["status"] for r in json.loads(prompt)["reports"]],
                    ["WATCH", "NO_DATA", "NO_DATA"],
                )
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(d, track, now=NOW)
        self.assertEqual(called, ["pre_next", "progress_coordinator"])
        self.assertEqual(result["specialists"][1]["status"], "NO_DATA")

    async def test_hallucinated_evidence_fails_closed_without_coordinator(self):
        called = []
        async def bad(role, prompt):
            called.append(role)
            return {
                "role": role, "status": "WATCH", "evidence_ids": ["not_in_payload"],
                "hypothesis": "bad", "invalidation": "none",
            }
        with self.assertRaises(pilot.Blocked):
            await pilot.coordinate(sample(), bad, now=NOW)
        self.assertEqual(called, ["pre_next"])


class LocalReceipt(unittest.TestCase):
    def test_idempotent_same_result_and_conflicting_replay_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "private_receipts.sqlite"
            result = asyncio.run(pilot.coordinate(
                sample(), fake_provider, now=NOW))
            fp = pilot.fingerprint(sample())
            self.assertEqual(pilot.persist_receipt(db, result, fp), "RECORDED")
            self.assertEqual(pilot.persist_receipt(db, result, fp),
                             "IDEMPOTENT_ALREADY_RECORDED")
            altered = result.copy()
            altered["state"] = "ALTERED"
            with self.assertRaises(pilot.Blocked):
                pilot.persist_receipt(db, altered, fp)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_no_implicit_api_optin(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / "synthetic.json"
            fixture.write_text(json.dumps(sample()), encoding="utf-8")
            safe_env = dict(os.environ)
            safe_env.pop("OPENAI_API_KEY", None)
            denied = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(fixture),
                 "--enable-billable-api"],
                env=safe_env, cwd=ROOT, text=True, capture_output=True
            )
            self.assertEqual(denied.returncode, 2)
            self.assertIn("API_KEY_MISSING_NO_CALL", denied.stdout)
            offline = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(fixture),
                 "--offline-test"],
                env=safe_env, cwd=ROOT, text=True, capture_output=True
            )
            self.assertEqual(offline.returncode, 0, offline.stderr)
            output = json.loads(offline.stdout)
            self.assertEqual(output["state"], "OFFLINE_SYNTHETIC_NO_API_CALL")
            self.assertIs(output["real_submit_allowed"], False)



class PaidAttemptGate(unittest.TestCase):
    def test_durable_paid_attempt_reservations_and_replay_block(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "attempts.sqlite"
            first = "budgeted_run_00001"
            pilot.reserve_billable_attempt(ledger, first, "fingerprint-a")
            with self.assertRaisesRegex(pilot.Blocked, "BILLABLE_REPLAY_BLOCKED"):
                pilot.reserve_billable_attempt(ledger, first, "fingerprint-a")
            for index in range(2, 9):
                pilot.reserve_billable_attempt(
                    ledger, f"budgeted_run_{index:05d}", f"fingerprint-{index}"
                )
            with self.assertRaisesRegex(pilot.Blocked, "LOCAL_BUDGET_RESERVATION_EXHAUSTED"):
                pilot.reserve_billable_attempt(ledger, "budgeted_run_00009", "fingerprint-9")
            with closing(sqlite3.connect(ledger)) as conn:
                self.assertEqual(
                    conn.execute("SELECT SUM(reserved_cents) FROM paid_attempts").fetchone()[0],
                    pilot.PAID_TOTAL_LEDGER_CENTS
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM paid_attempts").fetchone()[0], 8
                )

    def test_billable_without_ledger_fails_before_network(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / "synthetic.json"
            fixture.write_text(json.dumps(sample()), encoding="utf-8")
            safe_env = dict(os.environ)
            safe_env["OPENAI_API_KEY"] = "sk-fake-unit-test-not-real"
            denied = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(fixture),
                 "--enable-billable-api"], env=safe_env, cwd=ROOT,
                text=True, capture_output=True
            )
            self.assertEqual(denied.returncode, 2)
            self.assertIn("PAID_BUDGET_LEDGER_REQUIRED_NO_CALL", denied.stdout)

    def test_billable_unapproved_model_fails_before_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / "synthetic.json"
            fixture.write_text(json.dumps(sample()), encoding="utf-8")
            ledger = Path(td) / "attempts.sqlite"
            safe_env = dict(os.environ)
            safe_env["OPENAI_API_KEY"] = "sk-fake-unit-test-not-real"
            safe_env["OPENAI_AGENT_MODEL"] = "gpt-6-astra"
            denied = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(fixture),
                 "--enable-billable-api", "--paid-budget-db", str(ledger)],
                env=safe_env, cwd=ROOT, text=True, capture_output=True
            )
            self.assertEqual(denied.returncode, 2)
            self.assertIn("PAID_MODEL_OR_ENDPOINT_UNAPPROVED_NO_CALL", denied.stdout)
            self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
