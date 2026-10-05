# 100億PROJECT MASTER SPEC

記録日: 2026-10-06 JST

この版は、repo の `docs/100oku/` にある AI 作業コピーである。正式原本フォルダは `D:\100億PROJECT\MASTER_SPEC`。Cloud Agent から D: へは書けない。Owner PC の `downloads/SYNC_100OKU_MASTER_SPEC.ps1` だけがコピーする。

Owner PC の初回同期は PASS した。確認行は `MASTER_SPEC_SYNC=PASS`、`DESTINATION_WRITTEN=1`、`CLOUD_AGENT_WROTE_D_DRIVE=0`、`ARCHIVE=NONE_FIRST_SYNC`、`REPO_COMMIT=116ed28014af7b627b69882b2920ca09aa34924a`。そのとき同期された `100億PROJECT_MASTER_SPEC.md` は 4,644 bytes で、Research Data Lane の短い台帳だった。Word 版はその同期に含まれていない。

Owner PC はその後、commit `768d1f47553b70e85c0d04f6e4962820a2aef1ab` を `D:\100億PROJECT\MASTER_SPEC` へコピーした。`MASTER_SPEC_SYNC=PASS`、`DESTINATION_WRITTEN=1`、`CLOUD_AGENT_WROTE_D_DRIVE=0`、`ARCHIVE=2026-10-06_0227`。その時点の Markdown は 32,123 bytes、sha256 `b0d21ae173611a9a792335bca2ba5f1e3673dc97f52d78f5517c5393ebc551da`。Word は 51,104 bytes、sha256 `72e9ba6fbb9278ab30d6b2f0f797a529a6fca5ef0b38074bc1ab5ac6adcc6d29`。いま D: にある正式原本はその commit である。この段落を含む後続の repo 差分は、次に wrapper が成功するまで D: へは入らない。毎日 16:45 JST のタスクは未登録である。

未検証の期待値、勝率、収益は書かない。`SNAPSHOT` の週間数字を LIVE 成績にも Research 成績にも使わない。

## PROJECT PURPOSE / 100億円最上位目的

100億円を稼ぐシステムを AI と作る。手段は固定しない。期待値の高い手段を、探索し、検証し、実行し、改善し、再投資する。

AI Cockpit は現在の最重要 Trading Engine であり、100億PROJECT そのものではない。より期待値の高い手段が確認されたら採用候補にする。確認前の手段は候補のままである。

優先順位は、存続、資本保全、同じ入力に対する決定性、再現、監査、stale / 欠測 / 破損の検出、fail-closed、安全停止、統計として使える証拠、その後の期待値である。この順は `docs/AI_COCKPIT_MASTER_SPEC.md`（2026-09-22、checkpoint `1e856eeacdf71006fa095da27e1aa6e46862fb7b`）と同じである。

Owner の時間は有限であり、開発コストである。Owner がいないと作業が止まる構造は改善対象である。実注文の許可は、この目的から自動では出ない。

## Single Source of Truth

正本は層で分かれる。層を混ぜて「完成」と言わない。

| 層 | 役割 | この版での位置 |
|---|---|---|
| GitHub のコード | 実装の正本。チャット要約は完成ではない | 実装とテストが先 |
| `docs/100oku/` | MASTER の AI 作業コピー | このファイル |
| `D:\100億PROJECT\MASTER_SPEC` | Owner PC の正式原本 | 初回同期 PASS は前版。この版は未コピー |
| `C:\AI_Cockpit_OneClick_Starter` | 稼働ランタイム。`V9_RUNTIME.json` がある | 開発正本ではない |
| `C:\Users\yusuk\code\trade-cockpit` | Owner の repo。`C:\work\trade-cockpit` は使わない | 作業ツリー |
| `docs/AI_COCKPIT_MASTER_SPEC.md` | HISTORICAL BASELINE。2026-09-22 の Cockpit Baseline。G0 から G5 の表はここに無い | この MASTER は置き換えない |
| `docs/AI_COCKPIT_MASTER_SPEC_VNEXT.md` | 2026-10-03 の草案 | Baseline を置き換えない |

コード、テスト、実機の観測が文章と食い違うときは、検証済みの実装と証拠を採る。新しい承認済みの Issue コメントが文章と食い違うときは、そのコメントを採る。チャットの「できた」は証拠にしない。

