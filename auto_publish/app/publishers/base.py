"""Publisher adapter contract (spec §7). Real adapters are not part of R1."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PostBundle:
    story_id: str
    session_date: str
    platform: str
    story_dir: Path
    post_en: dict
    post_ja: dict
    render_manifest: dict
    content_sha256: str
    approved_by: str
    evidence_manifest_sha256: str
    fixture: bool
    idempotency_key: str
    extra: dict = field(default_factory=dict)


class PublisherAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def validate_credentials(self) -> dict: ...

    @abstractmethod
    def validate_asset(self, post: PostBundle) -> dict: ...

    @abstractmethod
    def create_draft(self, post: PostBundle) -> dict: ...

    @abstractmethod
    def schedule(self, post: PostBundle, publish_at: datetime) -> dict: ...

    @abstractmethod
    def publish(self, post: PostBundle) -> dict: ...

    @abstractmethod
    def verify_publish(self, publish_id: str) -> dict: ...

    @abstractmethod
    def fetch_metrics(self, publish_id: str) -> dict: ...
