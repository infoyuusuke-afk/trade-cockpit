"""Synthetic contract tests for strictly optional Brain research-only context."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import ai_brain_observer as brain
from scripts import v10_brain_research_consumer as consumer
from test_v10_brain_private_research_bridge import composed, NOW


class BrainResearchOptInTests(unittest.TestCase):
    def run_brain(self, research_private_dir=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(brain, "read_snapshot", return_value=({}, NOW)))
            stack.enter_context(patch.object(brain, "analyze", return_value={}))
            stack.enter_context(patch.object(
                brain, "status_snapshot", return_value={
                    "schema_version": "ai-brain-observer-1", "real_submit_allowed": False,
                    "state": "OBSERVATION_ONLY",
                }))
            write = stack.enter_context(patch.object(brain, "write_status"))
            result = brain.run_once(Path("synthetic-live.json"), Path("synthetic-status.json"),
                                    now=NOW, pid=123, research_private_dir=research_private_dir)
            write.assert_called_once()
            self.assertEqual(write.call_args.args[1], result)
            self.assertIs(result["real_submit_allowed"], False)
            return result

    def assert_nontrading(self, result):
        for key in brain._RESEARCH_FALSE_FLAGS:
            self.assertIs(result[key], False, key)

    def test_default_canonical_launch_has_no_research_dependency_or_schema_change(self):
        with patch.object(consumer, "consume_local", side_effect=AssertionError("not opted in")):
            result = self.run_brain()
        self.assertEqual(set(result), {"schema_version", "real_submit_allowed", "state"})
        self.assertNotIn("research_context", result)

    def test_explicit_missing_context_is_blocked_not_exception_or_last_good(self):
        with tempfile.TemporaryDirectory() as td:
            out = self.run_brain(td)["research_context"]
        self.assertEqual(out["state"], "BLOCKED")
        self.assertEqual(out["research_decision"], "HOLD_RESEARCH")
        self.assert_nontrading(out)

    def test_opted_in_existing_producer_contract_real_file_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / consumer.STATUS_NAME
            path.write_text(json.dumps(composed(), ensure_ascii=False), encoding="utf-8")
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            out = self.run_brain(td)["research_context"]
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(out["state"], "RESEARCH_OBSERVATION_ONLY")
        self.assertEqual(out["research_decision"], "COLLECT_MORE_VIRTUAL_SAMPLES")
        self.assertEqual(out["virtual_sample_count"], 1)
        self.assert_nontrading(out)

    def test_stale_and_corrupted_context_do_not_reuse_previous_success(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / consumer.STATUS_NAME
            path.write_text(json.dumps(composed()), encoding="utf-8")
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            self.assertEqual(brain._opt_in_research(td, now=NOW)["state"],
                             "RESEARCH_OBSERVATION_ONLY")
            stale = brain._opt_in_research(td, now=NOW + timedelta(minutes=2))
            self.assertEqual(stale["state"], "BLOCKED")
            self.assert_nontrading(stale)
            path.write_text('{"secret":"PRIVATE_SENTINEL"}', encoding="utf-8")
            corrupted = brain._opt_in_research(td, now=NOW)
            self.assertEqual(corrupted["state"], "BLOCKED")
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(corrupted))
            self.assert_nontrading(corrupted)

    def test_untrusted_consumer_output_cannot_promote_or_leak(self):
        valid = consumer._result(None, decision="COLLECT_MORE_VIRTUAL_SAMPLES", sample_count=1)
        for change in (
            {"real_submit_allowed": True},
            {"source_authenticated": True},
            {"path": "PRIVATE_SENTINEL"},
            {"reason": "PRIVATE_SENTINEL"},
            {"research_decision": "SUBMIT_ORDER"},
            {"virtual_sample_count": True},
        ):
            forged = dict(valid, **change)
            with patch.object(consumer, "consume_local", return_value=forged):
                out = brain._opt_in_research("/synthetic/private", now=NOW)
            self.assertEqual(out["state"], "BLOCKED", change)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(out))
            self.assert_nontrading(out)

    def test_consumer_crash_is_sanitized_blocked_not_brain_process_failure(self):
        with patch.object(consumer, "consume_local",
                          side_effect=RuntimeError("PRIVATE_SENTINEL")):
            out = self.run_brain("/synthetic/private")["research_context"]
        self.assertEqual(out["state"], "BLOCKED")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(out))
        self.assert_nontrading(out)

    def test_cli_optional_switch_requires_explicit_selection(self):
        with patch.object(brain, "run_once", return_value={}) as run:
            self.assertEqual(brain.main(["--live", "x", "--status", "y", "--once"]), 0)
            self.assertIsNone(run.call_args.kwargs["research_private_dir"])
            self.assertEqual(brain.main([
                "--live", "x", "--status", "y", "--once",
                "--research-private-dir", "/synthetic/private"]), 0)
            self.assertEqual(run.call_args.kwargs["research_private_dir"],
                             "/synthetic/private")


if __name__ == "__main__":
    unittest.main()
