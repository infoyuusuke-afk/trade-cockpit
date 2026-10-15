import errno
import hashlib
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from scripts.execution_contract import _HASH_FIELDS
from scripts.ms2_watcher_sidecar_contract import (
    SCHEMA_VERSION,
    SIDECAR_WRITER_DEFAULT_ENABLED,
    audit_private_sidecar,
    audit_sidecar_bytes,
    join_poll_references,
)
from scripts.ms2_offline_observation_writer import (
    SOURCE_DEFAULT,
    WATCHER_INTEGRATION_APPLIED,
    WRITER_DEFAULT_ENABLED,
    build_captured_record,
    exclusive_writer_lock,
    isolated_poll_boundary,
    main,
    producer_trace,
    record_captured_observation,
    watcher_integration_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
PINNED_SHA256 = {
    "scripts/ms2_watcher_sidecar_contract.py": "ffc45ca155d297506ce2f9f8758531e5a721df8f4dfef26c0dc0793b0c4ed80b",
    "ms2_live/Kioxia_RSS_Live_Watcher.ps1": "4babc10249c2ebd603b28dfc20542224ce4b7b646fe16111ff398f76d2f60c1b",
    "ms2_live/Resample_Kioxia_Ticks_15s.ps1": "0e2884a21a3ee325282576a8f57b8500bc38f2e7a34b44b8a8aee634bfa939a1",
    "scripts/execution_contract.py": "4c3e7d87978cdb4b187569cc7c3a8f8054ef2d7e289376a7023013807f7b9fdf",
    "scripts/shadow_fill_model.py": "a3a345b35f56ae190a76baf41e6eae6b75bf4cb2bee8355d7e6291fecf73d04a",
    "scripts/fill_execution_collector_contract.py": "6229f956c0c97bd8b4003af68fc871ca6b9e12e2399b7067242b00d0085feac9",
    "paper_trade_history.json": "6da1968f71d9e54011d3180d934a683ba9829833d1d4e743fbd42b4172f2d554",
}
RELATIVE = "data/private/ms2_sidecar/board.jsonl"
TICK_RELATIVE = "data/private/ms2_sidecar/ticks.jsonl"
GAP_RELATIVE = "data/private/ms2_sidecar/gaps.jsonl"
REPORT_REASONS = {
    "COST_ABSENT",
    "CAPTURE_NOT_AUTHENTICATED",
    "FILL_EVALUATOR_NOT_COUPLED",
    "ECONOMICS_UNKNOWN",
    "ELIGIBLE_OBSERVED_N_ZERO",
}


def _level(number, read_at=None, *, bid=100, ask=101, bid_qty=100, ask_qty=200):
    payload = {
        "Level": number,
        "BidPrice": bid,
        "AskPrice": ask,
        "BidQty": bid_qty,
        "AskQty": ask_qty,
    }
    if read_at is not None:
        payload["read_at"] = read_at
    return payload


def _board(**overrides):
    payload = {
        "symbol": "285A.T",
        "market": "TSE",
        "poll_seq": 3,
        "source": "synthetic-fixture",
        "clock_source": "WINDOWS_LOCAL",
        "levels": [
            _level(1, "2026-10-14T01:00:00.010+09:00", bid_qty=None, ask_qty=None),
            _level(2, "2026-10-14T01:00:00.050+09:00", bid_qty=None, ask_qty=None),
        ],
        "watcher_observed_at": "2026-10-14T01:00:00.000+09:00",
    }
    payload.update(overrides)
    return payload


def _synthetic(**overrides):
    payload = {
        "symbol": "285A.T",
        "market": "TSE",
        "poll_seq": 4,
        "observation_id": "obs-1",
        "source": "synthetic-fixture",
        "clock_source": "WINDOWS_LOCAL",
        "sequence_basis": "EXCHANGE",
        "order_proven": True,
        "exchange_sequence": 9001,
        "event_time": "2026-10-14T01:00:00.000+09:00",
        "event_time_basis": "EXCHANGE_SUPPLIED",
        "watcher_observed_at": "2026-10-14T01:00:00.200+09:00",
        "available_at": "2026-10-14T01:00:00.500+09:00",
        "available_at_basis": "DURABLE_CONSUMER_READ",
        "data_freshness": "OK",
        "freshness_bound_ms": 1000,
        "read_method": "BULK_RANGE",
        "snapshot_atomic": True,
        "bulk_read_evidenced": True,
        "read_started_at": "2026-10-14T01:00:00.200+09:00",
        "read_finished_at": "2026-10-14T01:00:00.200+09:00",
        "levels": [_level(1, "2026-10-14T01:00:00.200+09:00")],
        "gap": {
            "window_size": 10,
            "overlap_with_prev": 3,
            "prev_poll_nonempty": True,
            "new_appended": 2,
        },
        "last_trade_price": 100.5,
        "last_trade_qty": 100,
        "tick_size": 0.5,
    }
    payload.update(overrides)
    return payload


class OfflineObservationWriterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, capture=None, relative=RELATIVE, enabled=True, hooks=None):
        return record_captured_observation(
            self.root, relative, _board() if capture is None else capture, enabled=enabled, hooks=hooks,
        )

    def _path(self, relative=RELATIVE):
        return self.root / relative

    def _rows(self, relative=RELATIVE):
        return [json.loads(line) for line in self._path(relative).read_text(encoding="utf-8").splitlines()]

    def test_default_is_disabled_and_watcher_is_untouched(self):
        self.assertFalse(WRITER_DEFAULT_ENABLED)
        self.assertFalse(SIDECAR_WRITER_DEFAULT_ENABLED)
        self.assertFalse(WATCHER_INTEGRATION_APPLIED)
        sentinel = self.root / "paper_trade_history.json"
        sentinel.write_bytes(b"[]")
        report = record_captured_observation(self.root, RELATIVE, _synthetic(), enabled=False)
        self.assertEqual(report["writer_status"], "DISABLED")
        self.assertEqual(report["contract_status"], "NOT_READ")
        self.assertEqual(report["decision_state"], "DISABLED")
        self.assertEqual(report["close_state"], "DISABLED")
        self.assertEqual(report["transition"], "DISABLED")
        self.assertIn("SIDECAR_DISABLED", report["reasons"])
        self.assertFalse(report["writes_performed"])
        self.assertEqual(report["com_reads_added"], 0)
        self.assertFalse(report["real_submit_allowed"])
        self.assertFalse(report["promotion_eligible"])
        self.assertFalse(report["statistical_edge_confirmed"])
        self.assertFalse(report["closed_eligible"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertFalse((self.root / "data").exists())
        self.assertEqual(sentinel.read_bytes(), b"[]")
        proposal = watcher_integration_proposal()
        self.assertFalse(proposal["applied"])
        self.assertEqual(proposal["com_reads_added"], 0)
        self.assertEqual({item["id"]: item["status"] for item in proposal["windows_acceptance"]}, {
            "W1": "NOT_VERIFIED", "W2": "NOT_VERIFIED", "W3": "NOT_VERIFIED", "W4": "NOT_VERIFIED",
        })
        self.assertEqual(producer_trace()["extra_com_reads_added_by_this_module"], 0)
        self.assertIn("Do not edit Read-BoardDepth", proposal["touch_points"][0])

    def test_cli_default_writes_nothing_and_redacts_prices(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--repo-root", str(self.root)])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["contract_status"], "NOT_READ")
        self.assertNotIn("pit_records", payload)
        self.assertNotIn("bid", payload)
        self.assertFalse((self.root / "data").exists())

    def test_synthetic_projection_stays_unclosed_and_matches_contract(self):
        report = self._write(_synthetic())
        self.assertEqual(report["writer_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(report["contract_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(report["decision_state"], "BLOCKED")
        self.assertEqual(report["close_state"], "NOT_CLOSED")
        self.assertEqual(report["transition"], "APPENDED")
        self.assertIn("WRITER_APPENDED", report["reasons"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertEqual(report["synthetic_n"], 1)
        self.assertEqual(report["pit_evidence_origin"], "SYNTHETIC")
        self.assertIsNone(report["expectancy_yen"])
        self.assertIsNone(report["profit_factor"])
        self.assertIsNone(report["max_drawdown_yen"])
        self.assertIsNone(report["verified_net_pnl_yen"])
        self.assertIsNone(report["remaining_to_10b_yen"])
        self.assertFalse(report["exchange_order_proven"])
        self.assertFalse(report["snapshot_atomic_guaranteed"])
        self.assertNotIn("pit_records", report)
        audited = audit_sidecar_bytes(self._path().read_bytes())
        self.assertEqual(audited["contract_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(set(audited["reasons"]), REPORT_REASONS)
        self.assertEqual(audited["close_state"], "NOT_CLOSED")
        pit = audited["pit_records"][0]
        self.assertEqual(pit["schema_version"], "ms2-pit-observation-0.1")
        self.assertNotEqual(pit["sequence"], pit["poll_seq"])
        if os.name == "posix":
            self.assertEqual(self._path().stat().st_mode & 0o777, 0o600)
        else:
            self.assertTrue(self._path().is_file())
            self.assertFalse(self._path().is_symlink())
        via_contract = audit_private_sidecar(self.root, RELATIVE)
        self.assertEqual(via_contract["contract_status"], "PROJECTABLE_SYNTHETIC")

    def test_writer_readback_clock_is_local_evidence_not_consumer_available_at(self):
        report = self._write(_synthetic())
        self.assertEqual(report["transition"], "APPENDED")
        stamp = datetime.fromisoformat(report["writer_readback_completed_at"])
        self.assertIsNotNone(stamp.utcoffset())
        self.assertEqual(stamp.utcoffset(), timezone.utc.utcoffset(stamp))
        self.assertEqual(report["writer_readback_clock_basis"], "WRITER_LOCAL_UTC_AFTER_READBACK")
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertFalse(report["promotion_eligible"])
        self.assertIsNone(report["verified_net_pnl_yen"])
        self.assertFalse(report["real_submit_allowed"])
        default_report = self._write(enabled=False)
        self.assertNotIn("writer_readback_completed_at", default_report)

    def test_untrusted_available_at_claim_is_not_authenticated_evidence(self):
        # Even a valid local Writer APPENDED receipt plus a caller-asserted
        # DURABLE_CONSUMER_READ clock does not establish trusted provenance.
        report = self._write(_synthetic(
            available_at_basis="DURABLE_CONSUMER_READ",
            source="synthetic-fixture",
        ))
        self.assertEqual(report["transition"], "APPENDED")
        self.assertEqual(report["writer_status"], "PROJECTABLE_SYNTHETIC")
        self.assertFalse(report["promotion_eligible"])
        self.assertFalse(report["statistical_edge_confirmed"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertIsNone(report["verified_net_pnl_yen"])
        audited = audit_sidecar_bytes(self._path().read_bytes())
        self.assertIn("CAPTURE_NOT_AUTHENTICATED", audited["reasons"])
        self.assertEqual(audited["pit_evidence_origin"], "SYNTHETIC")
        self.assertEqual(audited["close_state"], "NOT_CLOSED")
        self.assertEqual(self._rows()[0]["available_at_basis"], "DURABLE_CONSUMER_READ")

    def test_missing_quantity_is_not_zero_and_reason_set_matches_contract(self):
        report = self._write()
        self.assertEqual(report["writer_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(report["decision_state"], "BLOCKED")
        self.assertEqual(report["close_state"], "NOT_CLOSED")
        self.assertEqual(report["synthetic_n"], 0)
        row = self._rows()[0]
        self.assertIsNone(row["top"]["bid_qty"])
        self.assertIsNone(row["top"]["ask_qty"])
        self.assertFalse(row["top"]["bid_qty_known"])
        self.assertFalse(row["top"]["ask_qty_known"])
        self.assertIsNone(row["levels"][0]["ask_qty"])
        self.assertFalse(row["snapshot_atomic"])
        self.assertEqual(row["read_method"], "SEQUENTIAL_CELL")
        self.assertEqual(row["read_skew_ms"], 40)
        self.assertIsNone(row["event_time"])
        self.assertIsNone(row["available_at"])
        self.assertIsNone(row["exchange_sequence"])
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertFalse(row["order_proven"])
        self.assertNotEqual(row["poll_seq"], row["exchange_sequence"])
        self.assertEqual(row["schema_version"], SCHEMA_VERSION)
        self.assertEqual(row["source"], "synthetic-fixture")
        audited = audit_sidecar_bytes(self._path().read_bytes())
        self.assertEqual(set(audited["reasons"]), REPORT_REASONS | {
            "EVENT_TIME_ABSENT",
            "AVAILABLE_AT_ABSENT",
            "EXCHANGE_SEQUENCE_ABSENT",
            "POLL_ORDER_NOT_EXCHANGE_ORDER",
            "FRESHNESS_UNKNOWN",
            "SUSPECTED_GAP_UNKNOWN",
            "SNAPSHOT_NOT_ATOMIC",
            "BOOK_QTY_UNKNOWN",
            "TRADE_PRINT_ABSENT",
            "TICK_SIZE_UNKNOWN",
        })
        self.assertIn("BOOK_QTY_UNKNOWN", report["reasons"])
        self.assertIn("SNAPSHOT_NOT_ATOMIC", report["reasons"])
        explicit_zero = self._write(
            _board(poll_seq=12, levels=[_level(1, bid_qty=None, ask_qty=0)]),
            relative="data/private/ms2_sidecar/zero.jsonl",
        )
        self.assertEqual(explicit_zero["contract_status"], "ADMITTED_INCOMPLETE")
        stored = self._rows("data/private/ms2_sidecar/zero.jsonl")[0]
        self.assertIsNone(stored["top"]["bid_qty"])
        self.assertFalse(stored["top"]["bid_qty_known"])
        self.assertEqual(stored["top"]["ask_qty"], 0)
        self.assertTrue(stored["top"]["ask_qty_known"])

    def test_partial_depth_is_not_padded_and_a_hole_is_not_renumbered(self):
        levels = [_level(number, bid_qty=10, ask_qty=None) for number in range(1, 9)]
        report = self._write(_board(levels=levels, watcher_observed_at=None, clock_source=None))
        self.assertEqual(report["contract_status"], "ADMITTED_INCOMPLETE")
        row = self._rows()[0]
        self.assertEqual(row["depth_claimed"], 8)
        self.assertEqual([item["level"] for item in row["levels"]], list(range(1, 9)))
        self.assertIsNone(row["levels"][0]["ask_qty"])
        self.assertEqual(row["levels"][0]["bid_qty"], 10)
        self.assertNotIn('"ask_qty":0', self._path().read_text(encoding="utf-8"))
        hole = self._write(_board(
            observation_id="hole-1",
            poll_seq=9,
            levels=[_level(1), _level(2), _level(4)],
        ), relative="data/private/ms2_sidecar/hole.jsonl")
        self.assertEqual(hole["writer_status"], "BLOCKED")
        self.assertIn("LEVEL_SEQUENCE_GAP", hole["reasons"])
        self.assertFalse((self.root / "data/private/ms2_sidecar/hole.jsonl").exists())

    def test_invalid_and_naive_clocks_fail_closed_without_a_file(self):
        naive = self._write(_board(watcher_observed_at="2026-10-14 01:00:00"))
        self.assertEqual(naive["writer_status"], "BLOCKED")
        self.assertEqual(naive["close_state"], "NOT_CLOSED")
        self.assertIn("TIMEZONE_UNKNOWN", naive["reasons"])
        named = self._write(_board(watcher_observed_at="2026-10-14T01:00:00 JST"))
        self.assertIn("TIMEZONE_UNKNOWN", named["reasons"])
        tokyo = self._write(_board(timezone="Asia/Tokyo"))
        self.assertIn("TIMEZONE_UNKNOWN", tokyo["reasons"])
        fine = self._write(_board(watcher_observed_at="2026-10-14T01:00:00.000500+09:00"))
        self.assertIn("SUBMILLISECOND_UNRECORDED", fine["reasons"])
        copied = self._write(_board(
            event_time="2026-10-14T01:00:00.000+09:00",
            event_time_basis="EXCHANGE_SUPPLIED",
            watcher_observed_at="2026-10-14T01:00:00.000+09:00",
        ))
        self.assertIn("CLOCKS_NOT_DISTINGUISHED", copied["reasons"])
        unordered = self._write(_board(
            read_started_at="2026-10-14T01:00:00.050+09:00",
            read_finished_at="2026-10-14T01:00:00.010+09:00",
            levels=[_level(1, bid_qty=None, ask_qty=None)],
        ))
        self.assertTrue(
            "TIME_ORDER_CONTRADICTION" in unordered["reasons"] or "SKEW_CONTRADICTION" in unordered["reasons"]
        )
        self.assertFalse(self._path().exists())
        self.assertEqual(naive["transition"], "REFUSED")

    def test_sequential_skew_is_recorded_and_not_called_atomic(self):
        claimed = self._write(_board(snapshot_atomic=True))
        self.assertIn("SNAPSHOT_ATOMIC_CONTRADICTION", claimed["reasons"])
        self.assertFalse(self._path().exists())
        bulk = self._write(_board(read_method="BULK_RANGE", snapshot_atomic=True))
        self.assertIn("BULK_READ_NOT_EVIDENCED", bulk["reasons"])
        written = self._write()
        self.assertEqual(written["contract_status"], "ADMITTED_INCOMPLETE")
        row = self._rows()[0]
        self.assertFalse(row["snapshot_atomic"])
        self.assertEqual(row["read_started_at"], "2026-10-14T01:00:00.010+09:00")
        self.assertEqual(row["read_finished_at"], "2026-10-14T01:00:00.050+09:00")
        self.assertEqual(row["read_skew_ms"], 40)
        self.assertEqual(row["levels"][0]["read_at"], row["read_started_at"])
        self.assertEqual(row["levels"][1]["read_at"], row["read_finished_at"])

    def test_suspected_gap_is_admitted_and_a_contradiction_is_not_written(self):
        gap = {
            "window_size": 300,
            "overlap_with_prev": 0,
            "prev_poll_nonempty": True,
            "new_appended": 20,
        }
        report = self._write(_board(gap=gap))
        self.assertEqual(report["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(report["close_state"], "NOT_CLOSED")
        self.assertIn("GAP_SUSPECTED", report["reasons"])
        self.assertTrue(self._rows()[0]["suspected_gap"])
        self.assertEqual(self._rows()[0]["gap_diag"]["poll_seq"], 3)
        contradicted = self._write(
            _board(poll_seq=8, gap={**gap, "suspected_gap": False}),
            relative="data/private/ms2_sidecar/gap-bad.jsonl",
        )
        self.assertEqual(contradicted["writer_status"], "BLOCKED")
        self.assertIn("GAP_FLAG_CONTRADICTION", contradicted["reasons"])
        self.assertFalse((self.root / "data/private/ms2_sidecar/gap-bad.jsonl").exists())
        self.assertEqual(self._path().read_bytes(), self._path().read_bytes())

    def test_duplicates_conflicts_and_mixed_market_do_not_rewrite(self):
        first = self._write()
        original = self._path().read_bytes()
        replay = self._write()
        self.assertEqual(replay["writer_status"], "IDEMPOTENT")
        self.assertEqual(replay["transition"], "REPLAY")
        self.assertIn("IDEMPOTENT_REPLAY", replay["reasons"])
        self.assertFalse(replay["writes_performed"])
        self.assertEqual(replay["file_sha256"], first["file_sha256"])
        self.assertEqual(self._path().read_bytes(), original)
        conflict = self._write(_board(levels=[
            _level(1, "2026-10-14T01:00:00.010+09:00", bid=110, bid_qty=None, ask_qty=None),
            _level(2, "2026-10-14T01:00:00.050+09:00", bid_qty=None, ask_qty=None),
        ]))
        self.assertIn("DUPLICATE_CONFLICT", conflict["reasons"])
        self.assertIn("EXISTING_FILE_PRESERVED", conflict["reasons"])
        self.assertEqual(self._path().read_bytes(), original)
        other_id = self._write(_board(observation_id="other-poll"))
        self.assertIn("DUPLICATE_POLL", other_id["reasons"])
        self.assertEqual(self._path().read_bytes(), original)
        other_market = self._write(_board(poll_seq=6, market="JNX", symbol="285A.JNX"))
        self.assertEqual(other_market["writer_status"], "BLOCKED")
        self.assertTrue("MIXED_MARKET" in other_market["reasons"] or "NOT_APPENDED" in other_market["reasons"])
        self.assertEqual(self._path().read_bytes(), original)

    def test_bad_paths_corruption_and_legacy_csv_are_preserved(self):
        sentinel = self.root / "paper_trade_history.json"
        sentinel.write_bytes(b"[]")
        escaped = self._write(relative="data/private/ms2_sidecar/../../paper_trade_history.json")
        self.assertIn("PRIVATE_PATH_INVALID", escaped["reasons"])
        absolute = self._write(relative="/tmp/board.jsonl")
        self.assertIn("PRIVATE_PATH_INVALID", absolute["reasons"])
        self.assertEqual(sentinel.read_bytes(), b"[]")
        self.assertFalse(self._path().exists())
        outside = Path(self._tmp.name + "-outside")
        outside.mkdir()
        private = self.root / "data" / "private"
        private.mkdir(parents=True)
        link = private / "ms2_sidecar"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            link = None
        if link is not None:
            linked = self._write()
            self.assertIn("PRIVATE_PATH_LINK", linked["reasons"])
            self.assertEqual(list(outside.iterdir()), [])
            link.unlink()
        sidecar = private / "ms2_sidecar"
        sidecar.mkdir()
        corrupt = sidecar / "board.jsonl"
        corrupt.write_bytes(b"{not-json\n")
        blocked = self._write()
        self.assertIn("DATA_CORRUPT", blocked["reasons"])
        self.assertIn("EXISTING_FILE_PRESERVED", blocked["reasons"])
        self.assertEqual(corrupt.read_bytes(), b"{not-json\n")
        legacy = sidecar / "legacy.jsonl"
        payload = b"recorded_at,tick_time,price,volume,poll_seq\n1,2,3,4,5\n"
        legacy.write_bytes(payload)
        refused = self._write(relative="data/private/ms2_sidecar/legacy.jsonl")
        self.assertIn("LEGACY_TICK_CSV", refused["reasons"])
        self.assertEqual(legacy.read_bytes(), payload)
        outside.rmdir()

    def test_disk_full_write_failure_lock_and_exception_do_not_escape(self):
        first = self._write()
        original = self._path().read_bytes()

        def no_space(_fd, _payload):
            raise OSError(errno.ENOSPC, "No space left")

        full = self._write(_board(poll_seq=4), hooks={"write": no_space})
        self.assertEqual(full["writer_status"], "BLOCKED")
        self.assertEqual(full["close_state"], "NOT_CLOSED")
        self.assertIn("DISK_FULL", full["reasons"])
        self.assertFalse(full["writes_performed"])
        self.assertEqual(self._path().read_bytes(), original)

        def fail_replace(_src, _dst):
            raise OSError(errno.EIO, "replace failed")

        failed = self._write(_board(poll_seq=5), hooks={"replace": fail_replace})
        self.assertIn("WRITE_FAILED", failed["reasons"])
        self.assertEqual(self._path().read_bytes(), original)

        with exclusive_writer_lock(self._path().parent):
            locked = self._write(_board(poll_seq=6))
        self.assertIn("WRITE_LOCKED", locked["reasons"])
        self.assertEqual(locked["lock_wait_s"], 0)
        self.assertLess(locked["elapsed_ms"], 1000)
        self.assertEqual(self._path().read_bytes(), original)

        def explode(*_args, **_kwargs):
            raise RuntimeError("secret-qty-16100")

        isolated = self._write(_board(poll_seq=7), hooks={"write": explode})
        self.assertEqual(isolated["transition"], "ISOLATED")
        self.assertIn("WRITER_EXCEPTION", isolated["reasons"])
        self.assertNotIn("secret-qty-16100", json.dumps(isolated))
        self.assertEqual(self._path().read_bytes(), original)
        self.assertEqual(first["file_sha256"], hashlib.sha256(original).hexdigest())

    def test_zero_fill_watcher_source_and_safety_flags_are_refused(self):
        zeroed = self._write(_board(fill_missing_with_zero=True))
        self.assertIn("QTY_ZERO_FILL_REFUSED", zeroed["reasons"])
        watcher = self._write(_board(source="Kioxia_RSS_Live_Watcher.ps1"))
        self.assertIn("WATCHER_SOURCE_HAS_NO_SIDECAR", watcher["reasons"])
        authed = self._write(_board(capture_authenticated=True))
        self.assertIn("CAPTURE_AUTHENTICATION_REFUSED", authed["reasons"])
        flagged = self._write(_board(real_submit_allowed=True))
        self.assertIn("SAFETY_FLAG_REFUSED", flagged["reasons"])
        reused = self._write(_synthetic(exchange_sequence=4))
        self.assertIn("POLL_SEQ_REUSED_AS_EXCHANGE_SEQUENCE", reused["reasons"])
        claimed = self._write(_board(sequence_basis="POLL", order_proven=True))
        self.assertIn("POLL_ORDER_NOT_EXCHANGE_ORDER", claimed["reasons"])
        ntp = self._write(_board(clock_quality="NTP_ASSERTED"))
        self.assertIn("CLOCK_QUALITY_UNPROVEN", ntp["reasons"])
        self.assertFalse(self._path().exists())

    def test_over_under_is_not_copied_into_top_quantity_and_crossed_book_is_not_swapped(self):
        report = self._write(_board(over_qty=500000, under_qty=12500))
        row = self._rows()[0]
        self.assertEqual(row["over_qty"], 500000)
        self.assertEqual(row["under_qty"], 12500)
        self.assertIsNone(row["top"]["bid_qty"])
        self.assertIsNone(row["top"]["ask_qty"])
        self.assertEqual(row["book_qty_source"], "RSS_LEVEL_QTY")
        crossed = self._write(
            _board(poll_seq=11, levels=[
                _level(1, "2026-10-14T01:00:01.010+09:00", bid=120, ask=110, bid_qty=None, ask_qty=None),
                _level(2, "2026-10-14T01:00:01.050+09:00", bid=119, ask=111, bid_qty=None, ask_qty=None),
            ], watcher_observed_at="2026-10-14T01:00:01.000+09:00"),
            relative="data/private/ms2_sidecar/crossed.jsonl",
        )
        self.assertEqual(crossed["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertIn("BOOK_CROSSED", crossed["reasons"])
        stored = self._rows("data/private/ms2_sidecar/crossed.jsonl")[0]
        self.assertGreater(stored["top"]["bid"], stored["top"]["ask"])

    def test_replay_is_deterministic_and_two_hundred_records_stay_fast(self):
        left = build_captured_record(_board())
        right = build_captured_record(_board())
        self.assertEqual(left, right)
        self.assertTrue(left["ok"])
        captures = [
            _board(poll_seq=poll, watcher_observed_at=None, levels=[_level(1, bid_qty=None, ask_qty=poll)])
            for poll in range(1, 201)
        ]
        started = time.perf_counter()
        built = [build_captured_record(item) for item in captures]
        raw = ("".join(
            json.dumps(item["record"], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for item in built
        )).encode("utf-8")
        audited = audit_sidecar_bytes(raw)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertTrue(all(item["ok"] for item in built))
        self.assertEqual(audited["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(audited["row_count"], 200)
        self.assertEqual(audited["eligible_observed_n"], 0)
        one = time.perf_counter()
        last = self._write(captures[-1])
        one_elapsed = time.perf_counter() - one
        self.assertLess(one_elapsed, 0.25)
        self.assertEqual(last["contract_status"], "ADMITTED_INCOMPLETE")
        again = self._write(captures[-1])
        self.assertEqual(again["writer_status"], "IDEMPOTENT")
        self.assertEqual(again["file_sha256"], last["file_sha256"])
        self.assertEqual(again["file_sha256"], hashlib.sha256(self._path().read_bytes()).hexdigest())

    def test_writer_failure_does_not_stop_the_captured_board_consumer(self):
        seen = []

        def consume(levels):
            seen.append(levels)

        def explode(*_args, **_kwargs):
            raise RuntimeError("disk")

        report = isolated_poll_boundary(
            consume, self.root, RELATIVE, _board(), enabled=True, hooks={"write": explode},
        )
        self.assertTrue(report["board_consumer_ran"])
        self.assertEqual(seen[0][0]["Level"], 1)
        self.assertIn("WRITER_EXCEPTION", report["reasons"])
        self.assertFalse(self._path().exists())

    def test_separate_tick_and_gap_records_join_without_proving_exchange_order(self):
        watcher = "2026-10-14T01:00:00.200+09:00"
        gap = {"window_size": 10, "overlap_with_prev": 3, "prev_poll_nonempty": True, "new_appended": 2}
        board = _board(
            poll_seq=4,
            poll_window_ms=2000,
            watcher_observed_at=watcher,
            levels=[
                _level(1, "2026-10-14T01:00:00.210+09:00", bid_qty=100, ask_qty=200),
                _level(2, "2026-10-14T01:00:00.250+09:00", bid_qty=50, ask_qty=40),
            ],
            gap=gap,
        )
        tick = {
            "kind": "TICK_PRINT",
            "symbol": "285A.T",
            "market": "TSE",
            "poll_seq": 4,
            "source": "synthetic-fixture",
            "clock_source": "WINDOWS_LOCAL",
            "watcher_observed_at": watcher,
            "poll_window_ms": 2000,
            "price": 100.5,
            "volume": 100,
            "gap": gap,
        }
        diag = {
            "kind": "GAP_DIAG",
            "symbol": "285A.T",
            "market": "TSE",
            "poll_seq": 4,
            "source": "synthetic-fixture",
            "clock_source": "WINDOWS_LOCAL",
            "watcher_observed_at": watcher,
            "poll_window_ms": 2000,
            **gap,
        }
        self.assertEqual(self._write(board)["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(self._write(tick, relative=TICK_RELATIVE)["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(self._write(diag, relative=GAP_RELATIVE)["contract_status"], "ADMITTED_INCOMPLETE")
        joined = join_poll_references(self._rows()[0], self._rows(TICK_RELATIVE)[0], self._rows(GAP_RELATIVE)[0])
        self.assertEqual(joined["status"], "POLL_REFERENCE_MATCHED")
        self.assertFalse(joined["exchange_order_proven"])
        self.assertFalse(joined["pit_projectable"])
        self.assertEqual(joined["eligible_observed_n"], 0)
        self.assertIn("POLL_MATCH_IS_NOT_EXCHANGE_ORDER", joined["reasons"])
        naive_tick = dict(tick)
        naive_tick["watcher_observed_at"] = "2026-10-14 01:00:00"
        naive_tick["poll_seq"] = 5
        refused = self._write(naive_tick, relative="data/private/ms2_sidecar/naive.jsonl")
        self.assertIn("TIMEZONE_UNKNOWN", refused["reasons"])

    def test_contract_watcher_history_and_canonical_hash_stay_pinned(self):
        for relative, digest in PINNED_SHA256.items():
            data = (ROOT / relative).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, relative)
            committed = subprocess.check_output(["git", "show", f"HEAD:{relative}"])
            self.assertEqual(data, committed, relative)
        self.assertEqual(_HASH_FIELDS, (
            "symbol", "side", "quantity", "order_type", "limit_price",
            "planned_entry", "planned_stop", "strategy_id", "strategy_version",
            "decision_snapshot_id", "execution_policy_version",
        ))
        history = json.loads((ROOT / "paper_trade_history.json").read_text(encoding="utf-8"))
        self.assertEqual(len(history), 263)
        watcher = (ROOT / "ms2_live/Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8")
        self.assertNotIn("ms2_offline_observation_writer", watcher)
        self.assertNotIn("record_captured_observation", watcher)
        source = (ROOT / "scripts/ms2_offline_observation_writer.py").read_text(encoding="utf-8")
        self.assertNotIn("win32com", source)
        self.assertNotIn("RssOrder", source)
        self.assertNotIn("Excel.Application", source)
        self.assertEqual(SOURCE_DEFAULT, "ms2-offline-observation-writer-0.1")


if __name__ == "__main__":
    unittest.main()
