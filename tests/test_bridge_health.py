"""Unit tests for scripts/bridge_health.py's classification logic and the
record/read round-trip of data/bridge_health_state.json.

These tests stub out git calls (subprocess) so they run offline and never
touch this repository's real state file or real git history.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "bridge_health.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bridge_health", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge_health = _load_module()


class ComputeHealthTest(unittest.TestCase):
    def _patch(self, behind, ahead=0, fetch_ok=True, uncommitted_lines="", unpushed=0):
        def _run(args):
            if args[:2] == ["git", "fetch"]:
                return ("", None) if fetch_ok else (None, "offline")
            if args == ["git", "rev-parse", "HEAD"]:
                return "localsha1234", None
            if args == ["git", "rev-parse", "origin/main"]:
                return "originsha5678", None
            if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
                return "some-branch", None
            if args == [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                "HEAD...origin/main",
            ]:
                return f"{ahead}\t{behind}", None
            if args == ["git", "status", "--porcelain"]:
                return uncommitted_lines, None
            if args == [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                "@{u}...HEAD",
            ]:
                return f"0\t{unpushed}", None
            raise AssertionError(f"unstubbed git call: {args}")

        return mock.patch.object(bridge_health, "_run", side_effect=_run)

    def test_zero_behind_is_healthy(self):
        with self._patch(behind=0):
            report = bridge_health.compute_health()
        self.assertEqual(report["status"], "HEALTHY")
        self.assertEqual(report["behind"], 0)

    def test_moderate_drift_is_drift_not_blocked(self):
        with self._patch(behind=bridge_health.DRIFT_BEHIND_THRESHOLD):
            report = bridge_health.compute_health()
        self.assertEqual(report["status"], "DRIFT")

    def test_severe_drift_is_blocked(self):
        with self._patch(behind=2150):
            report = bridge_health.compute_health()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("2150", report["reason"])

    def test_fetch_failure_is_blocked(self):
        with self._patch(behind=0, fetch_ok=False):
            report = bridge_health.compute_health()
        self.assertEqual(report["status"], "BLOCKED")

    def test_exit_codes_match_status(self):
        with self._patch(behind=0):
            self.assertEqual(bridge_health.compute_health()["status"], "HEALTHY")
        with self._patch(behind=bridge_health.BLOCKED_BEHIND_THRESHOLD):
            self.assertEqual(bridge_health.compute_health()["status"], "BLOCKED")


class StateRoundTripTest(unittest.TestCase):
    def test_save_then_load_state(self):
        with mock.patch.object(
            bridge_health, "STATE_PATH", Path(self._tmp_path())
        ):
            state = {
                "last_reconciled_sha": "abc123",
                "last_reconciled_c_id": "C-091",
                "last_sync_timestamp": "2026-09-25T00:00:00+09:00",
            }
            bridge_health._save_state(state)
            loaded = bridge_health._load_state()
        self.assertEqual(loaded, state)

    def _tmp_path(self):
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".json")
        import os

        os.close(fd)
        os.remove(path)  # _save_state must create it fresh
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path


if __name__ == "__main__":
    unittest.main()
