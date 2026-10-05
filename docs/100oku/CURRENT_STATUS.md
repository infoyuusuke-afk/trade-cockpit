# CURRENT_STATUS

記録日: 2026-10-06 JST

Owner PC の初回同期は PASS した。`MASTER_SPEC_SYNC=PASS`、`DESTINATION_WRITTEN=1`、`CLOUD_AGENT_WROTE_D_DRIVE=0`、`ARCHIVE=NONE_FIRST_SYNC`、`REPO_COMMIT=116ed28014af7b627b69882b2920ca09aa34924a`。同期された MASTER は当時の 4,644 bytes である。

この作業コピーは、その後に MASTER 本文と `100億PROJECT_MASTER_SPEC.docx` を広げた版である。Cloud Agent はこの版を D: へ書いていない。対象は `100億PROJECT_MASTER_SPEC.md`、`CURRENT_STATUS.md`、`CHANGELOG.md`、`HANDOVER.md`、および `docs/100oku` の `.docx`。16:45 のタスクは未登録である。

## Acceptance の層

- HISTORICAL BASELINE は `docs/AI_COCKPIT_MASTER_SPEC.md`（2026-09-22）だけである。G0 から G5 の表はそこに無い。
- G0 から G5 は Current Acceptance（2026-10-03、`docs/P0_ACCEPTANCE_MATRIX.md`）である。G0 は FAIL、G1 は NOT_RUN、G2 は NOT_RUN、G3 は PARTIAL、G4 は NOT_RUN、G5 は NOT_RUN。HISTORICAL BASELINE ではない。
- Collector の銘柄対応 PASS と Supervisor の台帳再読込 PASS は、その後の別観測である。G0 から G5 を置き換えない。

## Research Data Lane

- FETCHED **3/17**
- `short_sale_ratio`: `9180eb9ec` で初の FETCHED。JPX空売り売買代金の市場合計。日次。`source_stage=OFFICIAL_PUBLIC`。`trading_adoption=false`。LIVE signal には接続していない。
- `investor_futures_flow`: 2本目の FETCHED。JPX投資部門別の先物週次CSV。海外投資家の日経225先物・mini・マイクロ売買代金差引。`trading_adoption=false`。LIVE signal には接続していない。
- `arbitrage_balance`: 3本目の FETCHED。JPX裁定取引の日次市場合計。2026-10-01 の買いポジション合計は 849,191 千株。営業日差 3 で `STALE` のため研究値は null。参加者名と原票は保存していない。`trading_adoption=false`。LIVE signal には接続していない。銘柄候補にはしていない。
- 残り14件は `NOT_FETCHED`。
- 本番 Brain candidate は 0。linked は 0。Shadow Entry は 0。`UNIVERSE_SCOPE=LIMITED / PRECISION_WATCH_ONLY`。
- Correlation / Lead-Lag は `DESIGN_ONLY`。測定ペアは 0。係数は保存していない。
- `BASELINE_N=0`。`FEATURE_DELTA_EV=NOT_AVAILABLE`。`PROMOTION_CANDIDATE=NONE`。
- `real_submit_allowed=false`。

## 時刻と freshness

- `session_date` は対象セッションまたは週の最終日。
- `first_seen_at` はファイルを最初に観測した時刻。`available_at` はこれと同じ。
- `published_at` は HTTP `Last-Modified` がセッション日以降かつ初回観測以前のときだけ入る。無い場合は null。15:30 の掲載規則で過去時刻を埋めない。
- freshness は4暦日固定ではない。JPX休業日表の営業日差を使う。日次は直前営業日までを `FRESH` とする。週次は次週の第4営業日の前日までを `FRESH` とする。休業日表に無い年は `CALENDAR_MISSING` で研究値を出さない。
