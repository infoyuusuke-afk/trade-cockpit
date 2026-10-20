"""P0-AGENTS-SDK-V10-BRAIN-INTEGRATION-20261021: opt-in receiver inside the V10 Brain observer.

Synthetic only, no network, no API call, no V10 runtime started. The private
inbox path contains Japanese characters.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
NOW = datetime(2026, 10, 21, 1, 40, 0, tzinfo=timezone.utc)
KEY = "3c" * 32
RX_KEY = "d9" * 32


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


observer = _load("v10_observer_under_test", "scripts/ai_brain_observer.py")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)


def _fresh_package():
    for key in [k for k in sys.modules if k == observer.AGENT_PACKAGE or k.startswith(observer.AGENT_PACKAGE + ".")]:
        del sys.modules[key]


def _emit(inbox, run_id="observer_rx_20261021_01", now=NOW):
    pkg = observer.load_agent_receiver(SCRIPTS)
    pilot = sys.modules[observer.AGENT_PACKAGE + ".agent_sdk_coordination_pilot"]
    bridge = sys.modules[observer.AGENT_PACKAGE + ".agent_sdk_brain_handoff"]
    doc = {"schema_version": pilot.SCHEMA, "run_id": run_id, "sources": [{
        "source_id": "syn_pre_0", "role": "pre_next", "source_url": "https://www.boj.or.jp/rss/whatsnew.xml",
        "as_of": "2026-10-20T12:00:00+09:00", "available_at": "2026-10-20T16:35:00+00:00",
        "summary": "Synthetic offline headline; no trading information"}]}
    result = asyncio.run(pilot.coordinate(doc, pilot.offline_runner, now=now))
    result["state"] = "OFFLINE_SYNTHETIC_NO_API_CALL"
    bridge.produce(doc, result, private_dir=inbox, now=now)
    return pkg


class PinsMatchCommittedModules(unittest.TestCase):
    def test_each_pin_is_the_committed_blob(self):
        for name, pin in observer.AGENT_RECEIVER_MODULES:
            with self.subTest(module=name):
                self.assertEqual(observer.git_blob_sha1((SCRIPTS / (name + ".py")).read_bytes()), pin)
                got = _git("rev-parse", "HEAD:scripts/" + name + ".py")
                if got.returncode == 0:
                    self.assertEqual(got.stdout.strip(), pin)


class ObserverAgentReceiver(unittest.TestCase):
    def setUp(self):
        _fresh_package()
        tmp = tempfile.mkdtemp(prefix="v10-obs-rx-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.inbox = Path(tmp) / "100億PROJECT" / "受け箱"
        self.inbox.mkdir(parents=True)
        env = patch.dict(os.environ, {"AGENT_BRIDGE_HMAC_KEY": KEY, "AGENT_BRAIN_RECEIVER_HMAC_KEY": RX_KEY,
                                      observer.AGENT_INBOX_ENV: str(self.inbox)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(_fresh_package)

    def run_pass(self, state, now):
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = observer.agent_receiver_pass(state, now=now, script_dir=SCRIPTS)
        return out, buf.getvalue()

    def test_off_by_default_imports_and_runs_nothing(self):
        _fresh_package()
        with patch.dict(os.environ, {observer.AGENT_INBOX_ENV: ""}):
            out, printed = self.run_pass({}, NOW)
        self.assertIsNone(out)
        self.assertEqual(printed, "")
        self.assertNotIn(observer.AGENT_PACKAGE, sys.modules)

    def test_receives_in_the_observer_process_and_names_the_host(self):
        _emit(self.inbox)
        out, printed = self.run_pass({}, NOW + timedelta(minutes=1))
        self.assertEqual(out["agent_receiver"], "PASS")
        self.assertEqual(out["results"], {"RECEIVED": 1})
        self.assertIs(out["real_submit_allowed"], False)
        self.assertNotIn(str(self.inbox), printed)  # no private path in the log line
        ack = json.loads((self.inbox / "agent_research_observer_rx_20261021_01.brain_ack.json").read_text("utf-8"))
        self.assertEqual(ack["receiver"]["host_component"], "v10-ai-brain-observer")
        self.assertEqual(ack["receiver"]["process_id"], os.getpid())
        self.assertIs(ack["real_submit_allowed"], False)
        self.assertIs(ack["live_market_data"], False)

    def test_runs_at_most_every_30_seconds(self):
        _emit(self.inbox)
        state = {}
        first, _ = self.run_pass(state, NOW + timedelta(minutes=1))
        self.assertIsNotNone(first)
        self.assertIsNone(self.run_pass(state, NOW + timedelta(minutes=1, seconds=10))[0])
        self.assertIsNotNone(self.run_pass(state, NOW + timedelta(minutes=1, seconds=31))[0])

    def test_restart_keeps_receipts_and_does_not_reprocess(self):
        _emit(self.inbox)
        self.run_pass({}, NOW + timedelta(minutes=1))
        _fresh_package()  # a new observer process
        out, _ = self.run_pass({}, NOW + timedelta(minutes=2))
        self.assertEqual(out["results"], {})
        st = sys.modules[observer.AGENT_PACKAGE + ".v10_brain_agent_research_receiver"].status(self.inbox)
        self.assertEqual(st["received_run_ids"], ["observer_rx_20261021_01"])

    def test_modified_receiver_module_is_refused_and_nothing_is_written(self):
        _emit(self.inbox)
        _fresh_package()
        tmp = Path(tempfile.mkdtemp(prefix="v10-obs-pin-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name, _ in observer.AGENT_RECEIVER_MODULES:
            shutil.copy2(SCRIPTS / (name + ".py"), tmp / (name + ".py"))
        target = tmp / "v10_brain_agent_research_receiver.py"
        target.write_bytes(target.read_bytes() + b"\n# modified\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = observer.agent_receiver_pass({}, now=NOW + timedelta(minutes=1), script_dir=tmp)
        self.assertEqual(out["agent_receiver"], "BLOCKED")
        self.assertEqual(out["reason"], "AGENT_RECEIVER_MODULE_PIN_MISMATCH:v10_brain_agent_research_receiver")
        self.assertFalse(list(self.inbox.glob("*.brain_ack.json")))

    def test_missing_receiver_key_blocks_without_ack(self):
        _emit(self.inbox)
        with patch.dict(os.environ, {"AGENT_BRAIN_RECEIVER_HMAC_KEY": ""}):
            out, _ = self.run_pass({}, NOW + timedelta(minutes=1))
        self.assertEqual(out["agent_receiver"], "BLOCKED")
        self.assertEqual(out["reason"], "RECEIVER_HMAC_KEY_MISSING_OR_INVALID")
        self.assertFalse(list(self.inbox.glob("*.brain_ack.json")))

    def test_observer_status_is_unchanged_by_the_receiver(self):
        _emit(self.inbox)
        a = observer.status_snapshot(observer.analyze({}, now=NOW, file_modified_at=None), now=NOW, pid=1)
        self.run_pass({}, NOW + timedelta(minutes=1))
        b = observer.status_snapshot(observer.analyze({}, now=NOW, file_modified_at=None), now=NOW, pid=1)
        self.assertEqual(a, b)
        self.assertNotIn("agent", json.dumps(b))


if __name__ == "__main__":
    unittest.main()
