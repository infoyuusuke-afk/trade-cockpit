"""Adapter registry. In R1 only ``dry_run`` can ever be constructed."""
from __future__ import annotations

from ..config import ALLOWED_ADAPTERS_R1
from ..errors import AdapterNotAllowedError
from .base import PublisherAdapter
from .dry_run import DryRunPublisher


def get_adapter(platform: str, cfg: dict) -> PublisherAdapter:
    pcfg = cfg["platforms"].get(platform)
    if pcfg is None:
        raise AdapterNotAllowedError(f"unknown platform {platform}")
    adapter = pcfg["adapter"]
    if adapter not in ALLOWED_ADAPTERS_R1 or cfg.get("release_gate") != "R1":
        raise AdapterNotAllowedError(f"{platform}: adapter {adapter!r} is not permitted in release gate R1")
    return DryRunPublisher(platform)
