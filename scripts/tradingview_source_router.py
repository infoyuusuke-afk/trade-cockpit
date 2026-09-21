#!/usr/bin/env python3
"""Research-only TradingView source router with fail-closed provenance."""
from scripts.tradingview_mcp_adapter import adapt_mcp_payload,require_timeframe
from scripts.tradingview_source_crosscheck import crosscheck_sources

def route_tradingview_data(required_timeframe="15S",mcp_payload=None,replay_rows=None):
    replay_rows=replay_rows or []
    mcp_rows=[];mcp_error=None
    if mcp_payload is not None:
        try:
            mcp_rows=require_timeframe(adapt_mcp_payload(mcp_payload),required_timeframe)
        except ValueError as e:
            mcp_error=str(e)
    if mcp_rows and replay_rows:
        audit=crosscheck_sources(mcp_rows,replay_rows,required_timeframe)
        if audit["status"]=="MISMATCH":
            return {"status":"BLOCKED_SOURCE_MISMATCH","rows":[],
                    "selected_source":None,"crosscheck":audit,
                    "mcp_error":mcp_error,"research_only":True,"auto_execute":False}
        return {"status":"READY","rows":mcp_rows,"selected_source":"TRADINGVIEW_MCP",
                "crosscheck":audit,"mcp_error":mcp_error,
                "research_only":True,"auto_execute":False}
    if mcp_rows:
        return {"status":"READY","rows":mcp_rows,"selected_source":"TRADINGVIEW_MCP",
                "crosscheck":None,"mcp_error":mcp_error,
                "research_only":True,"auto_execute":False}
    if replay_rows:
        return {"status":"READY_FALLBACK","rows":replay_rows,
                "selected_source":"TRADINGVIEW_REPLAY",
                "crosscheck":None,"mcp_error":mcp_error,
                "research_only":True,"auto_execute":False}
    return {"status":"NO_USABLE_SOURCE","rows":[],"selected_source":None,
            "crosscheck":None,"mcp_error":mcp_error,
            "research_only":True,"auto_execute":False}
