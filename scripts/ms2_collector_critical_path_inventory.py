"""Static, OFFLINE Collector critical-path inventory (not a PowerShell parser).

This module does not execute PowerShell, read market/private data or connect to
MS2/Excel. Finding a sink is source risk evidence, not measured outage.
"""
from __future__ import annotations

from collections import Counter
import re

SCHEMA_VERSION = "ms2-collector-critical-path-inventory-0.1"

RULES = {
    "CSV_DIRECT_APPEND": r"(?m)^\s*Add-Content\s+-Encoding\s+UTF8\s+-Path\s+\$\w+Csv\b",
    "SAFE_APPEND_STILL_SYNCHRONOUS": r"\bInvoke-MS2SafeCsvAppend\b",
    "PER_POLL_HEADER_CHECK": r"(?m)^\s*Ensure-Csv\s+\$\w+Csv\b",
    "DIRECTORY_CREATE": r"\bNew-Item\s+-ItemType\s+Directory\b",
    "JSON_ATOMIC_WRITE": r"(?m)^\s*Write-AtomicUtf8\s+\$\w+",
    "ROWSET_WRITE": r"(?m)^\s*Write-CsvObjects\s+\$",
    "IMMUTABLE_SNAPSHOT_WRITE": r"\bWrite-ImmutableJson\s+\$",
    "EXCEL_COM_WRAPPER": r"\bInvoke-ExcelCom\b",
    "VOICE_INLINE": r"\bInvoke-SerializedSpeak\b",
    "EXTERNAL_WEB_GET": r"\bGet-Utf8WebContent\b",
    "SLEEP_IN_PATH": r"\bStart-Sleep\b",
    "FILE_READ": r"(?m)^\s*(?:try\s*\{\s*)?\$[\w]+\s*=\s*Get-Content\b",
}


def inspect(source: object) -> dict:
    out = {
        "schema_version": SCHEMA_VERSION,
        "status": "UNKNOWN_UNVERIFIED",
        "risk_counts": {},
        "main_loop_isolated": False,
        "disk_io_isolated": False,
        "excel_com_bounded_os_time": False,
        "monitor_continuity_verified": False,
        "actual_outage_count": None,
        "actual_latency_ms": None,
        "production_ready": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "eligible_observed_n": 0,
    }
    if not isinstance(source, str) or not source.strip():
        out["risk_counts"] = {"SOURCE_MISSING_OR_INVALID": 1}
        return out
    counts = Counter()
    for key, pattern in RULES.items():
        value = len(re.findall(pattern, source))
        if value:
            counts[key] = value
    if re.search(r"\[int\]\$Retries\s*=\s*240\b", source) and re.search(
        r"\[int\]\$DelayMilliseconds\s*=\s*250\b", source
    ):
        counts["EXCEL_COM_RETRY_SLEEP_POSSIBLE_MS"] = 240 * 250
    if re.search(r"\$maxAttempts\s*=\s*5\b", source) and re.search(
        r"Start-Sleep\s+-Milliseconds\s+150\b", source
    ):
        counts["FILE_REPLACE_RETRY_SLEEP_POSSIBLE_MS"] = 4 * 150
    if "while ($true)" in source:
        counts["SINGLE_MAIN_MONITOR_LOOP_SIGNATURE"] = 1
    out["risk_counts"] = dict(sorted(counts.items()))
    if counts.get("SINGLE_MAIN_MONITOR_LOOP_SIGNATURE") and any(
        counts.get(key) for key in ("CSV_DIRECT_APPEND", "SAFE_APPEND_STILL_SYNCHRONOUS",
                                    "JSON_ATOMIC_WRITE", "PER_POLL_HEADER_CHECK",
                                    "EXCEL_COM_WRAPPER")
    ):
        out["status"] = "CRITICAL_PATH_BLOCKING_RISKS_PRESENT"
    return out
