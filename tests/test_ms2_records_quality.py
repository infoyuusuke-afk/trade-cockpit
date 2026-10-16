"""Synthetic-only checks. No MS2/Excel/real CSV access or network."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import ms2_records_quality as audit_mod


def one_row(name):
    d = {key: "" for key in audit_mod.HEADERS[name]}
    d.update(captured_at="2026-10-14 09:01:02", ticker="SYNTHETIC.T", name="SYNTHETIC")
    if "price" in d:
        d["price"] = "100"
    if name == "ticks.csv":
        d.update(exchange_time="09:01:00", direction_estimate="UNKNOWN")
    if name == "market_snapshots.csv":
        d.update(volume="1000", bid="99", ask="101", bid_qty="100", ask_qty="200")
    if name == "trade_signals.csv":
        d.update(signal="BUY_SYNTHETIC", strategy="SYNTHETIC")
    return d


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "2026-10-14"
        self.root.mkdir()
        self.rows = {name: [one_row(name)] for name in audit_mod.HEADERS}
        self.write_all()

    def write(self, name):
        with (self.root / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=audit_mod.HEADERS[name])
            w.writeheader()
            w.writerows(self.rows[name])

    def write_all(self):
        for name in self.rows:
            self.write(name)

    def test_all_good_q1_only_and_not_eligible(self):
        a = audit_mod.audit(self.root)
        self.assertEqual(a["status"], "Q1_PARSED_ONLY")
        self.assertEqual(sum(v["records_parsed"] for v in a["files"].values()), 5)
        self.assertEqual(a["eligible_observed_n"], 0)
        self.assertFalse(a["pit_research_eligible"])
        self.assertFalse(a["real_submit_allowed"])
        self.assertFalse(a["statistical_edge_confirmed"])
        self.assertEqual(a, audit_mod.audit(self.root))
        combined = repr(a)
        self.assertNotIn("SYNTHETIC.T", combined)
        self.assertNotIn(self.tmp.name, combined)

    def test_missing_file_blocks_no_scanning(self):
        (self.root / "trade_signals.csv").unlink()
        a = audit_mod.audit(self.root)
        self.assertEqual(a["files"]["trade_signals.csv"]["reason_counts"], {"MISSING": 1})
        self.assertEqual(a["status"], "BLOCKED")

    def test_wrong_header_blocks(self):
        (self.root / "ticks.csv").write_text("capture,ticker\n1,ABC\n", encoding="utf8")
        a = audit_mod.audit(self.root)
        self.assertIn("HEADER_CONTRACT_MISMATCH", a["files"]["ticks.csv"]["reason_counts"])

    def test_negative_quantity_and_nonfinite(self):
        self.rows["market_snapshots.csv"][0]["volume"] = "-3"
        self.rows["market_snapshots.csv"][0]["ask"] = "NaN"
        self.write_all()
        reasons = audit_mod.audit(self.root)["files"]["market_snapshots.csv"]["reason_counts"]
        self.assertIn("NEGATIVE_QUANTITY_OR_LEVEL", reasons)
        self.assertIn("NONFINITE_OR_INVALID_NUMERIC", reasons)

    def test_date_mismatch(self):
        self.rows["condition_log.csv"][0]["captured_at"] = "2026-10-15 09:01:02"
        self.write_all()
        self.assertIn("CAPTURE_DATE_OR_TIME_INVALID", audit_mod.audit(self.root)["files"]["condition_log.csv"]["reason_counts"])

    def test_clock_reversal_is_per_ticker(self):
        a = one_row("market_snapshots.csv")
        b = dict(a, captured_at="2026-10-14 09:00:02")
        self.rows["market_snapshots.csv"] = [a, b]
        self.write_all()
        reasons = audit_mod.audit(self.root)["files"]["market_snapshots.csv"]["reason_counts"]
        self.assertEqual(reasons.get("TICKER_LOCAL_CLOCK_REVERSE"), 1)

    def test_repeated_tick_is_ambiguity_not_duplicate(self):
        a = one_row("ticks.csv")
        self.rows["ticks.csv"] = [a, dict(a)]
        self.write_all()
        t = audit_mod.audit(self.root)["files"]["ticks.csv"]
        self.assertEqual(t["status"], "Q1_PARSED_ONLY")
        self.assertEqual(t["records_parsed"], 2)
        self.assertEqual(t["same_tick_key_ambiguous"], 1)

    def test_bad_exchange_time(self):
        self.rows["ticks.csv"][0]["exchange_time"] = "not a clock"
        self.write_all()
        self.assertIn("EXCHANGE_TIME_FORMAT_INVALID", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_invalid_encoding(self):
        with (self.root / "ticks.csv").open("ab") as f:
            f.write(b"\xff\xff")
        self.assertIn("CSV_OR_ENCODING_INVALID", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_bad_row_shape(self):
        with (self.root / "ticks.csv").open("a", encoding="utf8") as f:
            f.write("too,few\n")
        self.assertIn("ROW_SHAPE_INVALID", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_quoted_newline_is_one_record(self):
        self.rows["ticks.csv"][0]["note"] = "SYNTHETIC\nmultiline"
        self.write_all()
        self.assertEqual(audit_mod.audit(self.root)["files"]["ticks.csv"]["records_parsed"], 1)

    def test_symlink_file_refused(self):
        path = self.root / "ticks.csv"
        other = Path(self.tmp.name) / "outside.csv"
        path.replace(other)
        try:
            path.symlink_to(other)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink disabled")
        self.assertIn("LINK_REFUSED", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_bad_dir_name(self):
        bad = Path(self.tmp.name) / "random"
        bad.mkdir()
        self.assertEqual(audit_mod.audit(bad)["block_reason"], "DAY_DIRECTORY_NAME_INVALID")

    def test_empty_data_rows(self):
        self.rows["ticks.csv"] = []
        self.write_all()
        self.assertIn("NO_DATA_ROWS", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_too_large_is_blocked(self):
        with patch.object(audit_mod, "MAX_FILE_BYTES", 1):
            self.assertIn("FILE_TOO_LARGE", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_row_limit_is_blocked(self):
        self.rows["ticks.csv"].append(one_row("ticks.csv"))
        self.write_all()
        with patch.object(audit_mod, "MAX_ROWS", 1):
            self.assertIn("ROW_LIMIT_EXCEEDED", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_file_change_fails_closed(self):
        real_stat = audit_mod._stat_key
        calls = [0]
        def change_key(stat):
            calls[0] += 1
            value = real_stat(stat)
            if calls[0] == 3:
                return tuple(x + 1 for x in value)
            return value
        with patch.object(audit_mod, "_stat_key", side_effect=change_key):
            self.assertIn("FILE_CHANGED_DURING_READ", audit_mod.audit(self.root)["files"]["ticks.csv"]["reason_counts"])

    def test_path_and_open_descriptor_must_refer_to_same_file(self):
        # A different opened file with matching size and mtime is not the path.
        target = self.root / "ticks.csv"
        decoy = Path(self.tmp.name) / "synthetic_decoy.csv"
        decoy.write_bytes(target.read_bytes())
        before = target.stat()
        os.utime(decoy, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(before.st_size, decoy.stat().st_size)
        self.assertEqual(before.st_mtime_ns, decoy.stat().st_mtime_ns)
        if audit_mod._stat_key(before) == audit_mod._stat_key(decoy.stat()):
            self.skipTest("Filesystem cannot distinguish separate file identities")
        real_open = Path.open

        def redirect_open(path, *args, **kwargs):
            if path == target:
                return real_open(decoy, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=redirect_open):
            result = audit_mod.audit(self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("FILE_CHANGED_DURING_READ", result["files"]["ticks.csv"]["reason_counts"])
        self.assertFalse(result["source_authenticated"])
        self.assertFalse(result["pit_research_eligible"])
        self.assertFalse(result["real_submit_allowed"])

    def test_windows_cross_api_timestamp_difference_is_not_mutation(self):
        # Windows stat(path) and fstat(handle) can express the same file
        # timestamps differently. Both views must be stable internally.
        original = audit_mod._stat_key
        calls = [0]

        def simulated_windows_view(stat):
            calls[0] += 1
            key = original(stat)
            if calls[0] <= 2:  # descriptor before/after
                return key[:3] + (key[3] + 1_000_000, key[4] + 1_000_000)
            return key  # pathname before/after

        with patch.object(audit_mod, "_stat_key", side_effect=simulated_windows_view):
            report = audit_mod._audit_file(self.root, "ticks.csv", "2026-10-14")
        self.assertEqual(calls[0], 4)
        self.assertEqual(report["status"], "Q1_PARSED_ONLY")
        self.assertEqual(report["reason_counts"], {})
        self.assertFalse(report["source_authenticated"])

    def test_descriptor_timestamp_change_remains_fail_closed(self):
        # An actual within-descriptor mutation must not be hidden by
        # permitting cross-API timestamp representation differences.
        original = audit_mod._stat_key
        calls = [0]

        def changed_descriptor_view(stat):
            calls[0] += 1
            key = original(stat)
            if calls[0] == 2:  # descriptor after read
                return key[:3] + (key[3] + 1, key[4])
            return key

        with patch.object(audit_mod, "_stat_key", side_effect=changed_descriptor_view):
            report = audit_mod._audit_file(self.root, "ticks.csv", "2026-10-14")
        self.assertEqual(calls[0], 4)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("FILE_CHANGED_DURING_READ", report["reason_counts"])
        self.assertFalse(report["pit_eligible"])

    def test_no_broker_or_account_fields_in_output(self):
        text = repr(audit_mod.audit(self.root))
        self.assertNotIn("account", text)
        self.assertNotIn("password", text)


if __name__ == "__main__":
    unittest.main()
