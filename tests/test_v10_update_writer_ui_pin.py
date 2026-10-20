"""Regression guards for V10 UI pinning in the generated-data writer.

Synthetic only. Never launches MS2, Excel, or broker orders.
"""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "update.yml"


class PinnedUiWriterAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_restore_after_legacy_generator_and_before_validation(self):
        w = self.workflow
        self.assertLess(w.index("python scripts/update.py"), w.index("git restore --source=HEAD --worktree -- index.html"))
        self.assertLess(w.index("git restore --source=HEAD --worktree -- index.html"), w.index("python -m unittest discover -s tests -v"))

    def test_worktree_and_staged_guard_in_both_steps(self):
        w = self.workflow
        self.assertEqual(w.count("git diff --exit-code HEAD -- index.html"), 2)
        self.assertEqual(w.count("git diff --cached --exit-code HEAD -- index.html"), 2)
        self.assertLess(w.index("git diff --cached --exit-code HEAD -- index.html"), w.index("python -m unittest discover -s tests -v"))

    def test_publish_step_never_adds_index_html(self):
        commit_step = self.workflow.split("- name: Commit and push updated files", 1)[1]
        self.assertNotIn("git add index.html", commit_step)
        self.assertIn("git add data.json signals.json", commit_step)
        self.assertIn("git diff --quiet -- data.json", commit_step)

    def test_scheduler_and_permissions_remain_unmodified(self):
        w = self.workflow
        for cron in ("0 23 * * 0-4", "20 0 * * 1-5", "0 1 * * 1-5", "45 2 * * 1-5", "45 5 * * 1-5", "35 6 * * 1-5", "0 0 * * 6"):
            self.assertIn(cron, w)
        self.assertIn("permissions:\n  contents: read", w)
        self.assertIn("group: trade-cockpit-writer", w)

    def test_restore_keeps_market_data_worktree_changes(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            def git(*args, check=True):
                return subprocess.run(["git", *args], cwd=d, capture_output=True, text=True, check=check)
            git("init", "-q")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            (d / "index.html").write_text("PINNED_V10", encoding="utf-8")
            (d / "data.json").write_text("old", encoding="utf-8")
            git("add", "index.html", "data.json")
            git("commit", "-qm", "baseline")
            (d / "index.html").write_text("LEGACY_HTML", encoding="utf-8")
            (d / "data.json").write_text("new", encoding="utf-8")
            git("restore", "--source=HEAD", "--worktree", "--", "index.html")
            self.assertEqual((d / "index.html").read_text(), "PINNED_V10")
            self.assertEqual((d / "data.json").read_text(), "new")
            git("diff", "--exit-code", "HEAD", "--", "index.html")

    def test_staged_only_legacy_html_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            def git(*args, check=True):
                return subprocess.run(["git", *args], cwd=d, capture_output=True, text=True, check=check)
            git("init", "-q")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            (d / "index.html").write_text("PINNED_V10", encoding="utf-8")
            git("add", "index.html")
            git("commit", "-qm", "baseline")
            (d / "index.html").write_text("LEGACY_HTML", encoding="utf-8")
            git("add", "index.html")
            git("restore", "--source=HEAD", "--worktree", "--", "index.html")
            self.assertEqual(git("diff", "--exit-code", "HEAD", "--", "index.html", check=False).returncode, 0)
            self.assertNotEqual(git("diff", "--cached", "--exit-code", "HEAD", "--", "index.html", check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
