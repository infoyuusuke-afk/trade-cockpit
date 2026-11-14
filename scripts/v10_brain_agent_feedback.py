"""Brain -> specialist feedback loop for the Agents SDK research lane (no orders, no API call).

PROJECT_ITEM_ID: P0-100B-THREE-ANALYST-BRAIN-BIDIRECTIONAL-20261022

The forward direction already exists: the sidecar's signed envelope reaches the
Brain receiver, which stores a receipt and writes its own ACK. This module adds
the return direction and closes the loop inside the API lane:

1. Brain side (``process_feedback``, run by the Brain observer after each
   receiver pass): for every received run not yet evaluated, one feedback record
   per specialist report: verdict, evidence used, missing evidence, outcome
   (UNKNOWN until an outcome source is linked), measured EV/PF/N (UNKNOWN, never
   filled with backtest numbers) and exactly one improvement request. Records are
   stored in a private SQLite file and the newest per role is written as
   ``feedback/brain_feedback_<role>.json``, HMAC-signed.
2. Sidecar side (``load_latest_feedback`` / ``write_read_receipt``, used by the
   pilot): the next research run verifies each role's newest feedback and puts it
   into that role's model input as untrusted data; after the envelope is written
   it writes ``agent_feedback_read_<run_id>.json``, HMAC-signed, naming exactly
   which feedback_id (and its sha256) went into which role's input.
3. Brain side again: a verified read receipt marks those feedback records
   DELIVERED_TO_NEXT_RUN with the reading run_id. That is the evidence that the
   sender of the original report received the Brain's request in its next run.
   It is not evidence that the model followed it; that is judged from the next
   reports and later outcomes.

Keys: no new environment variable. Both directions use keys derived from the
existing bridge key (AGENT_BRIDGE_HMAC_KEY, held by the sidecar and by the
Brain, which verifies envelopes with it) with distinct labels, so a feedback
file, a read receipt and a research envelope can never be mistaken for one
another. The receiver key stays Brain-only (its ACKs are unchanged).

Revenue Hunter stays PROJECT_PROGRESS_NOT_TRADING: its feedback asks only for
verified revenue/cost records; estimated sales are never treated as realized.
The ChatGPT scheduled tasks are a different runtime: nothing here writes to them
or to GitHub (see docs/P0_100B_THREE_ANALYST_BRAIN_BIDIRECTIONAL.md).
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3

if __package__:
    from . import agent_sdk_brain_handoff as handoff
else:
    import agent_sdk_brain_handoff as handoff

FEEDBACK_SCHEMA = "100b-v10-brain-agent-feedback-v1"
READ_SCHEMA = "100b-agent-feedback-read-receipt-v1"
FEEDBACK_LABEL = b"100b-brain-feedback-v1"
READ_LABEL = b"100b-agent-feedback-read-v1"
DB_NAME = "brain_agent_feedback.sqlite"
RECEIPT_DB = "brain_agent_research_receipts.sqlite"
FEEDBACK_DIR = "feedback"
READ_PREFIX = "agent_feedback_read_"
FEEDBACK_VALID = timedelta(days=7)
MAX_FILE_BYTES = 65_536
ROLES = ("premarket", "pre_next", "supply_sq", "revenue_hunter")
RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{3,80}$")
REPORT_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}\.(premarket|pre_next|supply_sq|revenue_hunter)$")
SIG = re.compile(r"^[0-9a-f]{64}$")

# One concrete, testable request per role and report state (OWNER P0: 改善要求1件).
REQUESTS = {
    ("premarket", "NO_DATA"): "No dated overseas/macro source reached this role. Until one is connected, return NO_DATA; never infer the session from memory.",
    ("pre_next", "NO_DATA"): "No dated catalyst source reached this role. Return NO_DATA until a release-time-verified catalyst (issuer, code, time) is supplied.",
    ("supply_sq", "NO_DATA"): "No margin/futures figures reached this role. Use JPX 銘柄別信用取引残高 (all issues) when supplied; never the daily-publication list as a full-market view.",
    ("revenue_hunter", "NO_DATA"): "No verified revenue or cost record was supplied. Report UNKNOWN; estimated sales are not realized revenue.",
    ("premarket", "NO_SIGNAL"): "State which dated source would turn NO_SIGNAL into WATCH, so the Brain can check whether it later appeared (missed-signal audit).",
    ("pre_next", "NO_SIGNAL"): "Name the dated trigger (issuer, 4-character code such as 285A, available_at) that would put an issue on watch, so a later move can be audited as missed or correctly ignored.",
    ("supply_sq", "NO_SIGNAL"): "Name the per-issue margin change (code, sales/purchases, ratio, as-of date) that would put an issue on watch, so the Brain can audit false alerts and misses.",
    ("revenue_hunter", "NO_SIGNAL"): "List the one revenue experiment to verify next with its measurable success metric and cost; keep it out of the market lane.",
    ("premarket", "WATCH"): "Write each watched issue's 4-character code (e.g. 285A), why and for which session window. Monitoring only: the Brain makes every trading decision.",
    ("pre_next", "WATCH"): "Write each watched issue's 4-character code (e.g. 285A), the dated reason and the watch horizon (next session / next week), so the Brain can audit whether it moved before others saw it. Monitoring only; no buy/sell call.",
    ("supply_sq", "WATCH"): "Write each watched issue's code with the margin figures behind it, so the Brain can audit early detection and false alerts. Monitoring only; no buy/sell call.",
    ("revenue_hunter", "WATCH"): "Attach the verified revenue/cost record behind the WATCH, or mark it UNVERIFIED; it never feeds a trade.",
}
REQUESTS.update({(r, "UNAVAILABLE"): "The previous run failed for this role. Keep the output within the schema (texts under 600 characters) and cite only supplied source IDs."
                 for r in ROLES})
MISSING_ALLOWED = ("dated public source for this role", "cited evidence for the WATCH")
RECEIPT_MAX_AGE = timedelta(days=1)
RECEIPT_CLOCK_SKEW = timedelta(minutes=2)
VERDICTS = {"WATCH": "PENDING_OUTCOME", "NO_SIGNAL": "PENDING_VERIFICATION",
            "NO_DATA": "INSUFFICIENT_EVIDENCE", "UNAVAILABLE": "RUN_FAILED"}


class FeedbackBlocked(ValueError):
    """Fail closed: never deliver or accept an unverified record."""


def _key(label: bytes) -> bytes:
    try:
        base = handoff._key()
    except handoff.BridgeBlocked as exc:
        raise FeedbackBlocked("BRIDGE_KEY_MISSING_OR_INVALID") from exc
    return hmac.new(base, label, hashlib.sha256).digest()


def _sign(body: dict, label: bytes) -> str:
    return hmac.new(_key(label), handoff._canon(body), hashlib.sha256).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise FeedbackBlocked("FILE_MISSING_OR_LINK")
    raw = path.read_bytes()
    if not 2 <= len(raw) <= MAX_FILE_BYTES:
        raise FeedbackBlocked("FILE_SIZE_INVALID")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise FeedbackBlocked("FILE_JSON_INVALID") from exc


def _verify(wrapper: dict, schema: str, label: bytes) -> dict:
    if (type(wrapper) is not dict or set(wrapper) != {"schema_version", "body", "hmac_sha256"}
            or wrapper["schema_version"] != schema or not SIG.fullmatch(str(wrapper["hmac_sha256"]))
            or type(wrapper["body"]) is not dict):
        raise FeedbackBlocked("WRAPPER_INVALID")
    if not hmac.compare_digest(_sign(wrapper["body"], label), wrapper["hmac_sha256"]):
        raise FeedbackBlocked("SIGNATURE_INVALID")
    body = wrapper["body"]
    if body.get("real_submit_allowed") is not False or body.get("trade_instruction") is not False:
        raise FeedbackBlocked("SAFETY_FLAGS_INVALID")
    return body


def _wrap(body: dict, schema: str, label: bytes) -> bytes:
    return handoff._canon({"schema_version": schema, "body": body, "hmac_sha256": _sign(body, label)}) + b"\n"


# ---------------------------------------------------------------- Brain side

def evaluate_report(report: dict, *, run_id: str, now: datetime) -> dict:
    """Deterministic feedback for one received report. No model, no guess."""
    role, status = report["role"], report["status"]
    if role not in ROLES or status not in VERDICTS:
        raise FeedbackBlocked("REPORT_ROLE_OR_STATUS_INVALID")
    missing = []
    if status == "NO_DATA":
        missing.append("dated public source for this role")
    if status == "WATCH" and not report.get("evidence_ids"):
        missing.append("cited evidence for the WATCH")
    return {
        "feedback_id": "fb." + report["report_id"],
        "in_reply_to": report["report_id"],
        "run_id": run_id,
        "role": role,
        "lane": report["lane"],
        "evaluated_at": _iso(now),
        "expires_at": _iso(now + FEEDBACK_VALID),
        "report_status": status,
        "verdict": VERDICTS[status],
        "evidence_ids_used": list(report.get("evidence_ids") or []),
        "missing_evidence": missing,
        # Outcome audit (MISSED_SIGNAL / FALSE_ALERT) needs a structured code and
        # direction plus recorded prices; until the report carries them it is UNKNOWN.
        "outcome": {"state": "UNKNOWN", "reason": "NO_STRUCTURED_CODE_DIRECTION_TO_SCORE" if role != "revenue_hunter"
                    else "NO_VERIFIED_REVENUE_RECORD"},
        "measured": {"ev_pct": None, "pf": None, "n": None, "status": "UNKNOWN"},
        "improvement_request": REQUESTS[(role, status)],
        "real_submit_allowed": False,
        "trade_instruction": False,
    }


def _connect(root: Path) -> sqlite3.Connection:
    db = root / DB_NAME
    if db.is_symlink():
        raise FeedbackBlocked("FEEDBACK_DB_LINK_UNTRUSTED")
    conn = sqlite3.connect(str(db), timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feedback ("
        " feedback_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, role TEXT NOT NULL,"
        " created_at TEXT NOT NULL, wrapper BLOB NOT NULL, sha256 TEXT NOT NULL,"
        " state TEXT NOT NULL CHECK (state IN ('ISSUED','DELIVERED_TO_NEXT_RUN')),"
        " delivered_run_id TEXT, delivered_at TEXT,"
        " real_submit_allowed INTEGER NOT NULL CHECK (real_submit_allowed = 0))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS read_receipts ("
        " run_id TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL, verified_at TEXT NOT NULL,"
        " state TEXT NOT NULL, reason TEXT)")
    return conn


def _received_runs(root: Path) -> list[tuple[str, dict]]:
    db = root / RECEIPT_DB
    if not db.is_file() or db.is_symlink():
        return []
    with closing(sqlite3.connect("file:" + str(db) + "?mode=ro", uri=True, timeout=10)) as conn:
        rows = conn.execute("SELECT run_id, ack_bytes FROM receipts ORDER BY received_at").fetchall()
    return [(run_id, json.loads(bytes(ack).decode("utf-8"))) for run_id, ack in rows]


def _write_latest(folder: Path, role: str, wrapper: bytes) -> None:
    folder.mkdir(exist_ok=True)
    target = folder / ("brain_feedback_" + role + ".json")
    if target.is_file() and not target.is_symlink() and target.read_bytes() == wrapper:
        return  # unchanged: not rewritten every pass
    temp = folder / ("brain_feedback_" + role + ".json.tmp")
    with temp.open("wb") as stream:
        stream.write(wrapper)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(target)


def _envelope_state(root: Path, run_id: str):
    """The run state from the received envelope itself (signature checked, age not), so
    api vs offline is not taken from the receipt's own claim. None if unreadable."""
    try:
        wrapper = _read_json(root / ("agent_research_" + run_id + ".json"))
        payload = wrapper["payload"]
        if not hmac.compare_digest(hmac.new(handoff._key(), handoff._canon(payload), hashlib.sha256).hexdigest(),
                                   str(wrapper["hmac_sha256"])):
            return None
        return payload["research"]["state"] if payload.get("run_id") == run_id else None
    except (FeedbackBlocked, handoff.BridgeBlocked, KeyError, TypeError, ValueError):
        return None