repo 内に、日付が 2026-09-21 の MASTER ファイルは無い。2026-09-18 の `docs/MS2_STABILITY_REVIEW_2026-09-18.md` が次の立会（文書は 2026-09-21 を想定）の確認を書いている。その実機確認は未達のまま残す。日付を書き換えて遅延を消さない。

## Current Architecture

LIVE の価格経路は次である。

```text
MarketSpeed II
  -> RSS 専用 Excel（Kioxia_MS2_RSS_Live_Signals.xlsx）
  -> Collector 127.0.0.1:28580
  -> Gateway 127.0.0.1:28581
  -> Strategy Input
  -> 固定 Strategy
  -> AI SHADOW（仮想）
```

一般 Excel と RSS 専用 Excel のザラ場中の共存は、必須要件から外してある。無関係な Excel を止める実装にはしない。ダイアログを自動で押さない。

判断の主体はまだ固定 Strategy である。Meta Brain は LIVE Entry を独立に決めていない。Control の `AI BRAIN LIVE` は研究候補、`AI SHADOW LIVE` は固定 Strategy の仮想売買である。Brain の表示は `RESEARCH ONLY / NOT EXECUTION AUTHORITY` とする。`BRAIN ENTRY` とは表示しない。

固定 Strategy のエントリー信号は次だけである。

- LONG: 初動買い候補、買いサイン、持ち越しロング確定
- SHORT: 初動ショート候補、空売りサイン、持ち越しショート確定

この集合を緩めて LIVE の往復を PASS にしない。合成データと replay を LIVE PASS にも LIVE の標本 N にも入れない。

公開してよい銘柄名は、公開識別子 `285A.T` に限る。個人の保有、認証情報、非公開の監視銘柄リストは、この公開 repo に置かない。

## Current Acceptance / PASS / PARTIAL / BLOCKED / NOT_RUN

ライブの PASS は Owner PC の観測だけが満たす。合成 fixture は照合器のテストであり、G0 から G5 の PASS ではない。

G0 から G5 の行は、2026-10-03 に観測した Current Acceptance である。出典は `docs/P0_ACCEPTANCE_MATRIX.md`。これは HISTORICAL BASELINE ではない。G1 から G5 を一括の NOT_RUN とは書かない。G3 は PARTIAL である。

HISTORICAL BASELINE は `docs/AI_COCKPIT_MASTER_SPEC.md`（2026-09-22、checkpoint `1e856eeacdf71006fa095da27e1aa6e46862fb7b`）だけを指す。その文書は、この G0 から G5 の表を持たない。

その後に Owner PC で確認した Collector の銘柄対応 PASS と、Supervisor の台帳再読込 PASS は、下の別行である。G0 から G5 の状態を置き換えない。MS2、RSS、Collector、Gateway、Strategy、AI SHADOW の経路確認を、この G0 の FAIL と同じ項目として読まない。

| 項目 | 状態 | 根拠 |
|---|---|---|
| G0 専用 Excel の単独起動 | FAIL | Current Acceptance（2026-10-03）。HISTORICAL BASELINE ではない。起動は確認画面で停止。`docs/P0_ACCEPTANCE_MATRIX.md`。OWNER ACTION PENDING |
| G1 RSS セルの更新 | NOT_RUN | Current Acceptance（2026-10-03）。HISTORICAL BASELINE ではない。OWNER ACTION PENDING |
| G2 Collector の fresh 一致 | NOT_RUN | Current Acceptance（2026-10-03）。HISTORICAL BASELINE ではない。器は KEEP。ライブ系列は未実施 |
| G3 Gateway の拒否 | PARTIAL | Current Acceptance（2026-10-03）。HISTORICAL BASELINE ではない。拒否契約は KEEP。ライブの正例は NOT_RUN |
| G4 五境界の一致 | NOT_RUN | Current Acceptance（2026-10-03）。HISTORICAL BASELINE ではない。MS2 表示の取り込みは MISSING |
| G5 一致印までの再開停止 | NOT_RUN | Current Acceptance（2026-10-03）。HISTORICAL BASELINE ではない。コード準備済み。ライブは未実施 |
| G6 `real_submit_allowed=false` | PASS | リポジトリ契約。ライブ再確認は NOT_RUN |
| Collector の銘柄対応 | PASS | Owner PC。`RUNTIME_ACCEPTANCE=PASS`。`SYMBOL=285A.T`。その実行の `CURRENT_PRICE=19120`。この 19,120 円は当時の観測であり、常時の現在値ではない |
| Supervisor の台帳再読込 | PASS | Owner PC。`SUPERVISOR_RELOAD_ACCEPTANCE=PASS`。worktree `4abf0a1a`。`REAL_SUBMIT 0`。`LIVE_SIGNAL_RULE_CHANGE=0`。Collector、Gateway、Excel、MS2 は対象外 |
| MASTER 初回同期 | PASS | 上記のトークン。対象は当時の 4,644 bytes。この版ではない |
| MASTER 本文の同期 | PASS | commit `768d1f47553b70e85c0d04f6e4962820a2aef1ab`。`ARCHIVE=2026-10-06_0227`。この表を含む後続差分は未同期 |
| Research Data Lane | PARTIAL | FETCHED 3/17。`trading_adoption=false` |
| Control の Brain / Shadow 表示 | PASS | 二段表示の配線。本番候補は 0。選出・Entry・Exit の精度は NOT_RUN |
| LIVE の往復 | NOT_RUN | 市場時間外や条件未達を、注入で PASS にしない |
| クリーンな Shadow 標本 | NOT_RUN | `BASELINE_N=0`。`FEATURE_DELTA_EV=NOT_AVAILABLE`。`PROMOTION_CANDIDATE=NONE` |
| ブローカー建玉 | BLOCKED | `BROKER_POSITION_RSS_UNIMPLEMENTED`。LIVE 注文では解除しない |
| 手数料 | BLOCKED | `FEE_UNKNOWN`。確認済み料金表が無い。Research の clean N には入れない |
| 16:45 の自動同期 | NOT_RUN | wrapper はある。`-Register` は実行していない。fetch なしの固定 worktree コピーは登録しない |
| 週間 15 件 | SNAPSHOT | 下に分離して書く。Research N ではない |

