"""100B: one public evidence file (v2) for the specialist analysts, from the
approved read-only adapters. Manual --fetch only; no model call.

Adapters (each can fail on its own without stopping the others):
  boj         BOJ RSS headlines -> pre_next / supply_sq
  jpx_margin  JPX 日々公表銘柄等信用取引残高 -> supply_sq (requested codes only)
  jpx_margin_all  JPX 銘柄別信用取引残高 (all issues, daily PDF) -> supply_sq (requested
              codes, in the caller's priority order; OWNER 2026-10-22)

Not connected (no approved free source with a verified time contract yet):
premarket overseas indices, TDnet (robots.txt disallows automated access),
JPX investor-type futures CSV (code tables not published with the file),
J-Quants (contract and cost are OWNER decisions).
Those roles stay NO_DATA instead of being filled with guesses.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

if __package__:
    from . import agent_sdk_coordination_pilot as pilot
    from . import agent_sdk_jpx_margin_all_ingest as jpx_all
    from . import agent_sdk_jpx_margin_ingest as jpx
    from . import agent_sdk_public_feed_ingest as boj
else:
    import agent_sdk_coordination_pilot as pilot
    import agent_sdk_jpx_margin_all_ingest as jpx_all
    import agent_sdk_jpx_margin_ingest as jpx
    import agent_sdk_public_feed_ingest as boj

ADAPTERS = ("jpx_margin_all", "boj", "jpx_margin")


def bundle(run_id: str, results: dict, *, now: datetime) -> tuple[dict, dict]:
    """results: adapter -> list of v2 source rows, or an Exception (that adapter failed)."""
    sources, status = [], {}
    for name in ADAPTERS:
        got = results.get(name)
        if got is None:
            status[name] = "NOT_REQUESTED"
        elif isinstance(got, Exception):
            status[name] = "BLOCKED:" + (str(got) if isinstance(got, (boj.EvidenceBlocked, jpx.MarginBlocked, jpx_all.MarginBlocked))
                                         else type(got).__name__)
        else:
            status[name] = "OK:%d" % len(got)
            sources.extend(got)
    if not sources:
        raise boj.EvidenceBlocked("NO_EVIDENCE_FROM_ANY_ADAPTER")
    doc = {"schema_version": pilot.SCHEMA, "run_id": run_id, "sources": sources[:pilot.MAX_SOURCES]}
    pilot.validate_snapshot(doc, now)  # the same contract the analysts enforce
    return doc, status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build one public evidence file for the specialist analysts")
    ap.add_argument("--fetch", action="store_true", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--boj", action="store_true", help="BOJ RSS headlines")
    ap.add_argument("--boj-per-role", type=int, help="Keep only the first N BOJ headlines per role (input size)")
    ap.add_argument("--jpx-margin-codes", help="JPX daily-publication margin for these codes, e.g. 285A,8035")
    ap.add_argument("--jpx-margin-all-codes", help="JPX all-issue margin for these codes, priority first (max 150)")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    results = {}
    if args.boj:
        try:
            feeds = {role: boj.fetch_official_feed(url) for role, url in boj.FEEDS.items()}
            rows = boj.build_snapshot(feeds, args.run_id, now)["sources"]
            if args.boj_per_role is not None:
                kept, count = [], {}
                for row in rows:
                    count[row["role"]] = count.get(row["role"], 0) + 1
                    if count[row["role"]] <= args.boj_per_role:
                        kept.append(row)
                rows = kept
            results["boj"] = rows
        except Exception as exc:  # one adapter failing never stops the others
            results["boj"] = exc
    if args.jpx_margin_all_codes:
        try:
            results["jpx_margin_all"] = jpx_all.fetch_sources(jpx_all.parse_codes(args.jpx_margin_all_codes), observed_at=now)[0]
        except Exception as exc:
            results["jpx_margin_all"] = exc
    if args.jpx_margin_codes:
        try:
            results["jpx_margin"] = jpx.fetch_sources(jpx.parse_codes(args.jpx_margin_codes), observed_at=now)[0]
        except Exception as exc:
            results["jpx_margin"] = exc
    try:
        if not boj.RUN_ID.fullmatch(args.run_id):
            raise boj.EvidenceBlocked("RUN_ID_INVALID")
        doc, status = bundle(args.run_id, results, now=now)
        boj.write_once(args.output, doc)
        print(json.dumps({"status": "PUBLIC_EVIDENCE_WRITTEN_RESEARCH_ONLY", "adapters": status,
                          "roles": sorted({r["role"] for r in doc["sources"]}), "sources": len(doc["sources"]),
                          "model_calls": 0, "real_submit_allowed": False}, sort_keys=True))
        return 0
    except (boj.EvidenceBlocked, pilot.Blocked, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc) if isinstance(exc, (boj.EvidenceBlocked, pilot.Blocked))
                          else "BUNDLE_IO_BLOCKED", "adapters": {k: ("BLOCKED" if isinstance(v, Exception) else "OK")
                                                                 for k, v in results.items()},
                          "model_calls": 0, "real_submit_allowed": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
