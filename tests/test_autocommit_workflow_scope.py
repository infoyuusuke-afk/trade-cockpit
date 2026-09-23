"""Guard against re-introducing C-116: auto-committing workflows must never
run on push to a non-main branch.

Root cause observed 2026-09-22: mobile-approval-feed.yml had a bare
`push: paths: [...]` trigger with no branch filter. Merging main into an
open Draft PR branch pulled in a change to one of its watched paths, the
workflow fired on the PR branch, committed data/mobile_approval_requests.json
back with the default GITHUB_TOKEN as github-actions[bot], and that bot-authored
push then made the PR's required "Mobile Control Tests" check permanently
stick at conclusion=action_required with zero jobs (GitHub never runs it),
poisoning the PR head with no way to reach green.

Any workflow with `permissions: contents: write` and a step that commits and
pushes back to the triggering ref must scope its `push` trigger to
`branches: [main]`, so it only ever runs on main and can never land an
unreviewable auto-commit on someone else's branch.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _writes_contents(text: str) -> bool:
    return bool(re.search(r"permissions:\s*\n\s*contents:\s*write", text))


def _pushes_back(text: str) -> bool:
    return "git push" in text


def _push_trigger_block(text: str) -> str | None:
    match = re.search(r"^  push:\n((?:^ {4}.*\n?)*)", text, re.MULTILINE)
    return match.group(0) if match else None


class AutoCommitWorkflowScopeTest(unittest.TestCase):
    def test_self_committing_workflows_are_main_only(self):
        offenders = []
        for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if not (_writes_contents(text) and _pushes_back(text)):
                continue
            block = _push_trigger_block(text)
            if block is None:
                # Not push-triggered at all (e.g. schedule-only) -> safe.
                continue
            if "branches:" not in block or "main" not in block:
                offenders.append(path.name)
        self.assertEqual(
            offenders,
            [],
            f"auto-commit workflows missing 'push: branches: [main]': {offenders}",
        )

    def test_self_committers_use_dedicated_data_writer_boundary(self):
        offenders = []
        for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if not _pushes_back(text):
                continue
            checks = {
                "contents_read": bool(re.search(r"permissions:\s*\n\s*contents:\s*read", text)),
                "environment": "environment: main-data-writer" in text,
                "main_job_guard": "if: github.ref == 'refs/heads/main'" in text,
                "deploy_key": "MAIN_DATA_WRITER_DEPLOY_KEY" in text,
            }
            if not all(checks.values()):
                offenders.append((path.name, checks))
        self.assertEqual(offenders, [], f"self-committing workflow boundary violations: {offenders}")

    def test_known_autocommit_workflows_present_and_scoped(self):
        # Explicit list so this test still fails loudly if a workflow is
        # renamed/removed in a way that silently drops coverage above.
        expected = {
            "mobile-approval-feed.yml",
            "calibrate-ev.yml",
            "ev-learning-loop.yml",
        }
        for name in expected:
            path = WORKFLOWS_DIR / name
            self.assertTrue(path.exists(), f"expected workflow missing: {name}")
            text = path.read_text(encoding="utf-8")
            block = _push_trigger_block(text)
            self.assertIsNotNone(block, f"{name}: no push trigger block found")
            self.assertIn("branches: [main]", block, f"{name}: push trigger not scoped to main")


if __name__ == "__main__":
    unittest.main()