週間保存 `weekly_review.json` は `created_at=2026-09-19 20:17 JST`、週 `2026-09-14～2026-09-20`、15 件、勝率 93.3%、PF 14.32、損益 +109,200 円である。これは SNAPSHOT である。AI Brain の LIVE SHADOW 成績ではなく、`BASELINE_N` にも promotion にも入れない。各行の fees 0 は料金表が無いときの仮置きであり、確認済みの手数料ではない。

## Market Universe / Dynamic Screening

画面には Control、SCALP 5、EVENT 5、REALTIME 5、OVERNIGHT 5、SWING 5、VALUE 5、KIOXIA、週間、相関などの枠がある。枠の名前は、動的スクリーニングが本番で銘柄集合を確定したという意味ではない。

fresh な行が無い枠は `NOT AVAILABLE` または「—」とする。SNAPSHOT、SYNTHETIC/REPLAY、LIVE を同じ成績に混ぜない。出来高急増、夜間 PTS、前日のストップ高安、当日ピックアップは、fresh な LIVE 行が無いとき点灯しない。

動的ユニバースの採用判定は NOT_RUN である。銘柄集合を広げる実装は、この MASTER の文章だけでは始まらない。

現在の Brain 探索範囲は全市場ではない。Control は `UNIVERSE_SCOPE=LIMITED / PRECISION_WATCH_ONLY` と出す。市場合計の統計から、市場全体で選んだ銘柄とは書かない。

## Candidate Generators

候補は二つを混ぜない。

1. 固定 Strategy の `entry_candidate`。上の LONG / SHORT 信号と、価格と、損切りの形が揃った行だけを仮想 Entry の候補にする。これは Brain の選出ではない。
2. AI Brain の研究候補。実データの銘柄行ができたときだけ `candidate_id` を作る。保存する項目は `candidate_id`、銘柄、`LONG` / `SHORT` / `WATCH` / `NO-TRADE`、`candidate_created_at`、`entry_candidate_at`、`source_generator`、`trigger`、`main_reasons`、`market_regime`、`available_at`、`data_quality`、`universe_scope`、`research_status` である。`execution_authority=true` の行は表示しない。価格は `price_fresh=true` のときだけ現在値にする。

本番ファイル `data/research_candidates/candidates.jsonl` の候補は 0 件である。理由は `NO_SYMBOL_LEVEL_OBSERVATION`。空売り比率、先物投資部門、裁定残の市場合計は銘柄候補にしない。fixture は本番統計に入れない。選出銘柄、方向、時刻、trigger、現在値は `NOT AVAILABLE` のままである。方向を `NO-TRADE` と補完しない。`NO-TRADE` は、記録された候補がそう言ったときだけ使う。

