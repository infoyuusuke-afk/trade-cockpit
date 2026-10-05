# CHANGELOG

`D:\100億PROJECT\MASTER_SPEC` の正式原本は commit `768d1f47553b70e85c0d04f6e4962820a2aef1ab` の同期結果である。このファイルの後続の行は、その後の repo 差分であり、次に wrapper が成功するまで D: には入らない。Cloud Agent は D: へ書いていない。

## 2026-10-06

- `9180eb9ec`: Research Data Lane の `short_sale_ratio` を初の `FETCHED` にした。JPX空売り売買代金合計を raw / history / latest に保存し、Research Layer から参照する。`trading_adoption=false`。LIVE signal は変えていない。
- freshness を「4暦日以内」だけに依存させず、JPX休業日表の営業日差を併用した。長期休業をまたぐ最新公表が、暦日数だけで `STALE` にならない。
- 時刻を `session_date` / `first_seen_at` / `published_at` に分けた。`published_at` は検証できた HTTP `Last-Modified` だけを入れる。空売り比率の 2026-10-05 は `published_at=2026-10-05T16:30:28+09:00`、`first_seen_at=2026-10-06T01:13:15.683407+09:00`。
- `investor_futures_flow` を2本目の `FETCHED` にした。2026-09-24〜09-25 の海外投資家・日経225先物売買代金差引は 186,407,123,040 円。`published_at=2026-10-01T15:30:29+09:00`。Research Data Lane は FETCHED 2/17。
- Owner PC 同期ブリッジを追加した。`downloads/SYNC_100OKU_MASTER_SPEC.ps1` が `docs/100oku/` を `D:\100億PROJECT\MASTER_SPEC` へコピーし、上書き前を `archive\YYYY-MM-DD_HHMM\` に退避する。sha256 の不一致、欠落、空ファイルは FAIL CLOSED。`LAST_SYNC.json` の `cloud_agent_wrote_destination` は false。`downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1` は毎日 16:45 を表示し、`-Register` が無いときは登録しない。Cloud 上の dry-run は D: へ書いていない。
- Owner PC の初回同期は PASS。`MASTER_SPEC_SYNC=PASS`、`DESTINATION_WRITTEN=1`、`CLOUD_AGENT_WROTE_D_DRIVE=0`、`ARCHIVE=NONE_FIRST_SYNC`。対象 commit は `116ed28014af7b627b69882b2920ca09aa34924a`。当時の MASTER は 4,644 bytes で、Word は無かった。
- MASTER 本文を、目的、正本、アーキテクチャ、Acceptance、ユニバース、候補、相関、Brain、Baseline / Research / Meta Brain / Shadow、データ台帳、freshness、データ源の役割、日記、収益、進化、停滞防止、省略監査、役割、16:30 棚卸し、変更管理、引継ぎ、安全まで広げた。同じ意味の `100億PROJECT_MASTER_SPEC.docx` を追加した。未検証の EV は入れていない。週間 15 件は SNAPSHOT のままである。16:45 は未登録。この版の D: コピーは未実施。
- `arbitrage_balance` を3本目の `FETCHED` にした。2026-10-01 の市場合計は売り 64,563 千株、買い 8,980 千株、買いポジション 849,191 千株。`published_at=2026-10-05T16:00:31+09:00`。営業日差 3 で研究値は null。参加者名と原票は保存していない。Research Data Lane は FETCHED 3/17。
- 本番 Research Candidate の保存先を追加した。銘柄行が無いので candidate は 0。`UNIVERSE_SCOPE=LIMITED / PRECISION_WATCH_ONLY`。fixture は本番統計に入れない。Shadow の Entry 条件は変えていない。linked は 0。Shadow Entry は 0。
- Correlation / Lead-Lag は設計のまま。測定ペアは 0。係数は保存していない。
- G0 から G5 を Current Acceptance（2026-10-03）と明記した。HISTORICAL BASELINE は 2026-09-22 の `docs/AI_COCKPIT_MASTER_SPEC.md` だけである。その後の Collector 銘柄対応 PASS と Supervisor 再読込 PASS は、G0 から G5 とは別行のままである。
- Owner PC は広げた MASTER を commit `768d1f47553b70e85c0d04f6e4962820a2aef1ab` で同期した。`MASTER_SPEC_SYNC=PASS`、`ARCHIVE=2026-10-06_0227`。Markdown は 32,123 bytes、sha256 `b0d21ae173611a9a792335bca2ba5f1e3673dc97f52d78f5517c5393ebc551da`。Word は 51,104 bytes、sha256 `72e9ba6fbb9278ab30d6b2f0f797a529a6fca5ef0b38074bc1ab5ac6adcc6d29`。
- 16:45 用に `downloads/UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1` を追加した。`git fetch` のあと、clean な専用 worktree だけを `cursor/master-spec-fetch-sync-d483` の最新 commit へ fast-forward し、その後に同期する。remote が同じ commit の日は再同期してよい。fetch 失敗、dirty、ローカルだけの commit、履歴の分岐、欠落、空、sha256 不一致では D: を更新しない。タスク自体は未登録である。
