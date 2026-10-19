"""Synthetic Windows acceptance for opt-in read-only V10 research; no real PC data."""
from __future__ import annotations

from datetime import timedelta
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import v10_brain_research_windows_acceptance as acceptance
from scripts import v10_brain_research_optin as sidecar
from test_v10_brain_private_research_bridge import NOW
from test_v10_brain_research_optin import BrainResearchOptInTests


SHA = "a" * 40
BRANCH = "dev/p0-v10-synthetic-readonly"


def proof(sha=SHA):
    return "\n".join((
        "V10_BRAIN_PREFLIGHT=OBSERVATION_ONLY",
        "VERIFIED_SHA=" + sha,
        "EXCHANGE_TICK_DATE_VERIFIED=0",
        "EXPECTED_RETURN_VALIDATED=0",
        "SOURCE_AUTHENTICATED=0",
        "REAL_SUBMIT_ALLOWED=0",
    )) + "\n"


class WindowsAcceptanceTests(unittest.TestCase):
    def make_inputs(self, td):
        root = Path(td)
        brain, private = BrainResearchOptInTests().make_inputs(td)
        repo = root / "repo"
        state_root = root / "controller"
        (repo / "downloads").mkdir(parents=True)
        (repo / "downloads" / acceptance.PREFLIGHT_NAME).write_text(
            "# synthetic read-only preflight placeholder", encoding="utf-8")
        state_root.mkdir()
        state_path = state_root / acceptance.STATE_NAME
        state_path.write_text(json.dumps({
            "repo_root": str(repo), "runtime_dir": str(brain.parent),
            "brain_observer_pid": 1234, "controller_pid": 5678,
        }), encoding="utf-8")
        os.utime(state_path, (NOW.timestamp(), NOW.timestamp()))
        return repo, state_root, private, state_path, brain

    def inspect(self, repo, root, private, *, result=(0, proof()),
                now=NOW, expected_sha=SHA, expected_branch=BRANCH):
        def fake_preflight(**kwargs):
            self.assertEqual(kwargs["repo_root"], repo)
            self.assertEqual(kwargs["state_root"], root)
            self.assertEqual(kwargs["expected_sha"], expected_sha)
            self.assertEqual(kwargs["expected_branch"], expected_branch)
            return result
        return acceptance.run_once(
            repo_root=repo, state_root=root, private_dir=private,
            expected_sha=expected_sha, expected_branch=expected_branch,
            now=now, preflight=fake_preflight)

    def safe(self, out):
        for key in sidecar.consumer.FLAGS:
            self.assertIs(out[key], False, key)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(out))
        self.assertNotIn("ledger.jsonl", json.dumps(out))
        self.assertNotIn("1000.T", json.dumps(out))

    def test_valid_snapshot_requires_real_brain_and_private_data_contract(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, private, state_path, brain = self.make_inputs(td)
            context = private / sidecar.consumer.STATUS_NAME
            files = (state_path, brain, context)
            before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
            out = self.inspect(repo, root, private)
            after = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
            self.assertEqual(before, after)
        self.assertEqual(out["state"], "RESEARCH_OBSERVATION_ONLY", out)
        self.assertEqual(out["research_decision"], "COLLECT_MORE_VIRTUAL_SAMPLES")
        self.assertEqual(out["virtual_sample_count"], 1)
        self.assertEqual(out["windows_preflight_gate"], "PASS")
        self.safe(out)

    def test_wrong_missing_or_unsafe_preflight_blocks_before_data_reads(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, private, state_path, brain = self.make_inputs(td)
            cases = [
                (1, proof()),
                (0, ""),
                (0, proof("b"*40)),
                (0, proof()+"VERIFIED_SHA="+SHA+"\n"),
                (0, proof()+"PRIVATE_SENTINEL\n"),
                (0, proof().replace("REAL_SUBMIT_ALLOWED=0", "REAL_SUBMIT_ALLOWED=1")),
                (0, proof().replace("SOURCE_AUTHENTICATED=0", "SOURCE_AUTHENTICATED=1")),
            ]
            for bad in cases:
                with self.subTest(bad=bad):
                    with patch.object(acceptance, "_stable_state",
                                      side_effect=AssertionError("must not read state")):
                        out = self.inspect(repo, root, private, result=bad)
                    self.assertEqual(out["state"], "BLOCKED")
                    self.safe(out)

    def test_stale_state_or_expired_quote_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, private, state_path, brain = self.make_inputs(td)
            self.assertEqual(self.inspect(repo, root, private)["state"],
                             "RESEARCH_OBSERVATION_ONLY")
            out = self.inspect(repo, root, private, now=NOW+timedelta(seconds=90))
            self.assertEqual(out["state"], "BLOCKED")
            os.utime(state_path, ((NOW-timedelta(seconds=32)).timestamp(),)*2)
            out = self.inspect(repo, root, private)
            self.assertEqual(out["state"], "BLOCKED")
            self.safe(out)

    def test_forged_state_root_or_pid_or_runtime_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, private, state_path, brain = self.make_inputs(td)
            good = json.loads(state_path.read_text())
            for bad in (
                {"repo_root": str(root)},
                {"runtime_dir": "PRIVATE_SENTINEL"},
                {"brain_observer_pid": 0},
                {"controller_pid": "not-a-pid"},
            ):
                with self.subTest(bad=bad):
                    state_path.write_text(json.dumps(dict(good, **bad)), encoding="utf-8")
                    os.utime(state_path, (NOW.timestamp(), NOW.timestamp()))
                    out = self.inspect(repo, root, private)
                    self.assertEqual(out["state"], "BLOCKED")
                    self.safe(out)

    def test_missing_context_or_untrusted_sidecar_output_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, private, _, _ = self.make_inputs(td)
            (private / sidecar.consumer.STATUS_NAME).unlink()
            self.assertEqual(self.inspect(repo, root, private)["state"], "BLOCKED")
            with patch.object(acceptance.sidecar, "run_once",
                              return_value={"state":"RESEARCH_OBSERVATION_ONLY",
                                            "real_submit_allowed":True}):
                out = self.inspect(repo, root, private)
            self.assertEqual(out["state"], "BLOCKED")
            self.safe(out)

    def test_invalid_cli_input_or_branch_injection_never_runs_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, private, _, _ = self.make_inputs(td)
            for sha, branch in (
                ("bad", BRANCH), (SHA.upper(), BRANCH),
                (SHA, "-evil"), (SHA, "../bad"),
                (SHA, "branch;echo SECRET"), (SHA, "dev//bad"),
            ):
                with patch.object(acceptance, "run_preflight",
                                  side_effect=AssertionError("no execution")):
                    out = acceptance.run_once(
                        repo_root=repo, state_root=root, private_dir=private,
                        expected_sha=sha, expected_branch=branch, now=NOW)
                self.assertEqual(out["state"], "BLOCKED")
                self.safe(out)

    def test_preflight_launch_uses_fixed_script_shell_false_no_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            repo, root, _, _, _ = self.make_inputs(td)
            with patch.object(acceptance.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0,stdout=proof())) as runner:
                r = acceptance.run_preflight(
                    repo_root=repo, state_root=root,
                    expected_sha=SHA, expected_branch=BRANCH)
            self.assertEqual(r, (0,proof()))
            arguments=runner.call_args.args[0]
            self.assertEqual(arguments[0], "powershell.exe")
            self.assertEqual(arguments[arguments.index("-File")+1],
                             str(repo/"downloads"/acceptance.PREFLIGHT_NAME))
            self.assertFalse(runner.call_args.kwargs["shell"])
            self.assertTrue(runner.call_args.kwargs["capture_output"])
            self.assertEqual(runner.call_args.kwargs["timeout"],20)
            self.assertNotIn("PRIVATE_SENTINEL", str(arguments))

    def test_cli_fail_does_not_echo_user_private_directory(self):
        with tempfile.TemporaryDirectory(prefix="PRIVATE_SENTINEL") as td:
            output=io.StringIO()
            with redirect_stdout(output):
                code=acceptance.main([
                    "--repo-root",td,"--state-root",td,
                    "--research-private-dir",td,
                    "--expected-sha",SHA,"--expected-branch",BRANCH])
            self.assertEqual(code,2)
            self.assertNotIn("PRIVATE_SENTINEL",output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["state"],"BLOCKED")


if __name__ == "__main__":
    unittest.main()