`candidate_id` が行に既にあるときだけ、仮想 Entry の記録へ写す。Shadow の Entry 条件は固定 Strategy のままである。Brain 候補に合わせて緩めない。無いときに ID を作らない。

## Correlation / Lead-Lag Research Engine

相関と lead-lag の設計は `scripts/lead_lag_research.py` にある。状態は `DESIGN_ONLY`。測定ペアは 0。相関係数は保存していない。Control の相関と lead-lag の値は `NOT AVAILABLE`、engine 表示は `DESIGN_ONLY / NOT MEASURED` である。

測定できるのは、両方の系列が同じ `session_date` を持ち、各点に `available_at` があり、きれいな観測が 30 以上重なるときだけである。その条件が揃っても、この版は係数を計算しない。市場合計は銘柄の先導にしない。fixture は入れない。

Research Data Lane の 17 系列は、相関エンジンの出力ではない。取得済みの 3 系列も `trading_adoption=false` であり、先導銘柄の判定には使っていない。

lead-lag の採用、しきい値、的中率は未検証なので書かない。将来の評価は、同じ `candidate_id` で結ばれた「銘柄選出」「Entry の時刻」「Exit」を分ける。標本が 0 のあいだ、三つの精度は `INSUFFICIENT SAMPLE` である。

## AI BRAIN PICKS

AI BRAIN PICKS は、LIVE の約定リストではない。Control 上部の `AI BRAIN LIVE` が研究候補を出す場所である。

現在の表示契約は次である。

- 権限: `RESEARCH ONLY / NOT EXECUTION AUTHORITY`
- バッジ: `RESEARCH / CANDIDATE`
- 検証済みの EV / PF / N が無いとき: `INSUFFICIENT SAMPLE`
- データが無い項目: `NOT AVAILABLE`
- Research status: `FETCHED 3/17 / trading_adoption=false`
- Universe scope: `LIMITED / PRECISION_WATCH_ONLY`
- 本番候補 0、linked 0、Shadow Entry 0

ピックの本数、推奨銘柄、確信度は、本番候補が 0 なので出さない。N=0 のとき、確率、EV、確信度を生成しない。

## BASELINE / Research Layer / Meta Brain / AI SHADOW

BASELINE は固定 Strategy である。AI SHADOW はその仮想の Entry、保有、Exit を記録する。約定は Collector の気配によるシミュレーションであり、`RssOrder` は未実装である。`order_status` は未送信、`quantity` は null、`real_submit_allowed` は false である。

Research Layer は、クリーンな live shadow の標本で特徴量の差を見る。手数料が `FEE_UNKNOWN` の行は clean N に入らない。SYNTHETIC/REPLAY は配管の確認であり、live 標本にも promotion にも入らない。現在は `BASELINE_N=0`、`FEATURE_DELTA_EV=NOT_AVAILABLE`、`PROMOTION_CANDIDATE=NONE` である。

Meta Brain は、独立して LIVE Entry を決める段階ではない。Brain が決めていない行を `BRAIN ENTRY` と呼ばない。

`AI SHADOW LIVE` の状態は `WAITING`、`ENTRY`、`IN POSITION`、`EXIT` だけである。表示は仮想 fill、時刻、LONG / SHORT、Strategy、仮想 P&L、`SHADOW / NO REAL ORDER` である。合成の `acceptance_class=synthetic` と `source_stage=SYNTHETIC/REPLAY` と stale は、この live カードに出さない。手数料が未知でも、LIVE_SHADOW で data_quality が OK の仮想 Exit はカードに出せる。その損益は 1 株あたりの差引前であり、ネットの円にしない。

タイムラインは、Brain 発見、Entry 候補、Shadow Entry、Shadow Exit、結果である。`candidate_id` が一致するときだけ一本にする。一致しないときは `UNLINKED` とし、別カードの時刻を一つの取引に見せない。

## Research Data Registry

Registry は 17 件である。FETCHED は 3 件。残り 14 件は NOT_FETCHED。取得済みでも売買条件には入れない。

