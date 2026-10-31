"""Synthetic CI for the 100B Agents SDK coordination pilot.

No SDK, API key, external network, Excel, broker or scheduled Task is needed.
"""
import asyncio
from datetime import datetime, timedelta, timezone
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
            "fetched_at": "2026-10-19T15:00:00+09:00",
            "source_name": "Synthetic public source", "source_type": "SYNTHETIC_TEST", "data_status": "PUBLICATION_TIME_VERIFIED",
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
        assert len(reports) == len(pilot.ROLES)
        assert all(set(r) >= {"report_id", "conditions", "invalidation"} for r in reports)
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
        "conditions": "Holds only while the cited source stays current",
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
                "conditions": "unknown", "invalidation": "unknown",
            }, sample()["sources"][:1])

    def test_watch_requires_evidence(self):
        with self.assertRaises(pilot.Blocked):
            pilot.validate_specialist("pre_next", {
                "role": "pre_next", "status": "WATCH",
                "evidence_ids": [], "hypothesis": "guess", "conditions": "unknown",
                "invalidation": "unknown",
            }, sample()["sources"][:1])

    def test_conditions_are_required(self):
        with self.assertRaises(pilot.Blocked):
            pilot.validate_specialist("pre_next", {
                "role": "pre_next", "status": "NO_SIGNAL", "evidence_ids": [],
                "hypothesis": "nothing", "invalidation": "unknown",
            }, sample()["sources"][:1])

    def test_unsafe_coordinator_output_is_rejected(self):
        with self.assertRaises(pilot.Blocked):
            pilot.validate_coordinator({
                "summary": "x", "conflicts": [], "next_checks": [""] * 9
            })


class SourceTimeContract(unittest.TestCase):
    """T02/T03/T05: evidence v2 time fields and URL rules."""

    def test_fetched_before_available_is_rejected(self):
        d = sample()
        d["sources"][0]["fetched_at"] = "2026-10-19T14:00:00+09:00"
        with self.assertRaisesRegex(pilot.Blocked, "FUTURE_OR_LOOKAHEAD_EVIDENCE"):
            pilot.validate_snapshot(d, NOW)

    def test_fetch_in_the_future_is_rejected(self):
        d = sample()
        d["sources"][0]["fetched_at"] = "2026-10-21T00:00:00+09:00"
        with self.assertRaisesRegex(pilot.Blocked, "FUTURE_OR_LOOKAHEAD_EVIDENCE"):
            pilot.validate_snapshot(d, NOW)

    def test_date_only_source_cannot_claim_an_earlier_release(self):
        d = sample()
        d["sources"][0]["data_status"] = "DATE_ONLY_OBSERVED_AT_FETCH"
        d["sources"][0]["fetched_at"] = "2026-10-19T16:00:00+09:00"
        with self.assertRaisesRegex(pilot.Blocked, "DATE_ONLY_SOURCE_MUST_BE_AVAILABLE_AT_FETCH"):
            pilot.validate_snapshot(d, NOW)

    def test_unknown_status_or_type_is_rejected(self):
        for key, value in (("data_status", "GUESSED"), ("source_type", "BLOG")):
            d = sample()
            d["sources"][0][key] = value
            with self.subTest(key=key), self.assertRaises(pilot.Blocked):
                pilot.validate_snapshot(d, NOW)

    def test_v1_evidence_without_fetch_fields_is_rejected(self):
        d = sample()
        d["schema_version"] = "100b-public-agent-evidence-v1"
        with self.assertRaisesRegex(pilot.Blocked, "SCHEMA_UNSUPPORTED"):
            pilot.validate_snapshot(d, NOW)
        d = sample()
        del d["sources"][0]["fetched_at"]
        with self.assertRaisesRegex(pilot.Blocked, "SOURCE_FIELDS_INVALID"):
            pilot.validate_snapshot(d, NOW)

    def test_http_and_credentialed_urls_are_rejected(self):
        for url in ("http://www.jpx.co.jp/a", "https://u:p@www.jpx.co.jp/a", "javascript:alert(1)",
                    "https://www.jpx.co.jp/a?x=1"):
            d = sample()
            d["sources"][0]["source_url"] = url
            with self.subTest(url=url), self.assertRaises(pilot.Blocked):
                pilot.validate_snapshot(d, NOW)


