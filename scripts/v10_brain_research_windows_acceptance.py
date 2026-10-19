"""Opt-in V10 Windows acceptance: pinned read-only preflight + research sidecar.

No deploy, broker, background task, file writes or private evidence export.
A successful snapshot is NOT exchange provenance, validated EV or order approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from scripts import v10_brain_research_consumer as consumer
from scripts import v10_brain_research_optin as sidecar

SCHEMA = "v10-brain-research-windows-acceptance-1"
STATE_NAME = "V10_CONTROLLER_STATE.json"
PREFLIGHT_NAME = "AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1"
MAX_STATE_BYTES = 65_536
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,150}$")


def _result(reason=None, *, research_decision="HOLD_RESEARCH", n=None):
    return {
        "schema_version": SCHEMA,
        "state": "BLOCKED" if reason else "RESEARCH_OBSERVATION_ONLY",
        "reason": reason,
        "research_decision": research_decision,
        "virtual_sample_count": n,
        "windows_preflight_gate": "BLOCKED" if reason else "PASS",
        "research_sidecar_gate": "BLOCKED" if reason else "PASS",
        "acceptance_scope": "LOCAL_READONLY_SNAPSHOT_NOT_LIVE_TRADING",
        **{k: False for k in sorted(consumer.FLAGS)},
    }


def _stable_state(path, *, now):
    """Read the exact existing V10 state without trusting raw JSON/paths."""
    if path.name != STATE_NAME or not path.is_absolute():
        raise ValueError("STATE_PATH_INVALID")
    consumer._plain_local(path.parent)
    consumer._plain_local(path)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
            not 2 <= before.st_size <= MAX_STATE_BYTES):
        raise ValueError("STATE_FILE_INVALID")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if consumer._identity(before) != consumer._identity(opened):
            raise ValueError("STATE_CHANGED")
        raw = handle.read(MAX_STATE_BYTES + 1)
        closed = os.fstat(handle.fileno())
    consumer._plain_local(path)
    after = path.lstat()
    if (len(raw) != before.st_size or
            consumer._identity(before, same_api=True) !=
            consumer._identity(after, same_api=True) or
            consumer._identity(opened, same_api=True) !=
            consumer._identity(closed, same_api=True) or
            consumer._identity(before) != consumer._identity(closed) or
            consumer._identity(after) != consumer._identity(closed)):
        raise ValueError("STATE_CHANGED")
    modified = datetime.fromtimestamp(before.st_mtime, timezone.utc)
    if not 0 <= (now - modified).total_seconds() <= 30:
        raise ValueError("STATE_STALE")
    obj = json.loads(raw.decode("utf-8-sig"),
                     object_pairs_hook=consumer._pairs,
                     parse_constant=consumer._constant)
    if type(obj) is not dict:
        raise ValueError("STATE_SCHEMA_INVALID")
    return obj


def _clean_branch(branch):
    return (type(branch) is str and BRANCH_RE.fullmatch(branch) is not None and
            not branch.startswith("-") and not branch.startswith("/") and
            ".." not in branch and "//" not in branch and not branch.endswith("/"))


def _preflight_is_valid(returncode, stdout, expected_sha):
    if returncode != 0 or type(stdout) is not str or len(stdout) > 4096:
        return False
    rows = stdout.strip().splitlines()
    wanted = {
        "V10_BRAIN_PREFLIGHT=OBSERVATION_ONLY",
        "VERIFIED_SHA=" + expected_sha,
        "EXCHANGE_TICK_DATE_VERIFIED=0",
        "EXPECTED_RETURN_VALIDATED=0",
        "SOURCE_AUTHENTICATED=0",
        "REAL_SUBMIT_ALLOWED=0",
    }
    # No unreviewed additional stdout, failure indication or ambiguous duplicates.
    return len(rows) == len(wanted) and set(rows) == wanted


def run_preflight(*, repo_root, state_root, expected_sha, expected_branch):
    script = repo_root / "downloads" / PREFLIGHT_NAME
    consumer._plain_local(script)
    if not stat.S_ISREG(script.lstat().st_mode):
        raise ValueError("PREFLIGHT_SCRIPT_INVALID")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script),
         "-RepoRoot", str(repo_root), "-ExpectedSha", expected_sha,
         "-ExpectedBranch", expected_branch, "-StateRoot", str(state_root)],
        shell=False, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=20, check=False,
    )
    return result.returncode, result.stdout


def run_once(*, repo_root, state_root, private_dir, expected_sha,
             expected_branch, now, preflight=run_preflight):
    """Read-only snapshot acceptance; never starts/stops V10 or writes evidence."""
    try:
        if not isinstance(now, datetime) or now.utcoffset() is None:
            return _result("CLOCK_UNVERIFIED")
        if (type(expected_sha) is not str or
                SHA_RE.fullmatch(expected_sha) is None or
                not _clean_branch(expected_branch)):
            return _result("SOURCE_PIN_INVALID")
        repo, state_dir, private = map(Path, (repo_root, state_root, private_dir))
        if not all(p.is_absolute() for p in (repo, state_dir, private)):
            return _result("PATH_BOUNDARY_UNVERIFIED")
        for p in (repo, state_dir, private):
            consumer._plain_local(p)
        if not (repo / "downloads" / PREFLIGHT_NAME).is_file():
            return _result("PREFLIGHT_MISSING")
        returncode, stdout = preflight(
            repo_root=repo, state_root=state_dir,
            expected_sha=expected_sha, expected_branch=expected_branch)
        if not _preflight_is_valid(returncode, stdout, expected_sha):
            return _result("V10_PREFLIGHT_BLOCKED")
        state_path = state_dir / STATE_NAME
        state = _stable_state(state_path, now=now)
        if (type(state.get("repo_root")) is not str or
                os.path.normcase(os.path.abspath(state["repo_root"])) !=
                os.path.normcase(os.path.abspath(str(repo))) or
                type(state.get("runtime_dir")) is not str or
                type(state.get("brain_observer_pid")) is not int or
                state["brain_observer_pid"] <= 0 or
                type(state.get("controller_pid")) is not int or
                state["controller_pid"] <= 0):
            return _result("CONTROLLER_STATE_UNVERIFIED")
        runtime = Path(state["runtime_dir"])
        if not runtime.is_absolute():
            return _result("CONTROLLER_RUNTIME_UNVERIFIED")
        consumer._plain_local(runtime)
        brain_path = runtime / sidecar.BRAIN_NAME
        brain_before = sidecar._load_brain_status(brain_path, now)
        if (type(brain_before.get("engine_pid")) is not int or
                brain_before["engine_pid"] != state["brain_observer_pid"] or
                not sidecar._brain_gate(brain_before, now)):
            return _result("BRAIN_PID_OR_STATE_MISMATCH")
        outcome = sidecar.run_once(
            brain_status_path=brain_path,
            research_private_dir=private, now=now)
        if (type(outcome) is not dict or
                outcome.get("state") != "RESEARCH_OBSERVATION_ONLY" or
                outcome.get("reason") is not None or
                outcome.get("brain_observation_gate") != "PASS" or
                outcome.get("research_context_gate") != "PASS" or
                any(outcome.get(flag) is not False for flag in consumer.FLAGS) or
                type(outcome.get("virtual_sample_count")) is not int or
                not 0 <= outcome["virtual_sample_count"] <= 100_000 or
                outcome.get("research_decision") not in (
                    "COLLECT_MORE_VIRTUAL_SAMPLES",
                    "REVIEW_CONTAMINATED_VIRTUAL_DATA",
                    "REVIEW_VIRTUAL_RESEARCH_ONLY")):
            return _result("RESEARCH_SNAPSHOT_BLOCKED")
        # The sidecar cannot bind the published Brain status to the
        # Controller's recorded PID on its own. Check that association
        # before and after the sidecar read, including state replacements.
        brain_after = sidecar._load_brain_status(brain_path, now)
        if (brain_before != brain_after or
                type(brain_after.get("engine_pid")) is not int or
                brain_after["engine_pid"] != state["brain_observer_pid"] or
                not sidecar._brain_gate(brain_after, now)):
            return _result("BRAIN_CHANGED_DURING_RESEARCH")
        state_after = _stable_state(state_path, now=now)
        if state_after != state:
            return _result("CONTROLLER_CHANGED_DURING_RESEARCH")
        return _result(
            None, research_decision=outcome["research_decision"],
            n=outcome["virtual_sample_count"])
    except Exception:
        # Do not expose exception, credentials, raw data, paths or PIDs.
        return _result("LOCAL_ACCEPTANCE_UNAVAILABLE")


def main(argv=None):
    p = argparse.ArgumentParser(description="Explicit Windows V10 research snapshot acceptance, no orders")
    p.add_argument("--repo-root", required=True)
    p.add_argument("--state-root", required=True)
    p.add_argument("--research-private-dir", required=True)
    p.add_argument("--expected-sha", required=True)
    p.add_argument("--expected-branch", required=True)
    a = p.parse_args(argv)
    if os.name != "nt":
        result = _result("WINDOWS_REQUIRED")
    else:
        result = run_once(repo_root=a.repo_root, state_root=a.state_root,
                          private_dir=a.research_private_dir,
                          expected_sha=a.expected_sha,
                          expected_branch=a.expected_branch,
                          now=datetime.now(timezone.utc))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["state"] == "RESEARCH_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
