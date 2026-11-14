"""Offline, no-network Brain research-only signed-envelope negative tests."""
import asyncio
from datetime import datetime, timezone, timedelta
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import agent_sdk_coordination_pilot as pilot
from scripts import agent_sdk_brain_handoff as bridge

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_sdk_coordination_pilot.py"
CONSUMER = ROOT / "scripts" / "agent_sdk_brain_handoff.py"
NOW = datetime(2026, 10, 21, 1, 40, 0, tzinfo=timezone.utc)
KEY = "c4" * 32


def doc():
    def row(role, ix):
        return {
            "source_id": "synthetic_" + ix,
            "role": role, "source_url": "https://www.boj.or.jp/rss/whatsnew.xml",
            "as_of": "2026-10-20T12:00:00+09:00",
            "available_at": "2026-10-20T16:35:00+00:00",
            "fetched_at": "2026-10-20T16:35:00+00:00",
            "source_name": "Synthetic public source", "source_type": "SYNTHETIC_TEST", "data_status": "PUBLICATION_TIME_VERIFIED",
            "summary": "Synthetic offline headline; no trading information",
        }
    return {
        "schema_version": pilot.SCHEMA,
        "run_id": "test_bridge_20261021_01",
        "sources": [row("pre_next", "a"), row("supply_sq", "b")],
    }


def result():
    value = asyncio.run(pilot.coordinate(doc(), pilot.offline_runner, now=NOW))
    value["state"] = "OFFLINE_SYNTHETIC_NO_API_CALL"
    return value


def resign(blob):
    blob["hmac_sha256"] = hmac.new(bytes.fromhex(KEY), bridge._canon(blob["payload"]),
                                   hashlib.sha256).hexdigest()


