"""M1: a clock override is only honoured on an explicitly initialised sandbox home.

Production-equivalent homes always run on the real clock: --now and AUTO_PUBLISH_NOW
are refused (fail-closed) for every command, so knowledge time, dispatch timing,
ingest freshness and audit timestamps cannot be forged there.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from auto_publish.app import controls
from auto_publish.app.clock import Clock, FixedClock, parse_aware
from auto_publish.app.db import connect
from auto_publish.app.errors import ValidationError
from auto_publish.app.sandbox import init_sandbox, is_sandbox, resolve_clock

REPO = Path(__file__).resolve().parents[2]
NOW = "2026-09-24T17:00:00+09:00"


class TestResolveClock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_production_home_real_clock_only(self):
        self.assertIs(type(resolve_clock(self.conn, None)), Clock)
        with self.assertRaises(ValidationError) as cm:
            resolve_clock(self.conn, NOW)
        self.assertEqual(cm.exception.code, "CLOCK_OVERRIDE_REFUSED")

    def test_sandbox_home_accepts_override(self):
        init_sandbox(self.conn, Clock(), "t")
        self.assertTrue(is_sandbox(self.conn))
        c = resolve_clock(self.conn, NOW)
        self.assertIsInstance(c, FixedClock)
        self.assertEqual(c.now(), parse_aware(NOW))
        self.assertTrue(init_sandbox(self.conn, Clock(), "t")["noop"])
        row = self.conn.execute("SELECT action, entity_id, to_state FROM audit_log").fetchone()
        self.assertEqual(tuple(row), ("set", "home.sandbox", "1"))

    def test_home_with_data_cannot_become_sandbox(self):
        controls.pause_all(self.conn, Clock(), "ops")            # any recorded activity
        with self.assertRaises(ValidationError) as cm:
            init_sandbox(self.conn, Clock(), "t")
        self.assertEqual(cm.exception.code, "SANDBOX_REQUIRES_EMPTY_HOME")
        self.assertFalse(is_sandbox(self.conn))

    def test_sandbox_init_itself_cannot_use_a_fixed_clock(self):
        with self.assertRaises(ValidationError):
            init_sandbox(self.conn, FixedClock(parse_aware(NOW)), "t")


class TestCliClockOverride(unittest.TestCase):
    def run_cli(self, home, *args, env_extra=None):
        env = {**os.environ, "AUTO_PUBLISH_HOME": str(home), "PYTHONPATH": str(REPO)}
        env.pop("AUTO_PUBLISH_NOW", None)
        env.update(env_extra or {})
        out = subprocess.run([sys.executable, "-m", "auto_publish.cli", *args], capture_output=True, text=True,
                             encoding="utf-8", env=env, cwd=REPO, timeout=120)
        return out.returncode, json.loads(out.stdout)

    def test_flag_and_env_refused_on_production_home_for_every_command(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            for args in (["--now", NOW, "would-publish"], ["--now", NOW, "metrics-import", "--platform", "tiktok",
                                                            "--csv", "x.csv"], ["--now", NOW, "queue"],
                         ["--now", NOW, "ingest", "--input", "nowhere"]):
                rc, doc = self.run_cli(home, *args)
                self.assertEqual((rc, doc["error"]["code"]), (2, "CLOCK_OVERRIDE_REFUSED"), args)
            rc, doc = self.run_cli(home, "would-publish", env_extra={"AUTO_PUBLISH_NOW": NOW})
            self.assertEqual((rc, doc["error"]["code"]), (2, "CLOCK_OVERRIDE_REFUSED"))
            rc, doc = self.run_cli(home, "would-publish")                       # real clock: allowed
            self.assertEqual(rc, 0)
            self.assertEqual(self.run_cli(home, "pause-all", "--reason", "ops")[0], 0)   # home now holds data
            rc, doc = self.run_cli(home, "sandbox-init")                         # -> can no longer become a sandbox
            self.assertEqual((rc, doc["error"]["code"]), (2, "SANDBOX_REQUIRES_EMPTY_HOME"))

    def test_sandbox_home_accepts_flag_and_env(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            self.assertEqual(self.run_cli(home, "sandbox-init")[0], 0)
            rc, doc = self.run_cli(home, "--now", NOW, "would-publish")
            self.assertEqual((rc, doc["result"]["evaluated_at_utc"]), (0, "2026-09-24T08:00:00Z"))
            rc, doc = self.run_cli(home, "would-publish", env_extra={"AUTO_PUBLISH_NOW": NOW})
            self.assertEqual(rc, 0)
            rc, doc = self.run_cli(home, "--now", NOW, "sandbox-init")           # still real clock only
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