| id | 状態 | 更新 | 出どころ |
|---|---|---|---|
| short_sale_ratio | FETCHED | 日次。セッション後 | JPX 空売り売買代金の市場合計 |
| investor_futures_flow | FETCHED | 週次。第4営業日の掲載規則 | JPX 先物の投資部門別 |
| nt_ratio | NOT_FETCHED | 未接続 | 日経平均の再配布条件が未確認。TOPIX だけでは NT にしない |
| futures_options_positioning | NOT_FETCHED | 未接続 | IV / PCR は未契約 |
| arbitrage_balance | FETCHED | 日次。セッション後 | JPX 裁定取引の市場合計。参加者名と原票は保存しない |
| credit_evaluation_loss | NOT_FETCHED | 未確認 | 単一系列が未確認 |
| crude | NOT_FETCHED | 未契約 | |
| gold | NOT_FETCHED | 未契約 | |
| silver | NOT_FETCHED | 未接続 | |
| copper | NOT_FETCHED | 未接続 | |
| korea_equity | NOT_FETCHED | 未契約 | |
| macro_release | NOT_FETCHED | 予定時刻のみ | 結果の数値系列は未接続 |
| official_speech | NOT_FETCHED | 未確認 | |
| earnings_schedule | NOT_FETCHED | 日程のみ | 日程は LIVE signal に未接続 |
| catalyst | NOT_FETCHED | 本文はコピーしない | |
| midterm_plan | NOT_FETCHED | 本文はコピーしない | |
| shikiho_fundamentals | NOT_FETCHED | 転載しない | 四季報の本文も指標も置かない |

### short_sale_ratio

- 初回 FETCHED の commit: `9180eb9ec`
- 2026-10-05 の市場合計: 8,721,605 百万円。実売 5,329,566（61.1%）、規制空売り 2,829,702（32.4%）、非規制 562,337（6.4%）。空売り比率 0.388924
- sha256: `cd29ffd0138ca38878d06e218f00489b78e3cdbfc1927d250aa46a11fea5a441`
- 取得元: https://www.jpx.co.jp/markets/statistics-equities/short-selling/ の市場合計 `-m.pdf`
- `session_date=2026-10-05`
- `first_seen_at=2026-10-06T01:13:15.683407+09:00`。`available_at` と `fetched_at` は同じ
- `published_at=2026-10-05T16:30:28+09:00`。根拠は HTTP Last-Modified
- `source_stage=OFFICIAL_PUBLIC`
- `trading_adoption=false`
- 場中判断には使わない

### investor_futures_flow

- 2026-09-24 から 2026-09-25。海外投資家。日経225先物、mini、マイクロの売買代金差引 186,407,123,040 円
- コード 60、商品 301 / 313 / 331。2026-09-24 週の公式 PDF の金額と照合した。他の週のラベルを推測で埋めない
- sha256: `5d092259946acb9c0a9777b93afc9a403360b392e2cae454849144988187befb`
- 取得元: https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html の `Tousi_DV_W_*.csv`。18MB の PDF は repo に置かない
- `session_date=2026-09-25`
- `first_seen_at=2026-10-06T01:26:55.678101+09:00`
- `published_at=2026-10-01T15:30:29+09:00`。根拠は HTTP Last-Modified
- 2026-04-17 週の `published_at` は null。ヘッダが検証窓に無いため埋めない
- 掲載規則「毎週第4営業日の午後3時30分」は `published_at` ではない
- `next_publication_due_on=2026-10-08`。これは予定であり、公表時刻ではない
- `trading_adoption=false`

### arbitrage_balance

- 3本目の FETCHED。JPX の日次 xls から市場合計だけを保存した。履歴は 10 セッション。最新は `session_date=2026-10-01`
- 売買は売り 64,563 千株、買い 8,980 千株。売りポジション合計 7,985 千株。買いポジション合計 849,191 千株。単位は千株
- 全社合計は売買の合計と一致した。参加者名の行は保存していない
- sha256: `004234bbfe70c28477815aece51a98db0e74923f84c2855a7aa27a5846d0c519`
- 取得元: https://www.jpx.co.jp/markets/statistics-equities/program/ の `261001.xls`。原票は repo に置かない。`raw_retained=false`
- `first_seen_at=2026-10-06T02:01:58.033482+09:00`。`available_at` と `fetched_at` は同じ
- `published_at=2026-10-05T16:00:31+09:00`。根拠は HTTP Last-Modified
- シートの `2026年10月5日` は日付であり、`published_at` ではない。`sheet_label_date=2026-10-05`
- 当限の注記は 2026-12 限まで。これは限月のラベルであり、時刻ではない
- 観測日 2026-10-06 の営業日差は 3。freshness は `STALE`。研究用の買い残は null
- `trading_adoption=false`。銘柄候補にはしない

`scripts/investor_regime.py` の既存アーカイブは、この lane の保存先ではない。`build_output` は呼ばない。

## Data freshness / available_at / no-lookahead

時刻は分けて持つ。

