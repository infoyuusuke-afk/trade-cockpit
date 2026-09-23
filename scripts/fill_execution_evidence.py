"""Pure validator for private independent execution evidence metadata.

No file I/O and no real-order path. Raw execution evidence remains under ignored private roots.
"""
from __future__ import annotations
import re

APPROVED_PRIVATE_ROOTS=("data/private/","ms2_live/records/")
ALLOWED_SOURCES=frozenset({"BROKER_EXECUTION_EXPORT","MANUAL_VERIFIED_EXECUTION"})
_SHA256=re.compile(r"^[0-9a-f]{64}$")

def is_approved_private_path(path) -> bool:
    if not isinstance(path,str) or not path.strip(): return False
    p=path.replace("\\","/")
    if p.startswith("/") or p.startswith("../") or "/../" in p: return False
    return any(p.startswith(root) for root in APPROVED_PRIVATE_ROOTS)

def validate_execution_evidence(meta:dict, *, shadow_order_id:str, observation_source:str) -> list[str]:
    reasons=[]
    if not isinstance(meta,dict): return ["EVIDENCE_META_INVALID"]
    if observation_source not in ALLOWED_SOURCES: reasons.append("EVIDENCE_SOURCE_NOT_ALLOWED")
    if meta.get("observation_source")!=observation_source: reasons.append("EVIDENCE_SOURCE_MISMATCH")
    if meta.get("shadow_order_id")!=shadow_order_id: reasons.append("EVIDENCE_ORDER_ID_MISMATCH")
    if not is_approved_private_path(meta.get("source_path")): reasons.append("EVIDENCE_PATH_NOT_PRIVATE")
    digest=meta.get("sha256")
    if not isinstance(digest,str) or not _SHA256.fullmatch(digest): reasons.append("EVIDENCE_SHA256_INVALID")
    anchor=meta.get("anchor")
    if not isinstance(anchor,str) or not _SHA256.fullmatch(anchor): reasons.append("EVIDENCE_ANCHOR_INVALID")
    return reasons
