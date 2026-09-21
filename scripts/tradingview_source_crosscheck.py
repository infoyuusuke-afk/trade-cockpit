#!/usr/bin/env python3
"""Cross-check TradingView MCP bars against Replay-derived CORE bars."""
FIELDS=("open","high","low","close","volume")

def _vals_equal(a,b,tol):
    return all(abs(float(a[k])-float(b[k]))<=tol for k in FIELDS)

def crosscheck_sources(mcp_rows,replay_rows,required_timeframe="15S",tolerance=0.0):
    if not mcp_rows or not replay_rows: raise ValueError("EMPTY_SOURCE")
    actual={str(r.get("source_timeframe")) for r in mcp_rows}
    if actual!={str(required_timeframe)}:
        raise ValueError("TIMEFRAME_MISMATCH")
    m={r["timestamp"]:r for r in mcp_rows}; q={r["timestamp"]:r for r in replay_rows}
    common=sorted(set(m)&set(q))
    mismatches=[]
    for ts in common:
        if not _vals_equal(m[ts],q[ts],tolerance):
            mismatches.append({"timestamp":ts,
              "mcp":{k:m[ts][k] for k in FIELDS},
              "replay":{k:q[ts][k] for k in FIELDS}})
    only_mcp=sorted(set(m)-set(q)); only_replay=sorted(set(q)-set(m))
    matched=len(common)-len(mismatches)
    status="NO_OVERLAP" if not common else ("PASS" if not mismatches else "MISMATCH")
    return {"status":status,"required_timeframe":required_timeframe,
            "overlap_n":len(common),"matched_n":matched,
            "mismatch_n":len(mismatches),"mismatches":mismatches,
            "only_mcp_n":len(only_mcp),"only_replay_n":len(only_replay),
            "only_mcp_timestamps":only_mcp,"only_replay_timestamps":only_replay,
            "auto_repair":False,"research_only":True}
