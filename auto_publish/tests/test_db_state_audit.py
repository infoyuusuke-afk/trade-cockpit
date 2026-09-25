import sqlite3
import tempfile
import unittest
from pathlib import Path

from auto_publish.app import audit
from auto_publish.app.clock import FixedClock, parse_aware
from auto_publish.app.db import connect, migrate
from auto_publish.app.errors import InvalidTransitionError, StateConflictError
from auto_publish.app.state_machine import STORY_TRANSITIONS, StoryState as S, can_transition, transition_story

CLOCK = FixedClock(parse_aware("2026-09-24T17:00:00+09:00"))


def _insert_story(conn, sid="st_x", state=S.SELECTED):
    conn.execute("INSERT INTO sessions(session_date, input_dir, state, created_at, updated_at)"
                 " VALUES ('2026-09-24','x','VALIDATED','t','t')")
    conn.execute("INSERT INTO stories(story_id, session_date, topic, state, score, score_breakdown_json, plan_json,"
                 " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (sid, "2026-09-24", "T", state.value, 0.5, "{}", "{}", "t", "t"))


class TestSchemaAndStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_migrations_are_idempotent(self):
        self.assertEqual(migrate(self.conn), [])
        versions = [r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")]
        self.assertEqual(versions, ["001_init"])

    def test_no_publish_state_exists_in_r1(self):
        names = {s.value for s in S}
        self.assertFalse(any("PUBLISH" in n for n in names), names)
        self.assertEqual(STORY_TRANSITIONS[S.SCHEDULED], {S.CANCELLED})

    def test_every_stage_transition_is_explicit(self):
        chain = [S.SELECTED, S.FACT_CHECKED, S.SCRIPTED, S.LOCALIZED, S.RENDERED, S.AWAITING_APPROVAL, S.APPROVED,
                 S.SCHEDULED]
        for a, b in zip(chain, chain[1:]):
            self.assertTrue(can_transition(a, b), (a, b))
        # stages cannot be skipped
        self.assertFalse(can_transition(S.RENDERED, S.APPROVED))
        self.assertFalse(can_transition(S.AWAITING_APPROVAL, S.SCHEDULED))
        self.assertFalse(can_transition(S.SELECTED, S.SCHEDULED))
        for st in chain[:-1]:
            self.assertTrue(can_transition(st, S.FAILED), st)

    def test_illegal_transition_rejected_and_state_unchanged(self):
        _insert_story(self.conn)
        with self.assertRaises(InvalidTransitionError):
            transition_story(self.conn, CLOCK, "st_x", S.SELECTED, S.APPROVED, actor="t")
        self.assertEqual(self.conn.execute("SELECT state FROM stories").fetchone()[0], "SELECTED")

    def test_compare_and_set_detects_stale_state(self):
        _insert_story(self.conn)
        transition_story(self.conn, CLOCK, "st_x", S.SELECTED, S.FACT_CHECKED, actor="t")
        with self.assertRaises(StateConflictError):
            transition_story(self.conn, CLOCK, "st_x", S.SELECTED, S.FACT_CHECKED, actor="t")
        row = self.conn.execute("SELECT state, version FROM stories").fetchone()
        self.assertEqual((row[0], row[1]), ("FACT_CHECKED", 1))

    def test_transition_writes_audit_row_atomically(self):
        _insert_story(self.conn)
        transition_story(self.conn, CLOCK, "st_x", S.SELECTED, S.FACT_CHECKED, actor="alice", reason="r")
        row = self.conn.execute("SELECT * FROM audit_log").fetchone()
        self.assertEqual((row["actor"], row["from_state"], row["to_state"]), ("alice", "SELECTED", "FACT_CHECKED"))

    def test_audit_log_is_append_only(self):
        audit.append(self.conn, CLOCK, actor="a", entity_type="x", entity_id="1", action="t")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE audit_log SET actor = 'evil'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM audit_log")

    def test_audit_chain_detects_tampering(self):
        for i in range(3):
            audit.append(self.conn, CLOCK, actor="a", entity_type="x", entity_id=str(i), action="t")
        self.assertTrue(audit.verify_chain(self.conn)["ok"])
        self.conn.execute("DROP TRIGGER audit_log_no_update")  # simulate an attacker with raw DB access
        self.conn.execute("UPDATE audit_log SET actor = 'evil' WHERE seq = 2")
        res = audit.verify_chain(self.conn)
        self.assertFalse(res["ok"])
        self.assertEqual(res["broken_at_seq"], 2)


if __name__ == "__main__":
    unittest.main()
