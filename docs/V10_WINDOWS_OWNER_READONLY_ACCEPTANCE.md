# 100億PROJECT — V10 Windows read-only LIVE acceptance (owner one-click)

PROJECT_ITEM_ID: P0-V10-WINDOWS-OWNER-READONLY-ACCEPTANCE-20261020
Status: GitHub code / synthetic only until owner's Windows PC evidence is checked.

## Safeguards and scope
This is a point-in-time read-only inspection of an already-running Windows V10
on an independently reviewed main checkout. It is not a start/stop button and
never installs, updates, checks out or modifies code. It never authorizes a
broker/order, reads private strategy or account rows, saves raw market data,
or posts PC diagnostics to public GitHub. Output is fixed status labels only.

Local-only downloads/V10_APPROVED_SOURCE.json (ignored by Git, owner-controlled)
is REQUIRED. The tool never invents, updates or signs one. Its branch must be
main, its commit_sha must exactly match the independently reviewed full 40-
character HEAD of the Windows checkout, and real_submit_allowed must be false.
A GitHub merge does not create this file on the owner's PC.

## Owner steps
1. Prepare an independently reviewed, clean Windows checkout on main. Do not
   silently git reset, overwrite local files, alter MS2 or replace business
   Excel. Its source pin/approval must match that checkout. Run the existing
   START_AI_COCKPIT_V10.ps1 with -VerifyOnly before launching; this is a
   read-only pre-launch source and 31-file bundle test.
2. Only after OWNER approval, launch using the existing
   downloads/START_AI_COCKPIT_V10.cmd (or already approved one-click entry).
   The new acceptance tool NEVER launches V10. Wait until Gateway and Brain
   publish fresh local observations.
3. Double-click downloads/V10_WINDOWS_READONLY_ACCEPTANCE.cmd.
   It invokes the new PowerShell read-only inspector; results stay visible
   in the console and no data is uploaded.
4. PASS prints V10_WINDOWS_READONLY_ACCEPTANCE=OBSERVATION_ONLY,
   V10_LOCAL_SOURCE_PIN=PASS, V10_BRAIN_LOCAL_HEALTH=PASS,
   V10_REAL_MARKET_AUTHENTICITY=NOT_VERIFIED,
   V10_REAL_TRADING_ACCEPTANCE=NOT_APPROVED, and REAL_SUBMIT_ALLOWED=0.
   BLOCKED and exit 2 are expected if the session is absent, mismatched,
   stale, unapproved, or not on main. Do not bypass the pin or safety checks.
5. When finished, use the existing V10 safe stop entry under its operator
   procedure. This inspector does NOT stop any process.

The default Controller state directory is C:\AI_Cockpit_OneClick_Starter,
and the repository root defaults to the parent of the inspector's downloads/
folder. Authorized operators can explicitly pass a different -StateRoot to
V10_WINDOWS_READONLY_ACCEPTANCE.ps1 if their V10 StateRoot differs.

## Meaning and limitations
The existing BRAIN preflight verifies exact Git SHA and branch, Controller
and BRAIN process ownership, local Gateway 127.0.0.1:28581/health, fresh
timestamps, 90–110 observed rows, fail-closed status and no real orders.
It is not an exchange-authentication system, nor does this one-click
inspection independently prove 100/100 symbol completeness. It is not
proof of MS2 provider provenance, real fills, profitability, research
sidecar private-context availability or continuing liveness.

For research sidecar acceptance, see
docs/V10_BRAIN_RESEARCH_WINDOWS_ACCEPTANCE.md. That separate workflow
requires a preselected local private context; the one-click inspection
does not create it or read its trading/private data.

## Synthetic CI
The dedicated workflow checks exact proof output, negative cases, unexpected
extra stdout, duplicates, forged unsafe flags, PS5.1 parser and static
non-mutating properties. No real Windows MS2/Excel/Controller is started
in CI. OWNER real-machine acceptance is NOT_RUN until verified on the PC.
