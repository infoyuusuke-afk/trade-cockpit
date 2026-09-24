import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EXPECTED_WRITERS = {
    "board-buzz.yml",
    "calibrate-ev.yml",
    "earnings-calendar.yml",
    "ev-learning-loop.yml",
    "live-focus.yml",
    "kioxia-breaking-radar.yml",
    "mention-tracker.yml",
    "mobile-approval-feed.yml",
    "next-theme-radar.yml",
    "swing-long-signals.yml",
    "update.yml",
    "world-market.yml",
}


class MainDataWriterSecurityTests(unittest.TestCase):
    def _writers(self):
        found = {}
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\bgit push\b", text):
                found[path.name] = text
        return found

    def test_writer_inventory_is_explicit(self):
        self.assertEqual(set(self._writers()), EXPECTED_WRITERS)

    def test_every_writer_uses_main_only_deploy_key(self):
        for name, text in self._writers().items():
            with self.subTest(workflow=name):
                self.assertIn("contents: read", text)
                self.assertNotIn("contents: write", text)
                self.assertIn("environment: main-data-writer", text)
                self.assertIn("if: github.ref == 'refs/heads/main'", text)
                self.assertIn(
                    "ssh-key: ${{ secrets.MAIN_DATA_WRITER_DEPLOY_KEY }}",
                    text,
                )
                self.assertIn(
                    "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
                    text,
                )

    def test_data_writer_environment_and_secret_have_no_extra_consumers(self):
        env_consumers = set()
        secret_consumers = set()
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            if "environment: main-data-writer" in text:
                env_consumers.add(path.name)
            if "MAIN_DATA_WRITER_DEPLOY_KEY" in text:
                secret_consumers.add(path.name)
                self.assertEqual(text.count("MAIN_DATA_WRITER_DEPLOY_KEY"), 1)
        self.assertEqual(env_consumers, EXPECTED_WRITERS)
        self.assertEqual(secret_consumers, EXPECTED_WRITERS)

    def test_every_push_trigger_is_scoped_to_main(self):
        for name, text in self._writers().items():
            with self.subTest(workflow=name):
                if re.search(r"(?m)^  push:\s*$", text):
                    self.assertRegex(text, r"(?m)^  push:\n    branches: \[main\]$")

    def test_owner_approval_gate_is_secret_free_and_latest_head_only(self):
        path = WORKFLOWS / "owner-main-approval.yml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("branches: [main]", text)
        self.assertIn("types: [opened, synchronize, reopened, ready_for_review]", text)
        self.assertIn("cancel-in-progress: true", text)
        self.assertIn("github.event.pull_request.draft == false", text)
        self.assertIn("environment:", text)
        self.assertIn("name: owner-main-approval", text)
        self.assertIn("PR_NUMBER: ${{ github.event.pull_request.number }}", text)
        self.assertIn("PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}", text)
        self.assertIn("run: |", text)
        self.assertIn("printf 'Owner approval accepted for PR #%s at %s\\n'", text)
        self.assertNotIn('run: echo "Owner approval accepted for PR #', text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("contents: write", text)


if __name__ == "__main__":
    unittest.main()
