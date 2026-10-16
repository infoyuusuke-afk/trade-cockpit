"""Offline legacy CSV quality counts; never promotes market or fill evidence."""
import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from scripts.private_broker_csv_preflight import MAX_BYTES, _number

HEADERS = {
    'ticks': 'recorded_at,tick_time,price,volume,poll_seq',
    'diag': 'poll_time,window_size,overlap_with_prev,new_appended,suspected_gap',
    'quotes': '日付,時刻,OVER気配数量,UNDER気配数量,UNDER比率,最良売気配値,最良買気配値,状態',
}

def audit_bytes(raw, kind, expected_date):
    """Deterministic byte audit. Naive clocks remain naive, freshness UNKNOWN."""
    reasons = Counter()
    total = 0
    duplicates = 0
    seen = set()
    previous = None
    previous_poll = None
    def flag(code): reasons[code] += 1
    try:
        datetime.strptime(expected_date, '%Y-%m-%d')
        if kind not in HEADERS: raise ValueError()
        if len(raw) > MAX_BYTES:
            flag('FILE_TOO_LARGE')
        else:
            text = raw.decode('utf-8-sig')
            if not text.endswith('\n'): flag('INCOMPLETE_FINAL_LINE')
            reader = csv.reader(io.StringIO(text, newline=''), strict=True)
            if next(reader, None) != HEADERS[kind].split(','):
                flag('HEADER_MISMATCH')
            else:
                for row in reader:
                    total += 1
                    if len(row) != len(HEADERS[kind].split(',')):
                        flag('ROW_SHAPE_INVALID'); continue
                    token = tuple(row)
                    if token in seen: duplicates += 1; flag('DUPLICATE_ROW')
                    seen.add(token)
                    try:
                        stamp = row[0] if kind != 'quotes' else row[0]+' '+row[1]
                        fmt = '%Y-%m-%d %H:%M' if kind == 'quotes' else '%Y-%m-%d %H:%M:%S'
                        moment = datetime.strptime(stamp, fmt)
                        if moment.strftime(fmt) != stamp: raise ValueError()
                        if moment.strftime('%Y-%m-%d') != expected_date: flag('DATE_MISMATCH')
                        if previous and moment < previous: flag('CLOCK_REGRESSION')
                        # Gap in rows is a suspicion, never a proven lost trade.
                        if previous and (moment-previous).total_seconds() > (120 if kind == 'quotes' else 10):
                            flag('RECORDING_INTERVAL_GAP_SUSPECTED')
                        previous = moment
                        if kind == 'ticks':
                            event = datetime.strptime(row[1], '%H:%M:%S')
                            if event.strftime('%H:%M:%S') != row[1]: raise ValueError()
                            if not _number(row[2], True) or not _number(row[3], True): flag('PRICE_VOLUME_INVALID')
                            poll = int(row[4])
                            if str(poll) != row[4] or poll < 1: raise ValueError()
                            if previous_poll is not None and poll < previous_poll: flag('POLL_RESET_OR_REGRESSION')
                            previous_poll = poll
                            key = ('tick', row[1], row[2], row[3])
                            if key in seen: flag('REPEATED_TICK_KEY')
                            seen.add(key)
                            # Tick order can be newest-first; no exchange ordering assertion.
                        elif kind == 'diag':
                            nums = [int(x) for x in row[1:4]]
                            if any(str(n) != s for n,s in zip(nums,row[1:4])) or min(nums)<0:
                                raise ValueError()
                            window, overlap, appended = nums
                            if window>300 or overlap>window or appended>window: flag('DIAG_COUNT_INVALID')
                            if row[4] not in ('True','False'): flag('GAP_BOOLEAN_INVALID')
                            if row[4]=='True': flag('GAP_SUSPECTED')
                            if window==0: flag('EMPTY_WINDOW_UNKNOWN')
                            if window>0 and overlap==0: flag('ZERO_OVERLAP_UNKNOWN')
                        else:
                            if not all(_number(x) for x in row[2:4]): flag('QUOTE_QUANTITY_INVALID')
                            if not row[4] or not _number(row[4]) or float(row[4])>1: flag('QUOTE_RATIO_INVALID')
                            if not all(_number(x, True) for x in row[5:7]): flag('BEST_QUOTE_MISSING_OR_INVALID')
                            flag('ZERO_AND_MISSING_QUANTITY_NOT_DISTINGUISHABLE')
                    except (ValueError, OverflowError): flag('FIELD_OR_TIME_INVALID')
    except (UnicodeError, csv.Error): flag('CSV_DECODE_OR_SYNTAX_INVALID')
    except (ValueError, TypeError): flag('AUDIT_ARGUMENT_INVALID')
    if total == 0: flag('EMPTY_OR_UNREADABLE')
    return {
        'schema_version':'ms2-legacy-quality-v1', 'kind':kind,
        'records_examined':total, 'duplicate_rows':duplicates, 'reasons':dict(sorted(reasons.items())),
        'status':'LEGACY_ONLY_BLOCKED', 'freshness':'UNKNOWN', 'timezone':'UNKNOWN',
        'exchange_order_proven':False, 'snapshot_atomic':False, 'fill_evidence_eligible':False,
        'eligible_observed_n':0, 'real_submit_allowed':False, 'promotion_eligible':False,
        'statistical_edge_confirmed':False,
    }

def audit_path(path, kind, expected_date):
    # Explicit offline file only, no directory discovery, COM, localhost or network.
    if str(path).startswith(('\\\\', '//')):
        raise ValueError('NETWORK_PATH_REFUSED')
    path = Path(path)
    current = path.absolute()
    for part in [current, *current.parents]:
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('FILE_LINK_REFUSED')
    if not path.is_file(): raise ValueError('FILE_MISSING')
    if path.stat().st_size>MAX_BYTES: raise ValueError('FILE_TOO_LARGE')
    # Bounded read; detect observed mutation. This is not an adversarial TOCTOU guarantee.
    before = path.stat()
    with path.open('rb') as source: raw=source.read(MAX_BYTES+1)
    after = path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('FILE_CHANGED_DURING_READ')
    return audit_bytes(raw,kind,expected_date)

def main(argv=None):
    p=argparse.ArgumentParser(description='Offline legacy CSV counts, source unchanged')
    p.add_argument('--input',required=True)
    p.add_argument('--kind',choices=HEADERS,required=True)
    p.add_argument('--date',required=True,help='explicit expected local date YYYY-MM-DD; no timezone inference')
    a=p.parse_args(argv)
    try: report=audit_path(a.input,a.kind,a.date)
    except (OSError,ValueError):
        report=audit_bytes(b'',a.kind,a.date)
        report['reasons']={'FILE_UNAVAILABLE_OR_UNSAFE':1}
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    # Quality counts complete is not a market decision PASS.
    return 2

if __name__=='__main__': raise SystemExit(main())
