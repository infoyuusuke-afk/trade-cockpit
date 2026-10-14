"""Synthetic durability checks for the private MS2 JSONL writer.

These run on Linux and Windows. They do not open Excel, connect a watcher,
or treat a GitHub runner as the owner PC. Power loss is not claimed.
"""
import ast
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from scripts.ms2_bridge_record import pack_capture
from scripts.ms2_offline_observation_writer import (
    exclusive_writer_lock,
    persist_bridge_record,
    record_captured_observation,
)
from scripts.ms2_watcher_sidecar_contract import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "data/private/ms2_sidecar/board.jsonl"
CONTRACT_SHA = "ffc45ca155d297506ce2f9f8758531e5a721df8f4dfef26c0dc0793b0c4ed80b"
HISTORY_SHA = "6da1968f71d9e54011d3180d934a683ba9829833d1d4e743fbd42b4172f2d554"
WATCHER_SHA = "4babc10249c2ebd603b28dfc20542224ce4b7b646fe16111ff398f76d2f60c1b"
EXECUTION_SHA = "4c3e7d87978cdb4b187569cc7c3a8f8054ef2d7e289376a7023013807f7b9fdf"


def _level(number, read_at=None, *, bid=100, ask=101, bid_qty=None, ask_qty=None):
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
            _level(1, "2026-10-14T01:00:00.010+09:00"),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ],
        "watcher_observed_at": "2026-10-14T01:00:00.000+09:00",
    }
    payload.update(overrides)
    return payload


