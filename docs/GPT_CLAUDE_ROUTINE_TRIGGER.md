# ChatGPT next instruction → Claude Routine (opt-in)

Status: implementation for Draft PR review, **not enabled or live-tested**.

This bridge is intentionally narrow: a verified ChatGPT GitHub Connector comment on Issue #171 may create one Claude Routine session for a reviewed repository-only task. It does not merge PRs, enable broker submit, change canonical trading semantics, expose private market/account data, or activate Scheduled Tasks.

## Authentication boundary

The bridge does **not** use an application-managed signing key.

GitHub already records which connected GitHub App performed an issue-comment write. The bridge re-fetches the live comment from the GitHub REST API and accepts it only when all of the following are true:

- repository is exactly `infoyuusuke-afk/trade-cockpit`;
- issue is exactly `#171` and is still open;
- GitHub user ID is exactly `307830101`;
- `performed_via_github_app.id` is exactly `1144995` (observed ChatGPT Codex Connector);
- that App owner ID is exactly `14957082` (OpenAI);
- comment body and timestamps still equal the original `issue_comment` event;
- the comment is less than 15 minutes old according to GitHub's server-owned `created_at`;
- the instruction is bound to the exact default-branch SHA that triggered the workflow;
- current `main` is still the same SHA and is reported protected by GitHub.

Independent evidence on 2026-09-22 showed multiple ChatGPT-authored Issue #171 comments attributed by GitHub to App `1144995`, while the Claude run report was attributed to a different App (`1236702`). A manual Owner comment, PAT comment, GitHub Actions comment, Claude comment, or another App therefore fails closed even when the visible GitHub username is the same.

If OpenAI changes the connector App identity, the bridge intentionally stops until this code and the observed GitHub provenance are reviewed again.

GitHub references:
- Issue comment REST API: https://docs.github.com/en/rest/issues/comments
- Actions `issue_comment`: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Git refs API: https://docs.github.com/en/rest/git/refs#create-a-reference

## Trusted-main requirement

The workflow has two protection gates:

1. job condition: `github.ref == 'refs/heads/main'` and `github.ref_protected == true`;
2. runtime: `GET /branches/main` must report `protected: true` and the exact reviewed SHA, both before reservations and immediately before the Claude API call.

Independent review on 2026-09-22 found current `main` unprotected and repository rulesets empty. Production firing is therefore blocked by design.

Do not treat a cosmetic protection rule as sufficient. The activation design must prevent Claude or an unreviewed automated writer from replacing `.github/workflows/gpt-claude-routine.yml` or `scripts/routine_bridge.mjs` and then obtaining the Environment secrets. This repository also has existing Actions that commit generated public data directly to `main`, so branch/ruleset changes must be designed without silently breaking those required data writers or granting a broad bypass to untrusted workflows.

## Owner setup after approved merge

1. Protect trusted `main` and the bridge code path. Keep `CLAUDE_ROUTINE_BRIDGE_ENABLED` unset or `false` while configuring. Confirm the resulting branch endpoint reports `protected: true`.
2. Create GitHub Environment `claude-routine-bridge` and restrict it to the trusted `main` deployment path.
3. In the existing Claude Routine settings, add an API trigger and obtain its per-routine values. Store only in that Environment's Actions Secrets:
   - `CLAUDE_ROUTINE_TOKEN`: per-routine bearer token;
   - `CLAUDE_ROUTINE_ID`: the `trig_...` identifier.
   Never put either value in an issue, repository file, public log, or ChatGPT/Claude instruction.
4. Ensure the Claude Routine's own schedule/GitHub triggers are off if this bridge is intended to be the only automatic entry point.
5. Update the `AI Cockpit GPT Reviewer` producer so that, only after a meaningful verified change and only when no Claude session is active/unknown, it posts the exact V2 envelope below through the connected ChatGPT GitHub Connector.
6. Set repository variable `CLAUDE_ROUTINE_BRIDGE_ENABLED=true`.
7. Run one harmless documentation/test-only end-to-end task. Verify:
   - exactly one bridge Action starts;
   - exactly one Claude session is created;
   - an ordinary Owner comment does not fire;
   - a Claude-authored comment does not fire;
   - a replay of the same task ID does not fire;
   - moving or unprotecting main blocks delivery.

