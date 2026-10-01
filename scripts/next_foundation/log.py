"""Judgment log for a later AI trade diary.

Each row keeps the decision-time features and empty forward slots for
30-second, 1-minute, 3-minute, and 5-minute return, MFE, and MAE.
Those slots stay null until a later pass observes them.
"""

from __future__ import annotations

import json
from pathlib import Path

HORIZONS = ("30s", "1m", "3m", "5m")


def empty_forward(anchor_price: float | None) -> dict:
    return {
        "anchor_price": anchor_price,
        "horizons": {
            horizon: {"return": None, "mfe": None, "mae": None}
            for horizon in HORIZONS
        },
    }


def judgment_record(row: dict, timestamp: str, run_id: str) -> dict:
    features = {key: value for key, value in (row.get("features") or {}).items()}
    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "symbol": row.get("symbol"),
        "score": row.get("score"),
        "rank": row.get("rank"),
        "previous_rank": row.get("previous_rank"),
        "rank_velocity": row.get("rank_velocity"),
        "state": row.get("state"),
        "lifecycle_state": row.get("lifecycle_state"),
        "lifecycle_alias": row.get("lifecycle_alias"),
        "reason_codes": list(row.get("reason_codes") or []),
        "features": features,
        "feature_components": row.get("components") or {},
        "fail_closed": bool(row.get("fail_closed")),
        "funnel": row.get("funnel"),
        "forward": empty_forward(row.get("price")),
    }


def write_judgments(path: Path | str, records: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
