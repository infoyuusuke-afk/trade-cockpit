# GPT / Cloud Shared Progress Handoff

This file is the canonical human-readable handoff for work coordinated between GPT, Cloud/Claude-side work, and the Owner.

## Operating rule
Before reporting project progress or starting continuation work, read this file and the referenced PR/issues. After meaningful work, update the handoff in the working branch/PR.

Code synchronization alone is not progress synchronization.

## Required handoff fields
- updated_at_jst
- updated_by: GPT | CLOUD | OWNER
- current_goal
- completed
- evidence
- decisions
- open_items
- next_actions
- owner_approval_required
- blocked_by
- active_prs

## Safety boundaries
- Do not treat conversation memory as the canonical project state.
- Do not mark work complete without repository/CI evidence where applicable.
- Do not merge, publish externally, or enable live-order behavior solely from this handoff.
- Trading signal/order logic remains governed by its own contracts and approval gates.

## Current handoff
updated_at_jst: 2026-09-23T20:20:00+09:00
updated_by: GPT
current_goal: Make GPT and Cloud/Claude-side progress visible from one repository-backed handoff.
completed:
  - Confirmed GitHub automatic update workflows are running.
  - Identified that code synchronization did not guarantee sharing of GPT/Cloud decisions and progress context.
  - Repository search found no existing canonical handoff/progress ledger under the searched terms.
evidence:
  - Recent Mobile Control Tests succeeded.
  - Recent Build Mobile Approval Feed succeeded.
  - Recent Update Trade Cockpit runs succeeded and new runs were triggered by subsequent pushes.
decisions:
  - Use a repository-backed handoff as the canonical progress bridge.
  - Keep Owner-facing operation Japanese-first.
  - Keep this change isolated from trading signals, order logic, and external publishing.
open_items:
  - Wire automated validation/update behavior around this handoff.
  - Identify the exact Cloud/Claude workflow entry point and require it to read this handoff before progress reporting.
  - Add machine-readable companion state only if needed by automation.
  - Treat generated-data-only movement on main as freshness drift, not a reason to repeatedly merge main into a code PR; code/workflow conflicts still require reconciliation.
next_actions:
  - Review existing workflow files for the safest integration point.
  - Add tests/validation so stale or malformed handoff state fails visibly.
  - Before owner approval, compare changed code/workflow paths against current main; generated market-data drift is reviewed separately.
owner_approval_required:
  - Merge to main after review/CI.
blocked_by: []
active_prs:
  - "#196 C-195 international cockpit presentation contract (separate workstream)"
