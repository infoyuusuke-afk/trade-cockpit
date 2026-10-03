# P0 Acceptance Matrix（G0–G6）

観測日: 2026-10-03。ライブ PASS は Owner PC の実観測だけが満たす。`scripts/p0_market_io_acceptance.py` の合成 fixture は照合器のテストであり、G0–G5 の PASS ではない。

| ID | Input | Expected | PASS | FAIL | Evidence | Automated / Owner PC | Dependency | Current Status |
|---|---|---|---|---|---|---|---|---|
| G0 | RSS 専用ブック `Kioxia_MS2_RSS_Live_Signals.xlsx` を単独起動 | Excel がブックを開き、重大エラーの確認で止まらない | プロセスが起動し、ブックが操作可能で、確認ダイアログが無い | ダイアログ残留、identity 失敗、ROT 未登録のまま停止 | 起動記録と、ダイアログが無いことの観測。PID 43904 の既存ダイアログは証拠であり、解消済みではない | Owner PC | なし | FAIL。2026-10-03 02:22:51 の起動は確認画面で停止。OWNER ACTION PENDING |
| G1 | 開いた専用ブックの RSS セル | 立会中の実市場値が更新される | セルの値と時刻が、停止した JSON の再利用ではなく更新される | 空、固定、前日値、sample | RSS 行の symbol / price / source_timestamp。repo には置かない | Owner PC | G0 | NOT_RUN。OWNER ACTION PENDING |
| G2 | Collector の `live_ms2.json` | RSS と同じ symbol / price / source_timestamp を fresh に書く | 契約の envelope が verified で、RSS と一致し、captured_at から 60 秒以内 | 欠測、stale、カバレッジ不足、別ブック、別シンボル | Collector payload。公開 repo に生値を置かない | harness は到着後に照合。取得は Owner PC | G1 | NOT_RUN。コードの器は KEEP |
| G3 | Gateway が読む同じ payload | fresh なら通し、stale / mismatch / missing / unverified は拒否する | 拒否時は 503 と `real_submit_allowed=false`。通過時は RSS と同一 quote | 古い JSON を OK として配信、mismatch を通過 | Gateway 応答。拒否の単体契約は既存 Gateway。正例の一致は harness | 拒否は repo で準備済み。正例は Owner PC の実系列 | G2 | 拒否ロジックは KEEP。ライブ正例は NOT_RUN |
| G4 | MS2 表示、RSS、Collector、Gateway、Strategy Input | 同一 symbol の price と source_timestamp が一致 | 5 境界の fingerprint が一致。strategy_input は明示の境界。MS2 表示が欠けると不合格 | どれか一つでも違う、欠ける、未検証 | harness の report。合成 fixture は `NOT_LIVE` | harness は repo。実束は Owner PC | G1–G3 と MS2 表示の観測 | NOT_RUN。MS2 表示の取り込みは MISSING |
| G5 | 直前が FAIL のあとの次スナップショット | 一致確認の印が付くまで再開しない | `agreement_checked=true` の観測束だけが再開可 | 印なしの自動再開 | `evaluate_resume`。合成は `NOT_LIVE` | harness は repo。実再開は Owner PC の系列 | G4 の FAIL 経験 | コード準備済み。ライブは NOT_RUN |
| G6 | この経路の全出力 | `real_submit_allowed=false`。注文関数を呼ばない | 全 envelope と診断が false。RssOrder なし | true、欠落、注文経路 | 既存 Controller / Gateway / Collector / harness | repo で確認済み。ライブ再確認は実系列到着時 | なし | PASS（リポジトリ契約）。ライブ再確認は NOT_RUN |

G0 と G1 は harness が PASS にできない。`OWNER_ACTION_PENDING` のままにする。
