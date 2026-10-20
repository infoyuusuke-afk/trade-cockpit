"""P0-AGENTS-SDK-V10-BRAIN-INTEGRATION-20261021: Brain-side receiver, synthetic only.

No network, no API key from the OWNER, no paid call, no V10 runtime file. The
inbox lives in a temporary directory whose path contains Japanese characters
(the OWNER's D:\\100億PROJECT layout).
"""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import agent_sdk_brain_handoff as bridge
from scripts import agent_sdk_coordination_pilot as pilot
from scripts import v10_brain_agent_research_receiver as receiver

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 21, 1, 40, 0, tzinfo=timezone.utc)
KEY = "5e" * 32


def source_doc(run_id="brain_rx_20261021_01", roles=("pre_next", "supply_sq")):
    rows = []
    for ix, role in enumerate(roles):
        rows.append({
            "source_id": "syn_%s_%d" % (role, ix), "role": role,
            "source_url": "https://www.boj.or.jp/rss/whatsnew.xml",
            "as_of": "2026-10-20T12:00:00+09:00", "available_at": "2026-10-20T16:35:00+00:00",
            "summary": "Synthetic offline headline; no trading information",
        })
    return {"schema_version": pilot.SCHEMA, "run_id": run_id, "sources": rows}


def research(doc, now=NOW, runner=pilot.offline_runner):
    value = asyncio.run(pilot.coordinate(doc, runner, now=now))
    value["state"] = "OFFLINE_SYNTHETIC_NO_API_CALL"
    return value


async def divergent_runner(role, prompt):
    if role == "progress_coordinator":
        return {"summary": "Synthetic review", "conflicts": ["pre_next WATCH vs supply_sq NO_SIGNAL"],
                "next_checks": ["Verify the dated source"]}
    data = json.loads(prompt)
    ids = [s["source_id"] for s in data["sources"]]
    if role == "pre_next":
        return {"role": role, "status": "WATCH", "evidence_ids": ids[:1],
                "hypothesis": "Synthetic watch hypothesis", "invalidation": "Synthetic invalidation"}
    return {"role": role, "status": "NO_SIGNAL", "evidence_ids": [],
            "hypothesis": "Synthetic no signal", "invalidation": "Synthetic invalidation"}


