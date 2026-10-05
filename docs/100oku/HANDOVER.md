# HANDOVER

記録日: 2026-10-06 JST

## 正本の置き場所

- AI作業コピーは repo の `docs/100oku/`。
- 正式原本フォルダは `D:\100億PROJECT\MASTER_SPEC`。
- Cloud Agent から D: へは書けない。repo を更新しただけでは正式原本は変わらない。
- Owner PC の `downloads/SYNC_100OKU_MASTER_SPEC.ps1` だけが D: へコピーする。
- 同期前のファイルは `D:\100億PROJECT\MASTER_SPEC\archive\YYYY-MM-DD_HHMM\` に退避する。
- 結果は `LAST_SYNC.json`。`cloud_agent_wrote_destination` は false のまま。

## Acceptance の層

- HISTORICAL BASELINE は 2026-09-22 の `docs/AI_COCKPIT_MASTER_SPEC.md`。
- G0 から G5 は 2026-10-03 の Current Acceptance。G0 は FAIL。G3 は PARTIAL。残りは NOT_RUN。
- Collector 銘柄対応 PASS と Supervisor 再読込 PASS は、G0 から G5 を置き換えない。

## いまの Research Data Lane

- FETCHED 3/17。`short_sale_ratio`、`investor_futures_flow`、`arbitrage_balance`。裁定残の原票と参加者名は保存していない。
- 本番 Brain candidate は 0。linked は 0。Shadow Entry は 0。探索範囲は `LIMITED / PRECISION_WATCH_ONLY`。
- Lead-Lag は `DESIGN_ONLY`。測定ペアは 0。
- `trading_adoption=false`。LIVE signal は変えていない。`real_submit_allowed=false`。
- `BASELINE_N=0`。`FEATURE_DELTA_EV=NOT_AVAILABLE`。`PROMOTION_CANDIDATE=NONE`。
- 詳細は `CURRENT_STATUS.md` と `100億PROJECT_MASTER_SPEC.md`。

## 同期

初回の同期は Owner PC で PASS した。`ARCHIVE=NONE_FIRST_SYNC`。そのコピーは 4,644 bytes の前版で、Word は含まれていない。広げた MASTER は commit `768d1f47553b70e85c0d04f6e4962820a2aef1ab` で再同期され、`ARCHIVE=2026-10-06_0227` である。いま D: にある正式原本はその commit である。

毎日 16:45 JST のタスクは `downloads/UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1` を実行する。先に `git fetch origin` し、`cursor/master-spec-fetch-sync-d483` の最新 commit を見る。専用 worktree が dirty でなく、その commit が今の HEAD と同じか、その子孫であるときだけ worktree を進める。その後に `SYNC_100OKU_MASTER_SPEC.ps1` を実行し、sha256 が一致したとき `LAST_SYNC.json` に source commit、destination hash、result を残す。remote に新しい commit が無い日は同じ commit を同期してよい。fetch 失敗、dirty、ローカルだけの commit、履歴の分岐、対象ファイルの欠落または空、sha256 不一致では D: を更新しない。後続の MASTER 更新は、この remote branch を fast-forward する。別 branch の先端だけでは 16:45 は拾わない。

登録スクリプトは `downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1`。`-Register` を付けない限り登録しない。16:45 は未登録である。固定 worktree を fetch なしでコピーするタスクは登録しない。
