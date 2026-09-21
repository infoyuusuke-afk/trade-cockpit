#!/usr/bin/env python3
"""Execution validation ladder. Research safety gate; never auto-enables live trading."""

STAGES=("RESEARCH","SHADOW","PAPER","MIN_LOT_LIVE","SCALED_LIVE")

def execution_stage_gate(current_stage, evidence):
    if current_stage not in STAGES: raise ValueError("invalid stage")
    reasons=[]
    target=current_stage

    if current_stage=="RESEARCH":
        if evidence.get("promotion_status")!="CANDIDATE": reasons.append("RESEARCH_NOT_CANDIDATE")
        else: target="SHADOW"

    elif current_stage=="SHADOW":
        if int(evidence.get("shadow_samples",0))<30: reasons.append("SHADOW_N_LT_30")
        if float(evidence.get("shadow_avg_net_pnl_pct",0))<=0: reasons.append("SHADOW_EDGE_NON_POSITIVE")
        if not reasons: target="PAPER"

    elif current_stage=="PAPER":
        if int(evidence.get("paper_samples",0))<30: reasons.append("PAPER_N_LT_30")
        if float(evidence.get("paper_avg_net_pnl_pct",0))<=0: reasons.append("PAPER_EDGE_NON_POSITIVE")
        if float(evidence.get("median_spread_bps",999))>20: reasons.append("SPREAD_TOO_WIDE")
        if float(evidence.get("median_daily_turnover_jpy",0))<500_000_000: reasons.append("LIQUIDITY_TOO_LOW")
        if not reasons: target="MIN_LOT_LIVE"

    elif current_stage=="MIN_LOT_LIVE":
        if int(evidence.get("live_samples",0))<30: reasons.append("LIVE_N_LT_30")
        if float(evidence.get("live_avg_net_pnl_pct",0))<=0: reasons.append("LIVE_EDGE_NON_POSITIVE")
        if float(evidence.get("fill_rate",0))<0.90: reasons.append("FILL_RATE_TOO_LOW")
        if float(evidence.get("avg_slippage_bps",999))>15: reasons.append("SLIPPAGE_TOO_HIGH")
        if not reasons: target="SCALED_LIVE"

    return {
      "current_stage":current_stage,
      "next_stage":target if not reasons else current_stage,
      "gate_pass":not reasons,
      "reasons":reasons,
      "auto_execute":False,
      "owner_approval_required": target in ("MIN_LOT_LIVE","SCALED_LIVE") and not reasons
    }
