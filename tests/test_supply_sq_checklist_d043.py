"""D-043 exact-file and per-run coverage regression (offline, no API/network)."""
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts"


def imported(name):
    spec = importlib.util.spec_from_file_location(name, SRC / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


checks = imported("supply_sq_checklist_d043")
pilot = imported("agent_sdk_coordination_pilot")
adapter = imported("agent_sdk_d043_adapter")
NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)


def source():
    return {
        "schema_version": pilot.SCHEMA,
        "run_id": "synthetic_d043_test_001",
        "sources": [{
            "source_id": "synthetic_supply_1", "role": "supply_sq",
            "source_url": "https://www.jpx.co.jp/markets/",
            "source_name": "Synthetic research only", "source_type": "SYNTHETIC_TEST",
            "data_status": "PUBLICATION_TIME_VERIFIED",
            "summary": "Synthetic fixture; no market figures",
            "as_of": "2026-10-19T09:00:00+09:00",
            "available_at": "2026-10-19T15:00:00+09:00",
            "fetched_at": "2026-10-19T15:00:00+09:00",
        }]
    }


def audited_result(role, request, *, drop_id=None):
    data = json.loads(request)
    if role == "progress_coordinator":
        return {"summary": "No verified forecast", "conflicts": [], "next_checks": []}
    out = {"role": role, "status": "WATCH",
           "evidence_ids": [x["source_id"] for x in data["sources"]],
           "hypothesis": "Synthetic hypothesis only",
           "conditions": "Test input, not a trade",
           "invalidation": "Unknown market evidence"}
    if role == "supply_sq":
        assert data["mandatory_checklist"]["full_text"]
        assert data["mandatory_checklist"]["checklist_sha256"]
        out["checklist_statuses"] = {i: "UNVERIFIED" for i in checks.IDS if i != drop_id}
        out["checklist_reasons"] = {i: "Synthetic source cannot verify this metric"
                                     for i in checks.IDS if i != drop_id}
    return out


class Integrity(unittest.TestCase):
    def test_exact_sha_and_all_ten_sections_are_required(self):
        body = "# Synthetic checklist\n" + "".join(
            "- **%s｜Synthetic**: No figures.\n" % i for i in checks.IDS)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "checklist.md"
            p.write_text(body, encoding="utf-8")
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(checks.load(p, expected_sha=digest)["checklist_sha256"], digest)
            with self.assertRaisesRegex(checks.ChecklistBlocked, "HASH_MISMATCH"):
                checks.load(p)
            p.write_text(body.replace("C05", "C11"), encoding="utf-8")
            with self.assertRaisesRegex(checks.ChecklistBlocked, "IDS_MISSING"):
                checks.load(p, expected_sha=hashlib.sha256(p.read_bytes()).hexdigest())

    def test_missing_or_modified_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(checks.ChecklistBlocked, "MISSING_OR_LINK"):
                checks.load(Path(td) / "missing.md")
            p = Path(td) / "garbage.md"
            p.write_text("not the checklist")
            with self.assertRaisesRegex(checks.ChecklistBlocked, "HASH_MISMATCH"):
                checks.load(p)

    def test_complete_statuses_even_when_missing_data(self):
        statuses = {i: "UNVERIFIED" for i in checks.IDS}
        reasons = {i: "No appropriate dated source" for i in checks.IDS}
        out = checks.audit(statuses, reasons, evidence_ids=[])
        self.assertEqual((out["answered"], out["verified"]), (10, 0))
        self.assertEqual(out["quality"], "QUALITY_INCOMPLETE")
        self.assertEqual(out["missing_ids"], list(checks.IDS))

    def test_cannot_mark_unverified_claims_as_verified(self):
        statuses = {i: "VERIFIED" for i in checks.IDS}
        reasons = {i: "Supposedly verified" for i in checks.IDS}
        with self.assertRaisesRegex(checks.ChecklistBlocked, "WITHOUT_EVIDENCE"):
            checks.audit(statuses, reasons, evidence_ids=[])
        del reasons["C10"]
        with self.assertRaisesRegex(checks.ChecklistBlocked, "COVERAGE_INCOMPLETE"):
            checks.audit(statuses, reasons, evidence_ids=["synthetic_supply_1"])


class Integration(unittest.IsolatedAsyncioTestCase):
    async def test_supply_prompt_carries_complete_checklist_and_audit(self):
        audit = []
        sample = {"checklist_version": checks.VERSION, "checklist_sha256": checks.APPROVED_SHA256,
                  "full_text": "Synthetic fixture " + " ".join(checks.IDS)}
        async def provider(role, prompt):
            return audited_result(role, prompt)
        result, attestation = await adapter.coordinate_with_checklist(
            source(), provider, now=NOW, checklist=sample)
        audit = [attestation["audit"]]
        self.assertEqual(next(x for x in result["specialists"]
                              if x["role"] == "supply_sq")["status"], "WATCH")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["answered"], 10)
        self.assertEqual(audit[0]["quality"], "QUALITY_INCOMPLETE")
        self.assertFalse(result["real_submit_allowed"])

    async def test_missing_tenth_entry_is_fail_closed(self):
        sample = {"checklist_version": checks.VERSION, "checklist_sha256": checks.APPROVED_SHA256,
                  "full_text": "Synthetic fixture"}
        async def provider(role, prompt):
            return audited_result(role, prompt, drop_id="C10")
        with self.assertRaisesRegex(adapter.AdapterBlocked, "AUDIT_NOT_COMPLETED"):
            await adapter.coordinate_with_checklist(source(), provider, now=NOW, checklist=sample)

    async def test_no_eligible_source_still_reports_ten_unknowns(self):
        sample = {"checklist_version": checks.VERSION, "checklist_sha256": checks.APPROVED_SHA256,
                  "full_text": "Synthetic fixture"}
        d = source()
        d["sources"] = []
        audit = []
        async def forbidden(role, prompt):
            raise AssertionError("No providers must be invoked without sources")
        out, attestation = await adapter.coordinate_with_checklist(
            d, forbidden, now=NOW, checklist=sample)
        audit = [attestation["audit"]]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["missing_ids"], list(checks.IDS))
        self.assertEqual(out["specialists"][2]["status"], "NO_DATA")

    async def test_paid_attempt_stopped_before_provider_or_ledger(self):
        async def forbidden(role, prompt):
            raise AssertionError("Paid provider must not run")
        with self.assertRaisesRegex(adapter.AdapterBlocked, "D041_PAID_API_FROZEN_NO_CALL"):
            await adapter.coordinate_with_checklist(source(), forbidden, now=NOW,
                checklist={"checklist_version": checks.VERSION, "checklist_sha256": checks.APPROVED_SHA256,
                           "full_text": "Synthetic only"}, billable=True)


if __name__ == "__main__":
    unittest.main()
