"""Build a strictly allowlisted, code-only MS2 offline OWNER package.

Does not inspect any live source folder, market CSV, account file or network.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from scripts.ms2_offline_csv_snapshot import _checked_path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = 'MS2_CSV_Local_Offline.zip'
MAX_FILE_BYTES = 256_000
FILES = (
    'START_MS2_CSV_CAPTURE.cmd',
    'scripts/ms2_local_csv_capture.py',
    'scripts/run_ms2_local_csv_capture.cmd',
    'scripts/ms2_offline_acceptance.py',
    'scripts/run_ms2_offline_acceptance.cmd',
    'scripts/ms2_offline_csv_snapshot.py',
    'scripts/ms2_observation_ingress.py',
    'scripts/timeseries_fill_audit.py',
    'scripts/shadow_fill_model.py',
    'tests/test_ms2_offline_csv_snapshot.py',
    'tests/test_ms2_local_csv_capture.py',
    'docs/MS2_LOCAL_CSV_CAPTURE.md',
    'docs/MS2_OFFLINE_ACCEPTANCE.md',
)
assert len(FILES) == len(set(FILES))
assert all(not Path(name).is_absolute()
           and '..' not in Path(name).parts
           and 'data' not in Path(name).parts
           for name in FILES)


def _safe_read(root, name):
    source = root / name
    _checked_path(source)
    before = source.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('CODE_FILE_INVALID')
    first = source.read_bytes()
    second = source.read_bytes()
    after = _checked_path(source).stat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                             item.st_mtime_ns, item.st_ctime_ns)
    if identity(before) != identity(after) or first != second or len(first) != before.st_size:
        raise ValueError('CODE_FILE_CHANGED')
    return first


def build_package(repo_root=ROOT, output_dir=None):
    root = _checked_path(repo_root)
    # Read ALL allowlisted sources before writing ANY part of the ZIP.
    payload = {name: _safe_read(root, name) for name in FILES}
    destination = Path(output_dir) if output_dir is not None else root / 'dist'
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = _checked_path(destination)
    archive = destination / ARCHIVE_NAME
    with ZipFile(archive, mode='x', compression=ZIP_DEFLATED) as bundle:
        for name, raw in sorted(payload.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, raw)
    return archive


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print('BLOCKED: ARGUMENTS_NOT_SUPPORTED')
        return 2
    try:
        build_package()
    except (OSError, ValueError, TypeError):
        # Never leak source filenames/paths in build errors.
        print('BLOCKED: CODE_ONLY_PACKAGE')
        return 1
    print('PASS: CODE_ONLY_PACKAGE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