class SignedHandoff(unittest.TestCase):
    def setUp(self):
        self.key = patch.dict(os.environ, {bridge.KEY_ENV: KEY})
        self.key.start()
        self.addCleanup(self.key.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def valid(self):
        f = bridge.produce(doc(), result(), private_dir=self.root, now=NOW)
        self.assertTrue(f.is_file())
        return f

    def test_signed_handoff_and_independent_ack_are_research_only(self):
        f = self.valid()
        ack = bridge.consume(input_path=f, private_dir=self.root, now=NOW,
                             write_ack=True)
        self.assertEqual(ack["state"], "RESEARCH_ONLY_ACK_RECEIVED_NOT_BRAIN_LIVE")
        self.assertIs(ack["real_submit_allowed"], False)
        self.assertIs(ack["brain_trade_decision_eligible"], False)
        self.assertEqual(ack["run_id"], doc()["run_id"])
        a = self.root / ("agent_research_" + doc()["run_id"] + ".ack.json")
        self.assertTrue(a.is_file())
        self.assertEqual(json.loads(a.read_text(encoding="utf-8")), ack)
        with self.assertRaisesRegex(bridge.BridgeBlocked, "DUPLICATE_HANDOFF_OR_ACK"):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW, write_ack=True)

    def test_one_shot_export_never_overwrites(self):
        self.valid()
        with self.assertRaisesRegex(bridge.BridgeBlocked, "DUPLICATE_HANDOFF_OR_ACK"):
            bridge.produce(doc(), result(), private_dir=self.root, now=NOW)

    def test_tampered_payload_denied_before_ack(self):
        f = self.valid()
        data = json.loads(f.read_text("utf-8"))
        data["payload"]["research"]["coordinator"]["summary"] = "BUY"
        f.write_bytes(bridge._canon(data))
        with self.assertRaisesRegex(bridge.BridgeBlocked, "AUTHENTICATION_FAILED"):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW,
                           write_ack=True)
        self.assertFalse(f.with_name(f.stem + ".ack.json").exists())

    def test_wrong_key_denied(self):
        f = self.valid()
        with patch.dict(os.environ, {bridge.KEY_ENV: "d5"*32}):
            with self.assertRaisesRegex(bridge.BridgeBlocked, "AUTHENTICATION_FAILED"):
                bridge.consume(input_path=f, private_dir=self.root, now=NOW)

    def test_stale_handoff_denied_even_if_file_timestamp_recent(self):
        f = self.valid()
        with self.assertRaisesRegex(bridge.BridgeBlocked, "HANDOFF_STALE"):
            bridge.consume(input_path=f, private_dir=self.root,
                           now=NOW+timedelta(minutes=16))
        self.assertFalse((self.root / ("agent_research_" +
                         doc()["run_id"] + ".ack.json")).exists())

    def test_signed_but_unsafe_result_denied(self):
        f = self.valid()
        data = json.loads(f.read_text(encoding="utf-8"))
        data["payload"]["research"]["real_submit_allowed"] = True
        resign(data)
        f.write_bytes(bridge._canon(data))
        with self.assertRaisesRegex(bridge.BridgeBlocked, "SAFETY_GATE"):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW)

    def test_signed_but_false_source_evidence_reference_denied(self):
        f = self.valid()
        data = json.loads(f.read_text(encoding="utf-8"))
        pre = [x for x in data["payload"]["research"]["specialists"] if x["role"] == "pre_next"][0]
        pre["status"] = "WATCH"
        pre["evidence_ids"] = ["fake"]
        resign(data)
        f.write_bytes(bridge._canon(data))
        with self.assertRaises((pilot.Blocked, bridge.BridgeBlocked)):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW)

    def test_signed_report_with_extended_expiry_is_denied(self):
        f = self.valid()
        data = json.loads(f.read_text(encoding="utf-8"))
        pre = [x for x in data["payload"]["research"]["specialists"] if x["role"] == "pre_next"][0]
        pre["expires_at"] = "2027-01-01T00:00:00+00:00"
        resign(data)
        f.write_bytes(bridge._canon(data))
        with self.assertRaisesRegex(bridge.BridgeBlocked, "REPORT_VALIDITY_WINDOW_INVALID"):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW)

    def test_signed_revenue_hunter_moved_to_market_lane_is_denied(self):
        f = self.valid()
        data = json.loads(f.read_text(encoding="utf-8"))
        rev = [x for x in data["payload"]["research"]["specialists"] if x["role"] == "revenue_hunter"][0]
        rev["lane"] = "MARKET_RESEARCH_NOT_EXECUTION"
        resign(data)
        f.write_bytes(bridge._canon(data))
        with self.assertRaisesRegex(bridge.BridgeBlocked, "REPORT_IDENTITY_OR_LANE_INVALID"):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW)

    def test_signed_status_rewrite_to_unavailable_is_denied(self):
        f = self.valid()
        data = json.loads(f.read_text(encoding="utf-8"))
        pre = [x for x in data["payload"]["research"]["specialists"] if x["role"] == "pre_next"][0]
        pre["status"] = "UNAVAILABLE"
        pre["unavailable_reason"] = "API_OR_RUNTIME_FAILED"
        resign(data)
        f.write_bytes(bridge._canon(data))
        with self.assertRaises(bridge.BridgeBlocked):
            bridge.consume(input_path=f, private_dir=self.root, now=NOW)

    def test_source_available_after_analysis_denied(self):
        bad = doc()
        bad["sources"][0]["available_at"] = "2026-10-21T01:41:00+00:00"
        with self.assertRaises(pilot.Blocked):
            bridge.produce(bad, result(), private_dir=self.root, now=NOW)

    def test_symlink_private_root_rejected(self):
        alias = self.root / "alias"
        target = self.root / "real"
        target.mkdir()
        try:
            alias.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks require extra permission on this Windows host")
        with self.assertRaisesRegex(bridge.BridgeBlocked, "LINK_UNTRUSTED"):
            bridge.produce(doc(), result(), private_dir=alias, now=NOW)

    def test_key_missing_does_not_write(self):
        with patch.dict(os.environ, {bridge.KEY_ENV: ""}):
            with self.assertRaisesRegex(bridge.BridgeBlocked, "HMAC_KEY_MISSING"):
                bridge.produce(doc(), result(), private_dir=self.root, now=NOW)
        self.assertEqual(list(self.root.glob("agent_research_*.json")), [])

    def test_handshake_input_filename_mismatch_fails(self):
        f = self.valid()
        other = self.root / "agent_research_wrong_20261021.json"
        other.write_bytes(f.read_bytes())
        with self.assertRaisesRegex(bridge.BridgeBlocked, "FILENAME_MISMATCH"):
            bridge.consume(input_path=other, private_dir=self.root, now=NOW)

    def test_paid_preflight_missing_hmac_key_blocks_before_api(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "budget.sqlite"
            fixture = Path(td) / "snapshot.json"
            fixture.write_text(json.dumps(doc()), encoding="utf-8")
            safe_env = dict(os.environ)
            safe_env.pop(bridge.KEY_ENV, None)
            safe_env["OPENAI_API_KEY"] = "sk-fake-not-real"
            cmd = [sys.executable, str(SCRIPT), "--input", str(fixture),
                   "--enable-billable-api", "--paid-budget-db", str(db),
                   "--receipt-db", str(Path(td)/"receipt.sqlite"),
                   "--handoff-dir", td]
            proc = subprocess.run(cmd, env=safe_env, cwd=ROOT,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("PRIVATE_HMAC_KEY_MISSING_OR_INVALID", proc.stdout)
            self.assertFalse(db.exists())

    def test_offline_cli_complete_handoff_and_ack(self):
        # Timestamps are generated fresh at runtime, no stale sample on CI.
        with tempfile.TemporaryDirectory() as td:
            now = datetime.now(timezone.utc)
            d = doc()
            for row in d["sources"]:
                row["as_of"] = (now-timedelta(minutes=5)).isoformat()
                row["available_at"] = (now-timedelta(minutes=1)).isoformat()
                row["fetched_at"] = row["available_at"]
            source = Path(td) / "sample.json"
            source.write_text(json.dumps(d), encoding="utf-8")
            env = dict(os.environ)
            env[bridge.KEY_ENV] = KEY
            env.pop("OPENAI_API_KEY", None)
            out = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(source),
                 "--offline-test", "--receipt-db", str(Path(td)/"receipt.sqlite"),
                 "--handoff-dir", td], capture_output=True, text=True,
                env=env, cwd=ROOT)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertEqual(json.loads(out.stdout)["handoff"],
                             "SIGNED_PRIVATE_RESEARCH_ONLY_PENDING_RECEIVER_ACK")
            packet = Path(td) / ("agent_research_" + d["run_id"] + ".json")
            recv = subprocess.run(
                [sys.executable, str(CONSUMER), "--consume", str(packet),
                 "--private-dir", td, "--write-ack"], env=env, cwd=ROOT,
                capture_output=True, text=True)
            self.assertEqual(recv.returncode, 0, recv.stdout + recv.stderr)
            self.assertEqual(json.loads(recv.stdout)["state"],
                             "RESEARCH_ONLY_ACK_RECEIVED_NOT_BRAIN_LIVE")
            replay = subprocess.run(
                [sys.executable, str(CONSUMER), "--consume", str(packet),
                 "--private-dir", td, "--write-ack"], env=env, cwd=ROOT,
                capture_output=True, text=True)
            self.assertEqual(replay.returncode, 2)
            self.assertIn("DUPLICATE_HANDOFF_OR_ACK_BLOCKED", replay.stdout)


if __name__ == "__main__":
    unittest.main()
