"""Offline preflight for a future MS2 watcher sidecar hook.

Issue #350. The live watcher already stores a 10-level board in ``$board``
after one ``Read-BoardDepth`` call (forty sequential ``Value2`` reads). Draft
PR #349 can persist that object. This module checks where a later hook would
sit, and simulates that hook without opening Excel and without editing
``Kioxia_RSS_Live_Watcher.ps1``.

The hook that PR #349 sketched before the B4 price read is rejected here.
A blocking write on that side of the loop delays the current price, and an
exception in the shared try skips the sign and the voice for that cycle.
The shape that keeps price, sign, and voice off the writer path is a nested
try after those updates and after the Excel log writes, immediately before
the inner catch. ``Start-Sleep -Seconds 2`` stays where it is.

A synchronous fsync can still delay the start of that sleep by its own
duration. This module does not hide that. One overrun latches a process-local
kill switch so later polls skip the writer. There is no preemptive timeout
and no background thread. Windows checks stay ``NOT_VERIFIED``.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from scripts.ms2_offline_observation_writer import (
    WATCHER_INTEGRATION_APPLIED,
    WRITER_DEFAULT_ENABLED,
    WRITER_VERSION,
    record_captured_observation,
    watcher_integration_proposal,
)
from scripts.ms2_watcher_sidecar_contract import PIT_SCHEMA_VERSION, SCHEMA_VERSION

PREFLIGHT_VERSION = "ms2-watcher-integration-preflight-0.1"
AUDITED_MAIN_SHA = "3db9267a7f1bd0d26a7f9cce50678378ace78fb0"
AUDITED_WRITER_COMMIT = "0b41bc66ea4160e3382c75b5532c68d15dced57a"
AUDITED_CONTRACT_COMMIT = "ce2f43b66cbb138320da8813d90f59b8cb909da0"
WATCHER_RELATIVE = "ms2_live/Kioxia_RSS_Live_Watcher.ps1"
ACCEPTED_PLACEMENT = "AFTER_EXCEL_WRITES"
REJECTED_PLACEMENT = "BEFORE_B4"
POLL_SLEEP_SECONDS = 2
EXISTING_BOARD_COM_READS = 40
_BOARD_CALL = re.compile(r"\$board\s*=\s*@\(\s*Read-BoardDepth\b")
_BOARD_NAME = re.compile(r"\$board(?![A-Za-z0-9_])")
_LOOP = re.compile(r"for\s*\(\s*\$lvl\s*=\s*1\s*;\s*\$lvl\s*-le\s*(\d+)\s*;\s*\$lvl\+\+\s*\)")
_PINNED = (
    "scripts/ms2_watcher_sidecar_contract.py",
    "scripts/ms2_offline_observation_writer.py",
    WATCHER_RELATIVE,
    "ms2_live/Resample_Kioxia_Ticks_15s.ps1",
    "scripts/execution_contract.py",
    "scripts/shadow_fill_model.py",
    "scripts/fill_execution_collector_contract.py",
    "paper_trade_history.json",
)


def shutoff_budget_ms() -> int:
    raw = watcher_integration_proposal().get("shutoff_elapsed_ms")
    if type(raw) is int and 0 < raw <= 1000:
        return raw
    return 50


def new_session() -> dict:
    return {
        "killed": False,
        "writer_calls": 0,
        "hook_com_reads": 0,
        "modeled_existing_board_reads": 0,
    }


def _seal(report: dict) -> dict:
    sealed = dict(report)
    reasons = set(sealed.get("reasons") or []) | {"ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"}
    if sealed.get("close_state") == "CLOSED" or sealed.get("closed_eligible") is True:
        sealed["close_state"] = "NOT_CLOSED"
        reasons.add("CLOSE_CLAIM_REFUSED")
    if sealed.get("pit_evidence_origin") == "RECORDED":
        sealed["pit_evidence_origin"] = None
        reasons.add("RECORDED_ORIGIN_REFUSED")
    sealed["reasons"] = sorted(reasons)
    sealed["real_submit_allowed"] = False
    sealed["promotion_eligible"] = False
    sealed["statistical_edge_confirmed"] = False
    sealed["com_reads_added"] = 0
    sealed["watcher_modified"] = False
    sealed["applied"] = False
    sealed["eligible_observed_n"] = 0
    sealed["closed_eligible"] = False
    sealed["autostart"] = False
    sealed["rss_order_enabled"] = False
    return sealed


def _local_hook(status: str, transition: str, reasons: list[str], *, elapsed: int = 0) -> dict:
    contract = "NOT_READ" if status in {"DISABLED", "DROPPED"} else "BLOCKED"
    return _seal({
        "writer_status": status,
        "contract_status": contract,
        "decision_state": status if status in {"DISABLED", "DROPPED"} else "BLOCKED",
        "close_state": "NOT_CLOSED",
        "transition": transition,
        "reasons": reasons,
        "elapsed_ms": elapsed,
        "writes_performed": False,
        "writer_invoked": False,
    })


def trace_watcher_text(text: str) -> dict:
    """Locate the board read and the safe hook anchors. Does not write the script."""
    lines = text.splitlines()
    reasons: list[str] = []

    def line_no(index: int | None) -> int | None:
        if index is None:
            return None
        return index + 1

    def find_exact_start(prefix: str, start: int = 0) -> int | None:
        for index in range(start, len(lines)):
            if lines[index].startswith(prefix):
                return index
        return None

    start = find_exact_start("function Read-BoardDepth")
    nxt = find_exact_start("function ", (start + 1) if start is not None else 0)
    if start is None or nxt is None:
        reasons.append("WATCHER_SHAPE_UNKNOWN")
        body: list[str] = []
    else:
        body = lines[start:nxt]
    value2_sites = sum(1 for line in body if ".Value2" in line)
    cell_sites = sum(1 for line in body if "Cells.Item" in line)
    loop_match = _LOOP.search("\n".join(body))
    loop_bound = int(loop_match.group(1)) if loop_match else None
    per_level_catch = any("catch { continue }" in line for line in body)
    if loop_bound != 10 or value2_sites != 4 or cell_sites != 4 or not per_level_catch:
        reasons.append("BOARD_READ_SHAPE_CHANGED")

    def_lines = []
    call_lines = []
    comment_lines = []
    for index, line in enumerate(lines):
        if "Read-BoardDepth" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            comment_lines.append(index + 1)
        elif stripped.startswith("function Read-BoardDepth"):
            def_lines.append(index + 1)
        elif _BOARD_CALL.search(line):
            call_lines.append(index + 1)
        else:
            call_lines.append(index + 1)
            reasons.append("EXTRA_BOARD_READ")
    if len(def_lines) != 1 or len(call_lines) != 1:
        reasons.append("EXTRA_BOARD_READ")

    board_uses = [index + 1 for index, line in enumerate(lines) if _BOARD_NAME.search(line)]
    assignment = call_lines[0] - 1 if len(call_lines) == 1 else None

    def find_after(predicate, start_index: int) -> int | None:
        for index in range(start_index, len(lines)):
            if predicate(lines[index]):
                return index
        return None

    price = sign = json_write = voice = save = None
    if assignment is not None:
        price = find_after(lambda line: 'Range("B4").Value2' in line and "Get-SafeNumber" in line, assignment)
        if price == assignment:
            price = find_after(lambda line: 'Range("B4").Value2' in line and "Get-SafeNumber" in line, assignment + 1)
        sign = find_after(lambda line: 'Set-CellValue $calc.Range("B2")' in line, (price + 1) if price is not None else assignment)
        json_write = find_after(lambda line: "Write-AtomicUtf8 $watcherJsonPath" in line, (sign + 1) if sign is not None else assignment)
        voice = find_after(lambda line: "Invoke-SerializedSpeak $speaker" in line, (json_write + 1) if json_write is not None else assignment)
        save = find_after(lambda line: "$book.Save()" in line, (voice + 1) if voice is not None else assignment)
    sleep_candidates = [
        index for index, line in enumerate(lines)
        if line.strip() == "Start-Sleep -Seconds 2" and (voice is None or index > voice)
    ]
    sleep = sleep_candidates[0] if sleep_candidates else None
    catch = None
    if voice is not None and sleep is not None:
        for index in range(sleep - 1, voice, -1):
            if lines[index].strip() == "} catch {":
                catch = index
                break
    insert_after = None
    if catch is not None and voice is not None:
        cursor = catch - 1
        while cursor > voice and not lines[cursor].strip():
            cursor -= 1
        insert_after = cursor

    anchors = (assignment, price, sign, json_write, voice, save, insert_after, catch, sleep)
    if any(item is None for item in anchors):
        reasons.append("WATCHER_SHAPE_UNKNOWN")
    elif not (assignment < price < sign < json_write < voice < save < insert_after < catch < sleep):
        reasons.append("ANCHOR_ORDER_INVALID")
    if "record_captured_observation" in text or "ms2_offline_observation_writer" in text or "ms2_watcher_integration_preflight" in text:
        reasons.append("WATCHER_ALREADY_REFERENCES_SIDECAR")

    status = "OK" if not reasons else "BLOCKED"
    modeled = EXISTING_BOARD_COM_READS if loop_bound == 10 and value2_sites == 4 else None
    return {
        "status": status,
        "reasons": sorted(set(reasons)),
        "watcher": WATCHER_RELATIVE,
        "read_board_depth_line": line_no(start),
        "read_board_depth_end_line": line_no(nxt - 1) if nxt is not None else None,
        "value2_sites_in_reader": value2_sites,
        "cell_sites_in_reader": cell_sites,
        "loop_bound": loop_bound,
        "per_level_catch": per_level_catch,
        "board_com_reads_per_poll": modeled,
        "extra_com_reads_in_watcher": 0,
        "reader_definition_lines": def_lines,
        "reader_call_lines": call_lines,
        "reader_comment_lines": comment_lines,
        "board_variable_lines": board_uses,
        "assignment_line": line_no(assignment),
        "price_line": line_no(price),
        "sign_line": line_no(sign),
        "json_line": line_no(json_write),
        "voice_line": line_no(voice),
        "excel_save_line": line_no(save),
        "insert_after_line": line_no(insert_after),
        "inner_catch_line": line_no(catch),
        "poll_sleep_line": line_no(sleep),
        "poll_sleep_seconds": POLL_SLEEP_SECONDS if sleep is not None else None,
        "snapshot_atomic": False,
        "sidecar_writer_in_watcher": False,
    }


def trace_watcher_file(path: Path) -> dict:
    data = Path(path).read_bytes()
    traced = trace_watcher_text(data.decode("utf-8"))
    traced["sha256"] = hashlib.sha256(data).hexdigest()
    traced["byte_length"] = len(data)
    return traced


def hook_plan(trace: dict) -> dict:
    """Implementation-grade plan. ``applied`` stays false. This is not approval."""
    shape_ok = trace.get("status") == "OK" and trace.get("board_com_reads_per_poll") == EXISTING_BOARD_COM_READS
    budget = shutoff_budget_ms()
    proposal = watcher_integration_proposal()
    return {
        "preflight_version": PREFLIGHT_VERSION,
        "applied": False,
        "watcher_modified": False,
        "owner_approval": "REQUIRED",
        "isolation_shape_ok": shape_ok,
        "default_enabled": False,
        "com_reads_added": 0,
        "calls_read_board_depth": False,
        "autostart": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "retries_inside_poll": 0,
        "blocking_lock": False,
        "lock_mode": "LOCK_EX_NONBLOCK",
        "budget_ms": budget,
        "drop_on_overload": True,
        "preemptive_timeout_available": False,
        "background_thread": False,
        "poll_sleep_seconds": POLL_SLEEP_SECONDS,
        "accepted_placement": ACCEPTED_PLACEMENT if shape_ok else None,
        "insert_after_line": trace.get("insert_after_line") if shape_ok else None,
        "insert_before_line": trace.get("inner_catch_line") if shape_ok else None,
        "call_order": [
            "Existing RSS Calculate, tick diff, and the single Read-BoardDepth stay unchanged (40 Value2 reads).",
            "Existing B4 price, B2 sign, dashboard JSON, voice, conditional workbook save, and pending evaluation cells finish first.",
            "Only then, and only when the process-local flag is exactly true and the kill switch is off, pass the $board list already in memory plus the existing poll_seq.",
            "The call sits in its own try. Failures are not rethrown and are not reported as the loop COM error.",
            "The inner catch and Start-Sleep -Seconds 2 stay on their current lines.",
        ],
        "rejected_placement": {
            "id": REJECTED_PLACEMENT,
            "source": "watcher_integration_proposal touch before the B4 price read",
            "proposal_applied": proposal.get("applied"),
            "isolation": "FAIL",
            "reason": "A blocking write before the B4 read delays the current price. An exception that escapes into the shared try skips the sign and the voice for that cycle.",
        },
        "kill_switch": {
            "name": "Ms2SidecarKilled",
            "scope": "process-local",
            "latches_when": ["writer status BLOCKED", "transition ISOLATED", "elapsed_ms above budget", "a COM read is requested by the hook"],
            "does_not_latch_when": ["flag off", "writer admitted within budget"],
            "effect": "Later polls skip the writer. Price, sign, voice, and the 2 second sleep still run.",
            "reset": "Process exit. The flag stays off unless a future approved patch turns it on again.",
        },
        "failure_isolation": {
            "disk_full": "reason DISK_FULL, no raise, critical path already finished, kill switch latches",
            "permission": "reason WRITE_FAILED, no raise, critical path already finished, kill switch latches",
            "file_lock": "nonblocking lock returns WRITE_LOCKED, no wait, kill switch latches",
            "corrupt_file": "DATA_CORRUPT, existing bytes kept, kill switch latches",
            "missing_or_naive_clock": "null stays null; a naive clock is TIMEZONE_UNKNOWN and is not given +09:00",
            "com_contention": "the hook receives no Excel object. A hook that asks for a cell read is refused and not called",
        },
        "cadence_limit": "One in-budget write does not change the sleep duration. One over-budget write delays the start of that sleep by the write duration, then the kill switch drops later writes. This is not a preemptive timeout.",
        "rollback": [
            "This preflight has no watcher delta. Rollback is: do not deploy a watcher patch.",
            "If a later patch is live: Ctrl+C the watcher console only. The existing finally sets RSS接続!B16 to 停止 and saves the workbook. Excel stays open.",
            "Do not Stop-Process Excel. Forced Excel termination is the known path to COM 0x80004002.",
            f"Restore Kioxia_RSS_Live_Watcher.ps1 from main {AUDITED_MAIN_SHA}. Leave kioxia_ticks, kioxia_tick_diag, and 気配値ログ.csv in place.",
            "A sidecar jsonl stays under data/private/ms2_sidecar. Do not upload it and do not delete the legacy market logs.",
        ],
        "sketch_not_applied": (
            "if ($script:Ms2SidecarEnabled -eq $true -and $script:Ms2SidecarKilled -ne $true) {\n"
            "    try {\n"
            "        # $board is already in memory. Do not read another cell.\n"
            "        $sidecar = Invoke-CapturedBoardSidecar -Board $board -PollSeq $script:tickPollSeq\n"
            "        if ($sidecar.Blocked -or $sidecar.ElapsedMs -gt 50) { $script:Ms2SidecarKilled = $true }\n"
            "    } catch {\n"
            "        $script:Ms2SidecarKilled = $true\n"
            "    }\n"
            "}"
        ),
    }


def windows_acceptance_protocol() -> list[dict]:
    """OWNER steps for a closed market. None of these ran in this change."""
    common_recovery = [
        "Watcherのコンソールだけで Ctrl+C する。",
        "finally が RSS接続!B16 を「停止」にし、ブックを保存する。Excelは開いたままにする。",
        "Excelを Stop-Process または taskkill しない。強制終了は失敗で、既知の COM 0x80004002 を招く。",
        "kioxia_ticks、kioxia_tick_diag、気配値ログ.csv は削除しない。",
        f"Watcherスクリプトを main {AUDITED_MAIN_SHA} のバイトへ戻す。",
        "sidecar の jsonl は data/private に残し、GitHubへ上げない。",
    ]
    return [
        {
            "id": "W1",
            "theme": "startup",
            "status": "NOT_VERIFIED",
            "this_pr_runs_it": False,
            "when": "市場が閉まっているときだけ。ザラバ中は始めない。Watcherが既に動いていないことをOWNERが確認してから行う。",
            "steps": [
                "このPRのパッチはWatcherへ入れない。監査済みの現行スクリプトを、サイドカーフラグなしで起動する。",
                "60秒見る。現在値、売買サイン、コンソールを目視する。",
                "data/private/ms2_sidecar が無いか、起動前とバイトが同じことを確認する。中身は公開しない。",
                "tick CSV と気配値ログのヘッダが起動前と同じことを確認する。ファイルはアップロードしない。",
            ],
            "pass": [
                "現在値の表示が少なくとも1回更新される。",
                "売買サインが凍結しない。市場外の既存表示のままでよい。",
                "音声は既存のサイン条件以外で鳴らない。",
                "ループが約2秒間隔で続く。",
                "private sidecar が増えない。",
            ],
            "abort": [
                "COMのエラーダイアログ、Excelの無応答、サイン凍結、5秒以上のポーリング空き、コンソールの終了。",
                "その時点で Ctrl+C し、フラグを足して続行しない。",
            ],
            "recovery": common_recovery,
        },
        {
            "id": "W2",
            "theme": "com_contention",
            "status": "NOT_VERIFIED",
            "this_pr_runs_it": False,
            "when": "市場が閉まっているときだけ。OWNERがWatcher改修を個別承認し、そのパッチがあるときだけ。このPRにはそのパッチが無い。",
            "steps": [
                "先にフラグなしで60秒の基準を取る。数えるのはポーリング遅れ、COMエラー件数、CPU、落ちた書込み件数だけとする。価格と板の生値は控えない。",
                "承認済みパッチに限り、明示フラグを60秒だけオンにする。Heartbeatと100銘柄収集器が動いていてよい。",
                "パッチ差分に Read-BoardDepth の再呼び出しと追加の Value2 が無いことを確認する。",
            ],
            "pass": [
                "フラグオンのCOMエラー件数が、フラグなしの基準より増えない。",
                "現在値、売買サイン、音声が更新を続ける。",
                "50msを超えた回数と、落ちた書込み件数が数として残る。",
                "private JSONLはPC内に留め、GitHubへ上げない。",
            ],
            "abort": [
                "RPC_E_CALL_REJECTED または VBA_E_IGNORE が増える。",
                "サインが凍る、ポーリングが空く、サイドカー例外がコンソールに出る。",
                "フラグをオフにして Ctrl+C する。",
            ],
            "recovery": common_recovery,
        },
        {
            "id": "W3",
            "theme": "storage_fault",
            "status": "NOT_VERIFIED",
            "this_pr_runs_it": False,
            "when": "市場が閉まっているときだけ。承認済みパッチがあるときだけ。",
            "steps": [
                "書込先を読み取り専用、満杯のボリューム、またはロックしたファイルにする。",
                "1ポーリングだけフラグをオンにする。",
            ],
            "pass": [
                "そのポーリングで現在値、音声、売買サインが更新される。",
                "2秒の待機が残る。",
                "失敗後はキルスイッチがオンになり、次のポーリングは書込みを再試行しない。",
                "Excelは開いたまま。",
            ],
            "abort": [
                "サインが止まる、音声が止まる、ループが終わる、Excelのダイアログが出る。",
            ],
            "recovery": common_recovery,
        },
        {
            "id": "W4",
            "theme": "graceful_stop",
            "status": "NOT_VERIFIED",
            "this_pr_runs_it": False,
            "when": "市場が閉まっているとき。現行Watcherの停止確認であり、サイドカーパッチは不要。",
            "steps": [
                "Watcherのコンソールだけで Ctrl+C する。",
                "Excelのプロセスは止めない。",
            ],
            "pass": [
                "RSS接続!B16 が「停止」になる。",
                "ブックは保存され、ExcelとMS2は起動したまま。",
                "WatcherがExcelを強制終了していない。",
                "既存の市場ログが残っている。",
                "戻したスクリプトのハッシュが監査済みWatcherと一致する。",
            ],
            "abort": [
                "Stop-Process Excel、taskkill、気配値ログまたは tick CSV の削除。これらは不合格。",
            ],
            "recovery": [
                "Excelを強制終了していた場合、その停止は失敗。通常の起動でExcelを開き直し、RSSを再接続する。自動発注はしない。",
                *common_recovery,
            ],
        },
    ]


def owner_cursor_steps() -> list[str]:
    return [
        "Cursorで New Agent を開く。",
        "Repository に infoyuusuke-afk/trade-cockpit を選ぶ。",
        "Branch は main ではなく、このDraft PRのブランチを選ぶ。",
        "W1からW4の操作、合格、中止、復旧をコピーする。",
        "Agentへ貼り付けて Enter を押す。",
        "返った報告をGPT統括へ戻す。実ファイルと口座情報は貼らない。",
        "この手順はWatcher改修、実機起動、mainマージ、実注文の承認ではない。",
    ]


def _file_sha256(root: Path, relative: str) -> str | None:
    path = root / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compatibility_report(repo_root) -> dict:
    root = Path(repo_root)
    history_rows = None
    history_path = root / "paper_trade_history.json"
    if history_path.is_file():
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, list):
            history_rows = len(payload)
    proposal = watcher_integration_proposal()
    return {
        "pr_347_schema": SCHEMA_VERSION,
        "pr_349_writer": WRITER_VERSION,
        "pr_349_writer_commit": AUDITED_WRITER_COMMIT,
        "pr_347_contract_commit": AUDITED_CONTRACT_COMMIT,
        "pr_345_pit_schema": PIT_SCHEMA_VERSION,
        "pr_343_evaluator_imported": False,
        "pr_345_ingress_imported": False,
        "forwards_recorded_evidence": False,
        "emits_virtual_close": False,
        "writer_default_enabled": WRITER_DEFAULT_ENABLED,
        "writer_integration_applied": WATCHER_INTEGRATION_APPLIED,
        "proposal_applied": proposal.get("applied"),
        "eligible_observed_n": 0,
        "history_rows": history_rows,
        "pinned_sha256": {relative: _file_sha256(root, relative) for relative in _PINNED},
        "note": "PR #343 and PR #345 are not ancestors of this branch. The PIT schema name is checked. The virtual-fill evaluator is not called.",
    }


def audit_bundle(repo_root) -> dict:
    root = Path(repo_root)
    watcher = root / WATCHER_RELATIVE
    trace = trace_watcher_file(watcher) if watcher.is_file() else {
        "status": "BLOCKED",
        "reasons": ["WATCHER_SHAPE_UNKNOWN"],
        "sha256": None,
    }
    plan = hook_plan(trace)
    safety = _seal({
        "preflight_version": PREFLIGHT_VERSION,
        "audited_main_sha": AUDITED_MAIN_SHA,
        "reasons": [],
        "expectancy_yen": None,
        "profit_factor": None,
        "max_drawdown_yen": None,
        "verified_net_pnl_yen": None,
        "remaining_to_10b_yen": None,
    })
    return {
        "trace": trace,
        "plan": plan,
        "windows": windows_acceptance_protocol(),
        "owner_cursor_steps": owner_cursor_steps(),
        "compatibility": compatibility_report(root),
        "safety": safety,
    }


def _snapshot(observed: dict) -> dict:
    return {
        "price": observed.get("price"),
        "sign": observed.get("sign"),
        "voice": observed.get("voice"),
    }


def _verdict(placement: str, critical_unchanged: bool, stretch: int, budget: int, hook_com: int) -> str:
    if hook_com != 0:
        return "FAIL_COM"
    if not critical_unchanged:
        return "FAIL_CRITICAL_PATH"
    if placement != ACCEPTED_PLACEMENT:
        return "FAIL_PLACEMENT"
    if stretch > budget:
        return "PASS_CRITICAL_CADENCE_STRETCHED"
    return "PASS_CRITICAL"


def _invoke_writer(session: dict, repo_root, relative, capture, *, enabled: bool, hooks, writer, excel_reader, budget: int) -> dict:
    if excel_reader is not None:
        session["killed"] = True
        report = _local_hook("BLOCKED", "ISOLATED", ["COM_READ_REFUSED"])
        report["session_effect"] = "LATCHED"
        return report
    if enabled is not True:
        report = _local_hook("DISABLED", "DISABLED", ["SIDECAR_DISABLED"])
        report["session_effect"] = "OPEN"
        return report
    if session["killed"]:
        report = _local_hook("DROPPED", "DROPPED", ["SIDECAR_KILLED"])
        report["session_effect"] = "DROPPED"
        return report
    session["writer_calls"] += 1
    started = time.perf_counter()
    try:
        produced = writer(repo_root, relative, capture, enabled=True, hooks=hooks)
    except Exception:
        produced = _local_hook("BLOCKED", "ISOLATED", ["WRITER_EXCEPTION"])
    if not isinstance(produced, dict):
        produced = _local_hook("BLOCKED", "ISOLATED", ["WRITER_EXCEPTION"])
    measured = int((time.perf_counter() - started) * 1000)
    reported = produced.get("elapsed_ms")
    elapsed = measured
    if type(reported) is int and reported > elapsed:
        elapsed = reported
    report = _seal(produced)
    report["elapsed_ms"] = elapsed
    report["writer_invoked"] = True
    blocked = report.get("writer_status") == "BLOCKED" or report.get("transition") == "ISOLATED"
    if blocked or elapsed > budget:
        session["killed"] = True
        report["session_effect"] = "LATCHED"
    else:
        report["session_effect"] = "OPEN"
    return report


def run_poll(session: dict, observed: dict, *, placement: str, enabled: bool = False,
             repo_root=None, relative: str | None = None, capture=None, hooks=None,
             writer=None, excel_reader=None) -> dict:
    """Simulate one poll. The accepted placement snapshots price, sign, and voice first."""
    if placement not in {ACCEPTED_PLACEMENT, REJECTED_PLACEMENT}:
        raise ValueError("PLACEMENT_UNKNOWN")
    if not isinstance(observed, dict):
        raise ValueError("OBSERVED_INVALID")
    budget = shutoff_budget_ms()
    original = _snapshot(observed)
    session["modeled_existing_board_reads"] += EXISTING_BOARD_COM_READS
    chosen = writer or record_captured_observation
    hook_args = {
        "session": session,
        "repo_root": repo_root,
        "relative": relative,
        "capture": capture,
        "enabled": enabled,
        "hooks": hooks,
        "writer": chosen,
        "excel_reader": excel_reader,
        "budget": budget,
    }

    if placement == REJECTED_PLACEMENT:
        hook = _invoke_writer(**hook_args)
        critical = _snapshot(observed)
        critical_delay = hook["elapsed_ms"]
        phases = ["sidecar", "price", "sign", "voice", "sleep"]
    else:
        critical = dict(original)
        hook = _invoke_writer(**hook_args)
        critical_delay = 0
        phases = ["price", "sign", "voice", "sidecar", "sleep"]

    stretch = hook["elapsed_ms"] if hook.get("writer_invoked") else 0
    state = hook["session_effect"]
    unchanged = critical == original
    return {
        "placement": placement,
        "phases": phases,
        "critical": critical,
        "critical_unchanged": unchanged,
        "critical_delay_ms": critical_delay,
        "cycle_stretch_ms": stretch,
        "sleep_seconds": POLL_SLEEP_SECONDS,
        "sleep_invoked": True,
        "hook": hook,
        "hook_com_reads": session["hook_com_reads"],
        "modeled_existing_board_reads": EXISTING_BOARD_COM_READS,
        "session_state": state,
        "killed": session["killed"],
        "writer_calls": session["writer_calls"],
        "budget_ms": budget,
        "verdict": _verdict(placement, unchanged, stretch, budget, session["hook_com_reads"]),
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "applied": False,
        "watcher_modified": False,
        "eligible_observed_n": 0,
    }


def measure_offline(repo_root, relative: str, capture: dict, *, polls: int, enabled: bool) -> dict:
    """Time the hook on synthetic captures. This is not a Windows measurement."""
    if polls < 1 or polls > 100:
        raise ValueError("POLL_COUNT_INVALID")
    samples = []
    over = 0
    budget = shutoff_budget_ms()
    for index in range(polls):
        session = new_session()
        item = dict(capture)
        item["poll_seq"] = index + 1
        item.pop("observation_id", None)
        result = run_poll(
            session,
            {"price": 100, "sign": "待機", "voice": "silent"},
            placement=ACCEPTED_PLACEMENT,
            enabled=enabled,
            repo_root=repo_root,
            relative=relative,
            capture=item,
        )
        samples.append(result["hook"]["elapsed_ms"])
        if result["cycle_stretch_ms"] > budget:
            over += 1
    ordered = sorted(samples)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) // 2
    return {
        "label": "OFFLINE_NOT_WINDOWS",
        "windows_performance": "NOT_VERIFIED",
        "preemptive_timeout_available": False,
        "polls": polls,
        "enabled": enabled is True,
        "min_ms": ordered[0],
        "median_ms": median,
        "max_ms": ordered[-1],
        "over_budget": over,
        "budget_ms": budget,
        "real_submit_allowed": False,
        "eligible_observed_n": 0,
    }


def redact_bundle(bundle: dict) -> dict:
    hidden = {"levels", "capture", "record", "price", "voice", "top", "pit_records"}
    if not isinstance(bundle, dict):
        return {}
    return {key: value for key, value in bundle.items() if key not in hidden}


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Offline MS2 watcher sidecar integration preflight. Writes nothing.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    json.dump(redact_bundle(audit_bundle(args.repo_root)), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
