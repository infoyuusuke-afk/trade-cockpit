"""Fixed 2048-byte board record shared by the offline handoff and the PowerShell producer.

The layout is the record inside one queue slot. It does not open Excel, lock a
file, or import the Windows-incompatible ``fcntl`` writer. ``poll_seq`` is the
loop counter. ``snapshot_atomic`` is stored false on unpack. Missing sizes stay
absent. ``available_at`` is not copied into the slot.
"""
from __future__ import annotations

import struct
import sys
from datetime import datetime

from scripts.ms2_watcher_sidecar_contract import CURRENT_WATCHER_SOURCE, SAFETY_KEYS

RECORD_SIZE = 2048
MAGIC = b"NBH1"
_FRESHNESS = ("UNKNOWN", "OK", "STALE", "MISSING", "FUTURE")
_CLOCK_LIMIT = 40
_SOURCE_LIMIT = 120
_ID_LIMIT = 80
_SYMBOL_LIMIT = 32


def _put_text(buf: bytearray, offset: int, size: int, text: str) -> bool:
    raw = text.encode("utf-8")
    if len(raw) > size:
        return False
    buf[offset:offset + size] = raw.ljust(size, b"\0")
    return True


def _get_text(blob: bytes, offset: int, size: int) -> str:
    raw = blob[offset:offset + size].split(b"\0", 1)[0]
    return raw.decode("utf-8")


def _clock_problem(value) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        return "TIMESTAMP_INVALID"
    if len(value) > _CLOCK_LIMIT or sys.getsizeof(value) > 1024:
        return "TIMESTAMP_INVALID"
    text = value.strip()
    if text.endswith("Z") or "JST" in text or "Tokyo" in text or "Japan" in text:
        return "TIMEZONE_NOT_GUESSED"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "TIMESTAMP_INVALID"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "TIMEZONE_NOT_GUESSED"
    if parsed.microsecond % 1000 != 0:
        return "SUBMILLISECOND_UNRECORDED"
    return None


def _number(value, *, positive: bool):
    if type(value) is bool or sys.getsizeof(value) > 40:
        return "HOSTILE_VALUE", None
    if type(value) is int or type(value) is float:
        number = float(value)
        if number != number or number in {float("inf"), float("-inf")}:
            return "QTY_INVALID", None
        if positive and number <= 0:
            return "QTY_INVALID", None
        if not positive and number < 0:
            return "QTY_INVALID", None
        return None, number
    return "HOSTILE_VALUE", None


def _refuse(reason: str) -> dict:
    return {"ok": False, "reason": reason, "record": None}


