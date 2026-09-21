import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import shadow_forward_private_path as policy


class PrivatePathPolicyTests(unittest.TestCase):
    def test_data_private_shadow_forward_allowed(self):
        self.assertTrue(policy.allowed_private_path(
            "data/private/shadow_forward/2026-09-22/session-1.jsonl"))

    def test_ms2_records_shadow_forward_allowed(self):
        self.assertTrue(policy.allowed_private_path(
            "ms2_live/records/shadow_forward/2026-09-22/session-1.jsonl"))

    def test_root_itself_rejected(self):
        self.assertFalse(policy.allowed_private_path("data/private/shadow_forward"))

    def test_public_path_rejected(self):
        self.assertFalse(policy.allowed_private_path("docs/shadow_forward/evidence.json"))

    def test_prefix_confusion_rejected(self):
        self.assertFalse(policy.allowed_private_path(
            "data/private/shadow_forward-public/evidence.json"))

    def test_parent_traversal_rejected(self):
        self.assertFalse(policy.allowed_private_path(
            "data/private/shadow_forward/../../public/evidence.json"))

    def test_absolute_posix_rejected(self):
        self.assertFalse(policy.allowed_private_path(
            "/data/private/shadow_forward/evidence.json"))

    def test_windows_absolute_or_backslash_rejected(self):
        self.assertFalse(policy.allowed_private_path(
            r"C:\repo\data\private\shadow_forward\evidence.json"))
        self.assertFalse(policy.allowed_private_path(
            r"data\private\shadow_forward\evidence.json"))

    def test_empty_rejected(self):
        self.assertFalse(policy.allowed_private_path(""))

    def test_require_returns_normalized_repo_relative(self):
        self.assertEqual(
            policy.require_private_evidence_path(
                "data/private/shadow_forward/2026-09-22/a.jsonl"),
            "data/private/shadow_forward/2026-09-22/a.jsonl",
        )

    def test_resolved_private_path_inside_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data/private/shadow_forward").mkdir(parents=True)
            result = policy.require_resolved_private_path(
                root, "data/private/shadow_forward/day/session.jsonl")
            self.assertTrue(result.is_relative_to(
                (root / "data/private/shadow_forward").resolve()))

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            private = root / "data/private/shadow_forward"
            private.mkdir(parents=True)
            link = private / "escape"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(ValueError):
                policy.require_resolved_private_path(
                    root, "data/private/shadow_forward/escape/session.jsonl")

    def test_require_raises_outside_private_root(self):
        with self.assertRaises(ValueError):
            policy.require_private_evidence_path("runtime/evidence.jsonl")


if __name__ == "__main__":
    unittest.main()