- `session_date` は対象セッション、または週の最終日
- `first_seen_at` はファイルを最初に観測した時刻
- `available_at` は、研究参照では `first_seen_at` と同じ
- `published_at` は、HTTP `Last-Modified` がセッション日以降かつ初回観測以前のときだけ入る。無いときは null
- 掲載予定の時刻で過去の `published_at` を埋めない
- HTML の index の Last-Modified はキャッシュ時刻であり、`published_at` にしない

freshness は 4 暦日固定ではない。JPX の休業日表（https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html）の営業日差を使う。表にある年は 2026 と 2027 だけである。表に無い年は `CALENDAR_MISSING` とし、研究値を出さない。平日だから営業日、とはしない。

日次は、観測日までの営業日差が 0 または 1 なら `FRESH`。2 以上、または未来セッションは `STALE`。2026-05-01 の値を 2026-05-07 に見ると暦日は 6 でも営業日差は 1 なので `FRESH`。2026-05-08 は `STALE`。

週次は、次の報告週の第4営業日が来る前を `FRESH` とする。2026-09-25 週の次の掲載予定日は 2026-10-08 なので、2026-10-06 の観測では暦日差 11 でも `FRESH`。掲載予定日以降に古い週だけを持つ場合は `STALE`。

判断に使えるのは、`available_at` がその判断時刻以前のデータだけである。後から見た値で過去の判断を通さない。

## TradingView / MS2-RSS / DEX等データ役割

役割は分ける。一つの画面に載っても、同じ権限にはならない。

| 源 | 役割 | 現在 |
|---|---|---|
| MarketSpeed II RSS | LIVE 価格の正 | 専用ブック経由。Current Acceptance（2026-10-03）では G0 は FAIL、G1 は NOT_RUN。HISTORICAL BASELINE（2026-09-22）の状態ではない |
| Collector / Gateway | RSS の配布と拒否 | 不一致、stale、別ブック、別銘柄、読めないコード列、重複は fail-closed |
| TradingView | 広域の探索候補 | 非公式 API の取得はしていない。NOT_FETCHED |
| JPX 公開統計 | Research Data Lane | 3/17 だけ FETCHED。売買には未接続 |
| DEX | 別ゲートの研究 | `docs/C189_DEX_ADOPTION_GATE.md`。正式シグナルと注文経路は変えない。`world_market.py` の表示名はライセンスではない |
| 四季報、日経平均の再配布 | 置かない | 契約が確認できるまで取得しない |

DEX を後で検討できる条件は、先行セッションだけの walk-forward、同じ baseline との比較、寄りのギャップと寄り後の分離、曜日と休日前の分割、欠測を埋めないこと、方向の的中率だけで改善と言わないこと、切片あたり N が 30 未満は探索のまま、しきい値はテスト切片の前に凍結、正式接続は別の明示承認、である。この条件は未達であり、DEX は NOT_FETCHED である。

NT 倍率は、日経平均の再配布条件が未確認なので計算して保存しない。

## Entertainment / AIトレード日記

Entertainment は、既に公開用へ整えた Cockpit の出来事を、内部の下書き列へ変える。経路は、整えた出来事、物語の点数、漫画 / X / YouTube の下書き、Owner の確認、である。出力は `DRAFT_INTERNAL`、`external_publish_allowed=false` である。ソーシャル API、認証情報、発注、タスク登録は持たない。公開は別の明示承認である。

AI トレード日記の行は、Shadow の記録を写したものと、週間 SNAPSHOT を混ぜない。`scripts/journal_projection.py` は、未知の手数料を円にしない。日記の公開投稿は、この版では NOT_RUN である。

## Distribution / Monetization / Revenue Engine

収益の Engine は、確認された数字が無い。売上、購読、広告、分配の金額は書かない。

公開してよいのは、個人の保有と認証情報を含まない成果物だけである。下書きの外部公開は `external_publish_allowed=false` のままである。収益の有無は、Trading の `real_submit_allowed` を true にする理由にしない。

この章の実装状態は NOT_RUN である。

## Continuous Evolution

改善の単位は、Acceptance の状態と、新しい観測である。commit の数は進捗ではない。

順序は次を維持する。

```text
P0 専用 Excel と市場 I/O
  -> P1 リアルタイム経路の一致
  -> P2 Strategy / Risk
  -> P3 AI SHADOW の実市場運転
  -> P4 Strategy の進化
  -> P5 UI / Voice / Journal
  -> P6 注文の DRY-RUN と照合
  -> P7 Controlled LIVE（別の明示承認まで HOLD）
```

