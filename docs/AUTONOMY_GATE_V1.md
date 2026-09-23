# Autonomy Gate v1

Autonomy is earned by evidence. This first gate turns strategy/execution metrics into an explicit autonomy state.

The gate checks evidence integrity, determinism, minimum sample sufficiency, drawdown validity, kill-switch testing and Shadow completion. Passing all checks yields only **CONTROLLED_LIVE_ELIGIBLE**.

Eligibility is not permission. This module deliberately returns `real_submit_allowed=false`; live broker activation remains a separate explicit approval and actual-machine boundary.

Thresholds in this v1 are contract scaffolding, not claims that 30 samples or any drawdown value proves profitability. Strategy-specific statistical promotion criteria belong in Strategy Lab and must be calibrated with out-of-sample evidence.
