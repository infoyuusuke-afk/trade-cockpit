"""DryRunPublisher: writes the exact payload that WOULD be sent, never sends it.

This module intentionally imports nothing capable of network I/O. ``publish``,
``verify_publish`` and ``fetch_metrics`` are hard-blocked in release gate R1.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..clock import iso_utc
from ..errors import PublishBlockedError, RenderError
from ..hashing import sha256_file, sha256_json, write_json_atomic
from ..render.ffmpeg_render import COVER, MASTER
from .base import PostBundle, PublisherAdapter

X_MAX_CHARS = 280
DURATION_RANGE = (20.0, 45.0)


def _x_text(post_en: dict) -> str:
    segs = {s["id"]: s["text"] for s in post_en["segments"]}
    tags = " ".join(post_en["hashtags"][:2])
    parts = [segs["hook"], segs.get("b1", ""), "Not investment advice.", tags]
    if post_en.get("fixture"):
        parts.insert(0, "[TEST FIXTURE]")
    text = "\n".join(p for p in parts if p)
    if len(text) > X_MAX_CHARS:
        text = "\n".join(p for p in parts if p and p != segs.get("b1"))
    return text[:X_MAX_CHARS]


class DryRunPublisher(PublisherAdapter):
    name = "dry_run"

    def __init__(self, platform: str):
        self.platform = platform

    def validate_credentials(self) -> dict:
        return {"ok": True, "adapter": self.name, "credentials": "none (dry run never authenticates)"}

    def validate_asset(self, post: PostBundle) -> dict:
        outputs = post.render_manifest["outputs"]
        for name in (MASTER, COVER):
            p = post.story_dir / name
            if not p.is_file():
                raise RenderError(f"{name} missing for {post.story_id}", code="ASSET_MISSING")
            if sha256_file(p) != outputs[name]["sha256"]:
                raise RenderError(f"{name} hash differs from render manifest", code="ASSET_TAMPERED")
        pr = post.render_manifest["probe"]
        if (pr["width"], pr["height"]) != (1080, 1920) or pr["video_codec"] != "h264":
            raise RenderError(f"asset is not 1080x1920 h264: {pr}", code="ASSET_INVALID")
        if not (DURATION_RANGE[0] <= pr["duration"] <= DURATION_RANGE[1]):
            raise RenderError(f"duration {pr['duration']}s outside {DURATION_RANGE}", code="ASSET_INVALID")
        return {"ok": True, **pr}

    def create_draft(self, post: PostBundle) -> dict:
        en = post.post_en
        media = {"file": MASTER, "sha256": post.render_manifest["outputs"][MASTER]["sha256"],
                 "bytes": post.render_manifest["outputs"][MASTER]["bytes"],
                 "cover": COVER, "captions": "captions.srt"}
        if self.platform == "youtube_shorts":
            request = {
                "api": "youtube.videos.insert",
                "snippet": {"title": en["title"][:100], "description": en["caption"][:5000],
                            "tags": [h.lstrip("#") for h in en["hashtags"]], "defaultLanguage": "en"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
                "media": media,
            }
        elif self.platform == "tiktok":
            request = {
                "api": "tiktok.content_posting.video.init",
                "post_info": {"title": en["caption"][:2200], "privacy_level": "SELF_ONLY",
                              "disable_duet": False, "disable_comment": False, "disable_stitch": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": media["bytes"]},
                "media": media,
            }
        elif self.platform == "x":
            request = {"api": "x.posts.create", "text": _x_text(en),
                       "media": {"file": COVER, "sha256": post.render_manifest["outputs"][COVER]["sha256"]}}
        else:
            request = {"api": f"{self.platform}.unsupported_in_r1", "media": media}
        return {
            "schema": "auto_publish.dry_run_payload.v1",
            "dry_run": True,
            "network": "none",
            "release_gate": "R1",
            "platform": self.platform,
            "adapter": self.name,
            "story_id": post.story_id,
            "session_date": post.session_date,
            "idempotency_key": post.idempotency_key,
            "content_sha256": post.content_sha256,
            "evidence_manifest_sha256": post.evidence_manifest_sha256,
            "approved_by": post.approved_by,
            "fixture": post.fixture,
            "data_class": "fixture" if post.fixture else "real",
            "request": request,
            "localized": {"ja-JP": {"title": post.post_ja["title"], "caption": post.post_ja["caption"]}},
        }

    def schedule(self, post: PostBundle, publish_at: datetime) -> dict:
        payload = self.create_draft(post)
        payload["would_publish_at_utc"] = iso_utc(publish_at)
        payload["schedule"] = post.extra.get("slot", {})
        path = Path(post.story_dir) / "dry_run" / f"{self.platform}.json"
        sha = write_json_atomic(path, payload)
        return {"payload_path": str(path), "payload_sha256": sha, "payload_body_sha256": sha256_json(payload)}

    def publish(self, post: PostBundle) -> dict:
        raise PublishBlockedError("release gate R1: PUBLISH is disabled; DryRunPublisher never sends")

    def verify_publish(self, publish_id: str) -> dict:
        raise PublishBlockedError("release gate R1: nothing is ever published, nothing to verify")

    def fetch_metrics(self, publish_id: str) -> dict:
        raise PublishBlockedError("release gate R1: metrics collection is not enabled")