前の Gate が FAIL のあいだ、後段を増築して PASS に見せない。既存の資産は捨てない。Office の追加原因調査と、表示中ダイアログへの追加操作は、vNext 草案のとおり止めたままである。

研究の特徴量は、backtest、walk-forward、replay、shadow が同じ方向を示し、標本が足りてから promotion 候補になる。現在の promotion は NONE である。

## Anti-Stagnation

画面の文言だけを増やすことを、データが進んだことと数えない。Registry が NOT_FETCHED のままなら、主成果は未取得の系列を FETCHED の条件まで進めることである。条件は、実取得、raw 保存、出典と `fetched_at` と `available_at` と freshness と license、保存できる履歴、欠測と破損の fail-closed、Research Layer からの参照、`trading_adoption=false`、LIVE signal を変えない、`real_submit_allowed=false`、合成を LIVE に混ぜない、である。

FETCHED は 3/17 である。残り 14 件は停滞として残っている。次の系列を、ライセンスと取得可能性の確認より前に保存しない。裁定残高は市場合計だけを保存し、参加者別の原票は保存しない。NT、IV/PCR、日経の共有ブランド、DEX、TradingView の非公式 API は、確認が終わるまで NOT_FETCHED のままである。

Brain の性能は、`BASELINE_N=0` のあいだ上がったとは書かない。

## OMISSION AUDIT

この版に意図して入れてないもの。

- 2026-09-21 付けの MASTER ファイルそのもの。repo に無い
- D: 上の、この版のコピー。初回 PASS は 4,644 bytes の前版
- Word の、D: へのコピー。初回同期に `.docx` は無かった
- 16:45 タスクの登録結果
- G0 から G5 のライブ PASS
- LIVE 往復の PASS
- Meta Brain が Entry を決めた記録
- Brain の選出銘柄と、現在の仮想建玉の中身。候補ファイルと live の shadow 行がこの作業コピーに無い
- クリーン標本の EV、PF、N。N は 0
- 確認済み手数料
- 個人の保有、注文、認証情報、非公開ウォッチリスト
- 裁定の参加者名
- 日経平均や四季報の本文と系列
- 収益の金額
- 相関と lead-lag の測定値
- DEX の採用
- 日記の外部公開

省略を、未検証の穴埋めに使わない。

## Owner / ChatGPT / Cursor / Codex役割

Owner は、製品の意図、実機、MS2 のログイン、危険な操作の承認、将来の実注文の承認を持つ。定例のコードとテストと文書を、Owner の手作業にしない。

ChatGPT は、戦略、統計、安全、仕様、レビューを持ち、`docs/AI_SHARED_SHEET.md` に提案を残す。提案は実装完了ではない。Claude の「完了」を証拠にしない。

Cursor と Claude Code は、実装、テスト、診断、STATUS の実装事実、bridge の返信を持つ。正本の契約は、明示された変更以外は維持する。この環境から D: と、稼働中の Excel、MS2、Collector、Gateway、AI SHADOW は触らない。

Codex は、`docs/C-023_ACTIONS_VERIFICATION.md` にある決算予定ワークフローの実機検証を受け持った記録がある。それ以外の常設権限は、この版では定義しない。

GitHub Actions は、秘密を含まないテストと公開物に使う。MS2 の実機試験の代わりにはしない。

共有シートの返信は `docs/CLAUDE_BRIDGE_RESPONSES.md` に残す。既存行は消さない。C-026 は、空売り比率と先物の投資部門までが一部取得で、統合表示は未着手である。

## 日次16:30 MASTER棚卸し

毎営業日 16:30 JST に、この MASTER と `CURRENT_STATUS.md` と `CHANGELOG.md` を棚卸しする。見るものは、Acceptance の状態、FETCHED の数、`BASELINE_N`、`real_submit_allowed`、LIVE signal を変えたか、未反映の D:、である。

