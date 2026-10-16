"""Create a fixed, script-only MS2 preservation ZIP; no executable or market data."""
from pathlib import Path
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from scripts.ms2_offline_csv_snapshot import _checked_path

ROOT = Path(__file__).resolve().parents[1]
NAME = 'MS2_CSV_Windows_Builtin.zip'
FILES = (
    'START_MS2_SAFE_CAPTURE.cmd',
    'scripts/ms2_native_offline_capture.ps1',
    'docs/MS2_WINDOWS_BUILTIN.md',
)

def build(root=ROOT, output_dir=None):
    root = _checked_path(root)
    sources = {}
    for name in FILES:
        source = _checked_path(root / name)
        before = source.stat()
        if not source.is_file() or before.st_size > 100_000:
            raise ValueError('SCRIPT_SOURCE_INVALID')
        raw = source.read_bytes()
        after = _checked_path(source).stat()
        if (len(raw) != before.st_size or source.read_bytes() != raw
                or after.st_mtime_ns != before.st_mtime_ns):
            raise ValueError('SCRIPT_SOURCE_CHANGED')
        sources[name] = raw
    target = Path(output_dir) if output_dir is not None else root / 'dist'
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = _checked_path(target)
    archive = target / NAME
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as out:
        for name, raw in sorted(sources.items()):
            meta = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            meta.compress_type = ZIP_DEFLATED
            meta.external_attr = 0o644 << 16
            out.writestr(meta, raw)
    with ZipFile(archive) as check:
        if set(check.namelist()) != set(FILES) or check.testzip() is not None:
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
    except (OSError, ValueError):
        print('BLOCKED: NATIVE_BUNDLE')
        return 1
    print('PASS: NATIVE_BUNDLE')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
