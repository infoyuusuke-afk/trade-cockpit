# 100億PROJECT — V10/main protected-source merge decision (2026-10-20)

PROJECT_ITEM_ID: P0-V10-MAIN-MERGE-CONFLICT-SAFE-20261020

## What this candidate is
This branch is a **review-only merge resolution**, NOT runtime deployment, broker activation, or an authorization to start V10. It has two Git parents: the existing `main` and the fully integrated V10 Draft #444 branch. In contrast to a force merge, it retains both histories and chooses each file's source based on its responsibility.

- Source `main` commit: `1df1d6ad35ac0e87bd71118b1fb159ebae08d826`
- V10 Draft #444 source commit: `e6032e6c496552ad812e6e9c46623e9eae1313df`
- Their nearest merge base at inspection: `62a02c4a2efc253500633bb2cd21962ee151181b`
- Verified comparison: exactly 37 `main`-side modified files, of which exactly 36 are JSON data files and the remaining one is `index.html`; all 36 JSON changes are disjoint from the V10 branch's source changes. The only common edited file is `index.html`.

## Deterministic merge rules
1. **Preserve all 36 JSON files from the examined `main` HEAD byte-for-byte**, including trading histories, research observations, market calendars and aggregate snapshots. Do not backdate, reprice, reset, sanitize, synthesize or otherwise rewrite their data. These are historical/unverified datasets, not proof of prices or fills.
2. **Use `index.html` unchanged from the reviewed V10 branch** because its safe-publication behavior, screen/appearance, and 31-file release source pin are tied to the exact Git blob `cb01cce5f7ed30f2670361ec5fad93ac3c57a693`. Never substitute the stale static tables embedded in main's former HTML as LIVE prices; never change styling, colors, fonts or panel arrangements in this conflict resolution.
3. **Use the reviewed V10 branch for code/workflow/doc changes**. Preserve every other `main` path untouched (because their contents have not changed on the V10 branch).
4. Preserve the original `main` HTML in Git history through the merge's `main` parent, not as another browser-executable HTML copy.
5. Retain source validation, scoped Excel controls, safe-stop, fail-closed market freshness and `real_submit_allowed=false`. No merge process, verification check, or research sidecar can promote a virtual trade into a real one.

## Important operational distinction
Keeping all 36 main JSON files does **not** imply that every historical HTML snapshot card displays the latest data. Real source timestamps, MS2 polling, observation freshness and UI publication fail-closed rules must separately pass real-machine acceptance. The V10 candidate intentionally replaces some HTML-embedded old price tables and scoring with safe unknown/blocked states. This is an essential safety change, not a statement that market data is unavailable.

The new candidate must pass exact-HEAD GitHub CI (Windows and Ubuntu), including source-pin manifest, UI fail-closed, safe-stop and main-data preservation checks before any main merge. The source branch's prior CI is not a substitute for this candidate's CI.

**Acceptance state:** Synthetic tests PENDING; Windows/MS2 owner hardware not tested; `main` unchanged by creation of this branch; auto-launch, merge to `main`, order activation, vendor API authorization and credentials are out of scope. `real_submit_allowed=false`. Economic profit and strategy EV UNKNOWN.
