#!/usr/bin/env python3
"""Research promotion gate for open-entry timing policies. Never grants LIVE."""

MIN_N=30
MIN_PF=1.10
MAX_DD_PCT=-10.0

def entry_policy_gate(summary_row, oos=None, walk_forward=None):
    reasons=[]
    if int(summary_row.get("sample_size",0))<MIN_N: reasons.append("INSUFFICIENT_SAMPLE")
    if float(summary_row.get("profit_factor",0))<MIN_PF: reasons.append("PF_BELOW_MIN")
    if float(summary_row.get("avg_net_pnl_pct",0))<=0: reasons.append("NON_POSITIVE_EDGE")
    if float(summary_row.get("max_drawdown_pct",-999))<MAX_DD_PCT: reasons.append("DD_TOO_LARGE")

    if oos is None:
        reasons.append("OOS_NOT_VALIDATED")
    else:
        if int(oos.get("sample_size",0))<10: reasons.append("OOS_INSUFFICIENT_SAMPLE")
        if float(oos.get("profit_factor",0))<MIN_PF: reasons.append("OOS_PF_BELOW_MIN")
        if float(oos.get("avg_net_pnl_pct",0))<=0: reasons.append("OOS_NON_POSITIVE_EDGE")

    if walk_forward is None:
        reasons.append("WALK_FORWARD_NOT_VALIDATED")
    else:
        if int(walk_forward.get("oos_fold_count",0))<2: reasons.append("WF_INSUFFICIENT_FOLDS")
        if float(walk_forward.get("positive_edge_fold_rate",0))<0.60: reasons.append("WF_UNSTABLE")

    return {
      "entry_policy":summary_row.get("entry_policy"),
      "status":"CANDIDATE" if not reasons else "RESEARCH",
      "reasons":reasons,
      "live_eligible":False
    }