def pack_capture(capture) -> dict:
    """Copy one board into a fixed record. Missing clocks and sizes stay absent.

    A naive clock is refused. It is not given a ``+09:00`` offset. ``poll_seq``
    is stored as the loop counter only. ``available_at`` is not copied.
    """
    if type(capture) is not dict:
        return _refuse("BOARD_INPUT_INVALID")
    if SAFETY_KEYS.intersection(capture) and any(capture.get(key) is True for key in SAFETY_KEYS):
        return _refuse("SAFETY_FLAG_REFUSED")
    if capture.get("capture_authenticated") not in (None, False):
        return _refuse("CAPTURE_AUTHENTICATION_REFUSED")
    if capture.get("fill_missing_with_zero") not in (None, False):
        return _refuse("QTY_ZERO_FILL_REFUSED")
    symbol = capture.get("symbol")
    market = capture.get("market")
    if type(symbol) is not str or not symbol or len(symbol) > _SYMBOL_LIMIT:
        return _refuse("SYMBOL_ABSENT")
    if market not in {"TSE", "JNX"}:
        return _refuse("MARKET_INVALID")
    poll = capture.get("poll_seq")
    if type(poll) is bool or type(poll) is not int or sys.getsizeof(poll) > 40 or not 1 <= poll <= 10**12:
        return _refuse("POLL_SEQ_INVALID")
    source = capture.get("source", "ms2-nonblocking-handoff-0.1")
    if type(source) is not str or not source.strip() or len(source) > _SOURCE_LIMIT:
        return _refuse("SOURCE_ABSENT")
    if source == CURRENT_WATCHER_SOURCE:
        return _refuse("WATCHER_SOURCE_HAS_NO_SIDECAR")
    observation_id = capture.get("observation_id")
    if observation_id is not None:
        if type(observation_id) is not str or not observation_id or len(observation_id) > _ID_LIMIT:
            return _refuse("OBSERVATION_ID_ABSENT")
    timezone = capture.get("timezone")
    if timezone is not None:
        if type(timezone) is not str or timezone in {"JST", "Asia/Tokyo"} or "Tokyo" in timezone or "Japan" in timezone:
            return _refuse("TIMEZONE_NOT_GUESSED")
    for name in ("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at"):
        problem = _clock_problem(capture.get(name)) if name in capture else None
        if problem:
            return _refuse(problem)
    if "available_at" in capture and capture.get("available_at") is not None:
        problem = _clock_problem(capture.get("available_at"))
        if problem and problem != "TIMEZONE_NOT_GUESSED":
            return _refuse(problem)
    levels = capture.get("levels")
    if type(levels) is not list:
        return _refuse("BOARD_INPUT_INVALID")
    if len(levels) > 10:
        return _refuse("DEPTH_LIMIT")
    numbers = []
    parsed_levels = []
    for item in levels:
        if type(item) is not dict:
            return _refuse("LEVEL_INVALID")
        number = item.get("Level", item.get("level"))
        if type(number) is not int or not 1 <= number <= 10:
            return _refuse("LEVEL_NUMBER_ABSENT")
        numbers.append(number)
        row = {"level": number}
        for price_key, out_key in (("AskPrice", "ask"), ("BidPrice", "bid"), ("ask", "ask"), ("bid", "bid")):
            if price_key in item and out_key not in row:
                raw = item.get(price_key)
                if raw is None:
                    row[out_key] = None
                else:
                    reason, number_value = _number(raw, positive=True)
                    if reason:
                        return _refuse(reason if reason != "HOSTILE_VALUE" else "BOOK_VALUE_TYPE_INVALID")
                    row[out_key] = number_value
        for qty_key, out_key in (("AskQty", "ask_qty"), ("BidQty", "bid_qty"), ("ask_qty", "ask_qty"), ("bid_qty", "bid_qty")):
            if qty_key in item and out_key not in row:
                raw = item.get(qty_key)
                if raw is None:
                    row[out_key] = None
                    row[out_key + "_known"] = False
                else:
                    reason, number_value = _number(raw, positive=False)
                    if reason:
                        return _refuse("QTY_INVALID" if reason != "HOSTILE_VALUE" else "BOOK_VALUE_TYPE_INVALID")
                    row[out_key] = number_value
                    row[out_key + "_known"] = True
        read_at = item.get("read_at", item.get("ReadAt"))
        if read_at is not None:
            problem = _clock_problem(read_at)
            if problem:
                return _refuse(problem)
            row["read_at"] = read_at.strip()
        parsed_levels.append(row)
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        return _refuse("LEVEL_SEQUENCE_GAP")
    freshness = capture.get("data_freshness", "UNKNOWN")
    if freshness not in _FRESHNESS:
        return _refuse("FRESHNESS_INVALID")
    gap = capture.get("gap")
    gap_flag = None
    if gap is not None:
        if type(gap) is not dict:
            return _refuse("GAP_DIAG_INVALID")
        for key in ("window_size", "overlap_with_prev", "new_appended"):
            raw = gap.get(key)
            if type(raw) is not int or raw < 0 or sys.getsizeof(raw) > 40:
                return _refuse("GAP_DIAG_INVALID")
        if type(gap.get("prev_poll_nonempty")) is not bool:
            return _refuse("GAP_DIAG_INVALID")
        if "suspected_gap" in gap and type(gap.get("suspected_gap")) is not bool:
            return _refuse("GAP_DIAG_INVALID")
        gap_flag = gap.get("suspected_gap")
    buf = bytearray(RECORD_SIZE)
    buf[0:4] = MAGIC
    buf[4] = 1
    buf[5] = len(parsed_levels)
    buf[6] = _FRESHNESS.index(freshness)
    flags = 0
    if "available_at" in capture and capture.get("available_at") is not None:
        flags |= 1
    if capture.get("snapshot_atomic") is True:
        flags |= 2
    if capture.get("exchange_sequence") is not None or capture.get("sequence_basis") == "EXCHANGE":
        flags |= 4
    if "synthetic" in source:
        flags |= 8
    buf[7] = flags
    struct_poll = int(poll).to_bytes(8, "little")
    buf[8:16] = struct_poll
    if not _put_text(buf, 16, _SYMBOL_LIMIT, symbol):
        return _refuse("SYMBOL_ABSENT")
    if not _put_text(buf, 48, 8, market):
        return _refuse("MARKET_INVALID")
    if observation_id is not None and not _put_text(buf, 56, _ID_LIMIT, observation_id):
        return _refuse("OBSERVATION_ID_ABSENT")
    if not _put_text(buf, 136, _SOURCE_LIMIT, source):
        return _refuse("SOURCE_ABSENT")
    clock_at = 256
    for name in ("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at"):
        raw = capture.get(name)
        if type(raw) is str and raw:
            if not _put_text(buf, clock_at, _CLOCK_LIMIT, raw.strip()):
                return _refuse("TIMESTAMP_INVALID")
        clock_at += _CLOCK_LIMIT
    level_at = clock_at
    for row in parsed_levels:
        ask_known = 1 if "ask" in row and row["ask"] is not None else 0
        bid_known = 1 if "bid" in row and row["bid"] is not None else 0
        ask_qty_known = 1 if row.get("ask_qty_known") else 0
        bid_qty_known = 1 if row.get("bid_qty_known") else 0
        buf[level_at] = row["level"]
        buf[level_at + 1] = ask_known | (bid_known << 1) | (ask_qty_known << 2) | (bid_qty_known << 3)
        struct.pack_into(
            "<dddd",
            buf,
            level_at + 8,
            float(row["ask"]) if ask_known else 0.0,
            float(row["bid"]) if bid_known else 0.0,
            float(row["ask_qty"]) if ask_qty_known else 0.0,
            float(row["bid_qty"]) if bid_qty_known else 0.0,
        )
        read_at = row.get("read_at") or ""
        if read_at and not _put_text(buf, level_at + 40, _CLOCK_LIMIT, read_at):
            return _refuse("TIMESTAMP_INVALID")
        level_at += 80
    if gap is not None:
        buf[1800] = 1
        buf[1801] = 0 if gap_flag is None else (1 if gap_flag else 2)
        buf[1802] = 1 if gap.get("prev_poll_nonempty") else 0
        buf[1808:1812] = int(gap["window_size"]).to_bytes(4, "little")
        buf[1812:1816] = int(gap["overlap_with_prev"]).to_bytes(4, "little")
        buf[1816:1820] = int(gap["new_appended"]).to_bytes(4, "little")
    if level_at > 1800:
        return _refuse("RECORD_LAYOUT")
    return {"ok": True, "reason": "PACKED", "record": bytes(buf), "flags": flags}


