# 100億PROJECT — OpenAI Agents SDK coordination pilot

Status: DRAFT / OFFLINE RESEARCH ONLY / NOT DEPLOYED. A Draft PR does not authorize an API cost or a runtime change. The new agents are NOT the existing ChatGPT Tasks. The old tasks remain scheduled and unchanged.

## Purpose

An independent, explicitly initiated programmatic coordinator running PRE-NEXT, supply/SQ, Revenue Hunter and an overarching coordinator. The official OpenAI Agents SDK (https://openai.github.io/openai-agents-python/) is imported only when there is an explicit OWNER-approved billable API trial.

Pipeline: public-only, dated evidence JSON -> three separated specialist research agents -> coordinating research agent -> validated research-only result -> optional locally stored receipt.

The system has NO broker, Excel, MS2, V10 runtime, GitHub writing, scheduled Tasks, private market data, payment, or auto-deployment tool. Existing safety gates and Task settings are untouched.

## Offline synthetic validation (no key and no network)

    python -m unittest discover -s tests -p test_agent_sdk_coordination_pilot.py -v

Provide an explicitly public-safe JSON file with schema_version, run_id and up to 30 sources. Every source must contain exactly the following fields:

- source_id: unique public-safe identifier
- role: pre_next, supply_sq or revenue_hunter
- source_url: public HTTPS URL with no credentials, query or fragment
- as_of: observation timestamp in offset-aware ISO 8601
- available_at: earliest public availability timestamp
- summary: at most 400 characters of NONPRIVATE public evidence

Synthetic example, NOT market evidence:

    {
      "schema_version": "100b-public-agent-evidence-v1",
      "run_id": "synthetic_20261020_01",
      "sources": [{
        "source_id": "example_jpx_001",
        "role": "supply_sq",
        "source_url": "https://www.jpx.co.jp/markets/",
        "as_of": "2026-10-19T09:00:00+09:00",
        "available_at": "2026-10-19T15:00:00+09:00",
        "summary": "Synthetic example only; no real market claim"
      }]
    }

Save to a local example.json and run:

    python scripts/agent_sdk_coordination_pilot.py --input example.json --offline-test

Expected state OFFLINE_SYNTHETIC_NO_API_CALL. The offline provider is a stub and performs ZERO model inference or external communication. Roles lacking input return NO_DATA.

## Paid API (not authorized to execute in this Draft)

Separate OWNER approval and local cost-control setup are mandatory before enabling API calls. Example gated manual invocation ONLY after approval:

    pip install openai-agents
    python scripts/agent_sdk_coordination_pilot.py --input example.json --enable-billable-api --receipt-db private_receipts.sqlite

Also requires OPENAI_API_KEY set privately. Multiple model calls can incur charges. THIS FIRST PILOT HAS NO HARD API BUDGET CEILING and is therefore not production ready. There is no automatic API invocation, no scheduled task, no API key committed to GitHub. The SDK's default tracing upload is disabled in code, but approved public-only excerpts are still submitted as model input. Source URLs are syntax validated; content is not independently fetched or verified in this pilot.

The optional SQLite receipt contains only run ID, source fingerprint, output hash, timestamp and research state. It is local-only and must never be committed. Identical repeated receipts are idempotent; conflicting reuse of a run ID blocks. Crash-safe at-most-once billable API requests are NOT yet implemented and must be designed before any scheduled use.

## Invariants

- as_of <= available_at <= evaluation time, explicit time zone required; future/missing/invalid means BLOCKED.
- Specialist WATCH requires IDs drawn from its provided role-specific sources. Hallucinated IDs or unsupported roles mean BLOCKED.
- Coordinator receives verified specialist summaries only; it cannot call an order route or independently approve a release.
- Output is research only: real_submit_allowed=false, actual_profit_yen=null, costs_verified=false, broker_fills_verified=false, promotion_eligible=false.
- No write to existing Shadow ledgers and no changes to Brain/Risk Gate/Permission Gate/Kill Switch.
- No modification of D-023 single-Excel restriction; no live V10 launch or source-pin changes; no GitHub Issue #282 write from runtime.
- GitHub Actions executes only Python standard-library offline tests on Windows and Ubuntu, no API key or cost.

## Acceptance gates

1. Pass offline cross-platform CI and independent review on exact Draft HEAD.
2. OWNER decides source availability contracts, API budget, model/key custody and spending cap; no charge before approval.
3. In an approved private runtime, test real SDK multi-agent result with explicit one-time billing authorization and strict call/accounting ceilings.
4. Add a read-only local Brain inbox adapter with independent source authentication, point-in-time semantics, restart persistence and receiver ACK.
5. Confirm live compatibility, Windows stop/recovery, safe source evidence and Shadow backtesting on a separate approved candidate SHA.
6. DEPLOYED and PRODUCTION_VERIFIED require independent evidence; the Draft is neither.
7. Real orders or hedges require a wholly separate explicit OWNER authorization, which is NOT granted.

Trading P/L, revenue, expenses, net profit, verified EV/PF/N and remainder to 100億 are UNKNOWN.
