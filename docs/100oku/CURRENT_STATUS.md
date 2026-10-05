# CURRENT_STATUS

記録日: 2026-10-06 JST

Owner PC の初回同期は PASS した。`MASTER_SPEC_SYNC=PASS`、`DESTINATION_WRITTEN=1`、`CLOUD_AGENT_WROTE_D_DRIVE=0`、`ARCHIVE=NONE_FIRST_SYNC`、`REPO_COMMIT=116ed28014af7b627b69882b2920ca09aa34924a`。同期された MASTER は当時の 4,644 bytes である。

Owner PC はその後、commit `768d1f47553b70e85c0d04f6e4962820a2aef1ab` を `D:\100億PROJECT\MASTER_SPEC` へコピーした。`MASTER_SPEC_SYNC=PASS`、`DESTINATION_WRITTEN=1`、`CLOUD_AGENT_WROTE_D_DRIVE=0`、`ARCHIVE=2026-10-06_0227`。その時点の Markdown は 32,123 bytes、sha256 `b0d21ae173611a9a792335bca2ba5f1e3673dc97f52d78f5517c5393ebc551da`。Word は 51,104 bytes、sha256 `72e9ba6fbb9278ab30d6b2f0f797a529a6fca5ef0b38074bc1ab5ac6adcc6d29`。いま D: にある正式原本はその commit である。この段落を含む後続の repo 差分は、次に wrapper が成功するまで D: へは入らない。

16:45 は未登録である。登録するタスクは `downloads/UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1` を実行する。順序は `git fetch origin`、`cursor/master-spec-fetch-sync-d483` の最新 commit の確認、専用 worktree が dirty でないことの確認、その commit への fast-forward、成功時だけ `SYNC_100OKU_MASTER_SPEC.ps1`、sha256 の一致、`LAST_SYNC.json` への source commit と destination hash と result の保存である。remote に新しい commit が無い日は同じ commit をコピーしてよい。fetch 失敗、dirty、ローカルだけの commit、履歴の分岐、対象ファイルの欠落または空、sha256 不一致では D: を更新しない。固定 worktree を fetch なしで毎日コピーするタスクは登録しない。

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