def unpack_capture(blob: bytes) -> dict | None:
    """Rebuild the writer capture. Exchange order and available_at stay absent."""
    if len(blob) != RECORD_SIZE or blob[0:4] != MAGIC or blob[4] != 1:
        return None
    import struct
    count = blob[5]
    freshness = _FRESHNESS[blob[6]] if blob[6] < len(_FRESHNESS) else "UNKNOWN"
    poll = int.from_bytes(blob[8:16], "little")
    symbol = _get_text(blob, 16, _SYMBOL_LIMIT)
    market = _get_text(blob, 48, 8)
    observation_id = _get_text(blob, 56, _ID_LIMIT)
    source = _get_text(blob, 136, _SOURCE_LIMIT)
    clocks = {}
    clock_at = 256
    for name in ("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at"):
        text = _get_text(blob, clock_at, _CLOCK_LIMIT)
        if text:
            clocks[name] = text
        clock_at += _CLOCK_LIMIT
    levels = []
    level_at = clock_at
    for _ in range(count):
        number = blob[level_at]
        mask = blob[level_at + 1]
        ask, bid, ask_qty, bid_qty = struct.unpack_from("<dddd", blob, level_at + 8)
        row = {"Level": number}
        if mask & 1:
            row["AskPrice"] = ask
        if mask & 2:
            row["BidPrice"] = bid
        if mask & 4:
            row["AskQty"] = ask_qty
        else:
            row["AskQty"] = None
        if mask & 8:
            row["BidQty"] = bid_qty
        else:
            row["BidQty"] = None
        read_at = _get_text(blob, level_at + 40, _CLOCK_LIMIT)
        if read_at:
            row["read_at"] = read_at
        levels.append(row)
        level_at += 80
    capture = {
        "symbol": symbol,
        "market": market,
        "poll_seq": poll,
        "kind": "BOARD_SNAPSHOT",
        "source": source,
        "sequence_basis": "POLL",
        "order_proven": False,
        "read_method": "SEQUENTIAL_CELL",
        "snapshot_atomic": False,
        "levels": levels,
        "data_freshness": freshness,
    }
    if observation_id:
        capture["observation_id"] = observation_id
    capture.update(clocks)
    if clocks.get("event_time"):
        capture["event_time_basis"] = "EXCHANGE_SUPPLIED"
    if blob[1800] == 1:
        gap = {
            "window_size": int.from_bytes(blob[1808:1812], "little"),
            "overlap_with_prev": int.from_bytes(blob[1812:1816], "little"),
            "prev_poll_nonempty": bool(blob[1802]),
            "new_appended": int.from_bytes(blob[1816:1820], "little"),
        }
        if blob[1801] == 1:
            gap["suspected_gap"] = True
        elif blob[1801] == 2:
            gap["suspected_gap"] = False
        capture["gap"] = gap
    return capture
