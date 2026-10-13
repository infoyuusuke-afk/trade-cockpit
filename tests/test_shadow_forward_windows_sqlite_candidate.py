"""Candidate validation only: never promote SQLite readback to durable evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from contextlib import closing
import unittest
from scripts.shadow_forward_windows_sqlite_candidate import append_candidate, inspect_candidate, _db

A="a"*64

class WindowsSQLiteCandidateTests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory()
  self.root=Path(self.temp.name)
 def tearDown(self):
  self.temp.cleanup()

 def test_dual_file_round_trip_readback_is_not_durable_gate(self):
  status=append_candidate(self.root,"paper_1",b"private-data",A)
  self.assertEqual(status,"CANDIDATE_READBACK_ONLY_NOT_PRODUCTION_DURABLE")
  self.assertTrue(_db(self.root,"evidence").exists())
  self.assertTrue(_db(self.root,"anchor").exists())
  self.assertNotEqual(_db(self.root,"evidence"),_db(self.root,"anchor"))
  self.assertEqual(inspect_candidate(self.root,"paper_1",expected_anchor=A),status)

 def test_partial_commit_is_detected_after_restart(self):
  with self.assertRaises(OSError):
   append_candidate(self.root,"paper_2",b"private-data",A,fail_after_evidence=True)
  self.assertEqual(inspect_candidate(self.root,"paper_2",expected_anchor=A),"HOLD_INCOMPLETE_PAIR")
  with self.assertRaises(FileExistsError):
   append_candidate(self.root,"paper_2",b"private-data",A)

 def test_duplicate_is_never_overwritten(self):
  append_candidate(self.root,"paper_3",b"first",A)
  with self.assertRaises(FileExistsError):
   append_candidate(self.root,"paper_3",b"second",A)
  with closing(sqlite3.connect(str(_db(self.root,"evidence")),isolation_level=None)) as conn:
   self.assertEqual(conn.execute("SELECT payload FROM immutable_artifact WHERE id='paper_3'").fetchone()[0],b"first")

 def test_modified_evidence_is_detected(self):
  append_candidate(self.root,"paper_4",b"original",A)
  with closing(sqlite3.connect(str(_db(self.root,"evidence")),isolation_level=None)) as conn:
   conn.execute("UPDATE immutable_artifact SET payload=? WHERE id=?",(b"tampered","paper_4"))
  self.assertEqual(inspect_candidate(self.root,"paper_4",expected_anchor=A),"BLOCK_DIGEST_MISMATCH")

 def test_anchor_mismatch_fails(self):
  append_candidate(self.root,"paper_5",b"data",A)
  self.assertEqual(inspect_candidate(self.root,"paper_5",expected_anchor="b"*64),"BLOCK_ANCHOR_MISMATCH")

 def test_invalid_id_and_anchor_fail_without_write(self):
  for ident in ("../../bad","other/slash","a\\b",""):
   with self.assertRaises(ValueError):
    append_candidate(self.root,ident,b"data",A)
  with self.assertRaises(ValueError):
   append_candidate(self.root,"normal",b"data","bad")
  self.assertFalse((self.root/"data").exists())

 def test_explicit_block_on_missing_anchor(self):
  append_candidate(self.root,"paper_6",b"data",A)
  with closing(sqlite3.connect(str(_db(self.root,"anchor")),isolation_level=None)) as conn:
   conn.execute("DELETE FROM immutable_artifact WHERE id='paper_6'")
  self.assertEqual(inspect_candidate(self.root,"paper_6",expected_anchor=A),"HOLD_INCOMPLETE_PAIR")

 def test_symlink_escape_refused(self):
  outside=Path(self.root)/"outside"
  outside.mkdir()
  private=Path(self.root)/"data"/"private"
  private.mkdir(parents=True)
  try:
   (private/"shadow_forward").symlink_to(outside,target_is_directory=True)
  except (OSError,NotImplementedError):
   self.skipTest("symlink creation not permitted on this runner")
  with self.assertRaises(ValueError):
   append_candidate(self.root,"x",b"data",A)

if __name__=="__main__":
 unittest.main()
