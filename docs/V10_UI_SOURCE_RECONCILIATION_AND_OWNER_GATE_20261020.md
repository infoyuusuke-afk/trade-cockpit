# AI Cockpit V10: UI source-of-truth reconciliation / OWNER decision gate
Date: 2026-10-20 JST  
Status: **EVIDENCE-BASED DRAFT; NOT A NEW APPROVED UI SPEC**  
Scope: freeze the current facts, recover prior decisions, and define acceptance BEFORE changing tab names/positions.

## Authority and sources

- Historical Master Project Specification, 2026-09-21: the AI Council / Strategy Lab / Command Center / Event Bus / Live Commentary / Journal / Shadow evidence loop, profitability objective and fail closed.
- Interim operation specification AIC-OPS-TEMP-001, 2026-10-02: PREOPEN, ZARABA, JOURNAL_CLOSE, AFTER_HOURS, Excel isolation, Journal closure, stale handling and PTS source independence.
- Historical **2026-10-08 16:30 JST** `AIトレードコクピット 配置固定案` image: 16 displayed top tab labels and a BRAIN fixed position mock. The image itself says **モック**. Do not falsely classify it as a separately verified owner sign-off.
- [Issue #266](https://github.com/infoyuusuke-afk/trade-cockpit/issues/266): V10 UI intelligence redesign, strategy KPI CONTROL, EVENT escalation, REALTIME gate, KIOXIA probability and earnings 30-day research.
- [Issue #251](https://github.com/infoyuusuke-afk/trade-cockpit/issues/251): market-provenance-gated LIVE narration / transitions / conditional net EV.
- [Issue #387](https://github.com/infoyuusuke-afk/trade-cockpit/issues/387): Owner's 2026-10-16 observation of duplicate windows and stale timestamps.
- `index.html`, `trade_control.js`, `earnings-calendar.js`, `scripts/weekly_tabs.py`, `v10_publication_status.js` on main, source audited 2026-10-20. UI static code alone is insufficient: runtime JS inserts tabs/cards.
- Related isolated remediation [PR #471](https://github.com/infoyuusuke-afk/trade-cockpit/pull/471) and stacked [PR #472](https://github.com/infoyuusuke-afk/trade-cockpit/pull/472); no merge/deploy authorization.

The most recent explicit OWNER decision supersedes generated code and earlier proposals. Where authority conflicts, **OWNER must decide**; do not reinterpret a mock or open Issue as unconditional permission.

## A. Historical top navigation — 16 slots (2026-10-08 mock)

01 CONTROL | 02 BRAIN | 03 AIトレード日記 | 04 SCALP | 05 EVENT | 06 REALTIME | 07 OVERNIGHT | 08 SWING | 09 VALUE | 10 FOCUS | 11 決算 | 12 相関 | 13 下ヒゲ | 14 拡大 | 15 大口 | 16 参考

Do not change the sequence, visual design, fonts, card positions or scroll behavior merely to align with current source. First resolve whether the mock's 16-tab nav remains binding after later implementation.

### BRAIN fixed structure in the historical mock

1. Always-visible upper left: BLOCK / 判断保留 when price identity, freshness, market mode or source remains unverified. No symbol/direction/EV presented in that state.
2. Upper right: **five permanent notice slots** (no automatic card reordering):
   P0-01 price/source mismatch; P0-02 Shadow stop; P0-03 SCALP5 data; P0-04 100-stock coverage; P0-05 displayed date.
3. Lower scroll region only: four ordered cards: SCALP5 monitor, 100銘柄 Precision Watch, 採用可能な判断, AIトレード日記への記録.
4. Audit/evidence detail below: clock/source distinction, reconnection vs real authenticated live, historic predictions not silently promoted, user-selected FOCUS stable.
5. Alerts may NOT change tab, card order or scroll position. Colors and fonts remain as shown; real submit OFF.

## B. Actual on-main navigation (source facts, not a replacement specification)

`index.html` declares **10 primary static buttons** in this order:
CONTROL [control], BRAIN [brain], SCALP 5 [scalp], EVENT 5 [event-hot], REALTIME 5 [ms2-live], OVERNIGHT 5 [overnight], SWING 5 [swing], VALUE 5 [value], KIOXIA [kioxia-calendar], 注意 [events].

The `参考` menu declares **10 static secondary buttons**:
円高恩恵TOP5 [strong-yen], 対米投資・SMR [us-smr], 主体レジーム [investor-regime], 検証・除外 [market], 相関 [correlation], 下ヒゲ [wick], 拡大 [expansion], 大口 [accumulation], 国策 [policy], 週間 [weekly].

**Dynamic navigation (critical):** `earnings-calendar.js` creates a further **決算日程 [earnings]** primary button before 注意. Thus effective primary order after successful script execution has **11** entries, plus 10 secondary buttons (21 button destinations, excluding nested policy panes). A static-only inventory wrongly calls earnings absent.

**Dynamic CONTROL (critical):** `trade_control.js` inserts owner-control-overview, owner-strategy-performance and per-pane performance/execution summaries. CONTROL is **not blank**. The audit does not establish that actual records are present or fresh.

### C. Existing section-to-tab allocation in current `index.html`

Order below follows current DOM/reparenting mapping. This is an inventory, not a proposed re-layout.

| Current destination | Current sections / injected content (DOM sequence) |
|---|---|
| CONTROL | `trade_control.js` summary, real/Shadow status, strategy-level performance, trace/provenance lanes |
| BRAIN | inline V10 health grid; `trade_control.js` per-pane summary; historical fixed upper/lower notification structure NOT verified |
| SCALP 5 | injected fixed 5 x one-minute MS2 cards, shared renderer |
| EVENT 5 | event introduction; `speculative-theme-monitor`; 短期急騰期待TOP5 |
| REALTIME 5 | `data-quality-gate`; `next-theme-radar`; `action-dashboard` (FOCUS-look cards); `watchlist-100`; `premarket-gap-ranking`; `market-ranking-watch`; `tradingview-screener-watch`; `ms2-live-top5`; 本日IN点灯; 本日準備点灯TOP30 |
| OVERNIGHT 5 | `overnight-top5`, 15:25 evidence/decision |
| SWING 5 | 安定上昇TOP5; 52週新高値TOP5; 急騰後過熱TOP5; AIスイングサイン; 持越しLONG / SHORT TOP5 |
| VALUE 5 | 月週足反転TOP5; `long-term-ma-rebound`; `dividend-rights-watch`; `buyback-watch` |
| KIOXIA | `kioxia-5m-calendar` (source contains old 285A name; code-migration scope separate) |
| 注意 | `event-calendar`; 市場警報 |
| 決算日程 (dynamic) | `earnings-calendar-panel`; 決算勝負TOP15 moved at runtime from its original pane |
| 円高恩恵TOP5 | `strong-yen-top5` |
| 対米投資・SMR | `us-smr-watch` |
| 主体レジーム | `investor-regime` |
| 検証・除外 | 世界市況; 市場環境; 地合いサマリー; 朝8:00候補の答え合わせ; TradingViewリスト出力; 運用ルール; 選定ロジック; 占い等; title-less sections require explicit DOM audit |
| 相関 | `correlation-monitor` |
| 下ヒゲ | `lower-wick-reversal` |
| 拡大 | BB上方エクスパンションTOP7 |
| 大口 | `large-lot-accumulation` TOP20 |
| 国策 | 資金流入テーマTOP5, priority overview, 秋田AI, 群馬レアアース, sector rotation, silicon photonics; separate nested panes: physical-ai, autonomous-driving, ai-drug-discovery, ai-semiconductor, defense-space, gx-power, quantum-computing |
| 週間 | `weekly-review`, later upgraded by `trade_control.js` from `weekly_review.json` |

At least three additional untitled sections route to the default [market] lane. Dynamic cards, hidden elements, and effects from other scripts demand browser-level inspection; this list does not claim complete runtime DOM verification.

### D. Confirmed specification / implementation conflicts

- Historical 16-tab layout vs current 11-primary-plus-10-reference (+7 policy nested) are NOT equivalent.
- AIトレード日記 and FOCUS are missing as independent top buttons; `action-dashboard` with FOCUS style is currently inside REALTIME 5. Do not infer that the OWNER chose to merge/retire FOCUS.
- The historical mock lacks KIOXIA and 注意 as independent top labels, whereas Issue #266 treats KIOXIA as a dedicated intelligence surface. OWNER decision required on its location.
- Issue #266 requires no visibly rendered data-quality gate or NEXT THEME RADAR in REALTIME 5; currently **both** route to REALTIME 5. NEXT THEME should be a research/source lane with evidence-bound escalation to EVENT 5. Moving these changes **tab content** and requires frozen target allocation before implementation.
- Existing control/performance and earnings are loaded dynamically. Earlier static-only statements calling CONTROL empty and earnings missing were inaccurate.
- `index.html` still includes static dated 2026-09-25 values and a Ver.5.4 header; these are not independently authenticated V10 LIVE values. Source/publication staleness and Browser/Windows real-screen reconciliation are P0.
- `scripts/update.py` and `scripts/weekly_tabs.py` regenerate legacy HTML; PR #471 blocks legacy page replacement in the scheduled generated-data writer. This alone does NOT prove every static card has fresh dynamic wiring.
- The Brain grid originally claimed 28584 ONLINE without checking the observer proof, and displayed UNKNOWN data conflict as FALSE; PR #472 corrects these source-only problems, **not** a real-machine proof.
- Writer/fail-closed protection requires keeping selected static data from being interpreted as live. A full screen acceptance must separately verify actual data provenance, source timestamps and no UI reordering.

## E. AI-upbringing / 100億 objective — non-negotiable acceptance

V10 must be an evidence-driven **observe -> discover -> challenge -> validate -> Shadow -> outcome -> learn** system. Features proposed by AI are scored and validated, not displayed as proven because a code test passes.

- Source layer: immutable point-in-time `available_at`, MS2 provenance, quote freshness, 100-stock coverage, board changes, asynchronous Writer + independent readback, missing/duplicate/gap/latency reasons.
- Discovery: PRE-NEXT picks before events (not post-rise publicity), missed-mover recall outside fixed100, material/earnings and PTS early signals, follow-on/pullback/fade classification.
- Council/Brain: immutable proposals, counterevidence, Risk gate, confidence and unverified-state semantics, coordination receipts, no fictional LIVE or implicit permissions.
- Strategy Lab: net EV (slippage/fees), PF, drawdown, enough N, chronological OOS/WF, post-selection leakage check, market-regime/time-of-day partitions and forward Shadow evaluation.
- Evaluation/upbringing: timestamped hypotheses, misses, latency, calibration/revision, strategy promotion/reversion evidence, independent acceptance and version lineage.
- CONTROL: Real, paper/Shadow and backtest segregated. Do not equate synthetic returns with ¥10B realized net P&L. Top 100億 expectation score (model metric only, source/uncertainty clearly stated) requires user-visible and auditable specification before implementation.
- Safety: real execution disabled (`real_submit_allowed=false`), no RssOrder, no live hedges, no automatic order replay, no private MS2/account data in public GitHub.

## F. Required acceptance before implementation claims

| Gate | PASS evidence |
|---|---|
| UX-01 | OWNER resolves authority for 16-tab mock vs current 21 navigation; exact tab names, order and internal card array accepted; no redesign by developer inference |
| UX-02 | Card IDs/table positions/pane DOM unchanged unless covered by UX-01; alert cannot navigate, reorder cards, or move scroll |
| DATA-01 | source timestamp, `available_at`, quote identity, freshness and Writer independent readback match; stale/unknown is neutral and non-actionable |
| OPS-01 | exact GitHub UI SHA / release manifest, localhost served asset lineage, no old `scripts/update.py` page overwrite |
| TEST-01 | negative tests, synthetic CI, current HEAD and independent code review; missing/contradictory source causes FAIL-CLOSED |
| WIN-01 | OWNER Windows real UI boot, data refresh, all tabs and buttons, Brain, Journal, save/stop/restart evidence; no MS2/Excel destructive operations |
| EV-01 | post-implementation measurable uplift (miss detection, stale rate, latency, net Shadow EV), no gain claimed from synthetic alone |

## G. Decisions to request from OWNER — **no guessed approvals**

**D-UI-1: Canonical top navigation and content authority.** Should the 2026-10-08 fixed 16-tab layout be promoted as exact latest canonical navigation? Specifically reconcile `KIOXIA` with FOCUS and the separate `決算日程` insertion; choose whether reference sub-tabs remain nested as-is. No placement changes until this is explicitly decided.

**D-REL-2: UI-source re-pin / release.** Source-only PR #472 modifies the V10 pinned `index.html`. Current manifest and CI deliberately reject the new SHA. Obtain independent current-HEAD review, explicitly authorize exact UI source/hash update and runtime bundle pin reconciliation **without relaxing the hash gate**, then repeat CI and Windows acceptance. PR #471 and #472 remain Draft; no merge until sign-off.

Unrelated old/retired specs, new IPC mechanisms, automations/schedules, and real-order paths must not be touched. Preserve public-safe coordination on Issue #282 and OWNER operations minimal.

## H. Updated OWNER delegation — necessity-first functionality decision, 2026-10-20

OWNER subsequently explicitly authorized the development lead to **keep, delete or modify UI functions based on necessity for ¥10B net realized profit**, instead of requiring preservation of the historical 16-tab count. This **supersedes D-UI-1 as an individual yes/no request**. A safe Draft design iteration is within the authorized scope; no independent approval bypass, real trading, automatic merge or Windows deploy is implied.

### Chosen navigation for Draft PR #474 (function-first; visual style retained)

Primary top-level destinations in display order:
1. CONTROL — authenticated vs Shadow/Backtest performance, source health and risk state
2. BRAIN — truth-constrained observer, AI review / fail closed
3. AIトレード日記 — result tracking, weekly reflection and learning; daily Journal integration remains PARTIAL
4. SCALP 5 — approved fast transitions, MS2-only live evidence
5. EVENT 5 — IR / PTS / material-first escalation, source-labeled
6. REALTIME 5 — 100-stock flow and source-validated discovery, no research-only NEXT THEME
7. PRE-NEXT — NEXT THEME / pre-move research; hypotheses NOT automatically executable
8. OVERNIGHT 5 — 15:25 next-day directional study
9. SWING 5 — multi-day strategy, trend and risk
10. VALUE 5 — longer duration, cross-reference quality / dividends / buybacks
11. FOCUS — OWNER-pinned five symbols, never auto-rotated; MS2 stale/unknown => no price
12. KIOXIA — special monitored instrument with chart and calibrated prediction history
13. 決算日程 — inserted by `earnings-calendar.js` ahead of 注意
14. 注意 — risk, events and trading-stop reason

Secondary reference menu is nine: 円高恩恵TOP5 / 対米投資・SMR / 主体レジーム / 検証・除外 / 相関 / 下ヒゲ / 拡大 / 大口 / 国策. Weekly moved into Journal, not deleted as evidence.

### Keep / merge / delete, with business rationale

| Decision | What | Rationale and audit |
|---|---|---|
| KEEP | CONTROL, BRAIN, main strategy lanes, KIOXIA, earnings | Needed for verifiable P&L separation, decision audit, horizon-specific OOS/EV and source-specific forecasting |
| KEEP / TOP-LEVEL | OWNER-fixed FOCUS, PRE-NEXT, AIトレード日記 | Early discovery, persistent human-curated watch and AI feedback loop are central to learning; incomplete parts marked research/partial |
| MERGE | Weekly review -> AIトレード日記 | Eliminates an empty redundant navigation destination while retaining all historical content and weekly source |
| MOVE | NEXT THEME RADAR -> PRE-NEXT | Research-stage themes must not sit among source-verified executable REALTIME symbols |
| DELETE DISPLAY ONLY | Static 2026-09-25 data quality PASS (56/100) | Misleading historical success; mandatory internal collector/Gateway safety gates retained |
| DELETE / REPLACE | 2026-09-25 FOCUS forecasts and stale trigger voice code (~60k chars) | Old static values falsely presented fresh; replaced with OWNER-selected ticker list and authenticated MS2 read-only cards, no speech or orders |
| REPAIR UI SINGLE LOCATION | SCALP fixed list 285A.T -> 464A.T | Matches approved successor watchlist intent; workbook/other engines are NOT modified in this Draft; no guessed quotes |

### Non-negotiable acceptance / remaining open gate

- PR #474 is stacked on #472 on #471, **Draft**; exact current HEAD, CI, negative tests and independent review must be obtained before choosing any release.
- Preexisting `index.html` git SHA and immutable V10 release manifest do not currently match after #472/#474 modifications. Do **not** disable pin checks, merge automatically, or interpret failed pin CI as a software-ready image. The pinned bundle should be updated only after review of the actual source diff and coherent signed/manifest constraints.
- FOCUS uses **existing Collector/Gateway evidence fields**, not invented quote fields: top-level `observed_at_offset`, `source`, `source_mode`, `live_price_diagnostics`, `live_values_available=true`, `stale=false`, `data_conflict=false`, `real_submit_allowed=false`, plus per-row `source_timestamp_basis=COLLECTOR_OBSERVED_CHANGE`, `source_timestamp_at`, `source_timestamp_observed_at`, `source_timestamp`. All timezone/age/identity checks must pass. An explicit `source_authenticated=false` blocks; an absent auth marker is NOT a claim of authentication. Display remains **read-only observation**, never trade-ready. Missing/old quote blocks the price. Stored owner choice contains only public ticker codes.
- No changes to approved color, font, background, telemetry infrastructure, Excel, generated Writer timing, other specialists' tasks, market source endpoints, or real-submit locks.
- Daily trade journal, objective 100億 expectation score, market-wide non-fixed100 discovery, and actual Shadow EV improvement **are not implemented by these UI changes**; these require dedicated contracts, measured evidence, future review.
- All Windows real-machine visual tests, exact Excel/PIT quote persistence, latency, independent readback, end-to-end AI learning, realized P&L remain PENDING/UNKNOWN.

**OWNER does not need to decide the tab count again.** The next true OWNER-controlled boundary is the independent-reviewed pinned UI release / Windows deployment decision. The development lead must continue non-release research, negative regression work and evidence collection autonomously.