棚卸しの 15 分後、16:45 JST に Owner PC が作業コピーを `D:\100億PROJECT\MASTER_SPEC` へ同期する、が目標のループである。実行ファイルは `downloads/UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1` である。順序は、`git fetch origin`、remote branch `cursor/master-spec-fetch-sync-d483` の最新 commit の確認、専用 worktree が dirty でないことの確認、HEAD がその commit と同じかその祖先であるときだけの fast-forward、対象ファイルの存在確認、`downloads/SYNC_100OKU_MASTER_SPEC.ps1`、sha256 の一致、`LAST_SYNC.json` への source commit と destination hash と result の保存である。remote に新しい commit が無い日は同じ commit を同期してよい。fetch 失敗、dirty、ローカルだけの commit、履歴の分岐、欠落、空、sha256 不一致では D: を更新しない。後続の MASTER 更新は、この remote branch を fast-forward する。登録スクリプトは `downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1`、タスク名 `TradeCockpit-100oku-MasterSpec-Sync`、時刻 16:45、前提はローカル時計が JST であることである。`-Register` を付けるまで登録しない。この版では未登録である。固定 worktree を fetch なしで毎日コピーするタスクは登録しない。

棚卸しで状態が変わっていない項目を、進んだと書かない。

## Change Management

変更の順は次である。

1. repo の `docs/100oku/` を更新する
2. Markdown と Word の意味を揃える
3. 同期スクリプトの dry-run で、対象と sha256 を見る
4. Owner PC の wrapper が remote branch を fetch し、clean な専用 worktree をその commit へ進めてから同期スクリプトを実行する
5. 上書き前のファイルを `archive\YYYY-MM-DD_HHMM\` へ退避する。同時刻があれば `YYYY-MM-DD_HHMMSS`
6. コピー後の sha256 が元と一致したときだけ PASS
7. 欠落、空、hash 不一致は FAIL CLOSED
8. `LAST_SYNC.json` に時刻、repo commit、対象、sha256、結果を書く。`cloud_agent_wrote_destination` は false
9. 16:45 の登録は、fetch してから同期する wrapper が揃った後の別作業である。この版では登録しない

同期対象は、`100億PROJECT_MASTER_SPEC.md`、`CURRENT_STATUS.md`、`CHANGELOG.md`、`HANDOVER.md`、および `docs/100oku/` にある `.docx` である。manifest は `docs/100oku/SYNC_MANIFEST.json`。

初回の `ARCHIVE=NONE_FIRST_SYNC` は、退避する前版が無かったという意味で正常である。二回目以降は退避する。

Cloud の dry-run は D: を作らない。`DESTINATION_WRITTEN=0` かつ `CLOUD_AGENT_WROTE_D_DRIVE=0` である。

## HANDOVER / 別AI復旧手順

別の AI が復旧するときは、この順で読む。

1. このファイル
2. `docs/100oku/CURRENT_STATUS.md`
3. `docs/100oku/CHANGELOG.md`
4. `docs/100oku/HANDOVER.md`
5. `STATUS.md` の実装事実
6. `docs/AI_COCKPIT_MASTER_SPEC.md` と `docs/P0_ACCEPTANCE_MATRIX.md`

復旧時に守ること。

- `real_submit_allowed=false` を維持する
- LONG / SHORT の信号集合を変えない
- Excel、MarketSpeed II、健全な Collector、差し替え済み Gateway、常駐の AI SHADOW を、この作業から止めない
- G0 から G5 を PASS と書かない
- `BASELINE_N=0` のあいだ EV と PF を作らない
- SNAPSHOT の 15 件を Research N に入れない
- FETCHED を売買採用と書かない
- D: へ書けたことにしない。同期の PASS は Owner PC のスクリプト出力だけが証拠である
- 個人の保有と認証情報を公開 repo に置かない
- 予測を注文に変えない

Owner の作業ツリーには未 commit の `STATUS.md` があり得る。`git reset --hard`、強制 checkout、無断 stash をしない。必要な実機操作は、絶対パスと `powershell.exe -NoProfile -ExecutionPolicy Bypass -File` で、作業ディレクトリに依存させない。

## Safety / real_submit_allowed=false

`real_submit_allowed=false` は固定である。RssOrder は未実装である。ブローカーへの送信はしない。モデルの予測を自動の実注文にしない。

fail-closed のままにする条件は、stale、別銘柄、Collector または watcher の重複、別ブック、コード列が読めないこと、`real_submit_allowed` が false でないこと、である。

仮想の記録は、数量 null、実送信 false、手数料は確認できるまで `FEE_UNKNOWN` である。合成 fixture の費用は、ブローカー料金表ではない。

実注文を将来開く条件は、別の明示的な Owner 承認、同時建玉の上限、一日の損失上限、一取引のリスク上限、fresh な一致、照合、である。この版はその承認を含まない。G6 のリポジトリ契約は PASS であり、ライブの再確認は NOT_RUN である。