class WindowsDurableWriterTests(unittest.TestCase):
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

    def test_01_normal_write_reread_keeps_poll_evidence(self):
        report = self._write()
        self.assertEqual(report["writer_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(report["transition"], "APPENDED")
        self.assertEqual(report["close_state"], "NOT_CLOSED")
        self.assertFalse(report["closed_eligible"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertEqual(report["power_loss_durability"], "NOT_VERIFIED")
        self.assertEqual(report["crash_consistency"], "PUBLISHED_BYTES_STABLE_UNTIL_REPLACE")
        self.assertEqual(report["lock_wait_s"], 0)
        self.assertFalse(report["real_submit_allowed"])
        row = self._rows()[0]
        self.assertEqual(row["schema_version"], SCHEMA_VERSION)
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertFalse(row["snapshot_atomic"])
        self.assertIsNone(row["event_time"])
        self.assertIsNone(row["available_at"])
        self.assertIsNone(row["top"]["bid_qty"])
        self.assertIsNone(row["top"]["ask_qty"])
        self.assertFalse(row["order_proven"])
        again = self._path().read_bytes()
        self.assertEqual(self._path().read_bytes(), again)
        if os.name == "nt":
            self.assertEqual(report["lock_backend"], "windows-lockfileex")
            self.assertEqual(report["directory_fsync"], "WINDOWS_NOT_SUPPORTED")
        else:
            self.assertEqual(report["lock_backend"], "posix-flock")
            self.assertEqual(report["directory_fsync"], "POSIX_FSYNC")

    def test_02_second_process_is_refused_without_waiting(self):
        self._write()
        original = self._path().read_bytes()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        script = (
            "import sys\n"
            "from pathlib import Path\n"
            "from scripts.ms2_offline_observation_writer import exclusive_writer_lock\n"
            "with exclusive_writer_lock(Path(sys.argv[1])):\n"
            "    print('HELD', flush=True)\n"
            "    sys.stdin.readline()\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script, str(self._path().parent)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(ROOT), env=env,
        )
        box = {}

        def _read():
            box["line"] = proc.stdout.readline()

        thread = threading.Thread(target=_read)
        thread.start()
        try:
            thread.join(5)
            if thread.is_alive():
                proc.kill()
                self.fail(proc.stderr.read())
            self.assertEqual(box["line"].strip(), "HELD")
            started = time.perf_counter()
            locked = self._write(_board(poll_seq=6))
            elapsed = time.perf_counter() - started
            proc.stdin.write("\n")
            proc.stdin.flush()
            proc.wait(timeout=5)
        finally:
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(locked["writer_status"], "BLOCKED")
        self.assertEqual(locked["transition"], "REFUSED")
        self.assertIn("WRITE_LOCKED", locked["reasons"])
        self.assertEqual(locked["lock_wait_s"], 0)
        self.assertFalse(locked["writes_performed"])
        self.assertEqual(self._path().read_bytes(), original)

    def test_03_in_process_lock_contention_preserves_bytes(self):
        self._write()
        original = self._path().read_bytes()
        with exclusive_writer_lock(self._path().parent):
            locked = self._write(_board(poll_seq=7))
        self.assertIn("WRITE_LOCKED", locked["reasons"])
        self.assertEqual(self._path().read_bytes(), original)

    def test_04_permission_denied_preserves_bytes(self):
        first = self._write()
        original = self._path().read_bytes()

        def deny(*_args, **_kwargs):
            raise PermissionError(errno.EACCES, "denied")

        injected = self._write(_board(poll_seq=8), hooks={"open": deny})
        self.assertEqual(injected["writer_status"], "BLOCKED")
        self.assertIn("WRITE_FAILED", injected["reasons"])
        self.assertEqual(self._path().read_bytes(), original)
        self.assertEqual(first["file_sha256"], hashlib.sha256(original).hexdigest())

        sidecar = self._path().parent
        other = "data/private/ms2_sidecar/other.jsonl"
        if os.name == "posix":
            sidecar.chmod(0o500)
            try:
                refused = self._write(_board(poll_seq=9), relative=other)
            finally:
                sidecar.chmod(0o700)
            self.assertIn("WRITE_FAILED", refused["reasons"])
            self.assertFalse((sidecar / "other.jsonl").exists())
            self.assertEqual(self._path().read_bytes(), original)
        else:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
            # Replacing this user's grant leaves group grants (e.g. Administrators)
            # effective. An explicit write deny exercises real Windows ACL refusal.
            grant = subprocess.run(
                ["icacls", str(sidecar), "/deny", f"{user}:(OI)(CI)(W)"],
                capture_output=True, text=True,
            )
            try:
                self.assertEqual(grant.returncode, 0, grant.stderr)
                refused = self._write(_board(poll_seq=9), relative=other)
            finally:
                restored = subprocess.run(
                    ["icacls", str(sidecar), "/remove:d", user],
                    capture_output=True, text=True,
                )
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertIn("WRITE_FAILED", refused["reasons"])
            self.assertFalse((sidecar / "other.jsonl").exists())
            self.assertEqual(self._path().read_bytes(), original)

    def test_05_injected_disk_full_does_not_truncate(self):
        self._write()
        original = self._path().read_bytes()

        def no_space(_fd, _payload):
            raise OSError(errno.ENOSPC, "No space left")

        full = self._write(_board(poll_seq=4), hooks={"write": no_space})
        self.assertIn("DISK_FULL", full["reasons"])
        self.assertEqual(full["close_state"], "NOT_CLOSED")
        self.assertFalse(full["writes_performed"])
        self.assertEqual(self._path().read_bytes(), original)
        self.assertEqual(full["power_loss_durability"], "NOT_VERIFIED")

    def test_06_replace_failure_keeps_the_published_file(self):
        self._write()
        original = self._path().read_bytes()

        def fail_replace(_src, _dst):
            raise OSError(errno.EIO, "replace failed")

        failed = self._write(_board(poll_seq=5), hooks={"replace": fail_replace})
        self.assertIn("REPLACE_FAILED", failed["reasons"])
        self.assertIn("WRITE_FAILED", failed["reasons"])
        self.assertEqual(failed["transition"], "REFUSED")
        self.assertEqual(self._path().read_bytes(), original)

    def test_07_and_08_crash_temp_is_quarantined_not_merged(self):
        self._write()
        original = self._path().read_bytes()
        poison = b"PARTIAL-SECRET-999\n"
        leftover = self._path().parent / f".{self._path().name}.dead.tmp"
        leftover.write_bytes(poison)
        restarted = self._write(_board(poll_seq=10))
        published = self._path().read_bytes()
        self.assertTrue(published.startswith(original))
        self.assertNotIn(poison, published)
        self.assertFalse(leftover.exists())
        names = [item["transition"] for item in restarted["recovery_transitions"]]
        self.assertIn("QUARANTINED_PARTIAL", names)
        self.assertTrue(all(item["repaired"] is False for item in restarted["recovery_transitions"]))
        quarantine = self._path().parent / f".{self._path().name}.quarantine"
        moved = list(quarantine.iterdir())
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].read_bytes(), poison)
        journal = self._path().parent / f".{self._path().name}.recovery.jsonl"
        text = journal.read_text(encoding="utf-8")
        self.assertNotIn("PARTIAL-SECRET-999", text)
        self.assertNotIn("12345.5", text)
        self.assertIn("QUARANTINED_PARTIAL", text)
        self.assertIn('"repaired":false', text)

    def test_09_corrupt_jsonl_is_preserved_and_not_repaired(self):
        sidecar = self.root / "data" / "private" / "ms2_sidecar"
        sidecar.mkdir(parents=True)
        corrupt = sidecar / "board.jsonl"
        payload = b"{not-json\n"
        corrupt.write_bytes(payload)
        blocked = self._write()
        self.assertEqual(blocked["writer_status"], "BLOCKED")
        self.assertEqual(blocked["close_state"], "NOT_CLOSED")
        self.assertIn("DATA_CORRUPT", blocked["reasons"])
        self.assertIn("EXISTING_FILE_PRESERVED", blocked["reasons"])
        self.assertEqual(corrupt.read_bytes(), payload)
        self.assertTrue(any(
            item["transition"] == "CORRUPT_PRESERVED" and item["repaired"] is False
            for item in blocked["recovery_transitions"]
        ))

    def test_10_restart_after_crash_does_not_overwrite_published_bytes(self):
        self._write()
        original = self._path().read_bytes()
        leftover = self._path().parent / f".{self._path().name}.mid.tmp"
        leftover.write_bytes(b"{\"bid\":12345.5}\n")
        replay = self._write()
        self.assertEqual(replay["writer_status"], "IDEMPOTENT")
        self.assertEqual(replay["transition"], "REPLAY")
        self.assertFalse(replay["writes_performed"])
        self.assertEqual(self._path().read_bytes(), original)
        self.assertFalse(leftover.exists())
        self.assertIn("QUARANTINED_PARTIAL", [item["transition"] for item in replay["recovery_transitions"]])

    def test_11_duplicate_event_does_not_append(self):
        self._write()
        original = self._path().read_bytes()
        replay = self._write()
        self.assertEqual(replay["transition"], "REPLAY")
        conflict = self._write(_board(levels=[
            _level(1, "2026-10-14T01:00:00.010+09:00", bid=110),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ]))
        self.assertIn("DUPLICATE_CONFLICT", conflict["reasons"])
        self.assertEqual(conflict["close_state"], "NOT_CLOSED")
        self.assertEqual(self._path().read_bytes(), original)

    def test_12_invalid_clock_is_not_closed_and_not_written(self):
        naive = self._write(_board(watcher_observed_at="2026-10-14 01:00:00"))
        self.assertEqual(naive["writer_status"], "BLOCKED")
        self.assertEqual(naive["close_state"], "NOT_CLOSED")
        self.assertEqual(naive["transition"], "REFUSED")
        self.assertIn("TIMEZONE_UNKNOWN", naive["reasons"])
        self.assertFalse(naive["closed_eligible"])
        self.assertFalse(self._path().exists())

    def test_13_invalid_quantity_is_refused(self):
        negative = self._write(_board(levels=[
            _level(1, "2026-10-14T01:00:00.010+09:00", bid_qty=-1),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ]))
        self.assertEqual(negative["writer_status"], "BLOCKED")
        self.assertEqual(negative["close_state"], "NOT_CLOSED")
        self.assertIn("BOOK_QTY_NEGATIVE_REFUSED", negative["reasons"])
        text = self._write(_board(levels=[
            _level(1, "2026-10-14T01:00:00.010+09:00", ask_qty="many"),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ]))
        self.assertEqual(text["close_state"], "NOT_CLOSED")
        self.assertTrue(
            "BOOK_VALUE_TYPE_INVALID" in text["reasons"] or "QTY_INVALID" in text["reasons"]
        )
        self.assertFalse(self._path().exists())

    def test_14_stale_and_gap_stay_unclosed(self):
        stale = self._write(_board(data_freshness="STALE"))
        self.assertEqual(stale["close_state"], "NOT_CLOSED")
        self.assertFalse(stale["closed_eligible"])
        self.assertIn("FRESHNESS_STALE", stale["reasons"])
        self.assertNotEqual(stale["close_state"], "CLOSED")
        gap = {
            "window_size": 300,
            "overlap_with_prev": 0,
            "prev_poll_nonempty": True,
            "new_appended": 20,
        }
        suspected = self._write(_board(poll_seq=4, gap=gap), relative="data/private/ms2_sidecar/gap.jsonl")
        self.assertEqual(suspected["close_state"], "NOT_CLOSED")
        self.assertIn("GAP_SUSPECTED", suspected["reasons"])
        contradicted = self._write(
            _board(poll_seq=5, gap={**gap, "suspected_gap": False}),
            relative="data/private/ms2_sidecar/gap-bad.jsonl",
        )
        self.assertEqual(contradicted["writer_status"], "BLOCKED")
        self.assertEqual(contradicted["close_state"], "NOT_CLOSED")
        self.assertIn("GAP_FLAG_CONTRADICTION", contradicted["reasons"])
        self.assertFalse((self.root / "data/private/ms2_sidecar/gap-bad.jsonl").exists())

    def test_15_windows_open_handle_cannot_replace_published_bytes(self):
        self._write()
        original = self._path().read_bytes()
        if os.name != "nt":
            held = os.open(self._path(), os.O_RDONLY)
            try:
                appended = self._write(_board(poll_seq=8))
            finally:
                os.close(held)
            self.assertEqual(appended["writer_status"], "ADMITTED_INCOMPLETE")
            self.assertTrue(self._path().read_bytes().startswith(original))
            self.assertNotEqual(self._path().read_bytes(), original)
            return
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(self._path()), 0x80000000, 0x00000001, None, 3, 0, None)
        invalid = ctypes.c_void_p(-1).value
        self.assertIsNotNone(handle)
        self.assertNotEqual(handle, invalid)
        try:
            denied = self._write(_board(poll_seq=8))
        finally:
            kernel.CloseHandle(handle)
        self.assertIn("WINDOWS_SHARING_VIOLATION", denied["reasons"])
        self.assertIn("REPLACE_FAILED", denied["reasons"])
        self.assertEqual(denied["close_state"], "NOT_CLOSED")
        self.assertEqual(self._path().read_bytes(), original)

    def test_16_path_escape_symlink_and_reparse_are_refused(self):
        escaped = self._write(relative="data/private/ms2_sidecar/../../paper_trade_history.json")
        self.assertIn("PRIVATE_PATH_INVALID", escaped["reasons"])
        absolute = self._write(relative="/tmp/board.jsonl")
        self.assertIn("PRIVATE_PATH_INVALID", absolute["reasons"])
        outside = Path(self._tmp.name + "-outside")
        outside.mkdir()
        private = self.root / "data" / "private"
        private.mkdir(parents=True)
        link = private / "ms2_sidecar"
        created = False
        try:
            link.symlink_to(outside, target_is_directory=True)
            created = True
        except OSError:
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                    capture_output=True, text=True,
                )
                created = result.returncode == 0
            else:
                raise
        self.assertTrue(created)
        linked = self._write()
        self.assertIn("PRIVATE_PATH_LINK", linked["reasons"])
        self.assertEqual(list(outside.iterdir()), [])
        if os.name == "nt" and not link.is_symlink():
            self.assertTrue(bool(os.lstat(link).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT))
        if link.is_symlink() or (os.name == "nt" and getattr(link, "is_junction", lambda: False)()):
            link.unlink()
        elif os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(link)], check=True)
        outside.rmdir()

    def test_17_same_input_is_byte_identical(self):
        left = self._write(relative="data/private/ms2_sidecar/left.jsonl")
        right = self._write(relative="data/private/ms2_sidecar/right.jsonl")
        self.assertEqual(left["file_sha256"], right["file_sha256"])
        self.assertEqual(
            (self.root / "data/private/ms2_sidecar/left.jsonl").read_bytes(),
            (self.root / "data/private/ms2_sidecar/right.jsonl").read_bytes(),
        )

    def test_18_history_263_is_unchanged(self):
        history_path = ROOT / "paper_trade_history.json"
        blob = history_path.read_bytes()
        self.assertEqual(hashlib.sha256(blob).hexdigest(), HISTORY_SHA)
        self.assertEqual(len(json.loads(blob.decode("utf-8"))), 263)
        committed = subprocess.check_output(["git", "show", f"HEAD:{history_path.relative_to(ROOT)}"])
        self.assertEqual(blob, committed)

    def test_19_canonical_contract_hash_is_unchanged(self):
        contract = ROOT / "scripts/ms2_watcher_sidecar_contract.py"
        execution = ROOT / "scripts/execution_contract.py"
        watcher = ROOT / "ms2_live/Kioxia_RSS_Live_Watcher.ps1"
        self.assertEqual(hashlib.sha256(contract.read_bytes()).hexdigest(), CONTRACT_SHA)
        self.assertEqual(hashlib.sha256(execution.read_bytes()).hexdigest(), EXECUTION_SHA)
        self.assertEqual(hashlib.sha256(watcher.read_bytes()).hexdigest(), WATCHER_SHA)
        for relative in (
            "scripts/ms2_watcher_sidecar_contract.py",
            "scripts/execution_contract.py",
            "ms2_live/Kioxia_RSS_Live_Watcher.ps1",
        ):
            self.assertEqual((ROOT / relative).read_bytes(), subprocess.check_output(["git", "show", f"HEAD:{relative}"]))

    def test_20_no_order_path_and_bridge_record_stays_offline(self):
        source = (ROOT / "scripts/ms2_offline_observation_writer.py").read_text(encoding="utf-8")
        self.assertNotIn("RssOrder", source)
        self.assertNotIn("win32com", source)
        self.assertNotIn("Excel.Application", source)
        tree = ast.parse(source)
        module_imports = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                module_imports.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                module_imports.append(node.module)
        self.assertNotIn("fcntl", module_imports)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        probe = subprocess.check_output(
            [sys.executable, "-c", "import sys; import scripts.ms2_offline_observation_writer; print('fcntl' in sys.modules)"],
            cwd=str(ROOT), env=env, text=True,
        )
        self.assertEqual(probe.strip(), "False")
        watcher = (ROOT / "ms2_live/Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8")
        self.assertNotIn("record_captured_observation", watcher)
        self.assertNotIn("persist_bridge_record", watcher)
        packed = pack_capture(_board())
        self.assertTrue(packed["ok"])
        disabled = persist_bridge_record(self.root, RELATIVE, packed["record"], enabled=False)
        self.assertEqual(disabled["writer_status"], "DISABLED")
        self.assertFalse((self.root / "data").exists())
        stored = persist_bridge_record(self.root, RELATIVE, packed["record"], enabled=True)
        self.assertEqual(stored["writer_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(stored["close_state"], "NOT_CLOSED")
        self.assertEqual(stored["bridge_format"], "NBH1-2048")
        self.assertFalse(stored["watcher_io"])
        self.assertEqual(stored["handoff_worker"], "NOT_STARTED")
        self.assertEqual(stored["live_watcher_connection"], "P0_BLOCKED")
        self.assertEqual(stored["eligible_observed_n"], 0)
        self.assertFalse(stored["real_submit_allowed"])
        self.assertFalse(stored["promotion_eligible"])
        self.assertFalse(stored["statistical_edge_confirmed"])
        row = self._rows()[0]
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertFalse(row["snapshot_atomic"])
        self.assertIsNone(row["available_at"])
        self.assertIsNone(row["event_time"])
        refused = persist_bridge_record(self.root, RELATIVE, b"x" * 10, enabled=True)
        self.assertIn("BRIDGE_RECORD_REFUSED", refused["reasons"])
        self.assertEqual(refused["close_state"], "NOT_CLOSED")


if __name__ == "__main__":
    unittest.main()
