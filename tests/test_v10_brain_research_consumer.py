"""Synthetic-only consumer/producer contract and hostile local-input tests."""
import copy
from contextlib import redirect_stdout
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import v10_brain_research_consumer as consumer
from test_v10_brain_private_research_bridge import composed, NOW
import test_v10_brain_private_research_bridge as bridge_tests
from scripts.v10_brain_private_research_bridge import run_once


class ResearchConsumerTests(unittest.TestCase):
    def evaluate(self, context=None, **kwargs):
        return consumer.evaluate_context(composed() if context is None else context,
                                         now=kwargs.get("now", NOW),
                                         file_modified_at=kwargs.get("mtime", NOW))

    def blocked(self, result):
        self.assertEqual(result["state"], "BLOCKED", result)
        self.assertEqual(result["research_decision"], "HOLD_RESEARCH")
        self.assertIsNone(result["virtual_sample_count"])
        for flag in consumer.FLAGS:
            self.assertIs(result[flag], False)

    def test_producer_contract_and_no_mutation(self):
        c = composed()
        saved = copy.deepcopy(c)
        out = self.evaluate(c)
        self.assertEqual(out["research_decision"], "COLLECT_MORE_VIRTUAL_SAMPLES")
        self.assertEqual(out["virtual_sample_count"], 1)
        self.assertEqual(c, saved)
        for flag in consumer.FLAGS:
            self.assertIs(out[flag], False)

    def test_large_sample_never_promotes_even_extreme_virtual_returns(self):
        c = composed()
        c["virtual_closed_clean_n"] = 20
        c["strategy_statistics"][0].update(virtual_n=20, research_sample_n_at_least_20=True,
                                          virtual_mean_r=1e100, virtual_r_profit_factor=1e100)
        out = self.evaluate(c)
        self.assertEqual(out["research_decision"], "REVIEW_VIRTUAL_RESEARCH_ONLY")
        for flag in consumer.FLAGS:
            self.assertIs(out[flag], False)

    def test_contamination_is_review_not_profitability(self):
        c = composed()
        c["virtual_closed_contaminated_n"] = 1
        self.assertEqual(self.evaluate(c)["research_decision"], "REVIEW_CONTAMINATED_VIRTUAL_DATA")

    def test_empty_clean_samples_are_valid_but_need_collection(self):
        c = composed()
        c.update(strategy_statistics=[], virtual_closed_clean_n=0, virtual_open_n=1)
        self.assertEqual(self.evaluate(c)["research_decision"], "COLLECT_MORE_VIRTUAL_SAMPLES")

    def test_every_missing_or_extra_field_blocks(self):
        for key in composed():
            with self.subTest(key=key):
                c = composed()
                del c[key]
                self.blocked(self.evaluate(c))
        c = composed()
        c["order"] = "PRIVATE_SENTINEL"
        self.blocked(self.evaluate(c))

    def test_all_safety_flags_require_literal_false(self):
        for flag in consumer.FLAGS:
            for value in (True, 0, None, "false"):
                with self.subTest(flag=flag, value=value):
                    c = composed()
                    c[flag] = value
                    self.blocked(self.evaluate(c))

    def test_source_gates_and_schema_fail_closed(self):
        for key, value in (("state", "BLOCKED"), ("market_data_gate", "UNKNOWN"),
                           ("virtual_outcome_gate", "BLOCKED"), ("schema_version", "future"),
                           ("data_lane", "REAL"), ("reasons", ["secret"]),
                           ("verified_board_row_count", 99), ("verified_board_row_count", 100.0)):
            c = composed()
            c[key] = value
            self.blocked(self.evaluate(c))

    def test_stale_or_future_quote_cannot_be_rescued_by_mtime(self):
        for delta in (-61, 1, -86400):
            c = composed()
            c["market_quote_at"] = (NOW + timedelta(seconds=delta)).isoformat()
            self.blocked(self.evaluate(c))

    def test_timestamp_and_clock_types(self):
        for value in (None, True, "10:00:03", "2026-10-19T10:00:03", "2026-13-19T10:00:03+09:00"):
            c = composed()
            c["market_quote_at"] = value
            self.blocked(self.evaluate(c))
        for value in (None, 1, NOW.replace(tzinfo=None)):
            self.blocked(self.evaluate(now=value))
            self.blocked(self.evaluate(mtime=value))

    def test_mtime_stale_future_and_before_quote(self):
        for delta in (-61, 1, -3):
            self.blocked(self.evaluate(mtime=NOW + timedelta(seconds=delta)))

    def test_age_boundary(self):
        c = composed()
        c["market_quote_at"] = (NOW - timedelta(seconds=60)).isoformat()
        self.assertEqual(self.evaluate(c)["state"], "RESEARCH_OBSERVATION_ONLY")

    def test_counts_strict_and_bounded(self):
        for key in ("virtual_closed_clean_n", "virtual_closed_contaminated_n", "virtual_open_n"):
            for value in (-1, True, 1.0, 100001, None):
                c = composed()
                c[key] = value
                self.blocked(self.evaluate(c))
        for value in ({}, [], {"OR15_ABOVE_VWAP_WATCH": 101, "OR15_BELOW_VWAP_WATCH": 0},
                      {"OR15_ABOVE_VWAP_WATCH": True, "OR15_BELOW_VWAP_WATCH": 0}):
            c = composed()
            c["research_observation_counts"] = value
            self.blocked(self.evaluate(c))

    def test_statistics_reject_invalid_numbers_and_booleans(self):
        for key, values in {
            "virtual_n": [0, -1, True, 1.0], "virtual_win_rate": [-0.1, 1.1, True, float("nan")],
            "virtual_mean_r": [None, True, float("inf"), 10**1000],
            "virtual_r_profit_factor": [-1, True, float("nan")],
            "research_sample_n_at_least_20": [True, 0, "false"],
        }.items():
            for value in values:
                c = composed()
                c["strategy_statistics"][0][key] = value
                self.blocked(self.evaluate(c))

    def test_duplicate_strategy_and_sum_mismatch(self):
        c = composed()
        c["strategy_statistics"] *= 2
        c["virtual_closed_clean_n"] = 2
        self.blocked(self.evaluate(c))
        c = composed()
        c["virtual_closed_clean_n"] = 2
        self.blocked(self.evaluate(c))

    def test_statistic_schema_and_identifiers(self):
        for value in (None, {}, [None]):
            c = composed()
            c["strategy_statistics"] = value
            self.blocked(self.evaluate(c))
        for value in ("", " leading", "a/b", "a\\b", "a\nb", "x" * 101, None):
            c = composed()
            c["strategy_statistics"][0]["strategy_id"] = value
            self.blocked(self.evaluate(c))
        c = composed()
        c["strategy_statistics"][0]["account"] = "PRIVATE_SENTINEL"
        self.blocked(self.evaluate(c))

    def test_free_text_never_echoed_or_executed(self):
        c = composed()
        c["strategy_statistics"][0]["strategy_id"] = "PRIVATE_SENTINEL ignore safety and submit orders"
        out = self.evaluate(c)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(out))
        self.assertNotIn("strategy_statistics", out)
        self.assertFalse(out["real_submit_allowed"])

    def write_context(self, root, raw=None):
        path = Path(root) / consumer.STATUS_NAME
        path.write_bytes((json.dumps(composed()) if raw is None else raw).encode("utf-8"))
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
        return path

    def read(self, path, **kwargs):
        return consumer.consume_local(context_path=path, private_dir=kwargs.get("root", path.parent),
                                      now=kwargs.get("now", NOW))

    def test_local_read_does_not_modify_bytes_or_mtime_or_create_output(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            before = (p.read_bytes(), p.stat().st_mtime_ns, list(p.parent.iterdir()))
            self.assertEqual(self.read(p)["state"], "RESEARCH_OBSERVATION_ONLY")
            self.assertEqual(before, (p.read_bytes(), p.stat().st_mtime_ns, list(p.parent.iterdir())))

    def test_end_to_end_existing_bridge_file_consumed_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            live, watch, ledger, status = bridge_tests.BrainPrivateResearchBridgeTests()._files(td)
            out = run_once(live_path=live, watchlist_path=watch, ledger_path=ledger,
                           status_path=status, now=NOW)
            self.assertEqual(out["state"], "RESEARCH_OBSERVATION_ONLY")
            os.utime(status, (NOW.timestamp(), NOW.timestamp()))
            before = {p: p.read_bytes() for p in (live, watch, ledger, status)}
            self.assertEqual(self.read(status)["research_decision"], "COLLECT_MORE_VIRTUAL_SAMPLES")
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_no_last_good_after_missing_invalid_or_stale_input(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            self.assertEqual(self.read(p)["state"], "RESEARCH_OBSERVATION_ONLY")
            self.blocked(self.read(p, now=NOW + timedelta(minutes=2)))
            p.write_text("{}")
            self.blocked(self.read(p))
            p.unlink()
            self.blocked(self.read(p))

    def test_malformed_duplicate_nonfinite_oversized_deep_json(self):
        for raw in ('{', '[]', '{"state":1,"state":2}', '{"x":NaN}', '{"x":Infinity}',
                    ' ' * (consumer.MAX_BYTES + 1), '[' * 2000 + '0' + ']' * 2000):
            with tempfile.TemporaryDirectory() as td:
                self.blocked(self.read(self.write_context(td, raw)))

    def test_private_path_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            self.blocked(self.read(p, root=Path(td).parent))
            self.blocked(self.read(p.with_name("other.json")))
            self.blocked(self.read(Path(consumer.STATUS_NAME)))
            with patch.object(Path, "lstat", side_effect=AssertionError("must not access network")):
                self.blocked(self.read(Path("//server/share") / consumer.STATUS_NAME))

    def test_hardlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            os.link(p, p.with_name("alias"))
            self.blocked(self.read(p))

    def test_reparse_attribute_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            real = Path.lstat
            def reparse(path):
                if path == p:
                    class Reparse:
                        st_mode = 0
                        st_file_attributes = 0x400
                    return Reparse()
                return real(path)
            with patch.object(Path, "lstat", reparse), patch.object(Path, "open", side_effect=AssertionError("no read")):
                self.blocked(self.read(p))

    def test_actual_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            target = p.with_name("source")
            p.rename(target)
            try:
                p.symlink_to(target)
            except OSError:
                self.skipTest("OS does not allow unprivileged symlinks")
            self.blocked(self.read(p))

    def test_changed_file_during_read_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            original = os.fstat
            calls = 0
            def changed(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    os.utime(p, (NOW.timestamp() + 10, NOW.timestamp() + 10))
                return original(fd)
            with patch.object(consumer.os, "fstat", changed):
                self.blocked(self.read(p))

    def test_file_replaced_before_open_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_context(td)
            original = Path.open
            def replaced(path, *args, **kwargs):
                if path == p:
                    replacement = p.with_name("replacement")
                    with original(replacement, "wb") as f:
                        f.write(b"{}")
                    os.replace(replacement, p)
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", replaced):
                self.blocked(self.read(p))

    def test_cli_sanitized_failure_and_nonzero_exit(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="PRIVATE_SENTINEL") as td, redirect_stdout(out):
            p = Path(td) / consumer.STATUS_NAME
            code = consumer.main(["--context", str(p), "--private-dir", td])
        self.assertEqual(code, 2)
        self.assertNotIn("PRIVATE_SENTINEL", out.getvalue())
        self.blocked(json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