class Orchestration(unittest.IsolatedAsyncioTestCase):
    async def test_source_published_after_target_is_not_given_to_the_role(self):
        seen = {}
        async def capture(role, prompt):
            if role != "progress_coordinator":
                seen[role] = [s["source_id"] for s in json.loads(prompt)["sources"]]
            return await fake_provider(role, prompt)
        # target before the 2026-10-19 15:00 JST publication: nothing is eligible.
        result = await pilot.coordinate(sample(), capture, now=NOW, target_at="2026-10-19T14:59:00+09:00")
        self.assertEqual(seen, {})
        by_role = {r["role"]: r for r in result["specialists"]}
        self.assertEqual(by_role["pre_next"]["status"], "NO_DATA")
        self.assertEqual(by_role["pre_next"]["unavailable_reason"], "NO_ELIGIBLE_SOURCE")
        self.assertEqual(by_role["pre_next"]["excluded_source_ids"], ["public_alpha"])

    async def test_premarket_uses_only_the_overnight_window(self):
        d = sample()
        d["sources"].append(dict(d["sources"][0], source_id="pre_old", role="premarket",
                                 as_of="2026-10-19T11:00:00+09:00", available_at="2026-10-19T12:00:00+09:00",
                                 fetched_at="2026-10-19T12:00:00+09:00"))
        d["sources"].append(dict(d["sources"][0], source_id="pre_new", role="premarket",
                                 as_of="2026-10-20T07:00:00+09:00", available_at="2026-10-20T07:30:00+09:00",
                                 fetched_at="2026-10-20T07:30:00+09:00"))
        seen = {}
        async def capture(role, prompt):
            if role == "premarket":
                seen[role] = [s["source_id"] for s in json.loads(prompt)["sources"]]
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(d, capture, now=NOW, target_at="2026-10-20T08:30:00+09:00")
        self.assertEqual(seen["premarket"], ["pre_new"])
        pre = [r for r in result["specialists"] if r["role"] == "premarket"][0]
        self.assertEqual(pre["excluded_source_ids"], ["pre_old"])
        self.assertEqual([e["source_id"] for e in pre["evidence"]], ["pre_new"])

    async def test_each_role_only_sees_its_own_sources(self):
        seen = {}
        async def capture(role, prompt):
            if role != "progress_coordinator":
                seen[role] = {s["role"] for s in json.loads(prompt)["sources"]}
            return await fake_provider(role, prompt)
        await pilot.coordinate(sample(), capture, now=NOW)
        for role, roles in seen.items():
            self.assertEqual(roles, {role})

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
                    ["NO_DATA", "WATCH", "NO_DATA", "NO_DATA"],
                )
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(d, track, now=NOW)
        self.assertEqual(called, ["pre_next", "progress_coordinator"])
        by_role = {r["role"]: r for r in result["specialists"]}
        self.assertEqual(by_role["supply_sq"]["status"], "NO_DATA")
        self.assertEqual(by_role["supply_sq"]["unavailable_reason"], "NO_SOURCE")
        self.assertEqual(by_role["premarket"]["status"], "NO_DATA")

    async def test_hallucinated_evidence_makes_each_role_unavailable_not_usable(self):
        called = []
        async def bad(role, prompt):
            called.append(role)
            return {
                "role": role, "status": "WATCH", "evidence_ids": ["not_in_payload"],
                "hypothesis": "bad", "conditions": "none", "invalidation": "none",
            }
        result = await pilot.coordinate(sample(), bad, now=NOW)
        self.assertEqual(called, ["pre_next", "supply_sq", "revenue_hunter"])
        for r in result["specialists"]:
            if r["role"] != "premarket":
                self.assertEqual((r["status"], r["unavailable_reason"]),
                                 ("UNAVAILABLE", "OUTPUT_VALIDATION_FAILED"))
                self.assertEqual(r["evidence_ids"], [])
        self.assertEqual(result["coordinator"]["status"], "UNAVAILABLE")

    async def test_one_role_api_failure_does_not_stop_the_others(self):
        async def flaky(role, prompt):
            if role == "supply_sq":
                raise TimeoutError("synthetic provider timeout")
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(sample(), flaky, now=NOW)
        by_role = {r["role"]: r for r in result["specialists"]}
        self.assertEqual(by_role["supply_sq"]["status"], "UNAVAILABLE")
        self.assertEqual(by_role["supply_sq"]["unavailable_reason"], "API_OR_RUNTIME_FAILED")
        self.assertEqual(by_role["pre_next"]["status"], "WATCH")
        self.assertEqual(result["coordinator"]["status"], "OK")
        self.assertIn("supply_sq:UNAVAILABLE:API_OR_RUNTIME_FAILED", result["verification"])

    async def test_coordinator_failure_keeps_specialist_reports(self):
        async def no_coord(role, prompt):
            if role == "progress_coordinator":
                raise ConnectionError("synthetic")
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(sample(), no_coord, now=NOW)
        self.assertEqual(result["coordinator"]["status"], "UNAVAILABLE")
        self.assertEqual({r["status"] for r in result["specialists"] if r["role"] != "premarket"}, {"WATCH"})
        # only the failure category is kept, never the exception text
        self.assertEqual(result["coordinator"]["summary"], "Coordinator call or output failed (ConnectionError)")

    async def test_coordinator_invalid_output_is_named(self):
        async def long_coord(role, prompt):
            if role == "progress_coordinator":
                return {"summary": "x" * 601, "conflicts": [], "next_checks": []}
            return await fake_provider(role, prompt)
        result = await pilot.coordinate(sample(), long_coord, now=NOW)
        self.assertEqual(result["coordinator"]["summary"], "Coordinator call or output failed (COORDINATOR_OUTPUT_INVALID)")
        self.assertEqual(pilot.SETTINGS["max_output_tokens_coordinator"][0], 1500)
        self.assertEqual(pilot.SETTINGS["max_output_tokens_per_call"][0], 600)
        self.assertEqual(pilot.SETTINGS["paid_input_limit_bytes"][0], 24000)

    async def test_every_report_is_traceable_and_expires(self):
        result = await pilot.coordinate(sample(), fake_provider, now=NOW,
                                        target_at="2026-10-20T08:30:00+09:00", slot="premarket_0830")
        self.assertEqual(result["schema_version"], pilot.RESULT_SCHEMA)
        self.assertEqual(result["slot"], "premarket_0830")
        for r in result["specialists"]:
            self.assertEqual(r["report_id"], "synthetic_20261020_01." + r["role"])
            self.assertEqual(r["target_at"], "2026-10-20T08:30:00+09:00")
            self.assertEqual(datetime.fromisoformat(r["expires_at"]) - datetime.fromisoformat(r["generated_at"]),
                             pilot.ROLE_VALIDITY[r["role"]])
            self.assertIs(r["real_submit_allowed"], False)
            for e in r["evidence"]:
                self.assertTrue(e["source_url"].startswith("https://"))
        lanes = {r["role"]: r["lane"] for r in result["specialists"]}
        self.assertEqual(lanes["revenue_hunter"], "PROJECT_PROGRESS_NOT_TRADING")
        self.assertEqual({lanes[k] for k in ("premarket", "pre_next", "supply_sq")},
                         {"MARKET_RESEARCH_NOT_EXECUTION"})

    async def test_revenue_hunter_never_counts_as_market_disagreement(self):
        async def mixed(role, prompt):
            out = await fake_provider(role, prompt)
            if role == "revenue_hunter":
                out["status"] = "NO_SIGNAL"
            return out
        result = await pilot.coordinate(sample(), mixed, now=NOW)
        self.assertNotIn("MARKET_ROLES_DISAGREE", result["verification"])


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
            pilot.reserve_billable_attempt(ledger, first, "fingerprint-a", now=NOW)
            with self.assertRaisesRegex(pilot.Blocked, "BILLABLE_REPLAY_BLOCKED"):
                pilot.reserve_billable_attempt(ledger, first, "fingerprint-a", now=NOW)
            for index in range(2, 9):
                pilot.reserve_billable_attempt(
                    ledger, f"budgeted_run_{index:05d}", f"fingerprint-{index}",
                    now=NOW + timedelta(days=index)
                )
            with self.assertRaisesRegex(pilot.Blocked, "LOCAL_BUDGET_RESERVATION_EXHAUSTED"):
                pilot.reserve_billable_attempt(ledger, "budgeted_run_00009", "fingerprint-9",
                                               now=NOW + timedelta(days=30))
            with closing(sqlite3.connect(ledger)) as conn:
                self.assertEqual(
                    conn.execute("SELECT SUM(reserved_cents) FROM paid_attempts").fetchone()[0],
                    pilot.PAID_TOTAL_LEDGER_CENTS
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM paid_attempts").fetchone()[0], 8
                )

    def test_daily_cap_and_same_slot_block_double_charging(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "attempts.sqlite"
            pilot.reserve_billable_attempt(ledger, "slot_run_00001", "fp1",
                                           slot_key="2026-10-20:premarket_0830", now=NOW)
            with self.assertRaisesRegex(pilot.Blocked, "BILLABLE_SLOT_ALREADY_RUN"):
                pilot.reserve_billable_attempt(ledger, "slot_run_00002", "fp2",
                                               slot_key="2026-10-20:premarket_0830", now=NOW)
            pilot.reserve_billable_attempt(ledger, "slot_run_00003", "fp3",
                                           slot_key="2026-10-20:supply_1730", now=NOW)
            with self.assertRaisesRegex(pilot.Blocked, "DAILY_PAID_RUN_CAP_REACHED"):
                pilot.reserve_billable_attempt(ledger, "slot_run_00004", "fp4",
                                               slot_key="2026-10-20:pre_next_2000", now=NOW)
            pilot.reserve_billable_attempt(ledger, "slot_run_00005", "fp5",
                                           slot_key="2026-10-21:premarket_0830", now=NOW + timedelta(days=1))
            with closing(sqlite3.connect(ledger)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM paid_attempts").fetchone()[0], 3)

    def test_legacy_ledger_without_slot_columns_is_upgraded_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "attempts.sqlite"
            with closing(sqlite3.connect(ledger)) as conn, conn:
                conn.execute("""CREATE TABLE paid_attempts (run_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL, reserved_cents INTEGER NOT NULL,
                    state TEXT NOT NULL, reserved_at TEXT NOT NULL)""")
                conn.execute("INSERT INTO paid_attempts VALUES ('old_run_0001','fp',100,'ATTEMPT_RESERVED','x')")
            pilot.reserve_billable_attempt(ledger, "new_run_00001", "fp", slot_key="k", now=NOW)
            with closing(sqlite3.connect(ledger)) as conn:
                self.assertEqual(conn.execute("SELECT SUM(reserved_cents) FROM paid_attempts").fetchone()[0], 200)

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