def process_feedback(private_dir, *, now: datetime) -> dict:
    """Issue feedback for newly received runs, then verify read receipts. Idempotent."""
    now = handoff._now(now)
    root = handoff._private_dir(private_dir)
    issued, delivered, rejected = 0, 0, []
    received = dict(_received_runs(root))
    with closing(_connect(root)) as conn:
        for run_id, ack in received.items():
            for report in ack.get("roles", []):
                try:
                    body = evaluate_report(report, run_id=run_id, now=now)
                except (FeedbackBlocked, KeyError, TypeError) as exc:  # one bad report never stops the others
                    rejected.append(run_id + ":" + str(report.get("role")) + ":" + type(exc).__name__)
                    continue
                if conn.execute("SELECT 1 FROM feedback WHERE feedback_id = ?", (body["feedback_id"],)).fetchone():
                    continue
                wrapper = _wrap(body, FEEDBACK_SCHEMA, FEEDBACK_LABEL)
                conn.execute(
                    "INSERT INTO feedback (feedback_id, run_id, role, created_at, wrapper, sha256, state,"
                    " real_submit_allowed) VALUES (?,?,?,?,?,?,'ISSUED',0)",
                    (body["feedback_id"], run_id, body["role"], body["evaluated_at"], wrapper,
                     hashlib.sha256(wrapper).hexdigest()))
                issued += 1
        # newest issued feedback per role is what the next run reads
        for role in ROLES:
            row = conn.execute("SELECT wrapper FROM feedback WHERE role = ? ORDER BY created_at DESC, feedback_id DESC"
                               " LIMIT 1", (role,)).fetchone()
            if row:
                _write_latest(root / FEEDBACK_DIR, role, bytes(row[0]))
        for path in sorted(root.glob(READ_PREFIX + "*.json")):
            run_id = path.name[len(READ_PREFIX):-len(".json")]
            if not RUN_ID.fullmatch(run_id) or conn.execute("SELECT 1 FROM read_receipts WHERE run_id = ?",
                                                             (run_id,)).fetchone():
                continue
            if run_id not in received:
                continue  # audit 6327787186: not received yet -> judged once the run is received
            raw = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
            try:
                body = _verify(_read_json(path), READ_SCHEMA, READ_LABEL)
                if body.get("run_id") != run_id or type(body.get("delivered")) is not list:
                    raise FeedbackBlocked("READ_RECEIPT_FIELDS_INVALID")
                # audit 6326093087: only a run the Brain itself received, made by the paid API
                # runner, written after the feedback existed and recently, and only roles whose
                # model was called in that run.
                if body.get("runner") != "api" or _envelope_state(root, run_id) != "RESEARCH_ONLY_NOT_LIVE":
                    raise FeedbackBlocked("READ_RECEIPT_NOT_AN_API_RUN")
                written = handoff._dt(body["written_at"])
                if written > now + RECEIPT_CLOCK_SKEW or now - written > RECEIPT_MAX_AGE:
                    raise FeedbackBlocked("READ_RECEIPT_STALE_OR_FUTURE")
                called = {r.get("role") for r in received[run_id].get("roles", []) if r.get("status") != "NO_DATA"}
                for item in body["delivered"]:
                    row = conn.execute("SELECT sha256, role, state, created_at FROM feedback WHERE feedback_id = ?",
                                       (item.get("feedback_id"),)).fetchone()
                    if not row or row[0] != item.get("feedback_sha256") or row[1] != item.get("role"):
                        raise FeedbackBlocked("READ_RECEIPT_FEEDBACK_UNKNOWN_OR_CHANGED")
                    if not handoff._dt(row[3]) < written:
                        raise FeedbackBlocked("READ_RECEIPT_BEFORE_FEEDBACK")
                    if item.get("role") not in called:
                        raise FeedbackBlocked("READ_RECEIPT_ROLE_NOT_CALLED")
                for item in body["delivered"]:
                    cur = conn.execute("UPDATE feedback SET state='DELIVERED_TO_NEXT_RUN', delivered_run_id=?, delivered_at=?"
                                       " WHERE feedback_id = ? AND state = 'ISSUED'",
                                       (run_id, _iso(now), item["feedback_id"]))
                    delivered += cur.rowcount   # only rows actually changed are counted
                state, reason = "VERIFIED", None
            except FeedbackBlocked as exc:
                state, reason = "REJECTED", str(exc)
                rejected.append(run_id)
            conn.execute("INSERT INTO read_receipts (run_id, receipt_sha256, verified_at, state, reason) VALUES (?,?,?,?,?)",
                         (run_id, hashlib.sha256(raw).hexdigest(), _iso(now), state, reason))
        counts = dict(conn.execute("SELECT state, COUNT(*) FROM feedback GROUP BY state").fetchall())
    return {"feedback": "PASS", "issued": issued, "delivered": delivered, "rejected_receipts": rejected,
            "states": counts, "real_submit_allowed": False}


