"""Offline synthetic acceptance only; never discovers or accepts market CSV paths."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import sys
from pathlib import Path
import unittest
import uuid

from scripts.ms2_offline_csv_snapshot import SAFETY, _checked_path

def runtime_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT = runtime_root()


def _d_drive_root():
    """Fixed owner storage drive; never infer a location from the EXE."""
    if os.name != 'nt':
        raise ValueError('D_DRIVE_WINDOWS_ONLY')
    return Path('D:\\')


def private_root():
    """Frozen CSV/evidence goes ONLY to D:\\AI_Cockpit_Data\\MS2_CSV.

    A missing/unavailable D: drive or a symlink/reparse-point parent BLOCKS
    capture. Never silently fall back to C:, user profile, Downloads, synced
    folders, the EXE folder or an external server.
    Non-frozen source-checkout tests retain their explicit local sandbox.
    """
    if not getattr(sys, 'frozen', False):
        return ROOT
    parent = _checked_path(_d_drive_root())  # D: must exist, no fallback
    if not parent.is_dir():
        raise ValueError('D_DRIVE_UNAVAILABLE')
    for name in ('AI_Cockpit_Data', 'MS2_CSV'):
        parent = parent / name
        parent.mkdir(mode=0o700, exist_ok=True)
        parent = _checked_path(parent)
    return parent
CODE_FILES = (
    'scripts/ms2_offline_acceptance.py',
    'scripts/ms2_offline_csv_snapshot.py',
    'scripts/ms2_observation_ingress.py',
    'scripts/timeseries_fill_audit.py',
    'scripts/shadow_fill_model.py',
    'tests/test_ms2_offline_csv_snapshot.py',
    'scripts/run_ms2_offline_acceptance.cmd',
    'scripts/ms2_local_csv_capture.py',
    'scripts/run_ms2_local_csv_capture.cmd',
)
# Fixed, reviewed names only. Never serialize test exceptions, skip messages,
# arbitrary test identifiers, stdout, environment variables or user paths.
CHECKS = (
    'no_opt_in_no_filesystem_access',
    'raw_bytes_hash_size_and_readonly_source',
    'duplicate_and_existing_data_protected',
    'diag_separate_hash_and_nonatomic_safety',
    'mismatched_missing_and_corrupt_diag',
    'invalid_header_corrupt_partial_and_values',
    'invalid_paths_and_size',
    'source_symlink_and_destination_link',
    'stat_api_timestamp_representation_difference',
    'handle_timestamp_mutation_refused',
    'change_between_reads_rejected',
    'tick_change_during_diag_rejected',
    'failed_publication_protects_previous_snapshot',
    'readback_corruption_refused',
)


def inspect_synthetic():
    from tests.test_ms2_offline_csv_snapshot import SnapshotTests
    checks = []
    for name in CHECKS:
        result = unittest.TestResult()
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                SnapshotTests('test_' + name).run(result)
            passed = (result.testsRun == 1 and result.wasSuccessful()
                      and not result.skipped and not result.expectedFailures
                      and not result.unexpectedSuccesses)
        except Exception:
            passed = False
        checks.append({'check': name, 'status': 'PASS' if passed else 'BLOCKED'})
    return checks


def run_acceptance():
    """Return only allowlisted evidence. All test files are temporary synthetic data."""
    checks = inspect_synthetic()
    return dict(
        SAFETY, schema='ms2-offline-acceptance-1',
        state='PASS' if all(c['status'] == 'PASS' for c in checks) else 'BLOCKED',
        scope='SYNTHETIC_ONLY', owner_ms2_verified=False,
        real_market_capture_verified=False, pair_atomic=False,
        created_utc=datetime.now(timezone.utc).isoformat(),
        code_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in CODE_FILES},
        checks=checks,
    )


def save_evidence(report):
    # Fixed private location, exclusive new file; never overwrite a prior report.
    parent = _checked_path(private_root())
    for name in ('data', 'private', 'ms2_offline_acceptance'):
        parent = parent / name
        parent.mkdir(exist_ok=True, mode=0o700)
        _checked_path(parent)
    target = parent / (uuid.uuid4().hex + '.json')
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
    if json.loads(target.read_text(encoding='utf-8')) != report:
        raise ValueError('EVIDENCE_READBACK_FAILED')


def main(argv=None):
    import sys
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print('BLOCKED: ARGUMENTS_NOT_SUPPORTED')
        return 2
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            report = run_acceptance()
            save_evidence(report)
        print(report['state'] + ': SYNTHETIC_ONLY; evidence=data/private/ms2_offline_acceptance')
        return 0 if report['state'] == 'PASS' else 1
    except Exception:
        print('BLOCKED: ACCEPTANCE_OR_EVIDENCE_FAILED')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
