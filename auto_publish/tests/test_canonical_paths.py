"""Cross-platform canonical relative paths (POSIX "/") in evidence, and a golden lock on the
fixture shadow flow so Windows and Linux must produce identical bytes / hashes.

Version boundary: records written from this change on use "/" on every OS. Older Windows
records may contain "\\"; they are immutable evidence and are never rewritten or migrated.
"""
import json
import os
import socket
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import mock

from auto_publish.app.db import connect
from auto_publish.app.dispatch.simulator import run_due
from auto_publish.app.errors import ValidationError
from auto_publish.app.pipeline import rel_posix
from auto_publish.app.shadow import day as shadow
from auto_publish.tests.helpers import GOLDEN_DIR
from auto_publish.tests.test_shadow_day import J, T_FINAL, ShadowCase, TestSubtitlesAndSummary

GOLDEN = GOLDEN_DIR / "shadow_fixture.json"
UPDATE = os.environ.get("AUTO_PUBLISH_UPDATE_GOLDEN") == "1"


class TestRelPosix(unittest.TestCase):
    def test_windows_and_posix_inputs_give_the_same_canonical_path(self):
        w = rel_posix(PureWindowsPath(r"C:\ap\home\artifacts\2026-09-24\st_1\dry_run\tiktok.json"),
                      PureWindowsPath(r"C:\ap\home\artifacts"))
        p = rel_posix(PurePosixPath("/srv/home/artifacts/2026-09-24/st_1/dry_run/tiktok.json"),
                      PurePosixPath("/srv/home/artifacts"))
        self.assertEqual(w, p)
        self.assertEqual(w, "2026-09-24/st_1/dry_run/tiktok.json")
        self.assertNotIn("\\", w)

    def test_non_relative_or_escaping_paths_are_refused(self):
        with self.assertRaises(ValueError):                               # outside the base
            rel_posix(PurePosixPath("/other/x.json"), PurePosixPath("/srv/home/artifacts"))
        with self.assertRaises(ValidationError):
            rel_posix(PurePosixPath("/srv/a/../b.json"), PurePosixPath("/srv"))


class Flow(ShadowCase):
    """Fixture shadow flow over two trading days (monotonic fixed clock, FakeRenderer)."""

    second_session = TestSubtitlesAndSummary.second_session

    def two_days(self):
        self.day(with_proposal=True)
        d1 = shadow.record(self.ctx, "2026-09-24", J(T_FINAL))
        self.second_session()
        d2 = shadow.record(self.ctx, "2026-09-25", J("2026-09-26T08:30:00"))
        return d1, d2


class TestCanonicalEvidencePaths(Flow):
    def test_stored_paths_are_posix_everywhere(self):
        self.two_days()
        c = self.ctx.conn
        paths = [r[0] for r in c.execute("SELECT rel_path FROM artifacts")]
        paths += [r[0] for r in c.execute("SELECT payload_path FROM schedules")]
        for r in c.execute("SELECT detail_json FROM audit_log WHERE to_state='SCHEDULED'"):
            paths += [e["payload_path"] for e in json.loads(r[0])["entries"]]
        for r in c.execute("SELECT trace_json FROM dispatches WHERE status='WOULD_PUBLISH'"):
            paths.append(json.loads(r[0])["payload"]["path"])
        self.assertTrue(paths)
        for p in paths:
            self.assertNotIn("\\", p)
            self.assertFalse(p.startswith("/") or ":" in p, p)                 # no absolute / drive letter
            self.assertTrue(p.startswith(("2026-09-24/", "2026-09-25/")), p)
        home = str(self.ctx.paths.home)
        for table in ("audit_log", "dispatches", "schedules", "shadow_days"):
            for row in c.execute(f"SELECT * FROM {table}"):
                self.assertNotIn(home, json.dumps([str(v) for v in tuple(row)]), table)

    def test_golden_shadow_hashes(self):
        """Same logical input -> same canonical bytes -> same SHA256 on every OS."""
        d1, d2 = self.two_days()
        c = self.ctx.conn
        cal = [json.loads(r[0])["tse_calendar_sha256"] for r in c.execute(
            "SELECT detail_json FROM audit_log WHERE entity_type='session' AND to_state='VALIDATED' ORDER BY seq")]
        got = {"inputs": {"tse_calendar_sha256": sorted(set(cal)),
                          "metrics_import_sha256": [r[0] for r in c.execute(
                              "SELECT sha256 FROM metrics_imports ORDER BY import_id")]}}
        for name, d in (("day1", d1), ("day2", d2)):
            rep = d["report"]
            got[name] = {"observation_as_of_utc": rep["observation_as_of_utc"], "report_sha256": d["report_sha256"],
                         "audit_head_at_as_of": rep["audit"]["head_at_as_of"],
                         "trace_sha256": sorted(x["trace_sha256"] for x in rep["dispatches"] if x["trace_sha256"]),
                         "day_status": rep["day_status"]}
        if UPDATE:
            GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertEqual(got, json.loads(GOLDEN.read_text(encoding="utf-8")))
        again = shadow.record(self.ctx, "2026-09-24", J(T_FINAL))              # idempotent no-op
        self.assertEqual((again["noop"], again["report_sha256"]), (True, d1["report_sha256"]))

    def test_existing_backslash_evidence_is_never_rewritten(self):
        """A record written by an older Windows build keeps its bytes through migrations and every reader."""
        self.two_days()
        c = self.ctx.conn
        legacy = "2026-09-24\\st_legacy\\dry_run\\tiktok.json"
        c.execute("UPDATE schedules SET payload_path=? WHERE platform='tiktok' AND story_id=?", (legacy, self.sid))
        c.execute("UPDATE artifacts SET rel_path=? WHERE name='cover.jpg' AND story_id=?",
                  ("2026-09-24\\st_legacy\\cover.jpg", self.sid))
        c.close()
        self.ctx.conn = connect(self.ctx.paths.db)                             # re-open: all migrations run
        run_due(self.ctx)                                                      # dispatch pass
        shadow.build(self.ctx, "2026-09-24", J(T_FINAL))                       # shadow read
        c = self.ctx.conn
        self.assertEqual(c.execute("SELECT payload_path FROM schedules WHERE platform='tiktok' AND story_id=?",
                                   (self.sid,)).fetchone()[0], legacy)
        self.assertEqual(c.execute("SELECT rel_path FROM artifacts WHERE name='cover.jpg' AND story_id=?",
                                   (self.sid,)).fetchone()[0], "2026-09-24\\st_legacy\\cover.jpg")

    def test_canonical_input_bytes_have_no_cr(self):
        """Hashed inputs are fixed at the byte level (no silent CRLF->LF at hash time)."""
        from auto_publish.app.marketcal.tse import DEFAULT_PATH
        from auto_publish.tests.test_slot_optimizer import series, write_csv
        from datetime import date
        self.assertNotIn(b"\r", DEFAULT_PATH.read_bytes(), "tse_calendar.json was checked out with CRLF")
        p = write_csv(self.root / "lf.csv", series("tiktok", date(2026, 8, 10), 3, "22:00", 1000, "a"))
        self.assertNotIn(b"\r", p.read_bytes())

    def test_offline(self):
        def boom(*a, **k):
            raise AssertionError(f"network access attempted: {a!r}")
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            self.two_days()


if __name__ == "__main__":
    unittest.main()