CODE_IN_TEXT = re.compile(r"(?<![0-9A-Za-z])([0-9][0-9A-Z]{2}[0-9A-Z])(?![0-9A-Za-z])")


def specialist_watch_codes(private_dir, *, now: datetime, known_codes) -> dict:
    """OWNER 2026-10-22: specialists watch the market and pick issues to watch ahead; the
    Brain decides. Codes named in unexpired WATCH reports of the market lanes, restricted
    to the cockpit's own universe (known_codes), as code -> [{role, report_id, expires_at}]."""
    root = handoff._private_dir(private_dir)
    known = {str(c).upper() for c in known_codes}
    out = {}
    for run_id, ack in _received_runs(root):
        for report in ack.get("roles", []):
            if (report.get("status") != "WATCH" or report.get("lane") != "MARKET_RESEARCH_NOT_EXECUTION"
                    or handoff._dt(report["expires_at"]) <= now):
                continue
            text = " ".join(str(report.get(k) or "") for k in ("hypothesis", "conditions"))
            for code in sorted(set(CODE_IN_TEXT.findall(text.upper())) & known):
                out.setdefault(code, []).append({"role": report["role"], "report_id": report["report_id"],
                                                 "expires_at": report["expires_at"]})
    return out


def feedback_status(private_dir) -> list[dict]:
    """Per-feedback state for the display / reports (no secret, no market data)."""
    root = handoff._private_dir(private_dir)
    db = root / DB_NAME
    if not db.is_file():
        return []
    with closing(sqlite3.connect("file:" + str(db) + "?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT feedback_id, role, created_at, state, delivered_run_id FROM feedback"
                            " ORDER BY created_at DESC LIMIT 40").fetchall()
    return [dict(zip(("feedback_id", "role", "created_at", "state", "delivered_run_id"), r)) for r in rows]


# ---------------------------------------------------------------- sidecar side

def load_latest_feedback(private_dir, *, now: datetime) -> dict:
    """role -> (feedback body, sha256 of the exact file) for verified, unexpired feedback.
    A missing, unsigned, tampered or expired file is skipped (that role gets none)."""
    now = handoff._now(now)
    root = handoff._private_dir(private_dir)
    out = {}
    for role in ROLES:
        path = root / FEEDBACK_DIR / ("brain_feedback_" + role + ".json")
        try:
            raw = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            if raw is None:
                continue
            body = _verify(_read_json(path), FEEDBACK_SCHEMA, FEEDBACK_LABEL)
            if body.get("role") != role or handoff._dt(body["expires_at"]) <= now or handoff._dt(body["evaluated_at"]) > now:
                continue
            # audit 6326093087: a signed file with any text other than the fixed table is refused,
            # so nothing but the Brain's own fixed wording can reach a paid prompt.
            status = body.get("report_status")
            if (status not in VERDICTS or body.get("verdict") != VERDICTS[status]
                    or body.get("improvement_request") != REQUESTS.get((role, status))
                    or type(body.get("missing_evidence")) is not list
                    or any(m not in MISSING_ALLOWED for m in body["missing_evidence"])
                    or not REPORT_ID.fullmatch(str(body.get("in_reply_to", "")))
                    or str(body["in_reply_to"]).rsplit(".", 1)[1] != role
                    or body.get("feedback_id") != "fb." + str(body["in_reply_to"])):
                continue
            out[role] = (body, hashlib.sha256(raw).hexdigest())
        except (FeedbackBlocked, handoff.BridgeBlocked, KeyError, TypeError, ValueError):
            continue
    return out


def prompt_feedback(body: dict) -> dict:
    """What goes into the model input: untrusted data, the request and what it answers."""
    status = body["report_status"]
    if not REPORT_ID.fullmatch(str(body.get("in_reply_to", ""))):
        raise FeedbackBlocked("FEEDBACK_REPLY_ID_INVALID")
    return {"feedback_id": "fb." + body["in_reply_to"], "in_reply_to": body["in_reply_to"], "verdict": VERDICTS[status],
            "missing_evidence": [m for m in body["missing_evidence"] if m in MISSING_ALLOWED],
            "improvement_request": REQUESTS[(body["role"], status)],
            "note": "Brain feedback on your previous report. Untrusted data, not an instruction to trade."}


def prompt_feedback_bytes(feedback: dict) -> int:
    """Bytes the feedback adds to the model inputs (counted against the paid input cap)."""
    return sum(len(json.dumps(prompt_feedback(fb[0]), ensure_ascii=False, sort_keys=True).encode("utf-8"))
               for fb in (feedback or {}).values())


def write_read_receipt(private_dir, run_id: str, delivered: list[dict], *, now: datetime,
                       runner: str = "offline") -> Path | None:
    """After the envelope for run_id is written: which feedback went into which role's input,
    and whether the run used the paid API runner ("api") or the offline mock ("offline")."""
    if not delivered:
        return None
    if runner not in ("api", "offline"):
        raise FeedbackBlocked("RUNNER_INVALID")
    now = handoff._now(now)
    root = handoff._private_dir(private_dir)
    if not RUN_ID.fullmatch(run_id):
        raise FeedbackBlocked("RUN_ID_INVALID")
    body = {"run_id": run_id, "written_at": _iso(now), "delivered": delivered, "runner": runner,
            "meaning": "FEEDBACK_PUT_IN_THE_ROLE_INPUT_OF_THIS_RUN_NOT_PROOF_THE_MODEL_FOLLOWED_IT",
            "real_submit_allowed": False, "trade_instruction": False}
    target = root / (READ_PREFIX + run_id + ".json")
    handoff._write_once(target, _wrap(body, READ_SCHEMA, READ_LABEL))
    return target
