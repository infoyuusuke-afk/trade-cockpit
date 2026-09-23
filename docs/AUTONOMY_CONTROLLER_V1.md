# AI Cockpit Autonomy Controller v1

This is the first top-level controller that joins the autonomous components already on main.

Decision order:

1. Build system health from data, strategy, execution, reporting and learning.
2. SAFE/BLOCKED never proceeds as healthy; route to the self-healing supervisor.
3. DEGRADED also routes to recovery rather than silently continuing.
4. HEALTHY enters the autonomous daily loop.
5. The daily loop performs acquisition/validation/analysis/decision/evaluation/report/learn planning.

The Controller is deliberately deterministic and side-effect free. It does not place broker orders, restart Windows processes, activate schedules, publish externally, or handle credentials. Those adapters must remain separate from policy/orchestration so they can be tested and fail closed.

The long-term target is Owner-independent routine operation. v1 establishes the control plane without prematurely granting real-world authority.
