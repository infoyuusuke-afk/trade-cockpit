"""Read-only exporter: AI Cockpit post-market files -> content_drop/<date>/ (daily_summary.v1).

Boundary
--------
* Reads ONLY the explicit input files it is given (``data.json`` stock snapshot and
  ``paper_trade_history.json``). Opened read-only; hashed before parsing and again
  after the export -- any change while exporting is fail-closed.
* Never writes next to, over, or into the inputs. Never imports AI Cockpit code,
  never talks to MS2/RSS or any process, never touches trading/order code.
* ALLOWLIST: only the fields listed in ``ALLOWLIST`` are copied. Everything else
  (share counts, yen P/L, fees, slippage, scores, strategy internals, source URLs...)
  is dropped, and the output is additionally scanned against ``DENY_KEYS``.
* Every exported record carries ``source_ref`` = {file, sha256, pointer} into the
  original input, so a published sentence traces back to the original bytes.
* Fail-closed on: missing file, unparseable JSON, schema errors, non-finite /
  inconsistent numbers, snapshot date != session, stale/premature snapshot,
  unknown trade result/side/source values, no verified quotes.
* Output is labelled ``data_class: "real"`` (fixtures are ``TEST_FIXTURE``).
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from ..clock import JST
from ..errors import EvidenceError, ValidationError
from ..hashing import sha256_bytes, sha256_file, write_atomic
from . import radar_import

EXPORTER = "auto_publish.cockpit_export"
EXPORTER_VERSION = "1"
NAMES_FILE = Path(__file__).resolve().parents[2] / "config" / "instrument_names_en.json"

ALLOWLIST = {
    "data.json": {
        "top": ["updated_at", "stocks"],
        "stock": ["ticker", "price", "prev_close", "change_pct", "rvol", "data_date", "ok", "quote_verified",
                  "identity_verified"],
        "stock_key": "display name '<name>（<code>）' -> name_ja",
    },
    "paper_trade_history.json": {
        "trade": ["date", "ticker", "side", "entry", "triggered", "result", "r", "source"],
    },
    "condition_log.csv": {
        "public": ["captured_at -> time_jst/detected_at_jst", "ticker", "name -> name_ja", "price",
                   "price vs vwap -> vwap_relation (vwap itself stays internal)",
                   "or5_long/or5_short/or15_long/or15_short/pullback_long/pullback_short -> event + direction"],
        "internal_only": radar_import.INTERNAL_FIELDS,
    },
}
DATA_CLASSES = ("real", "fixture")
FIXTURE_TICKER_RE = re.compile(r"^TST[0-9A-Z]\.T$")
# Output fields that exist (after mapping) -- anything else in the output is a bug.
OUTPUT_MOVER_KEYS = {"ticker", "name_en", "name_ja", "name_en_source", "close", "change_pct", "volume_ratio",
                     "source_ref"}
OUTPUT_TRADE_KEYS = {"date", "ticker", "side", "entry", "triggered", "closed", "outcome", "r", "basis", "source_ref"}

# Defence in depth: none of these may ever appear anywhere in the export output.
DENY_KEYS = {
    "shares", "qty", "quantity", "pnl", "pnl_yen", "fees", "slippage", "simulated_fill", "account", "account_id",
    "order", "order_id", "orders", "position", "positions", "holdings", "balance", "cash", "margin", "broker",
    "password", "token", "secret", "api_key", "email", "phone", "address", "turnover", "stop", "target1",
    "target2", "entry_limit", "entry_trigger", "strategy_id", "strategy_version", "score", "day_score",
    "swing_score", "mfe", "mae",
}

RESULT_MAP = {
    # result text -> (triggered expected, outcome, closed)  ; None outcome = excluded
    "IFO利確1": (True, "target1", True),
    "IFO損切り": (True, "stop", True),
    "大引け決済": (True, "close_exit", True),
    "時点評価・未決済": (True, "open_mark", False),
    "未発動（見送り）": (False, None, None),
    "順序不明（成績除外）": (True, None, None),
}
ALLOWED_TRADE_SOURCES = {None, "morning_snapshot"}
TICKER_RE = re.compile(r"^[0-9A-Z]{4}\.T$")
NAME_KEY_RE = re.compile(r"^(?P<name>.+)（(?P<code>[0-9A-Z]{4})）$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _finite(v, where: str, *, positive: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValidationError(f"{where} must be a finite number (got {v!r})", code="INVALID_VALUE")
    if positive and v <= 0:
        raise ValidationError(f"{where} must be > 0 (got {v!r})", code="INVALID_VALUE")
    return float(v)


def _read_input(path: Path, role: str) -> tuple[object, dict]:
    if not path.is_file():
        raise EvidenceError(f"{role} input not found: {path.name}", code="EXPORT_INPUT_MISSING")
    if path.is_symlink():
        raise EvidenceError(f"{role} input must not be a symlink", code="EVIDENCE_SYMLINK")
    with open(path, "rb") as fh:  # read-only
        raw = fh.read()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{role} is not valid UTF-8 JSON: {exc}", code="SCHEMA_INVALID") from exc
    return doc, {"role": role, "file": path.name, "sha256": sha256_bytes(raw), "bytes": len(raw), "_path": path}


def _parse_updated_at(value) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("data.json updated_at missing", code="SCHEMA_INVALID")
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2}) JST$", value)
    if not m:
        raise ValidationError(f"data.json updated_at has unexpected format {value!r}", code="SCHEMA_INVALID")
    d, hh, mm, ss = m.groups()
    return datetime.combine(date.fromisoformat(d), time(int(hh), int(mm), int(ss)), tzinfo=JST)


def _load_names(path: Path | None) -> dict:
    p = path or NAMES_FILE
    return json.loads(p.read_text(encoding="utf-8")).get("names", {})


def _deny_scan(obj, where: str = "") -> list[str]:
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in DENY_KEYS:
                hits.append(f"{where}/{k}")
            hits.extend(_deny_scan(v, f"{where}/{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(_deny_scan(v, f"{where}/{i}"))
    return hits


def build_export(
    session_date: str,
    data_json: Path,
    paper_history: Path,
    *,
    market_close_jst: str = "15:30",
    max_age_hours: float = 18.0,
    max_movers: int = 10,
    names_file: Path | None = None,
    condition_log: Path | None = None,
    data_class: str = "real",
) -> dict:
    """Pure transform (reads inputs, returns the files to write). No writes here."""
    if data_class not in DATA_CLASSES:
        raise ValidationError(f"data_class must be one of {DATA_CLASSES}", code="SCHEMA_INVALID")
    if not DATE_RE.match(session_date or ""):
        raise ValidationError(f"bad session date {session_date!r}")
    sess = date.fromisoformat(session_date)
    if sess.weekday() >= 5:
        raise ValidationError(f"{session_date} is a weekend", code="NOT_TRADING_DAY")
    data_json, paper_history = Path(data_json).resolve(), Path(paper_history).resolve()
    snap, snap_meta = _read_input(data_json, "data.json")
    trades_doc, paper_meta = _read_input(paper_history, "paper_trade_history.json")
    excluded_records: list[dict] = []

    # ---------------- snapshot: freshness + date
    if not isinstance(snap, dict) or not isinstance(snap.get("stocks"), dict):
        raise ValidationError("data.json must be an object with a 'stocks' object", code="SCHEMA_INVALID")
    updated = _parse_updated_at(snap.get("updated_at"))
    hh, mm = map(int, market_close_jst.split(":"))
    close_at = datetime.combine(sess, time(hh, mm), tzinfo=JST)
    if updated < close_at:
        raise ValidationError(f"snapshot {updated.isoformat()} is before the {session_date} close",
                              code="EVIDENCE_PREMATURE")
    if updated > close_at + timedelta(hours=max_age_hours):
        raise ValidationError(f"snapshot {updated.isoformat()} is too old/new for session {session_date}",
                              code="EVIDENCE_STALE")

    names_en = _load_names(names_file)
    eligible: dict[str, dict] = {}
    for key in sorted(snap["stocks"]):
        s = snap["stocks"][key]
        ptr = "/stocks/" + _escape(key)
        if not isinstance(s, dict):
            raise ValidationError(f"stock {key!r} is not an object", code="SCHEMA_INVALID")
        if s.get("ok") is not True:
            excluded_records.append({"kind": "stock", "pointer": ptr, "reason": "ok != true"})
            continue
        if s.get("data_date") != session_date:
            raise ValidationError(
                f"stock {key!r} data_date {s.get('data_date')!r} != session {session_date}", code="DATE_MISMATCH")
        ticker = s.get("ticker")
        m = NAME_KEY_RE.match(key)
        if not isinstance(ticker, str) or not TICKER_RE.match(ticker) or not m or m["code"] != ticker[:-2]:
            raise ValidationError(f"stock {key!r}: ticker/name inconsistent ({ticker!r})", code="SCHEMA_INVALID")
        if bool(FIXTURE_TICKER_RE.match(ticker)) != (data_class == "fixture"):
            raise ValidationError(f"{ticker}: fixture tickers (TST*) and real tickers must never mix "
                                  f"(export data_class={data_class})", code="DATA_CLASS_MIXED")
        if s.get("quote_verified") is not True or s.get("identity_verified") is not True:
            excluded_records.append({"kind": "stock", "pointer": ptr, "ticker": ticker,
                                     "reason": "quote or identity not verified"})
            continue
        price = _finite(s.get("price"), f"{key}.price", positive=True)
        prev = _finite(s.get("prev_close"), f"{key}.prev_close", positive=True)
        chg = _finite(s.get("change_pct"), f"{key}.change_pct")
        if abs(round((price / prev - 1) * 100, 2) - chg) > 0.02:
            raise ValidationError(f"{key}: change_pct {chg} inconsistent with price/prev_close", code="INVALID_VALUE")
        mover = {
            "ticker": ticker,
            "name_ja": m["name"],
            "name_en": names_en.get(ticker) or f"TSE {m['code']}",
            "name_en_source": "curated" if ticker in names_en else "code_fallback",
            "close": s["price"],
            "change_pct": s["change_pct"],
            "source_ref": {"file": snap_meta["file"], "sha256": snap_meta["sha256"], "pointer": ptr,
                           "fields": {"close": "price", "change_pct": "change_pct", "volume_ratio": "rvol",
                                      "name_ja": "<key>"}},
        }
        if s.get("rvol") is not None:
            if _finite(s["rvol"], f"{key}.rvol") < 0:
                raise ValidationError(f"{key}: rvol negative", code="INVALID_VALUE")
            mover["volume_ratio"] = s["rvol"]
        eligible[ticker] = mover
    if not eligible:
        raise ValidationError("no verified quotes for this session; refusing to export", code="NO_VERIFIED_QUOTES")

    # ---------------- paper trades (paper basis only)
    if not isinstance(trades_doc, list):
        raise ValidationError("paper_trade_history.json must be a list", code="SCHEMA_INVALID")
    trades_out = []
    for idx, t in enumerate(trades_doc):
        if not isinstance(t, dict):
            raise ValidationError(f"paper[{idx}] is not an object", code="SCHEMA_INVALID")
        if t.get("date") != session_date:
            continue
        ptr = f"/{idx}"
        ticker, side, result = t.get("ticker"), t.get("side"), t.get("result")
        if not isinstance(ticker, str) or not TICKER_RE.match(ticker):
            raise ValidationError(f"paper[{idx}] ticker invalid", code="SCHEMA_INVALID")
        if side not in ("LONG", "SHORT"):
            raise ValidationError(f"paper[{idx}] side {side!r} unknown", code="INVALID_VALUE")
        if t.get("source") not in ALLOWED_TRADE_SOURCES:
            raise ValidationError(f"paper[{idx}] source {t.get('source')!r} not allowed", code="INVALID_VALUE")
        if not isinstance(t.get("triggered"), bool):
            raise ValidationError(f"paper[{idx}] triggered must be boolean", code="SCHEMA_INVALID")
        if result not in RESULT_MAP:
            raise ValidationError(f"paper[{idx}] result {result!r} unknown", code="UNKNOWN_RESULT")
        exp_triggered, outcome, closed = RESULT_MAP[result]
        if t["triggered"] != exp_triggered:
            raise ValidationError(f"paper[{idx}] triggered={t['triggered']} contradicts result {result!r}",
                                  code="INVALID_VALUE")
        if outcome is None:
            excluded_records.append({"kind": "paper_trade", "pointer": ptr, "ticker": ticker,
                                     "reason": f"result {result!r} is not publishable"})
            continue
        if ticker not in eligible:
            excluded_records.append({"kind": "paper_trade", "pointer": ptr, "ticker": ticker,
                                     "reason": "no verified quote for this ticker"})
            continue
        entry = _finite(t.get("entry"), f"paper[{idx}].entry", positive=True)
        r = None
        if closed:
            r = _finite(t.get("r"), f"paper[{idx}].r")
        trades_out.append({
            "date": session_date, "ticker": ticker, "side": side, "entry": t["entry"],
            "triggered": True, "closed": closed, "outcome": outcome, "r": t["r"] if closed else None,
            "basis": "paper",
            "source_ref": {"file": paper_meta["file"], "sha256": paper_meta["sha256"], "pointer": ptr,
                           "fields": {"r": "r" if closed else None, "entry": "entry", "outcome": "result"}},
        })

    # ---------------- Opportunity Radar (optional): public events + internal records, split
    radar_public: list[dict] = []
    radar_internal: list[dict] = []
    radar_meta = None
    radar_snapshot = None
    if condition_log is not None:
        condition_log = Path(condition_log).resolve()
        radar_snapshot = radar_import.read_snapshot(condition_log)
        parsed = radar_import.parse_condition_log(radar_snapshot, session_date)
        radar_meta = {"role": "condition_log.csv", "file": radar_import.FILE_NAME, "sha256": parsed["file_sha256"],
                      "bytes": parsed["bytes"], "rows": parsed["rows"], "duplicate_rows": parsed["duplicate_rows"],
                      "_path": condition_log}
        internal_by_id = {i["event_id"]: i for i in parsed["internal"]}
        for ev in parsed["public"]:
            if bool(FIXTURE_TICKER_RE.match(ev["ticker"])) != (data_class == "fixture"):
                raise ValidationError(f"radar ticker {ev['ticker']} does not match data_class {data_class}",
                                      code="DATA_CLASS_MIXED")
            if ev["ticker"] not in eligible:
                excluded_records.append({"kind": "radar_event", "event_id": ev["event_id"], "ticker": ev["ticker"],
                                         "row": ev["source_ref"]["row"], "reason": "no verified quote for this ticker"})
                continue
            radar_public.append(ev)
            radar_internal.append(internal_by_id[ev["event_id"]])

    # ---------------- mover selection: tickers with a paper trade or radar event + the largest moves
    trade_tickers = {t["ticker"] for t in trades_out} | {e["ticker"] for e in radar_public}
    by_move = sorted(eligible.values(), key=lambda m: (-abs(m["change_pct"]), m["ticker"]))
    chosen = {m["ticker"] for m in by_move[:max_movers]} | trade_tickers
    movers = [eligible[t] for t in sorted(chosen)]

    summary = {
        "schema": "auto_publish.daily_summary.v1",
        "session_date": session_date,
        "generated_at": updated.isoformat(),
        "source": "ai_cockpit_export" if data_class == "real" else "TEST_FIXTURE",
        "data_class": data_class,
        "movers": movers,
        "radar_events": radar_public,
        "export": {"exporter": EXPORTER, "version": EXPORTER_VERSION,
                   "inputs": [{k: v for k, v in meta.items() if not k.startswith("_")}
                              for meta in (snap_meta, paper_meta, radar_meta) if meta]},
    }
    for m in movers:
        assert set(m) <= OUTPUT_MOVER_KEYS, set(m) - OUTPUT_MOVER_KEYS
    for t in trades_out:
        assert set(t) <= OUTPUT_TRADE_KEYS, set(t) - OUTPUT_TRADE_KEYS

    dropped_stock_fields = sorted({k for s in snap["stocks"].values() if isinstance(s, dict) for k in s}
                                  - set(ALLOWLIST["data.json"]["stock"]))
    dropped_trade_fields = sorted({k for t in trades_doc if isinstance(t, dict) for k in t}
                                  - set(ALLOWLIST["paper_trade_history.json"]["trade"]))
    manifest = {
        "schema": "auto_publish.export_manifest.v1",
        "exporter": EXPORTER, "version": EXPORTER_VERSION,
        "session_date": session_date, "data_class": data_class,
        "inputs": summary["export"]["inputs"],
        "allowlist": ALLOWLIST,
        "dropped_fields": {"data.json/stocks/*": dropped_stock_fields,
                           "paper_trade_history.json/*": dropped_trade_fields,
                           "data.json (top-level)": sorted(set(snap) - set(ALLOWLIST["data.json"]["top"])),
                           "condition_log.csv (internal only, never public)": radar_import.INTERNAL_FIELDS
                           if condition_log is not None else []},
        "excluded_records": excluded_records,
        "counts": {"movers": len(movers), "paper_trades": len(trades_out), "radar_events": len(radar_public),
                   "excluded": len(excluded_records)},
        "boundary": "read-only export; R1 DRY-RUN; never publishes",
    }
    for name, obj in (("daily_summary.json", summary), ("paper_trade_history.json", trades_out)):
        hits = _deny_scan(obj)
        if hits:
            raise ValidationError(f"{name} would contain denied fields: {hits}", code="DENIED_FIELD_LEAK")
    internal_doc = None
    if condition_log is not None:
        internal_doc = {"schema": "auto_publish.radar_internal.v1", "visibility": "internal",
                        "note": "Local explanation data. Never rendered, posted or placed in payloads.",
                        "session_date": session_date, "source_sha256": radar_meta["sha256"],
                        "events": radar_internal}
    return {"summary": summary, "trades": trades_out, "manifest": manifest, "internal": internal_doc,
            "_inputs": [(snap_meta["_path"], snap_meta["sha256"]), (paper_meta["_path"], paper_meta["sha256"])],
            "_appendable": [(radar_meta["_path"], radar_snapshot)] if radar_meta else []}


def _dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def export_session(session_date: str, data_json: Path, paper_history: Path, out_root: Path, **kw) -> dict:
    """Build and write ``out_root/<session_date>/``. Idempotent; refuses to overwrite a different export."""
    out_dir = Path(out_root).resolve() / session_date
    inputs = [Path(data_json).resolve(), Path(paper_history).resolve()]
    if kw.get("condition_log") is not None:
        inputs.append(Path(kw["condition_log"]).resolve())
    for p in inputs:
        if p.parent == out_dir or out_dir in p.parents:
            raise ValidationError("output directory must not contain the input files (inputs are read-only)",
                                  code="OUTPUT_OVERLAPS_INPUT")
    built = build_export(session_date, data_json, paper_history, **kw)
    files = {
        "daily_summary.json": _dump(built["summary"]),
        "paper_trade_history.json": _dump(built["trades"]),
    }
    if built["internal"] is not None:
        files["internal/radar_internal.json"] = _dump(built["internal"])
    manifest = dict(built["manifest"])
    manifest["outputs"] = {n: sha256_bytes(b) for n, b in sorted(files.items())}
    files["export_manifest.json"] = _dump(manifest)

    # Inputs must be byte-identical to what we parsed (no concurrent modification, no writes by us).
    for path, sha in built["_inputs"]:
        if sha256_file(path) != sha:
            raise EvidenceError(f"{path.name} changed during export", code="EVIDENCE_CHANGED_DURING_INGEST")
    for path, snapshot in built["_appendable"]:
        radar_import.verify_prefix_unchanged(path, snapshot)

    if out_dir.exists():
        existing = {n: (out_dir / n).read_bytes() for n in files if (out_dir / n).is_file()}
        if existing == files:
            return {"out_dir": str(out_dir), "noop": True, **manifest["counts"], "outputs": manifest["outputs"]}
        if existing:
            raise EvidenceError(f"{out_dir} already holds a different export; refusing to overwrite",
                                code="EXPORT_CHANGED")
    for name, data in files.items():
        write_atomic(out_dir / name, data)
    return {"out_dir": str(out_dir), "noop": False, **manifest["counts"], "outputs": manifest["outputs"],
            "inputs": manifest["inputs"]}
