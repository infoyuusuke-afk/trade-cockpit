"""Guard against silently re-removing the Owner approval gate.

Root cause observed 2026-09-23 (PR #198): the `approve` job in
owner-main-approval.yml had its `environment: name: owner-main-approval`
reference dropped while the job's `if`/steps were left intact, so the check
still ran and reported success, but it no longer waited on the GitHub
Environment's required reviewer (the Owner). At least 13 PRs merged to main
over the following ~30 minutes without an actual human approval click before
this was noticed and reverted (see STATUS.md 2026-09-25 entry).

The job continuing to exist and pass is not evidence the gate is real: only
the `environment:` reference makes GitHub actually block on the required
reviewer. This test fails loudly if that reference is ever removed again.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "owner-main-approval.yml"
)

REQUIRED_ENVIRONMENT_NAME = "owner-main-approval"


class OwnerApprovalGatePresentTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_approve_job_declares_the_required_environment(self):
        match = re.search(r"^  approve:\n((?:^ {4}.*\n?)*)", self.text, re.MULTILINE)
        self.assertIsNotNone(
            match, "could not find an 'approve:' job in owner-main-approval.yml"
        )
        job_body = match.group(1)
        self.assertRegex(
            job_body,
            r"environment:\s*\n\s*name:\s*" + re.escape(REQUIRED_ENVIRONMENT_NAME),
            "the 'approve' job no longer declares "
            f"'environment: name: {REQUIRED_ENVIRONMENT_NAME}' - this silently "
            "disables the required-reviewer gate even though the job still "
            "runs and reports a passing check. Restore the environment "
            "reference; do not just rename the step back.",
        )

    def test_approve_job_only_runs_for_non_draft_prs(self):
        self.assertIn(
            "if: github.event.pull_request.draft == false",
            self.text,
            "the approve job should stay scoped to ready-for-review PRs",
        )


if __name__ == "__main__":
    unittest.main()
