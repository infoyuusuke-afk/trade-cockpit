#!/usr/bin/env python3
"""Build mobile approval requests from AI Cockpit signals.

Safety rule: legacy/technical scores are never promoted to empirical EV scores.
Until an empirical EV record is supplied, trade approval stays BLOCKED.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

def load_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)

def build(signals: dict, limit: int = 10) -> dict:
    rows = signals.get("prepared") or []
    out = []
    for i, s in enumerate(rows[:limit], 1):
        code = str(s.get("code") or s.get("ticker") or "-").replace(".T", "")
        tech = s.get("technical_score", s.get("score"))
        out.append({
            "request_id": f"SIG-{s.get('signal_date','NA')}-{code}-{i:02d}",
            "request_type": "trade",
            "symbol": code,
            "name": s.get("name", ""),
            "action": "WAIT",
            "ev_score": None,
            "technical_score": tech,
            "sample_size": None,
            "profit_factor": None,
            "avg_pl_pct": None,
            "max_dd_pct": None,
            "trigger_summary": s.get("reason") or s.get("setup") or "",
            "source_signal_date": s.get("signal_date"),
            "source_updated_at": signals.get("updated_at"),
            "data_freshness_sec": None,
            "risk_gate": "BLOCK",
            "risk_reason": "EMPIRICAL_EV_NOT_AVAILABLE",
            "status": "pending",
            "expires_in_sec": 0,
            "paper_only": True,
            "trigger_price": s.get("trigger"),
            "stop_price": s.get("stop"),
            "target1": s.get("target1"),
            "target2": s.get("target2"),
        })
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "paper",
        "source": "signals.json adapter",
        "requests": out,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input", default="signals.json")
    p.add_argument("--output", default="data/mobile_approval_requests.json")
    p.add_argument("--limit", type=int, default=10)
    a=p.parse_args()
    payload=build(load_json(Path(a.input)), a.limit)
    dst=Path(a.output); dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"wrote {len(payload['requests'])} blocked paper requests -> {dst}")

if __name__=="__main__":
    main()