def resign(path):
    blob = json.loads(path.read_bytes().decode("utf-8"))
    blob["hmac_sha256"] = hmac.new(bytes.fromhex(KEY), bridge._canon(blob["payload"]), hashlib.sha256).hexdigest()
    path.write_bytes(bridge._canon(blob) + b"\n")


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {bridge.KEY_ENV: KEY})
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.mkdtemp(prefix="v10-brain-rx-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = Path(tmp) / "100億PROJECT" / "研究受け箱"
        self.root.mkdir(parents=True)

    def emit(self, doc=None, result=None, now=NOW):
        doc = doc or source_doc()
        return bridge.produce(doc, result or research(doc, now=now), private_dir=self.root, now=now)

    def receive(self, now=NOW + timedelta(minutes=1)):
        return receiver.receive_inbox(self.root, now=now)

    def only(self, out):
        self.assertEqual(len(out["results"]), 1, out)
        return out["results"][0]

    # -- positive ---------------------------------------------------------
    def test_valid_signed_research_is_received_with_brain_ack(self):
        self.emit()
        got = self.only(self.receive())
        self.assertEqual(got["state"], "RECEIVED")
        ack = json.loads((self.root / "agent_research_brain_rx_20261021_01.brain_ack.json").read_text("utf-8"))
        self.assertEqual(ack["ack_kind"], "BRAIN_RECEIVER_ACK")
        self.assertEqual(ack["receiver"]["component"], "v10-brain-agent-research-receiver")
        self.assertEqual(ack["receiver"]["process_id"], os.getpid())
        self.assertRegex(ack["receiver"]["receiver_code_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(ack["verification"], "PASS")
        self.assertIs(ack["real_submit_allowed"], False)
        self.assertIs(ack["live_market_data"], False)
        self.assertIs(ack["brain_trade_decision_eligible"], False)
        roles = {r["role"]: r["status"] for r in ack["roles"]}
        self.assertEqual(roles, {"pre_next": "NO_SIGNAL", "revenue_hunter": "NO_DATA", "supply_sq": "NO_SIGNAL"})
        body = {k: v for k, v in ack.items() if k != "hmac_sha256"}
        self.assertTrue(hmac.compare_digest(
            hmac.new(bytes.fromhex(KEY), bridge._canon(body), hashlib.sha256).hexdigest(), ack["hmac_sha256"]))

    def test_revenue_hunter_without_data_is_no_data(self):
        self.emit()
        self.receive()
        st = receiver.status(self.root)
        self.assertEqual(st["received_run_ids"], ["brain_rx_20261021_01"])
        with sqlite3.connect(str(self.root / receiver.DB_NAME)) as conn:
            roles = json.loads(conn.execute("SELECT roles_json FROM receipts").fetchone()[0])
        self.assertEqual([r for r in roles if r["role"] == "revenue_hunter"],
                         [{"role": "revenue_hunter", "status": "NO_DATA", "evidence_ids": []}])

    def test_divergent_specialists_are_recorded_as_conflicts(self):
        doc = source_doc()
        self.emit(doc, research(doc, runner=divergent_runner))
        self.only(self.receive())
        ack = json.loads((self.root / "agent_research_brain_rx_20261021_01.brain_ack.json").read_text("utf-8"))
        kinds = sorted(c["kind"] for c in ack["conflicts"])
        self.assertEqual(kinds, ["COORDINATOR_REPORTED", "ROLE_STATUS_DIVERGENCE"])
        self.assertIn("pre_next=WATCH", [c for c in ack["conflicts"] if c["kind"] == "ROLE_STATUS_DIVERGENCE"][0]["text"])

    # -- negative ---------------------------------------------------------
    def assertBlocked(self, out, reason_prefix):
        got = self.only(out)
        self.assertEqual(got["state"], "BLOCKED", got)
        self.assertTrue(got["reason"].startswith(reason_prefix), got)
        self.assertFalse(list(self.root.glob("*.brain_ack.json")))
        self.assertEqual(receiver.status(self.root)["received_run_ids"], [])

    def test_signature_mismatch_is_blocked(self):
        path = self.emit()
        blob = json.loads(path.read_bytes().decode("utf-8"))
        blob["payload"]["research"]["coordinator"]["summary"] = "tampered"
        path.write_bytes(bridge._canon(blob) + b"\n")
        self.assertBlocked(self.receive(), "HANDOFF_AUTHENTICATION_FAILED")

    def test_old_envelope_is_blocked(self):
        self.emit()
        self.assertBlocked(self.receive(now=NOW + timedelta(minutes=20)), "HANDOFF_STALE_OR_FUTURE")

    def test_future_envelope_is_blocked(self):
        self.emit()
        self.assertBlocked(self.receive(now=NOW - timedelta(minutes=5)), "HANDOFF_STALE_OR_FUTURE")

    def test_unknown_publication_time_is_blocked(self):
        path = self.emit()
        blob = json.loads(path.read_bytes().decode("utf-8"))
        blob["payload"]["sources"]["sources"][0]["available_at"] = "unknown"
        path.write_bytes(bridge._canon(blob) + b"\n")
        resign(path)
        self.assertBlocked(self.receive(), "PAYLOAD_SOURCE_BINDING_INVALID")

    def test_non_public_source_is_blocked(self):
        path = self.emit()
        blob = json.loads(path.read_bytes().decode("utf-8"))
        blob["payload"]["sources"]["sources"][0]["source_url"] = "http://example.com/x"
        blob["payload"]["source_fingerprint_sha256"] = pilot.fingerprint(blob["payload"]["sources"])
        path.write_bytes(bridge._canon(blob) + b"\n")
        resign(path)
        self.assertBlocked(self.receive(), "SOURCE_URL_PUBLIC_HTTPS_ONLY")

    def test_real_order_flag_true_is_blocked(self):
        path = self.emit()
        blob = json.loads(path.read_bytes().decode("utf-8"))
        blob["payload"]["real_submit_allowed"] = True
        path.write_bytes(bridge._canon(blob) + b"\n")
        resign(path)
        self.assertBlocked(self.receive(), "PAYLOAD_SOURCE_BINDING_INVALID")
        path2 = self.root / "agent_research_brain_rx_20261021_02.json"
        doc = source_doc("brain_rx_20261021_02")
        res = research(doc)
        p2 = bridge.produce(doc, res, private_dir=self.root, now=NOW)
        blob = json.loads(p2.read_bytes().decode("utf-8"))
        blob["payload"]["research"]["real_submit_allowed"] = True
        p2.write_bytes(bridge._canon(blob) + b"\n")
        resign(p2)
        out = self.receive()
        states = {r["file"]: r["state"] for r in out["results"]}
        self.assertEqual(states[path2.name], "BLOCKED")

    def test_partially_written_file_is_blocked_then_received_when_complete(self):
        path = self.emit()
        full = path.read_bytes()
        path.write_bytes(full[: len(full) // 2])
        self.assertBlocked(self.receive(), "INBOX_JSON_INVALID")
        path.write_bytes(full)
        got = self.only(self.receive())
        self.assertEqual(got["state"], "RECEIVED")

    def test_resent_run_id_is_rejected_as_duplicate(self):
        path = self.emit()
        self.assertEqual(self.only(self.receive())["state"], "RECEIVED")
        # A second, differently timed envelope with the same run_id.
        path.unlink()
        self.emit(now=NOW + timedelta(minutes=2))
        got = self.only(self.receive(now=NOW + timedelta(minutes=3)))
        self.assertEqual(got["state"], "DUPLICATE_REJECTED")
        self.assertEqual(len(list(self.root.glob("*.brain_ack.json"))), 1)

    def test_missing_key_blocks_before_reading(self):
        self.emit()
        with patch.dict(os.environ, {bridge.KEY_ENV: ""}):
            with self.assertRaises(bridge.BridgeBlocked):
                self.receive()
        self.assertEqual(receiver.main(["--private-dir", str(self.root), "--status"]), 0)

    # -- lifecycle --------------------------------------------------------
    def test_brain_stopped_leaves_envelope_pending(self):
        self.emit()
        st = receiver.status(self.root)
        self.assertEqual(st["pending_files"], ["agent_research_brain_rx_20261021_01.json"])
        self.assertEqual(st["received_run_ids"], [])

    def test_restart_restores_receipts_and_does_not_reprocess(self):
        self.emit()
        self.only(self.receive())
        # New process view: only the private directory survives.
        st = receiver.status(self.root)
        self.assertEqual(st["received_run_ids"], ["brain_rx_20261021_01"])
        self.assertEqual(st["pending_files"], [])
        self.assertEqual(st["ack_mismatch_run_ids"], [])
        again = self.receive(now=NOW + timedelta(minutes=2))
        self.assertEqual(again["results"], [])

    def test_tampered_ack_is_reported_after_restart(self):
        self.emit()
        self.only(self.receive())
        ack = self.root / "agent_research_brain_rx_20261021_01.brain_ack.json"
        data = json.loads(ack.read_text("utf-8"))
        data["state"] = "FORGED"
        ack.write_bytes(bridge._canon(data) + b"\n")
        st = receiver.status(self.root)
        self.assertEqual(st["ack_mismatch_run_ids"], ["brain_rx_20261021_01"])
        self.assertEqual(st["received_run_ids"], [])

    def test_sidecar_ack_is_never_counted_as_brain_receipt(self):
        path = self.emit()
        bridge.consume(input_path=str(path), private_dir=str(self.root), now=NOW + timedelta(minutes=1),
                       write_ack=True)
        self.assertTrue((self.root / "agent_research_brain_rx_20261021_01.ack.json").exists())
        st = receiver.status(self.root)
        self.assertEqual(st["received_run_ids"], [])
        self.assertEqual(st["pending_files"], ["agent_research_brain_rx_20261021_01.json"])
        self.only(self.receive())
        self.assertEqual(receiver.status(self.root)["received_run_ids"], ["brain_rx_20261021_01"])

    def test_receipt_table_refuses_real_submit_true(self):
        self.emit()
        self.only(self.receive())
        with sqlite3.connect(str(self.root / receiver.DB_NAME)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE receipts SET real_submit_allowed = 1")


class NoOrderPath(unittest.TestCase):
    def test_receiver_has_no_network_broker_or_process_code(self):
        import ast
        tree = ast.parse((ROOT / "scripts" / "v10_brain_agent_research_receiver.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
                names |= {a.name for a in node.names}
        self.assertEqual(names - {"__future__", "annotations", "argparse", "contextlib", "closing", "datetime", "timezone",
                                  "hashlib", "hmac", "json", "os", "pathlib", "Path", "sqlite3", "sys", "",
                                  "agent_sdk_brain_handoff"}, set())
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for banned in ("system", "popen", "Popen", "urlopen", "connect_ex", "sleep", "startfile"):
            self.assertNotIn(banned, calls)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(receiver.main(["--private-dir", "relative/path", "--once"]), 2)


if __name__ == "__main__":
    unittest.main()
