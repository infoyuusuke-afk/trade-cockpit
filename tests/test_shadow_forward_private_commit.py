import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import shadow_forward_private_commit as commit


class PrivateCommitTests(unittest.TestCase):
    def root(self, td):
        root = Path(td)
        (root / "data/private/shadow_forward").mkdir(parents=True)
        return root

    def test_new_artifact_commits(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            p = commit.commit_new_private_artifact(
                root, "data/private/shadow_forward/a.bin", b"evidence")
            self.assertEqual(p.read_bytes(), b"evidence")
            self.assertFalse(p.with_name("a.bin.pending").exists())

    def test_existing_final_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            p = root / "data/private/shadow_forward/a.bin"
            p.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                commit.commit_new_private_artifact(
                    root, "data/private/shadow_forward/a.bin", b"replacement")
            self.assertEqual(p.read_bytes(), b"original")

    def test_existing_pending_blocks_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            pending = root / "data/private/shadow_forward/a.bin.pending"
            pending.write_bytes(b"uncertain")
            with self.assertRaises(FileExistsError):
                commit.commit_new_private_artifact(
                    root, "data/private/shadow_forward/a.bin", b"new")
            self.assertEqual(pending.read_bytes(), b"uncertain")

    def test_pending_is_never_committed_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.pending"
            p.write_bytes(b"x")
            self.assertFalse(commit.is_committed_artifact(p))

    def test_empty_payload_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            with self.assertRaises(ValueError):
                commit.commit_new_private_artifact(
                    root, "data/private/shadow_forward/a.bin", b"")

    def test_outside_private_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            with self.assertRaises(ValueError):
                commit.commit_new_private_artifact(root, "docs/a.bin", b"x")

    def test_fsync_failure_does_not_create_final(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            with mock.patch("shadow_forward_private_commit.os.fsync",
                            side_effect=OSError("fsync failed")):
                with self.assertRaises(OSError):
                    commit.commit_new_private_artifact(
                        root, "data/private/shadow_forward/a.bin", b"x")
            final = root / "data/private/shadow_forward/a.bin"
            self.assertFalse(final.exists())
            self.assertTrue(final.with_name("a.bin.pending").exists())


if __name__ == "__main__":
    unittest.main()