No merge approval is implied by this setup guide.

## Producer protocol

The entire new Issue #171 comment must be exactly four lines:

```text
GPT-CLAUDE-NEXT-V2
main_sha: <current 40-character reviewed main SHA>
task_id: <stable 1-80 character A-Z/a-z/0-9/_/- identifier>
text: <one-line public next instruction, at most 8000 characters>
```

There is no signing key, public key, producer token, or timestamp field.

Freshness comes from GitHub's immutable comment `created_at`. The workflow accepts a comment only for less than 15 minutes. If `main` changes between review and execution, the attempt blocks. Use one stable `task_id` for one approved task/evidence revision; do not mint a new ID merely to bypass a consumed reservation.

The optional local formatter remains:

```text
node scripts/routine_bridge.mjs encode public-instruction.json
```

where the JSON contains only `main_sha`, `task_id`, and one-line `text`. The ChatGPT Automation does not need this command; it can emit the four lines directly.

## Delivery, limits and recovery

Before contacting Anthropic, the workflow creates permanent atomic Git refs:

- `refs/tags/routine-bridge/intent/<SHA256(task_id)>`
- `refs/tags/routine-bridge/budget/<UTC six-hour bucket>`

The intent ref prevents replay of a task ID. The budget ref allows at most one attempted delivery in each UTC six-hour bucket, at most four per UTC day. These are conservative attempt limits, not a session-completion lock.

State is:

`validated provenance → trusted protected main → intent reserved → budget reserved → trusted main rechecked → POST attempted → accepted or UNKNOWN`

Claims are never rolled back. A timeout, HTTP error, redirect, malformed response, uncertain ref write, main movement, or protection loss stops without automatic retry. Because the Claude Routine API exposes no idempotency key, delivery is deliberately **at-most-one attempt per task**, not exactly-once execution.

A budget rejection consumes the task ID. A crash after reservation may lose that task. Do not delete reservation refs or automatically create a replacement task ID after an UNKNOWN result. Inspect Actions and Claude session history first; only the Owner/GPT review process may approve a later replacement task.

To stop the bridge, set `CLAUDE_ROUTINE_BRIDGE_ENABLED=false`, cancel queued/running bridge jobs if necessary, and pause/revoke the Routine token in Claude. Existing Claude sessions must be handled separately.

## API contract checked 2026-09-22

Claude Routine API:
https://platform.claude.com/docs/en/api/claude-code/routines-fire

Expected request:
- POST `https://api.anthropic.com/v1/claude_code/routines/{trig_id}/fire`
- per-routine Bearer token
- `anthropic-version: 2023-06-01`
- beta `experimental-cc-routine-2026-04-01`
- JSON body containing only `text`

HTTP 200 creates a session; it does not prove session completion. The implementation follows no redirect and performs no automatic retry.

## Validation

`node --test tests/routine_bridge.test.mjs` uses mocked GitHub/Anthropic HTTP only and no secrets. It covers:

- wrong user/repo/issue/event;
- ordinary Owner comment;
- old V1 envelope;
- stale/future/edited comments;
- live body/timestamp mutation;
- missing App provenance;
- Claude App instead of ChatGPT App;
- wrong App owner;
- unprotected or moved main;
- duplicate task IDs and concurrent attempts;
- six-hour budget;
- uncertain reservation writes;
- API timeout/401/429/500/redirect/bad response;
- no automatic retry;
- protected-main workflow gate;
- absence of signing-key configuration.

Live Environment storage, branch/ruleset enforcement, the producer update, and one harmless end-to-end Claude session remain deployment acceptance steps.
