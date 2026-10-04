"""Compliance gate. Any violation is fail-closed (ComplianceError).

Runs after LOCALIZE and again immediately before SCHEDULE (defence in depth),
so a draft edited on disk after approval cannot slip through.
"""
from __future__ import annotations

import re

from ..errors import ComplianceError

BANNED = [
    (re.compile(r"\bguarante\w*", re.I), "guarantee wording"),
    (re.compile(r"\brisk[\s-]?free\b", re.I), "risk-free wording"),
    (re.compile(r"\beasy\s+(money|profits?|gains?)\b", re.I), "easy-profit wording"),
    (re.compile(r"\b(can'?t|cannot)\s+lose\b", re.I), "cannot-lose wording"),
    (re.compile(r"\bsure\s+thing\b", re.I), "sure-thing wording"),
    (re.compile(r"\bmust\s+(buy|sell)\b", re.I), "must buy/sell wording"),
    (re.compile(r"\b(buy|sell)\s+(it\s+)?now\b", re.I), "buy/sell-now call to action"),
    (re.compile(r"\b100\s*%\s*(win|profit|accura|sure)", re.I), "100% claim"),
    (re.compile(r"\bget\s+rich\b", re.I), "get-rich wording"),
    (re.compile(r"\bdouble\s+your\s+money\b", re.I), "double-your-money wording"),
    (re.compile(r"必ず(儲|上が|勝|利益)"), "必ず系の断定"),
    (re.compile(r"絶対(に)?(儲|上が|勝|利益)"), "絶対系の断定"),
    (re.compile(r"確実に(儲|上が|勝|利益)"), "確実系の断定"),
    (re.compile(r"元本保証|ノーリスク|リスクゼロ"), "元本保証/ノーリスク表現"),
    (re.compile(r"今すぐ(買|売)"), "今すぐ売買の推奨"),
    (re.compile(r"爆益|億り人"), "誇大な利益表現"),
]

PROFIT_CLAIM = [
    re.compile(r"\b(profit(s|able)?|earned|won|winnings|gain(ed|s)?|returns?|p\s*/\s*l|pnl)\b", re.I),
    re.compile(r"\bmade\s+[¥$€£]?\s*\d", re.I),
    re.compile(r"[+＋]\s*[¥$€£]\s*\d"),
    re.compile(r"利益|儲け|儲か|勝ち|損益|収支|含み益"),
]
TRADE_KINDS = {"paper_trade", "shadow_trade", "real_trade"}
PAPER_LABELS = {"en-US": re.compile(r"\b(paper|shadow|simulated)\b", re.I),
                "ja-JP": re.compile(r"ペーパー|シャドー|シミュレーション")}
SIMULATED_NOTE = {"en-US": re.compile(r"simulated", re.I), "ja-JP": re.compile(r"シミュレーション")}
FIXTURE_LABEL = {"en-US": re.compile(r"TEST FIXTURE"), "ja-JP": re.compile(r"テスト用")}


def check_post(post: dict, session_date: str) -> list[dict]:
    v: list[dict] = []
    lang = post.get("lang", "en-US")
    refs = {r["fact_id"]: r for r in post.get("source_refs", [])}

    def add(rule: str, seg: str | None, msg: str):
        v.append({"rule": rule, "segment": seg, "lang": lang, "message": msg})

    if post.get("session_date") != session_date:
        add("DATE_MISMATCH", None, f"post session {post.get('session_date')} != {session_date}")
    if not str(post.get("title", "")).strip():
        add("EMPTY_TEXT", "title", "title is empty")
    segs = post.get("segments") or []
    if not segs:
        add("EMPTY_TEXT", None, "no script segments")
    for r in refs.values():
        if r.get("session_date") != session_date:
            add("DATE_MISMATCH", None, f"source {r['fact_id']} is from {r.get('session_date')}")
        if r.get("basis") == "real":
            add("REAL_ACCOUNT_RESULT", None, f"{r['fact_id']} is real-account data (not publishable in R1)")
        if not r.get("sha256") or len(r["sha256"]) != 64:
            add("MISSING_SOURCE_REFS", None, f"{r.get('fact_id')} has no SHA256")

    disclaimers = [s for s in segs if s.get("type") == "disclaimer"]
    any_paper = False
    for s in segs:
        text = str(s.get("text", ""))
        sid = s.get("id")
        if not text.strip():
            add("EMPTY_TEXT", sid, "segment text is empty")
            continue
        for rx, label in BANNED:
            if rx.search(text):
                add("BANNED_PHRASE", sid, label)
        if s.get("type") == "disclaimer":
            continue
        fids = s.get("fact_ids") or []
        if not fids or any(f not in refs for f in fids):
            add("MISSING_SOURCE_REFS", sid, "segment is not backed by a recorded source ref")
            continue
        seg_refs = [refs[f] for f in fids]
        if any(rx.search(text) for rx in PROFIT_CLAIM) and not any(r["kind"] in TRADE_KINDS for r in seg_refs):
            add("UNSUPPORTED_PROFIT_CLAIM", sid, "profit/return wording without a trade-result source")
        if any(r["basis"] in ("paper", "shadow") for r in seg_refs):
            any_paper = True
            if not PAPER_LABELS[lang].search(text):
                add("PAPER_NOT_LABELED", sid, "paper/shadow result must be labelled as such")

    if not disclaimers or not str(disclaimers[0].get("text", "")).strip():
        add("DISCLAIMER_MISSING", None, "end disclaimer missing")
    elif any_paper and not SIMULATED_NOTE[lang].search(disclaimers[0]["text"]):
        add("PAPER_NOT_LABELED", "disclaimer", "disclaimer must say paper results are simulated")
    if post.get("fixture") and not FIXTURE_LABEL[lang].search(" ".join(str(s.get("text", "")) for s in segs)):
        add("FIXTURE_NOT_LABELED", None, "fixture content must carry the TEST FIXTURE label")
    if not str(post.get("caption", "")).strip():
        add("EMPTY_TEXT", "caption", "caption is empty")
    return v


def check_captions_srt(srt_text: str, lang: str = "en-US") -> list[dict]:
    cues = [b for b in srt_text.strip().split("\n\n") if b.strip()]
    bad = [c for c in cues if len(c.strip().splitlines()) < 3]
    out = []
    if not cues:
        out.append({"rule": "EMPTY_TEXT", "segment": "captions", "lang": lang, "message": "captions are empty"})
    if bad:
        out.append({"rule": "EMPTY_TEXT", "segment": "captions", "lang": lang, "message": f"{len(bad)} empty cues"})
    return out


def enforce(posts: list[dict], session_date: str) -> None:
    violations = []
    for p in posts:
        violations.extend(check_post(p, session_date))
    if violations:
        raise ComplianceError(f"{len(violations)} compliance violation(s)", violations)
