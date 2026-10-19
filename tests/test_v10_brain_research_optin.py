"""Synthetic read-only Brain status + private research sidecar tests."""
from __future__ import annotations

from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from scripts import ai_brain_observer as brain
from scripts import v10_brain_research_consumer as consumer
from scripts import v10_brain_research_optin as optin
from test_v10_brain_private_research_bridge import composed, NOW


class BrainResearchOptInTests(unittest.TestCase):
    def make_inputs(self, td):
        root = Path(td)
        runtime, private = root / "runtime", root / "private_shadow"
        runtime.mkdir()
        private.mkdir()
        status = runtime / optin.BRAIN_NAME
        judgment = private / consumer.STATUS_NAME
        observer = {
            "state": "OBSERVATION_ONLY",
            "reasons": [],
            "source_publication_at": (NOW - timedelta(seconds=2)).isoformat(),
            "observed_rows": 100,
            "watch_counts": {
                "OR15_ABOVE_VWAP_WATCH": 1,
                "OR15_BELOW_VWAP_WATCH": 0,
            },
            "watch_observations": [],
        }
        snapshot = brain.status_snapshot(observer, now=NOW, pid=1234)
        status.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        judgment.write_text(json.dumps(composed(), ensure_ascii=False), encoding="utf-8")
        os.utime(status, (NOW.timestamp(), NOW.timestamp()))
        os.utime(judgment, (NOW.timestamp(), NOW.timestamp()))
        return status, private

    def run_optin(self, status, private, now=NOW):
        return optin.run_once(brain_status_path=status,
                              research_private_dir=private, now=now)

    def assert_safe(self, result):
        for flag in consumer.FLAGS:
            self.assertIs(result[flag], False)
        text = json.dumps(result)
        for secret in ("PRIVATE_SENTINEL", "OR15押し目", "1000.T", "ledger.jsonl"):
            self.assertNotIn(secret, text)

    def test_read_only_valid_synthetic_files_and_research_only_result(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            context = private / consumer.STATUS_NAME
            before = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (status, context)
            }
            result = self.run_optin(status, private)
            after = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in before
            }
            self.assertEqual(before, after)
            self.assertEqual(set(status.parent.iterdir()), {status})
            self.assertEqual(set(private.iterdir()), {context})
        self.assertEqual(result["state"], "RESEARCH_OBSERVATION_ONLY", result)
        self.assertEqual(result["research_decision"], "COLLECT_MORE_VIRTUAL_SAMPLES")
        self.assertEqual(result["virtual_sample_count"], 1)
        self.assertEqual(result["brain_observation_gate"], "PASS")
        self.assert_safe(result)

    def test_absent_or_nonlocal_brain_status_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            for p in (Path("relative.json"), status.with_name("wrong.json"),
                      Path("//server/share") / optin.BRAIN_NAME):
                result = self.run_optin(p, private)
                self.assertEqual(result["state"], "BLOCKED", result)
                self.assert_safe(result)
            status.unlink()
            result = self.run_optin(status, private)
            self.assertEqual(result["state"], "BLOCKED")
            self.assert_safe(result)

    def test_stale_future_and_naive_decision_clock_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            for now in (NOW + timedelta(minutes=3), NOW - timedelta(seconds=1),
                        NOW.replace(tzinfo=None)):
                r = self.run_optin(status, private, now=now)
                self.assertEqual(r["state"], "BLOCKED", r)
                self.assert_safe(r)

    def test_brain_status_unsafe_claims_and_observer_state_fail_closed(self):
        fields = {
            "state": "BLOCKED", "real_submit_allowed": True,
            "source_authenticated": True, "promotion_eligible": True,
            "cross_source_join_allowed": True, "eligible_observed_n": 1,
            "last_market_data_at": "forged", "engine_pid": 0,
            "observed_rows": 99, "source_publication_at": "2020-01-01T00:00:00Z",
            "exchange_tick_date_verified": True, "tested_expectancy_available": True,
        }
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            clean = json.loads(status.read_text())
            for key, value in fields.items():
                with self.subTest(key=key):
                    edited = dict(clean, **{key: value})
                    status.write_text(json.dumps(edited), encoding="utf-8")
                    os.utime(status, (NOW.timestamp(), NOW.timestamp()))
                    result = self.run_optin(status, private)
                    self.assertEqual(result["state"], "BLOCKED", key)
                    self.assert_safe(result)

    def test_context_missing_corrupt_stale_never_uses_last_good(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            context = private / consumer.STATUS_NAME
            self.assertEqual(self.run_optin(status, private)["state"],
                             "RESEARCH_OBSERVATION_ONLY")
            context.unlink()
            self.assertEqual(self.run_optin(status, private)["state"], "BLOCKED")
            context.write_text('{"secret":"PRIVATE_SENTINEL"}', encoding="utf-8")
            os.utime(context, (NOW.timestamp(), NOW.timestamp()))
            bad = self.run_optin(status, private)
            self.assertEqual(bad["state"], "BLOCKED")
            self.assert_safe(bad)
            context.write_text(json.dumps(composed()), encoding="utf-8")
            os.utime(context, ((NOW-timedelta(seconds=61)).timestamp(),) * 2)
            self.assertEqual(self.run_optin(status, private)["state"], "BLOCKED")

    def test_untrusted_consumer_return_cannot_promote_or_leak(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            valid = consumer._result(None, decision="COLLECT_MORE_VIRTUAL_SAMPLES",
                                     sample_count=1)
            forged = (
                {"real_submit_allowed": True}, {"source_authenticated": True},
                {"path": "PRIVATE_SENTINEL"}, {"reason": "PRIVATE_SENTINEL"},
                {"virtual_sample_count": True}, {"research_decision": "SUBMIT_ORDER"},
            )
            for change in forged:
                with self.subTest(change=change):
                    with patch.object(consumer, "consume_local",
                                      return_value=dict(valid, **change)):
                        result = self.run_optin(status, private)
                    self.assertEqual(result["state"], "BLOCKED", change)
                    self.assert_safe(result)

    def test_ntfs_descriptor_creation_time_difference_not_false_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            original = os.fstat
            class DescriptorStat:
                def __init__(self, s):
                    self.s = s
                def __getattr__(self, name):
                    if name == "st_ctime_ns":
                        return self.s.st_ctime_ns + 10000000
                    return getattr(self.s, name)
            with patch.object(optin.os, "fstat",
                              side_effect=lambda fd: DescriptorStat(original(fd))):
                result = self.run_optin(status, private)
            self.assertEqual(result["state"], "RESEARCH_OBSERVATION_ONLY", result)
            self.assert_safe(result)

    def test_real_change_during_read_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            original = os.fstat
            calls = 0
            def change(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    os.utime(status, ((NOW+timedelta(seconds=10)).timestamp(),) * 2)
                return original(fd)
            with patch.object(optin.os, "fstat", side_effect=change):
                result = self.run_optin(status, private)
            self.assertEqual(result["state"], "BLOCKED", result)
            self.assert_safe(result)

    def test_symlink_to_brain_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            original = status.with_name("original.json")
            status.rename(original)
            try:
                status.symlink_to(original)
            except (OSError, NotImplementedError):
                self.skipTest("unprivileged Windows symlink creation unavailable")
            result = self.run_optin(status, private)
            self.assertEqual(result["state"], "BLOCKED")
            self.assert_safe(result)

    def test_cli_failure_sanitizes_private_path_and_exits_two(self):
        with tempfile.TemporaryDirectory(prefix="PRIVATE_SENTINEL") as td:
            out = io.StringIO()
            with redirect_stdout(out):
                code = optin.main([
                    "--brain-status", str(Path(td) / optin.BRAIN_NAME),
                    "--research-private-dir", td])
            self.assertEqual(code, 2)
            self.assert_safe(json.loads(out.getvalue()))
            self.assertNotIn("PRIVATE_SENTINEL", out.getvalue())

    def test_consumer_error_blocks_without_changing_canonical_brain(self):
        with tempfile.TemporaryDirectory() as td:
            status, private = self.make_inputs(td)
            orig = status.read_bytes()
            with patch.object(consumer, "consume_local",
                              side_effect=RuntimeError("PRIVATE_SENTINEL")):
                result = self.run_optin(status, private)
            self.assertEqual(result["state"], "BLOCKED")
            self.assert_safe(result)
            self.assertEqual(orig, status.read_bytes())


if __name__ == "__main__":
    unittest.main()
