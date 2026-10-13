"""Regression contracts for the shared market-data writer queue.

These inspect parsed YAML, not a simulation of GitHub's scheduler. Hosted queue
behavior is exercised by the isolated matrix in market-writer-queue-tests.yml.
"""
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # Optional test dependency; dedicated queue CI installs it.

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SHARED_WRITERS = {
    "board-buzz.yml", "earnings-calendar.yml", "live-focus.yml",
    "mention-tracker.yml", "next-theme-radar.yml", "swing-long-signals.yml",
    "update.yml", "world-market.yml",
}


@unittest.skipIf(yaml is None, "PyYAML required; enforced by Market Writer Queue Tests CI")
class MarketWriterQueueTests(unittest.TestCase):
    def test_all_shared_writers_queue_without_replacing_pending_work(self):
        found = set()
        for path in WORKFLOWS.glob("*.yml"):
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            concurrency = config.get("concurrency", {})
            if concurrency.get("group") == "trade-cockpit-writer":
                found.add(path.name)
        self.assertEqual(found, SHARED_WRITERS)
        for name in SHARED_WRITERS:
            with self.subTest(workflow=name):
                config = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
                self.assertEqual(config["concurrency"], {
                    "group": "trade-cockpit-writer", "queue": "max",
                    "cancel-in-progress": False,
                })
                self.assertEqual(config["permissions"], {"contents": "read"})
                for job in config["jobs"].values():
                    self.assertEqual(job["environment"], "main-data-writer")
                    condition = job["if"]
                    self.assertIn("github.ref == 'refs/heads/main'", condition)
                    if name == "update.yml":
                        self.assertIn("github.actor == 'github-actions[bot]'", condition)
                        self.assertIn(
                            "startsWith(github.event.head_commit.message, "
                            "'Auto-update trade cockpit')",
                            condition,
                        )
                    else:
                        self.assertEqual(condition, "github.ref == 'refs/heads/main'")
                    self.assertGreater(job["timeout-minutes"], 0)
                    checkouts = [s for s in job["steps"]
                                 if s.get("uses", "").startswith("actions/checkout@")]
                    self.assertEqual(len(checkouts), 1)
                    self.assertEqual(checkouts[0]["uses"],
                                     "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683")
                    self.assertEqual(checkouts[0]["with"]["ref"], "main")
                    self.assertEqual(checkouts[0]["with"]["ssh-key"],
                                     "${{ secrets.MAIN_DATA_WRITER_DEPLOY_KEY }}")

    def test_update_writer_does_not_reenter_from_its_own_generated_commit(self):
        config = yaml.safe_load((WORKFLOWS / "update.yml").read_text(encoding="utf-8"))
        condition = config["jobs"]["update"]["if"]
        self.assertIn("github.event_name == 'push'", condition)
        self.assertIn("github.actor == 'github-actions[bot]'", condition)
        self.assertIn("'Auto-update trade cockpit'", condition)
        self.assertNotIn("github.event_name == 'schedule' &&", condition)
        # Event-level path filters are evaluated before the job guard; a
        # bot-authored generated-output push must not queue the workflow.
        triggers = config.get("on", config.get(True))
        self.assertIsNotNone(triggers)
        push_paths = set(triggers["push"]["paths"])
        generated_outputs = {
            "credit_supply.json",
            "kioxia_catalysts.json",
            "kioxia_prediction_history.json",
            "investor_regime.json",
        }
        self.assertFalse(
            push_paths & generated_outputs,
            f"Generated outputs unexpectedly trigger update.yml: {push_paths & generated_outputs}",
        )
        self.assertIn("scripts/investor_regime.py", push_paths)

    def test_ci_smoke_queue_is_isolated_from_production(self):
        config = yaml.safe_load((WORKFLOWS / "market-writer-queue-tests.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["permissions"], {"contents": "read"})
        job = config["jobs"]["queue-smoke"]
        self.assertEqual(job["strategy"]["matrix"]["slot"], [1, 2, 3])
        self.assertEqual(job["concurrency"], {
            "group": "p0-writer-queue-smoke-${{ github.run_id }}",
            "queue": "max", "cancel-in-progress": False,
        })
        for job in config["jobs"].values():
            self.assertNotIn("environment", job)
            for step in job["steps"]:
                self.assertNotIn("secrets.", str(step))
                self.assertNotIn("git push", str(step))


if __name__ == "__main__":
    unittest.main()
