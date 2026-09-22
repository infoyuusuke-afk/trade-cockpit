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
            result = commit.commit_new_private_artifact(
                root, "data/private/shadow_forward/a.bin", b"evidence")
            self.assertEqual(result.path.read_bytes(), b"evidence")
            self.assertTrue(result.file_fsync)
            self.assertEqual(result.directory_fsync, commit.os.name == "posix")
            self.assertEqual(result.durability_verified, commit.os.name == "posix")
            self.assertFalse(result.path.with_name("a.bin.pending").exists())

    def test_existing_final_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            p = root / "data/private/shadow_forward/a.bin"
            p.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                commit.commit_new_private_artifact(
                    root, "data/private/shadow_forward/a.bin", b"replacement")
            self.assertEqual(p.read_bytes(), b"original")

    def test_publish_race_never_overwrites_competing_final(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            final = root / "data/private/shadow_forward/a.bin"
            real_link = commit.os.link

            def competing_link(src, dst):
                Path(dst).write_bytes(b"competitor")
                return real_link(src, dst)

            with mock.patch("shadow_forward_private_commit.os.link",
                            side_effect=competing_link):
                with self.assertRaises(FileExistsError):
                    commit.commit_new_private_artifact(
                        root, "data/private/shadow_forward/a.bin", b"ours")
            self.assertEqual(final.read_bytes(), b"competitor")
            self.assertTrue(final.with_name("a.bin.pending").exists())

    def test_unsupported_hardlink_fails_closed_without_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            with mock.patch("shadow_forward_private_commit.os.link",
                            side_effect=OSError("hardlink unsupported")):
                with self.assertRaises(OSError):
                    commit.commit_new_private_artifact(
                        root, "data/private/shadow_forward/a.bin", b"ours")
            final = root / "data/private/shadow_forward/a.bin"
            self.assertFalse(final.exists())
            self.assertTrue(final.with_name("a.bin.pending").exists())
            self.assertEqual(final.with_name("a.bin.pending").read_bytes(), b"ours")

    def test_existing_pending_blocks_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            pending = root / "data/private/shadow_forward/a.bin.pending"
            pending.write_bytes(b"uncertain")
            with self.assertRaises(FileExistsError):
                commit.commit_new_private_artifact(
                    root, "data/private/shadow_forward/a.bin", b"new")
            self.assertEqual(pending.read_bytes(), b"uncertain")

    def test_filename_alone_has_no_commit_eligibility_api(self):
        self.assertFalse(hasattr(commit, "is_committed_artifact"))

    def test_unverified_windows_durability_never_publishes_final(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            with mock.patch("shadow_forward_private_commit._platform_name", return_value="nt"):
                with self.assertRaises(OSError):
                    commit.commit_new_private_artifact(
                        root, "data/private/shadow_forward/a.bin", b"ours")
            final = root / "data/private/shadow_forward/a.bin"
            self.assertFalse(final.exists())
            self.assertTrue(final.with_name("a.bin.pending").exists())
            self.assertEqual(final.with_name("a.bin.pending").read_bytes(), b"ours")

    def test_unverified_directory_durability_blocks_acceptance(self):
        result = commit.CommitResult(Path("private.bin"), True, False)
        self.assertEqual(commit.evidence_commit_status(result),
                         "HOLD_DURABILITY_UNVERIFIED")
        with self.assertRaises(ValueError):
            commit.require_durable_for_acceptance(result)

    def test_unverified_file_durability_blocks_acceptance(self):
        result = commit.CommitResult(Path("private.bin"), False, True)
        self.assertEqual(commit.evidence_commit_status(result),
                         "HOLD_FILE_DURABILITY_UNVERIFIED")
        with self.assertRaises(ValueError):
            commit.require_durable_for_acceptance(result)

    def test_verified_durable_commit_may_enter_next_validation_layer(self):
        result = commit.CommitResult(Path("private.bin"), True, True)
        self.assertEqual(commit.evidence_commit_status(result), "COMMITTED_DURABLE")
        self.assertEqual(commit.require_durable_for_acceptance(result), result.path)

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

    def test_directory_fsync_failure_never_returns_success(self):
        if commit.os.name != "posix":
            self.skipTest("POSIX directory fsync test")
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            real_fsync = commit.os.fsync
            calls = {"n": 0}

            def fail_first_directory_fsync(fd):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError("directory fsync failed")
                return real_fsync(fd)

            with mock.patch("shadow_forward_private_commit.os.fsync",
                            side_effect=fail_first_directory_fsync):
                with self.assertRaises(OSError):
                    commit.commit_new_private_artifact(
                        root, "data/private/shadow_forward/a.bin", b"x")
            final = root / "data/private/shadow_forward/a.bin"
            self.assertTrue(final.exists())
            self.assertTrue(final.with_name("a.bin.pending").exists())

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
