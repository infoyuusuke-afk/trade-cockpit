"""Build a code-only, Python-free Windows MS2 CSV executable bundle."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

from scripts.ms2_offline_acceptance import CODE_FILES
from scripts.ms2_offline_csv_snapshot import _checked_path

ROOT = Path(__file__).resolve().parents[1]
EXE = 'MS2_Local_CSV'
ZIP = 'MS2_CSV_Windows_NoPython.zip'
ENTRYPOINT = 'scripts/ms2_local_csv_capture.py'


def installer_arguments(root=ROOT):
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
            '--onedir', '--console', '--contents-directory', '.', '--name', EXE,
            '--log-level', 'ERROR', '--distpath', str(root / 'dist_frozen'),
            '--workpath', str(root / 'build_frozen'),
            '--specpath', str(root / 'build_frozen'),
            '--hidden-import', 'tests.test_ms2_offline_csv_snapshot']
    for path in CODE_FILES:
        # --specpath changes where PyInstaller resolves relative input paths.
        # Always bind an absolute checked source beneath the pinned repo root.
        args.extend(['--add-data',
                     str(root / path) + os.pathsep + str(Path(path).parent)])
    return args + [ENTRYPOINT]


def build(root=ROOT):
    root = _checked_path(root)
    for name in (*CODE_FILES, ENTRYPOINT):
        file = _checked_path(root / name)
        info = file.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 256_000:
            raise ValueError('INPUT_INVALID')
        first = file.read_bytes()
        if first != file.read_bytes() or len(first) != info.st_size:
            raise ValueError('INPUT_CHANGED')
    subprocess.run(installer_arguments(root), cwd=root, check=True,
                   stdout=subprocess.DEVNULL)
    folder = _checked_path(root / 'dist_frozen' / EXE)
    if not (folder / (EXE + '.exe')).is_file():
        raise ValueError('BINARY_MISSING')
    files = sorted(path for path in folder.rglob('*') if path.is_file())
    if not files or any('data' in path.relative_to(folder).parts for path in files):
        raise ValueError('PRIVATE_FILES_PRESENT')
    archive = root / 'dist' / ZIP
    archive.parent.mkdir(mode=0o700, exist_ok=True)
    _checked_path(archive.parent)
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as z:
        for file in files:
            _checked_path(file)
            z.write(file, (Path(EXE) / file.relative_to(folder)).as_posix())
    with ZipFile(archive) as check:
        if EXE + '/' + EXE + '.exe' not in check.namelist() or check.testzip():
            raise ValueError('ARCHIVE_INVALID')
    return archive


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print('BLOCKED: ARGUMENTS_NOT_SUPPORTED')
        return 2
    try:
        build()
    except (OSError, ValueError, subprocess.CalledProcessError):
        print('BLOCKED: WINDOWS_EXE_BUNDLE')
        return 1
    print('PASS: WINDOWS_EXE_BUNDLE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
