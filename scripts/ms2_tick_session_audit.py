"""Pure watcher tick session segmentation; no market authentication or orders.

A poll_seq decrease indicates a watcher-session boundary candidate, never
proof of source restart, exact downtime, missing exchange prints, or
exchange-order chronology. No input bytes are modified.
"""
from datetime import datetime
from scripts.ms2_observation_ingress import MAX_BYTES, TICK_HEADER, _csv_table

VERSION = "ms2-poll-session-audit-1"
STAMP = "%Y-%m-%d %H:%M:%S"


def audit_tick_sessions(raw: bytes, *, interval_alert_seconds: int = 60) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES or not raw.endswith(b"\n"):
        raise ValueError("SESSION_SOURCE_INVALID")
    if type(interval_alert_seconds) is not int or interval_alert_seconds < 1:
        raise ValueError("SESSION_INTERVAL_INVALID")
    header, rows = _csv_table(raw)
    if header != TICK_HEADER or not rows:
        raise ValueError("SESSION_HEADER_INVALID")
    segments, boundaries = [], []
    large_intervals = max_interval = time_reversals = 0
    prev_time = prev_poll = None
    segment_start = 1

    def close_session(last_index, last_poll, last_stamp):
        segments.append({
            "session_index": len(segments) + 1,
            "first_data_row": segment_start,
            "last_data_row": last_index,
            "row_count": last_index - segment_start + 1,
            "last_poll_seq": last_poll,
            "last_recorded_at": last_stamp.strftime(STAMP),
            "join_to_previous_session_allowed": False,
        })

    for index, row in enumerate(rows, 1):
        try:
            observed = datetime.strptime(row[0], STAMP)
            seq = row[4]
            if not seq.isascii() or not seq.isdecimal():
                raise ValueError("INVALID_POLL")
            poll = int(seq)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("SESSION_ROW_INVALID") from exc
        if prev_time is not None:
            delta = int((observed - prev_time).total_seconds())
            if delta < 0:
                time_reversals += 1
            elif delta > interval_alert_seconds:
                large_intervals += 1
                max_interval = max(max_interval, delta)
            if poll < prev_poll:
                close_session(index - 1, prev_poll, prev_time)
                boundaries.append({
                    "at_data_row": index,
                    "at_csv_line": index + 1,
                    "recorded_at": observed.strftime(STAMP),
                    "previous_poll_seq": prev_poll,
                    "current_poll_seq": poll,
                    "adjacent_append_clock_delta_seconds": delta,
                    "reason": "POLL_SEQ_DECREASE_RESTART_CANDIDATE",
                    "restart_confirmed_by_machine": False,
                    "capture_downtime_seconds": None,
                })
                segment_start = index
        prev_time, prev_poll = observed, poll

    close_session(len(rows), prev_poll, prev_time)
    return {
        "version": VERSION,
        "row_count": len(rows),
        "session_count": len(segments),
        "poll_reset_count": len(boundaries),
        "boundaries": boundaries,
        "segments": segments,
        "append_clock_reversal_count": time_reversals,
        "long_append_intervals_count": large_intervals,
        "max_long_append_interval_seconds": max_interval,
        "long_interval_alert_threshold_seconds": interval_alert_seconds,
        "gap_state": "UNKNOWN_NO_JOINED_DIAGNOSTIC",
        "verified_missing_tick_count": None,
        "capture_downtime_seconds": None,
        "clock_semantics": "WATCHER_APPEND_LOCAL_TIME_NO_OFFSET",
        "exchange_order_established": False,
        "cross_session_join_allowed": False,
        "source_authenticated": False,
        "eligible_observed_n": 0,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }
