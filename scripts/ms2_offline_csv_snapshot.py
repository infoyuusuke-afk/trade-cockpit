"""Explicit offline legacy CSV preservation; no market eligibility or order path.

Run with python -m scripts.ms2_offline_csv_snapshot --source-root DIR
--input kioxia_ticks_YYYYMMDD.csv [--diag kioxia_tick_diag_YYYYMMDD.csv].
The source directory is an explicit local trust boundary. Stop the producer or
copy offline first: two stable reads detect changes, not an atomic capture.
Only a completed manifest marks a successful snapshot. No exchange time,
available_at, symbol, or authenticated provenance is inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
from datetime import datetime

from scripts.ms2_tick_session_audit import audit_tick_sessions
from scripts.ms2_observation_ingress import (
    MAX_BYTES, TICK_HEADER, DIAG_HEADER, _csv_table, _legacy_reasons,
)

SAFETY = dict(source_authenticated=False, promotion_eligible=False,
              real_submit_allowed=False, eligible_observed_n=0)


def _checked_path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('PATH_LINK')  # includes Windows junctions/reparse points
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path):
    before = _checked_path(path).stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError('SOURCE_TYPE_OR_SIZE_INVALID')
    views = []
    for _ in range(2):
        with path.open('rb') as stream:
            handle_before = os.fstat(stream.fileno())
            # Windows path-stat and handle-stat timestamps can differ in
            # representation. Compare identities across APIs, and full
            # timestamps only within each API, before/after the read.
            if ((handle_before.st_dev, handle_before.st_ino, handle_before.st_size)
                    != (before.st_dev, before.st_ino, before.st_size)):
                raise ValueError('SOURCE_CHANGED_DURING_READ')
            raw = stream.read(MAX_BYTES + 1)
            if _identity(os.fstat(stream.fileno())) != _identity(handle_before):
                raise ValueError('SOURCE_CHANGED_DURING_READ')
        if (len(raw) != before.st_size or len(raw) > MAX_BYTES
                or _identity(_checked_path(path).stat()) != _identity(before)):
            raise ValueError('SOURCE_CHANGED_DURING_READ')
        views.append(raw)
    if views[0] != views[1]:
        raise ValueError('SOURCE_CHANGED_DURING_READ')
    return views[0]


def _validate(raw, header, day):
    actual, rows = _csv_table(raw)
    if actual != header or not rows or not raw.endswith(b'\n'):
        raise ValueError('CSV_SCHEMA_OR_COMPLETENESS_INVALID')
    for row in rows:
        try:
            stamp = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            if stamp.strftime('%Y%m%d') != day:
                raise ValueError()
            if header == TICK_HEADER:
                datetime.strptime(row[1], '%H:%M:%S')
                price = float(row[2])
                if not math.isfinite(price) or price <= 0:
                    raise ValueError()
                numbers = [row[3], row[4]]
            else:
                numbers = row[1:4]
                if row[4] not in {'True', 'False', 'true', 'false'}:
                    raise ValueError()
            if any(not re.fullmatch(r'\d+', n) for n in numbers):
                raise ValueError()
            if header == DIAG_HEADER and (int(row[2]) > int(row[1]) or int(row[3]) > int(row[1])):
                raise ValueError()
        except (ValueError, OverflowError):
            raise ValueError('CSV_VALUE_INVALID') from None
    return rows


def preserve_csv(repo_root, source_root=None, input_name=None, *, diag_name=None):
    """No filesystem access unless input_name is explicitly supplied.

    Reports contain codes only, never source paths, prices or quantities.
    Files are independent observations; pair_atomic is always false. Existing
    snapshot directories are never reused, repaired, replaced, or removed.
    """
    result = dict(SAFETY, state='NOT_REQUESTED', pair_atomic=False)
    if not input_name:
        return result
    owned = None
    try:
        match = re.fullmatch(r'kioxia_ticks_(\d{8})\.csv', input_name)
        if not match or source_root is None:
            raise ValueError('SOURCE_PATH_INVALID')
        day = match[1]
        datetime.strptime(day, '%Y%m%d')
        if diag_name is not None and diag_name != f'kioxia_tick_diag_{day}.csv':
            raise ValueError('DIAGNOSTIC_DATE_MISMATCH')
        source = _checked_path(source_root)
        root = _checked_path(repo_root)
        paths = [source / input_name]
        if diag_name is not None:
            paths.append(source / diag_name)
        raws = [_read(p) for p in paths]
        _validate(raws[0], TICK_HEADER, day)
        session_audit = audit_tick_sessions(raws[0])
        if diag_name is not None:
            _validate(raws[1], DIAG_HEADER, day)
        # Reuse ingress diagnostic semantics without interpreting them as proof.
        _, limitations, _ = _legacy_reasons(TICK_HEADER, _csv_table(raws[0])[1],
                                            raws[1] if diag_name is not None else None)
        if any(_read(p) != raw for p, raw in zip(paths, raws)):
            raise ValueError('SOURCE_CHANGED_DURING_READ')
        entries = [dict(name=p.name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                   for p, raw in zip(paths, raws)]
        token = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
        parent = root
        for component in ('data', 'private', 'ms2_csv_snapshots'):
            parent = parent / component
            if not parent.exists():
                parent.mkdir(mode=0o700)
            _checked_path(parent)
        destination = parent / (day + '_' + token)
        if any(p == destination or destination in p.parents for p in paths):
            raise ValueError('SOURCE_DESTINATION_OVERLAP')
        # Exclusive directory creation reserves this identity across processes.
        destination.mkdir(mode=0o700)
        owned = destination
        for entry, raw in zip(entries, raws):
            target = destination / entry['name']
            with target.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            saved = _read(target)
            if len(saved) != entry['size'] or hashlib.sha256(saved).hexdigest() != entry['sha256']:
                raise ValueError('PRESERVATION_READBACK_MISMATCH')
        manifest = dict(SAFETY, state='PRESERVED_UNAUTHENTICATED', pair_atomic=False,
                        pair_evidence='INDEPENDENT_FILE_READS_NOT_SIMULTANEOUS',
                        files=entries, limitations=limitations,
                        session_audit=session_audit)
        with (destination / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        owned = None
        return dict(result, state='PRESERVED_UNAUTHENTICATED', snapshot_id=destination.name)
    except (OSError, ValueError, TypeError):
        # Never echo exception text: it may contain private paths or CSV fields.
        return dict(result, state='BLOCKED', reason='SNAPSHOT_REFUSED')
    finally:
        if owned is not None:
            shutil.rmtree(owned)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--source-root')
    parser.add_argument('--input')
    parser.add_argument('--diag')
    args = parser.parse_args(argv)
    result = preserve_csv(args.repo_root, args.source_root, args.input, diag_name=args.diag)
    print(json.dumps(result, sort_keys=True))
    return int(result['state'] == 'BLOCKED')


if __name__ == '__main__':
    raise SystemExit(main())
