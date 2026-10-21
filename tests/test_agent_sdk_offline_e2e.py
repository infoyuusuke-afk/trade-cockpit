"""100B offline cross-component acceptance: Agents SDK contract -> signed Brain ACK.

Runs against synthetic public-shaped fixtures, with no SDK/API/network,
no owner secrets, no V10 process, no broker, and no trading permissions.
This is NOT proof of live API connectivity or market performance.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import agent_sdk_coordination_pilot as pilot
from scripts import agent_sdk_brain_handoff as bridge
from scripts import v10_brain_agent_research_receiver as receiver


NOW = datetime(2026, 10, 21, 6, 0, 0, tzinfo=timezone.utc)
SIDECAR_TEST_KEY = "31" * 32
BRAIN_TEST_KEY = "c4" * 32


def synthetic_sources(run_id):
    rows = []
    for index, role in enumerate(pilot.ROLES):
        rows.append({
            "source_id": "offline_fixture_%d" % index,
            "role": role,
            "source_url": "https://www.boj.or.jp/rss/whatsnew.xml",
            "as_of": (NOW - timedelta(hours=4)).isoformat(),
            "available_at": (NOW - timedelta(hours=3)).isoformat(),
            "summary": "FICTIONAL TEST INPUT, not observed financial information",
        })
    return {"schema_version": pilot.SCHEMA, "run_id": run_id, "sources": rows}


async def fake_four_role_provider(role, prompt):
    if role == "progress_coordinator":
        data = json.loads(prompt)
        assert len(data["reports"]) == 3
        return {
            "summary": "OFFLINE SYNTHETIC ONLY; no GPT API invocation",
            "conflicts": [],
            "next_checks": ["Real API and Windows live acceptance remain pending"],
        }
    data = json.loads(prompt)
    assert data["research_only"] is True
    return {
        "role": role,
        "status": "NO_SIGNAL",
        "evidence_ids": [],
        "hypothesis": "Synthetic stub; no investment prediction",
        "invalidation": "No verified source contents or live quotes",
    }


class FourRoleToBrainOfflineAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="100b-offline-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "100億PROJECT" / "非公開研究"
        self.root.mkdir(parents=True)
        env = patch.dict(os.environ, {
            bridge.KEY_ENV: SIDECAR_TEST_KEY,
            receiver.RECEIVER_KEY_ENV: BRAIN_TEST_KEY,
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def _produce(self, run_id):
        source = synthetic_sources(run_id)
        result = asyncio.run(pilot.coordinate(source, fake_four_role_provider, now=NOW))
        self.assertFalse(result["real_submit_allowed"])
        self.assertIsNone(result["actual_profit_yen"])
        # The fake runner must never be represented as paid GPT inference.
        result["state"] = "OFFLINE_SYNTHETIC_NO_API_CALL"
        fingerprint = pilot.fingerprint(source)
        receipt_db = self.root / "research_receipts.sqlite"
        self.assertEqual(pilot.persist_receipt(receipt_db, result, fingerprint), "RECORDED")
        envelope = bridge.produce(source, result, private_dir=self.root,
                                  now=NOW + timedelta(minutes=1))
        self.assertTrue(envelope.is_file())
        return envelope

    def test_full_synthetic_chain_receiver_ack_and_restart_idempotency(self):
        run_id = "offline_e2e_20261021_0001"
        self._produce(run_id)
        first = receiver.receive_inbox(
            self.root, now=NOW + timedelta(minutes=2),
            host_component="v10-ai-brain-observer")
        self.assertEqual(first["state"], "PASS_COMPLETED")
        self.assertEqual(len(first["results"]), 1)
        self.assertEqual(first["results"][0]["state"], "RECEIVED")
        self.assertFalse(first["real_submit_allowed"])
        ack_file = self.root / ("agent_research_" + run_id + ".brain_ack.json")
        self.assertTrue(ack_file.is_file())
        ack = json.loads(ack_file.read_text(encoding="utf-8"))
        self.assertEqual(ack["ack_kind"], "BRAIN_RECEIVER_ACK")
        self.assertEqual(ack["receiver"]["host_component"], "v10-ai-brain-observer")
        self.assertFalse(ack["live_market_data"])
        self.assertFalse(ack["brain_trade_decision_eligible"])
        self.assertFalse(ack["real_submit_allowed"])
        self.assertEqual({row["role"] for row in ack["roles"]}, set(pilot.ROLES))
        self.assertEqual({row["status"] for row in ack["roles"]}, {"NO_SIGNAL"})
        signed_body = {k: v for k, v in ack.items() if k != "hmac_sha256"}
        expected = hmac.new(bytes.fromhex(BRAIN_TEST_KEY), bridge._canon(signed_body),
                            hashlib.sha256).hexdigest()
        self.assertTrue(hmac.compare_digest(ack["hmac_sha256"], expected))
        status = receiver.status(self.root)
        self.assertEqual(status["received_run_ids"], [run_id])
        self.assertEqual(status["pending"], [])
        # The durable database survives independent receive passes; no repeat ACK.
        second = receiver.receive_inbox(
            self.root, now=NOW + timedelta(minutes=3),
            host_component="v10-ai-brain-observer")
        self.assertEqual(second["results"], [])
        self.assertEqual(second["restored_acks"], [])

    def test_missing_brain_ack_recovered_from_durable_receipt(self):
        run_id = "offline_e2e_20261021_0002"
        self._produce(run_id)
        first = receiver.receive_inbox(self.root, now=NOW + timedelta(minutes=2))
        self.assertEqual(first["results"][0]["state"], "RECEIVED")
        ack_file = self.root / ("agent_research_" + run_id + ".brain_ack.json")
        original = ack_file.read_bytes()
        ack_file.unlink()
        status = receiver.status(self.root)
        self.assertEqual(status["ack_missing_run_ids"], [run_id])
        restored = receiver.receive_inbox(self.root, now=NOW + timedelta(minutes=3))
        self.assertEqual(restored["results"], [])
        self.assertEqual(len(restored["restored_acks"]), 1)
        self.assertEqual(restored["restored_acks"][0]["ack"], "ACK_WRITTEN")
        self.assertEqual(ack_file.read_bytes(), original)

    def test_modified_research_blocked_without_brain_ack(self):
        run_id = "offline_e2e_20261021_0003"
        envelope = self._produce(run_id)
        wrapper = json.loads(envelope.read_text(encoding="utf-8"))
        wrapper["payload"]["research"]["coordinator"]["summary"] = "tampered"
        envelope.write_bytes(bridge._canon(wrapper) + b"\n")
        out = receiver.receive_inbox(self.root, now=NOW + timedelta(minutes=2))
        self.assertEqual(out["results"][0]["state"], "BLOCKED")
        self.assertEqual(out["results"][0]["reason"], "HANDOFF_AUTHENTICATION_FAILED")
        self.assertEqual(receiver.status(self.root)["received_run_ids"], [])
        self.assertFalse(list(self.root.glob("*.brain_ack.json")))


if __name__ == "__main__":
    unittest.main()
