"""Synthetic candidate-key and PIT refusal tests. No private MS2 data."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import ms2_records_quality as q1
from scripts import ms2_records_alignment_probe as probe


def make_row(name, time="2026-10-14 09:00:10", ticker="SYNTHETIC-A"):
    fields = q1.HEADERS[name]
    row = dict.fromkeys(fields, "")
    row["ticker"] = ticker
    row["captured_at"] = time
    row["name"] = "SYNTHETIC"
    if "price" in row:
        row["price"] = "123"
    if name == "ticks.csv":
        row["exchange_time"] = "09:00:09"
        row["direction_estimate"] = "UNKNOWN"
    if name == "trade_signals.csv":
        row.update(signal="SYNTHETIC", strategy="SYNTHETIC", entry="124")
    return row


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.day = Path(self.temp.name) / "2026-10-14"
        self.day.mkdir()
        self.rows = {name: [make_row(name)] for name in q1.HEADERS}
        self.save()

    def save(self):
        for name in q1.HEADERS:
            with (self.day / name).open("w", encoding="utf8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=q1.HEADERS[name])
                writer.writeheader()
                writer.writerows(self.rows[name])

    def report(self):
        return probe.inspect(self.day)

    def test_matching_keys_never_pit_proof(self):
        x = self.report()
        self.assertEqual(x["status"], "CANDIDATE_DIAGNOSTIC_ONLY")
        self.assertEqual(x["diagnostics"]["triplet_unique_candidate_keys"], 1)
        self.assertEqual(x["diagnostics"]["signals_with_one_snapshot_key_candidate"], 1)
        self.assertEqual(x["source_attribution"], "UNVERIFIED_NO_EMBEDDED_PRODUCER_OR_SESSION_PROOF")
        self.assertFalse(x["poll_join_proven"])
        self.assertFalse(x["decision_asof_proven"])
        self.assertFalse(x["pit_research_eligible"])
        self.assertFalse(x["shadow_forward_eligible"])
        self.assertFalse(x["performance_eligible"])
        self.assertFalse(x["future_leak_excluded"])
        self.assertEqual(x["eligible_observed_n"], 0)
        self.assertFalse(x["real_submit_allowed"])

    def test_identical_row_totals_can_be_unmatched(self):
        self.rows["condition_log.csv"][0]["ticker"] = "SYNTHETIC-B"
        self.save()
        x = self.report()
        self.assertEqual(x["diagnostics"]["snapshot_rows"], 1)
        self.assertEqual(x["diagnostics"]["condition_rows"], 1)
        self.assertEqual(x["diagnostics"]["triplet_unique_candidate_keys"], 0)
        self.assertEqual(x["diagnostics"]["triplet_incomplete_keys"], 2)
        self.assertIn("CROSS_FILE_KEY_INCOMPLETE_OR_AMBIGUOUS", x["reason_codes"])

    def test_two_snapshots_same_key_ambiguous(self):
        self.rows["market_snapshots.csv"].append(dict(self.rows["market_snapshots.csv"][0]))
        self.save()
        x = self.report()
        self.assertEqual(x["diagnostics"]["triplet_multirow_ambiguous_keys"], 1)
        self.assertEqual(x["diagnostics"]["signals_with_multiple_snapshot_key_candidates"], 1)
        self.assertEqual(x["diagnostics"]["triplet_unique_candidate_keys"], 0)

    def test_missing_signal_snapshot_is_not_backfilled(self):
        self.rows["trade_signals.csv"][0]["captured_at"] = "2026-10-14 09:00:12"
        self.save()
        x = self.report()
        self.assertEqual(x["diagnostics"]["signals_with_no_snapshot_key_candidate"], 1)
        self.assertEqual(x["diagnostics"]["signals_with_one_snapshot_key_candidate"], 0)

    def test_two_signals_same_key_cannot_claim_two_trades(self):
        self.rows["trade_signals.csv"].append(dict(self.rows["trade_signals.csv"][0]))
        self.save()
        x = self.report()
        self.assertEqual(x["diagnostics"]["signal_rows"], 2)
        self.assertEqual(x["diagnostics"]["repeated_signal_key_rows"], 1)
        self.assertFalse(x["performance_eligible"])

    def test_snapshot_and_condition_extra_keys(self):
        self.rows["market_snapshots.csv"].append(make_row("market_snapshots.csv", "2026-10-14 09:00:20"))
        self.save()
        x = self.report()
        self.assertEqual(x["diagnostics"]["triplet_unique_candidate_keys"], 1)
        self.assertEqual(x["diagnostics"]["triplet_incomplete_keys"], 1)
        self.assertEqual(x["diagnostics"]["missing_source_keys"]["condition"], 1)

    def test_wrong_header_blocks_inherited_q1(self):
        (self.day / "market_snapshots.csv").write_text("ticker,time\nABC,123\n", encoding="utf8")
        x = self.report()
        self.assertEqual(x["status"], "BLOCKED")
        self.assertIn("Q1_NOT_PASSED", x["reason_codes"])

    def test_missing_input_blocks_q1(self):
        (self.day / "under_over.csv").unlink()
        x = self.report()
        self.assertEqual(x["status"], "BLOCKED")
        self.assertFalse(x["pit_research_eligible"])

    def test_bad_timestamp_blocks_q1(self):
        self.rows["condition_log.csv"][0]["captured_at"] = "2026-10-13 08:00:00"
        self.save()
        self.assertIn("Q1_NOT_PASSED", self.report()["reason_codes"])

    def test_symlink_escape_blocked_by_q1(self):
        target = self.day / "market_snapshots.csv"
        external = Path(self.temp.name) / "external.csv"
        target.replace(external)
        try:
            target.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("OS denies symlinks")
        self.assertIn("Q1_NOT_PASSED", self.report()["reason_codes"])

    def test_changed_second_read_is_blocked(self):
        with patch.object(probe, "_read_keys", side_effect=probe.ProbeBlocked("SOURCE_CHANGED_DURING_READ")):
            x = self.report()
        self.assertEqual(x["status"], "BLOCKED")
        self.assertIn("SOURCE_CHANGED_DURING_READ", x["reason_codes"])

    def test_windows_path_handle_timestamp_representation_skew_allowed(self):
        # Windows path.stat and fstat may expose different time encodings.
        # Both views are stable, and dev/inode/size bind to the same file.
        path_view = (1, 11, 500, 100, 300)
        handle_view = (1, 11, 500, 200, 400)
        with patch.object(probe.q1, "_stat_key",
                          side_effect=[path_view, handle_view, handle_view, path_view]):
            keys = probe._read_keys(self.day, "market_snapshots.csv")
        self.assertEqual(sum(keys.values()), 1)

    def test_same_size_and_timestamps_different_file_identity_blocked(self):
        # Same size and timestamp must not hide a pathname/handle race.
        path_view = (1, 11, 500, 100, 300)
        handle_view = (1, 12, 500, 100, 300)
        with patch.object(probe.q1, "_stat_key",
                          side_effect=[path_view, handle_view, handle_view, path_view]):
            with self.assertRaises(probe.ProbeBlocked) as raised:
                probe._read_keys(self.day, "market_snapshots.csv")
        self.assertEqual(raised.exception.code, "SOURCE_CHANGED_DURING_READ")


    def _mutate_after_q1(self, file_name, mutate):
        # Q1 validates original bytes; a producer may replace a CSV before Q2.
        original_audit = probe.q1.audit

        def audit_then_mutate(day_dir):
            result = original_audit(day_dir)
            self.assertEqual(result["status"], "Q1_PARSED_ONLY")
            mutate(self.rows[file_name])
            with (self.day / file_name).open("w", encoding="utf8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=q1.HEADERS[file_name])
                writer.writeheader()
                writer.writerows(self.rows[file_name])
            return result

        with patch.object(probe.q1, "audit", side_effect=audit_then_mutate):
            return self.report()

    def test_second_pass_invalid_numeric_after_q1(self):
        def change(rows):
            rows[0]["price"] = "not-a-number"
        x = self._mutate_after_q1("market_snapshots.csv", change)
        self.assertEqual(x["status"], "BLOCKED")
        self.assertIn("SECOND_PASS_NUMERIC_INVALID", x["reason_codes"])
        self.assertFalse(x["pit_research_eligible"])
        self.assertEqual(x["eligible_observed_n"], 0)

    def test_second_pass_wrong_day_after_q1(self):
        def change(rows):
            rows[0]["captured_at"] = "2026-10-13 09:00:10"
        x = self._mutate_after_q1("condition_log.csv", change)
        self.assertEqual(x["status"], "BLOCKED")
        self.assertIn("SECOND_PASS_KEY_INVALID", x["reason_codes"])
        self.assertFalse(x["shadow_forward_eligible"])

    def test_second_pass_clock_reverse_after_q1(self):
        def change(rows):
            rows.append(make_row("under_over.csv", "2026-10-14 09:00:09"))
        x = self._mutate_after_q1("under_over.csv", change)
        self.assertEqual(x["status"], "BLOCKED")
        self.assertIn("SECOND_PASS_CLOCK_REVERSE", x["reason_codes"])
        self.assertFalse(x["performance_eligible"])
        self.assertFalse(x["real_submit_allowed"])

    def test_index_limit_rejects(self):
        self.rows["market_snapshots.csv"].append(make_row("market_snapshots.csv", "2026-10-14 09:00:20"))
        self.save()
        with patch.object(probe, "MAX_UNIQUE_KEYS", 1):
            self.assertIn("KEY_INDEX_CAPACITY_EXCEEDED", self.report()["reason_codes"])

    def test_deterministic_output(self):
        self.assertEqual(self.report(), self.report())

    def test_no_private_keys_paths_or_values_in_output(self):
        s = json.dumps(self.report(), sort_keys=True)
        self.assertNotIn("SYNTHETIC-A", s)
        self.assertNotIn("123", s)
        self.assertNotIn(self.temp.name, s)
        self.assertNotIn("2026-10-14", s)
        self.assertNotIn("09:00", s)

    def test_read_only_original_data_remains_unchanged(self):
        old = {n: (self.day / n).read_bytes() for n in q1.HEADERS}
        self.report()
        self.assertEqual(old, {n: (self.day / n).read_bytes() for n in q1.HEADERS})

    def test_no_recursive_or_history_scan(self):
        outside = self.day / "history"
        outside.mkdir()
        (outside / "secret.txt").write_text("private test", encoding="utf8")
        self.assertEqual(self.report()["status"], "CANDIDATE_DIAGNOSTIC_ONLY")

    def test_cli_never_exits_zero_without_pit(self):
        with patch.object(sys, "argv", ["audit", "--day-dir", str(self.day)]):
            with contextlib.redirect_stdout(io.StringIO()) as f:
                exit_code = probe.main()
        self.assertEqual(exit_code, 2)
        self.assertFalse(json.loads(f.getvalue())["pit_research_eligible"])

    def test_empty_signal_file_does_not_turn_into_valid_join(self):
        self.rows["trade_signals.csv"] = []
        self.save()
        x = self.report()
        self.assertEqual(x["status"], "BLOCKED")
        self.assertIn("Q1_NOT_PASSED", x["reason_codes"])


if __name__ == "__main__":
    unittest.main()
