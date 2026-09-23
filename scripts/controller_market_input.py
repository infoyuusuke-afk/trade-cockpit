"""Compose market-input failover with the AI Cockpit Autonomy Controller."""
from scripts.market_input_failover import choose
from scripts.autonomy_controller import control

def control_with_market_inputs(candidates, component_health, market_open):
    selection=choose(candidates)
    h=dict(component_health)
    incident=None
    if selection["status"]=="READY":
        h["data"]="OK"
    elif selection["status"]=="WAIT_DATA":
        h["data"]="DEGRADED";incident="STALE_DATA"
    else:
        h["data"]="BLOCKED";incident=selection.get("incident_code") or "SOURCE_DISAGREEMENT"
    result=control({"health":h,"market_open":market_open,"incident_code":incident})
    result["market_input"]=selection
    return result
