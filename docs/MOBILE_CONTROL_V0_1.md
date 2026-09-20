# AI Cockpit Mobile Control v0.1

## Goal
Make iPhone Chrome and iPad Chrome first-class control terminals. The owner performs approval/rejection/emergency-stop decisions; routine data collection, analysis, testing and implementation are delegated to agents/workers.

## Device roles
- iPhone Chrome: immediate trade alerts, approval/rejection, emergency stop, system-update approval.
- iPad Chrome: all iPhone controls plus charts, EV performance, NIKKEI FLOW RADAR, overnight/swing AI meeting summaries.
- Windows Worker: MS2/RSS, TradingView-derived processing, live execution sensors and local-only integrations.

## Trading modes
### Scalping / intraday live / surge detection
No AI meeting in the critical path.
Market data -> features -> Expected Value Engine -> Risk Gate -> LONG/SHORT/WAIT/EXIT -> owner approval where required -> result logging.

### Overnight / swing / long-term
Strategy + Fundamental/Catalyst + Quant + News -> structured AI meeting -> Risk/QA -> consolidated proposal -> owner approval.

## Mobile approval contract
Each approval card must expose:
- request_id
- request_type: trade | system_update | emergency
- symbol (trade only)
- action: LONG | SHORT | WAIT | EXIT
- ev_score (0-100)
- empirical sample size N
- realized historical metrics where available: average P/L, PF, max DD
- trigger/reason summary
- data freshness timestamp
- risk-gate state
- status: pending | approved | rejected | expired
- created_at / expires_at

The EV score is not a probability of price increase.

## Safety gates
- Never allow an approval when required live data are stale.
- Approval requests expire.
- Duplicate taps must be idempotent.
- System updates and trade approvals are separate permission domains.
- Emergency stop must be visible from every mobile control screen.
- v0.1 must not directly place a live broker order. It establishes the approval/control path first.

## UI
Responsive Chrome-first web UI.
Visual direction: professional chart-centric trading terminal with restrained premium hardware-UI aesthetics; no direct copying of proprietary UI.
Character/voice layer must not obstruct real-time signals.

## Acceptance criteria
1. iPhone Chrome: approval list and approval detail usable without horizontal scrolling.
2. iPad Chrome: split view supports approval queue plus detail/analytics area.
3. Mock trade request can transition pending -> approved/rejected.
4. Expired/stale request cannot be approved.
5. Emergency-stop control is persistent and requires confirmation.
6. All actions create an append-only audit record.
7. Existing desktop cockpit remains functional.
8. No live broker order is sent in v0.1.
