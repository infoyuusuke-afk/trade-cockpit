# P0 Data Contract

境界は `MS2表示 → RSS → Collector → Gateway → Strategy Input`。下流は上流の quote を作り直さない。一致しないときは Strategy Input を作らない。

## Quote

各境界が持つの必須項目。

| 項目 | 契約 |
|---|---|
| symbol | 文字列。東証は `285A.T` の形。JNX は別 symbol で、東証の価格へ混ぜない |
| price | 有限の正の数。bool は不可。境界間は完全一致。丸めて合わせない |
| source_timestamp | RSS 現状は `HH:mm:ss`。絶対時刻ではない。harness は証拠の `captured_at` の日付にだけ結合する。別の日の時刻を今日へ修復しない。解析できない時刻は未検証 |
| source | `MarketSpeed II RSS / local PC` |
| freshness | `captured_at` と評価時刻の差、および quote 時刻と `captured_at` の差が、どちらも 60 秒以内。評価器の「今日」で古いファイルを fresh にしない |
| verified | `live_values_available=true`、`price_source_status=OK`、`stale=false`、`data_conflict=false`、`source_mode=MS2_RSS_WORKBOOK`、行の `data=LIVE` |
| mismatch | `data_conflict=true`、ブック名不一致、symbol 不一致、境界間の price または source_timestamp 不一致 |
| sequence / fingerprint | 単調な配信番号は未実装。当面は symbol / price / source_timestamp / source の SHA-256。境界の fingerprint が違うときは不一致 |
| real_submit_allowed | すべての境界で false |

Collector と Gateway の envelope は、既存の `live_ms2.json`（`schema_version=ms2-common-1.0`）を正とする。診断の `workbook_name` は `Kioxia_MS2_RSS_Live_Signals.xlsx`。

## 境界

| 境界 | 現状の置き場 | 契約上の役割 |
|---|---|---|
| MS2 表示 | 未実装。画面値を repo に写さない | G4 の外部観測。無いときは G4 は不合格 |
| RSS | 専用ブックのセル。Collector が読む | 実市場値の入口 |
| Collector | `ms2_live/MS2_RSS_100_Collector.ps1` の `all_targets[]` と envelope | RSS の写し。価格を別ソースで埋めない |
| Gateway | `downloads/AI_COCKPIT_GATEWAY_V9.ps1` | 同じ payload を配信するか、503 で拒否する。値を修復しない |
| Strategy Input | harness の明示 `strategy_input.quotes` | Collector からの射影だけを許す。射影が無い束は不合格。signal は verified のあとだけ |

`scripts/local_market_data_gateway.py` は C-115 の研究用正規化であり、この V9 Gateway ではない。P0 の正本にしない。

## 合成データ

`synthetic_bundle()` は symbol `TEST` と価格 `100` を作る。`generated_by` が付く。origin を `owner_pc_observed` に書き換えても `NOT_LIVE` のままである。この fixture で G0–G5 を PASS にしない。
