# V10 Brain research-only judgment layer

PROJECT_ITEM_ID: P0-V10-BRAIN-RESEARCH-CONSUMER-20261020

## Change and boundary

PR #461 produces a private `brain_research_context_v1.json` but has no consumer.
This separate module consumes that existing format and makes only a research
workflow judgment. A valid one-sample context requests more virtual samples;
missing, stale, malformed or inconsistent input yields `BLOCKED/HOLD_RESEARCH`.
There is no last-good cache. No strategy is selected for trading.

`scripts.v10_brain_research_consumer.py` exposes `consume_local` and a one-shot
CLI. It is the opt-in Brain research layer, **not installed in the running Brain**.
Existing observer, producer, runtime bundle, UI, CSS, process lifecycle, Excel,
hourly tasks, other AI configuration and real execution routes are unchanged.
No broker, network, paid API, timer, subprocess or file-write code is present.

## Contract

- Exact #461 success schema and literal false safety flags; unknown fields,
  duplicate JSON keys, non-finite values and unsupported schemas fail closed.
- Both quote time and file mtime must be within 0..60 seconds of the aware
  decision clock. Future clocks and quotes newer than file mtime are rejected.
  Rewriting an old file cannot refresh its quote. This does not recheck original
  board rows; the consumer validates the aggregate snapshot from #461.
- Require exactly 100 verified board rows, bounded integer counts, observation
  counts totaling at most 100, unique strategy IDs, finite/range-checked virtual
  statistics, exact sample threshold flags, and clean-total reconciliation.
- Explicit absolute private directory and expected filename only. Reject
  UNC/device/relative/traversal paths, symlinks, Windows reparse points and
  hardlinks. Bounded regular-file read (64 KiB), descriptor/path identity checks
  before/after read; detected concurrent mutation returns BLOCKED.
- Strategy names are untrusted data, never instructions. They and all virtual
  returns, raw market data and local paths are omitted from the result.
- Output is only an anonymous state, reason, research decision, sample count,
  data-lane label and permanently false safety flags. CLI exit: 0 research-only,
  2 blocked. A zero exit is not permission to trade or deploy.

Research decisions: `COLLECT_MORE_VIRTUAL_SAMPLES`,
`REVIEW_CONTAMINATED_VIRTUAL_DATA`, `REVIEW_VIRTUAL_RESEARCH_ONLY`.
The inherited threshold of 20 is bookkeeping only, not a statistical test.
No ranking by virtual profit, expected value, sizing or order recommendation.

## Use after separate deployment review

From a reviewed checkout (use `-B` to avoid Python bytecode writes):

```text
python -B -m scripts.v10_brain_research_consumer --private-dir <absolute-owner-selected-private-shadow-dir> --context <same-dir/brain_research_context_v1.json>
```

Do not copy private input into GitHub or invoke the writer as part of consumption.
The module reads only the specified context; it neither regenerates nor repairs
the producer output. The caller must handle BLOCKED each invocation.

The selected directory is not proof of privacy or cryptographic authenticity.
A privileged adversary can forge timestamps/content or race filesystem checks;
this is not an adversarial filesystem sandbox. Source authentication remains
false. No persistent anti-replay/cross-run monotonicity or source-origin proof
is claimed. File access may update OS access-time metadata.

## Independent baseline inspection (2026-10-20 JST)

Main observed: `501f93024970fcc52486775c030ad30e24055094`.
All dependencies below were OPEN Draft, unmerged; their reported checks were
SUCCESS except #444 Owner Main Approval Gate SKIPPED (not approval).

| PR | Exact HEAD | Relevant CI run |
|---|---|---|
| [461](https://github.com/infoyuusuke-afk/trade-cockpit/pull/461) | `343315b9ec041329a0296e7af1dbc86690e879c8` | [39277281673](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39277281673) |
| [459](https://github.com/infoyuusuke-afk/trade-cockpit/pull/459) | `d1c35f6df86cae443dca4796bef855d84687b8ee` | [39275632114](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39275632114) |
| [458](https://github.com/infoyuusuke-afk/trade-cockpit/pull/458) | `716bcacedfefaac6aa004006a4359ef6e0c7b73a` | [39270822148](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39270822148) |
| [457](https://github.com/infoyuusuke-afk/trade-cockpit/pull/457) | `7a84ec1f1ce67bdc2cbb71c5dc760f333743d45b` | [39267053431](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39267053431) |
| [456](https://github.com/infoyuusuke-afk/trade-cockpit/pull/456) | `e3796ff23363e51cd5f1a76810d2402a90cde573` | [39239772822](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39239772822) |
| [446](https://github.com/infoyuusuke-afk/trade-cockpit/pull/446) | `46081f8a3589d35c56c2a4c6f601792caaf9714f` | [39221960828](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39221960828) |
| [444](https://github.com/infoyuusuke-afk/trade-cockpit/pull/444) | `c7163273b3aefeba105848dce3394fdf6eeb793f` | [39083947522](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39083947522) |

This PR is separately reviewable on #461's branch; it is not independent of
the unmerged stack. No parent PR is modified, merged or closed.

## Validation and remaining gates

27 new consumer tests plus 21 bridge and 18 audit regressions, all synthetic.
The workflow explicitly checks out the PR's exact head SHA on Ubuntu/Windows.
Tests include producer-to-file-to-consumer integration, no data/mtime changes,
malformed/duplicate/non-finite JSON, unsafe flags, freshness, count mismatches,
sample-vs-EV separation, filesystem replacement, links and sanitized CLI errors.
Local Windows: 66 discovered, 62 passed, 4 symlink cases skipped due to OS
privileges. Reparse-attribute rejection is separately exercised without skipping.
Initial sandbox-only filesystem errors were environment restrictions; the
isolated disposable-folder run outside the sandbox passed as stated above.

**Actual OWNER Windows/MS2 Acceptance: NOT_RUN.** No real private context read.
Deployment, running-Brain wiring, independent code review, source authentication,
real fills/costs/slippage, forward/out-of-sample EV validation: NOT_DONE.
Synthetic CI does not satisfy any of those gates. All paths preserve
`real_submit_allowed=false`, `brain_trade_decision_eligible=false`,
`tested_expectancy_available=false`, `promotion_eligible=false`.
Economic impact, realized profit and progress toward 100B JPY remain UNKNOWN.
