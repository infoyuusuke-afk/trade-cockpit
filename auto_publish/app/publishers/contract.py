"""Frozen dry-run payload contract per platform (``auto_publish.dry_run_payload.v1``).

Checked when the payload is written (SCHEDULE) and again at the scheduled time
(WOULD_PUBLISH). A payload that violates the contract never becomes a
would_publish event (PAYLOAD_CONTRACT_VIOLATION, fail-closed).

The platform limits mirror the public API constraints the future real adapters
must meet (title/text lengths, privacy); the dry-run additionally *requires*
the most private setting so a payload can never be mistaken for a live post.
Changing this contract is a deliberate act: bump CONTRACT_VERSION and the
golden payload tests.
"""
from __future__ import annotations

import re
import unicodedata

from ..errors import FailClosedError

CONTRACT_VERSION = "auto_publish.payload_contract.v1"
SCHEMA = "auto_publish.dry_run_payload.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
COMMON_KEYS = {
    "schema", "dry_run", "network", "release_gate", "platform", "adapter", "story_id", "session_date",
    "idempotency_key", "content_sha256", "evidence_manifest_sha256", "approved_by", "fixture", "data_class",
    "request", "localized", "would_publish_at_utc", "schedule",
}
SLOT_KEYS = {"wave", "publish_at_utc", "publish_at_jst", "audience_tz", "audience_local"}
PLATFORMS = ("youtube_shorts", "tiktok", "x")


class PayloadContractError(FailClosedError):
    code = "PAYLOAD_CONTRACT_VIOLATION"


def x_weighted_length(text: str) -> int:
    """X counts CJK / full-width characters as 2."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _media(req: dict, errs: list[str], file: str) -> None:
    m = req.get("media")
    if not isinstance(m, dict) or m.get("file") != file or not HEX64.match(str(m.get("sha256", ""))):
        errs.append(f"request.media must reference {file} with a sha256")


def _youtube(req: dict, errs: list[str]) -> None:
    if req.get("api") != "youtube.videos.insert":
        errs.append("request.api")
    sn, st = req.get("snippet", {}), req.get("status", {})
    title = sn.get("title", "")
    if not (isinstance(title, str) and 1 <= len(title) <= 100) or "<" in title or ">" in title:
        errs.append("snippet.title must be 1..100 chars without < >")
    if not isinstance(sn.get("description"), str) or len(sn["description"].encode("utf-8")) > 5000:
        errs.append("snippet.description must be <= 5000 bytes")
    tags = sn.get("tags", [])
    if not isinstance(tags, list) or sum(len(t) for t in tags) > 500:
        errs.append("snippet.tags total must be <= 500 chars")
    if st.get("privacyStatus") != "private" or st.get("selfDeclaredMadeForKids") is not False:
        errs.append("status must be private and not made-for-kids (dry run)")
    _media(req, errs, "master_1080x1920.mp4")
    if not isinstance(req.get("media", {}).get("bytes"), int) or req["media"]["bytes"] <= 0:
        errs.append("request.media.bytes")


def _tiktok(req: dict, errs: list[str]) -> None:
    if req.get("api") != "tiktok.content_posting.video.init":
        errs.append("request.api")
    pi, si = req.get("post_info", {}), req.get("source_info", {})
    if not isinstance(pi.get("title"), str) or not 1 <= len(pi["title"]) <= 2200:
        errs.append("post_info.title must be 1..2200 chars")
    if pi.get("privacy_level") != "SELF_ONLY":
        errs.append("post_info.privacy_level must be SELF_ONLY (dry run)")
    _media(req, errs, "master_1080x1920.mp4")
    if si.get("source") != "FILE_UPLOAD" or si.get("video_size") != req.get("media", {}).get("bytes") \
            or not isinstance(si.get("video_size"), int) or si["video_size"] <= 0:
        errs.append("source_info must be FILE_UPLOAD with video_size == media.bytes")


def _x(req: dict, errs: list[str]) -> None:
    if req.get("api") != "x.posts.create":
        errs.append("request.api")
    text = req.get("text")
    if not isinstance(text, str) or not 1 <= x_weighted_length(text) <= 280:
        errs.append("text must be 1..280 weighted chars")
    if "Not investment advice" not in (text or ""):
        errs.append("text must carry the disclaimer")
    _media(req, errs, "cover.jpg")


CHECKS = {"youtube_shorts": _youtube, "tiktok": _tiktok, "x": _x}


def validate_payload(payload: dict, platform: str) -> None:
    errs: list[str] = []
    if not isinstance(payload, dict):
        raise PayloadContractError("payload is not an object", details={"platform": platform})
    missing, extra = COMMON_KEYS - set(payload), set(payload) - COMMON_KEYS
    if missing or extra:
        errs.append(f"keys: missing {sorted(missing)} unexpected {sorted(extra)}")
    fixed = {"schema": SCHEMA, "dry_run": True, "network": "none", "release_gate": "R1", "adapter": "dry_run",
             "platform": platform}
    for k, v in fixed.items():
        if payload.get(k) != v:
            errs.append(f"{k} must be {v!r}")
    if platform not in CHECKS:
        errs.append(f"platform {platform!r} has no contract")
    for k, rx in (("idempotency_key", HEX32), ("content_sha256", HEX64), ("evidence_manifest_sha256", HEX64),
                  ("session_date", DATE), ("would_publish_at_utc", UTC_TS)):
        if not rx.match(str(payload.get(k, ""))):
            errs.append(f"{k} malformed")
    if not str(payload.get("story_id", "")).startswith("st_"):
        errs.append("story_id malformed")
    if not isinstance(payload.get("approved_by"), str) or not payload["approved_by"].strip():
        errs.append("approved_by required")
    if not isinstance(payload.get("fixture"), bool) or \
            payload.get("data_class") != ("fixture" if payload.get("fixture") else "real"):
        errs.append("fixture/data_class inconsistent")
    slot = payload.get("schedule")
    if not isinstance(slot, dict) or set(slot) != SLOT_KEYS or slot.get("publish_at_utc") != payload.get(
            "would_publish_at_utc"):
        errs.append("schedule slot must match would_publish_at_utc")
    ja = payload.get("localized", {}).get("ja-JP", {}) if isinstance(payload.get("localized"), dict) else {}
    if not (isinstance(ja.get("title"), str) and ja["title"] and isinstance(ja.get("caption"), str) and ja["caption"]):
        errs.append("localized.ja-JP title/caption required")
    req = payload.get("request")
    if not isinstance(req, dict):
        errs.append("request must be an object")
    elif platform in CHECKS:
        CHECKS[platform](req, errs)
    if errs:
        raise PayloadContractError(f"{platform}: payload violates {CONTRACT_VERSION}",
                                   details={"platform": platform, "violations": errs})
