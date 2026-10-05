# 100億PROJECT MASTER SPEC

このファイルはリポジトリ上の Data Source Registry である。`D:\100億PROJECT\MASTER_SPEC` へは未反映。この環境からそのパスへは書き込めない。

## 正式保存

AI 作業コピーは repo の `docs/100oku/`。正式原本は `D:\100億PROJECT\MASTER_SPEC`。Cloud Agent は D: へ書けない。Owner PC の `downloads/SYNC_100OKU_MASTER_SPEC.ps1` だけがコピーする。上書き前は `archive\YYYY-MM-DD_HHMM\`。hash 不一致、欠落、空ファイルは FAIL CLOSED。`LAST_SYNC.json` は `cloud_agent_wrote_destination=false`。この記録時点では D: へ未反映。16:45 JST のタスクは `downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1` に用意し、`-Register` 無しでは登録しない。対象は本書、`CURRENT_STATUS.md`、`CHANGELOG.md`、`HANDOVER.md`。Word 版が `docs/100oku` にあれば `.docx` も対象。

## Data Source Registry / Research Data Lane

Research Data Lane は公式公開データを研究参照として保持する。`source_stage=OFFICIAL_PUBLIC` は LIVE でも SYNTHETIC/REPLAY でもない。`trading_adoption=false` を維持し、LIVE signal と `real_submit_allowed` は変えない。`published_at` が検証できない行は null のままにする。

freshness は JPX の休業日表（https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html）にある営業日で判定する。表に無い年は研究値を出さない。4暦日を唯一の条件にはしない。

| id | 状態 | 更新 | 出どころ |
|---|---|---|---|
| short_sale_ratio | FETCHED | 日次。セッション後 | OFFICIAL_PUBLIC。JPX空売り売買代金合計 |
| investor_futures_flow | FETCHED | 週次。第4営業日の掲載規則 | OFFICIAL_PUBLIC。JPX先物の投資部門別 |
| nt_ratio | NOT_FETCHED | 未接続 | 日経平均の再配布条件が未確認 |
| futures_options_positioning | NOT_FETCHED | 未接続 | IV/PCR は未契約 |
| arbitrage_balance | NOT_FETCHED | 未切り出し | 参加者別PDFは保存しない |
| credit_evaluation_loss | NOT_FETCHED | 未確認 | 単一系列が未確認 |
| crude | NOT_FETCHED | 未契約 | |
| gold | NOT_FETCHED | 未契約 | |
| silver | NOT_FETCHED | 未接続 | |
| copper | NOT_FETCHED | 未接続 | |
| korea_equity | NOT_FETCHED | 未契約 | |
| macro_release | NOT_FETCHED | 予定時刻のみ | |
| official_speech | NOT_FETCHED | 未確認 | |
| earnings_schedule | NOT_FETCHED | 日程のみ | |
| catalyst | NOT_FETCHED | 本文はコピーしない | |
| midterm_plan | NOT_FETCHED | 本文はコピーしない | |
| shikiho_fundamentals | NOT_FETCHED | 転載しない | |

### short_sale_ratio

- 初回 FETCHED: `9180eb9ec`
- データ: JPX立会市場の空売り売買代金合計。2026-10-05 の合計は 8,721,605 百万円、空売り比率 0.388924。
- 取得元: https://www.jpx.co.jp/markets/statistics-equities/short-selling/ の市場合計 `-m.pdf`
- 更新: 日次。セッション後の公表。場中判断には使わない。
- `session_date=2026-10-05`
- `first_seen_at=2026-10-06T01:13:15.683407+09:00`
- `published_at=2026-10-05T16:30:28+09:00`（HTTP Last-Modified。根拠が無い時刻は入れない）
- `source_stage=OFFICIAL_PUBLIC`
- `trading_adoption=false`
- LIVE signal 非接続
- 日次 freshness: 観測日までの JPX 営業日差が 1 以内なら `FRESH`。2026-05-01 の値を 2026-05-07 に見ても営業日差は 1 なので `FRESH`。営業日差が 2 以上、または未来セッションは `STALE`。

### investor_futures_flow

- データ: 海外投資家の日経225先物、mini、マイクロの売買代金差引。2026-09-24〜2026-09-25 は 186,407,123,040 円。
- 取得元: https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html の `Tousi_DV_W_*.csv`
- コード対応は 2026-09-24 週の公式PDFの金額と照合した。照合できない週の `published_at` は埋めない。2026-04-17 週は `published_at=null`。
- 更新: 週次。掲載規則は第4営業日の午後3時30分。この規則は `published_at` ではない。
- `session_date=2026-09-25`
- `first_seen_at` は初回観測時刻。`available_at` は同じ。
- `published_at=2026-10-01T15:30:29+09:00`（HTTP Last-Modified）
- `source_stage=OFFICIAL_PUBLIC`
- `trading_adoption=false`
- LIVE signal 非接続
- 週次 freshness: 次の報告週の第4営業日が来る前は `FRESH`。2026-09-25 週は 2026-10-08 が次の掲載予定日なので、2026-10-06 の観測では暦日差 11 でも `FRESH`。掲載予定日以降に古い週だけを持つ場合は `STALE`。
