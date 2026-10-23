# 100億PROJECT｜Zero-Token Strategy Lab v1（24時間ローカル戦略探索AI）

**PROJECT_ITEM_ID:** P0-ZERO-TOKEN-STRATEGY-DISCOVERY-20261023

**状態:** Draft／隔離実装・合成テスト専用。OWNERの取引PCへの実機導入、MS2実データ接続、取引・Shadow注文作成は未実施。

## 1. 目的

OpenAI/xAI/GrokなどへのLLM推論を**0回**とし、APIトークンを消費せず、既存の15秒足データが追加される度に統計的な手法探索・評価を繰り返す。これはローカルのルール探索／パラメータ最適化であり、言語モデルが24時間思考し続ける仕組みではない。**勝てる戦略の発見は保証できない。**

- **市場開場中（東証 09:00–11:30／12:30–15:30）**：取得済み・確定済みの板／約定データで研究。AIコクピットV10のExcel／RSS収集を変更しない。
- **市場閉場中**：蓄積済みのデータを再検証する。入力が更新されなければスキップするので無駄なCPU使用を減らす。24時間の「常時研究可」はPC／サーバーの起動を要する。
- **コスト**：クラウドAI推論トークン0。PC電気代、記憶領域、OS運用やデータライセンス、クラウド／GitHub Actionsの計算資源費はゼロとは限らない。
- **注文**：`real_submit_allowed=false` 固定。ブローカー／RssOrder／Excel／V10 Observer／Risk Gate／Permission Gate／Kill Switchに接続しない。Shadow注文も自動作成しない。

## 2. 実装ファイル

- `scripts/zero_token_strategy_lab.py`：確定15秒足CSV検証、64個の固定仮説（OR5/OR15 × LONG/SHORT × BREAK/VWAP × 損切り30/50bps × 目標1.5/2R × 保有40/80本）、翌足始値の保守的な約定仮定、日付区切りでの学習／検証／隔離テスト、費用ストレス、日単位ブートストラップ。
- `scripts/zero_token_strategy_worker.py`：既存の**非公開**CSVを15分おきに再読できる常駐処理（明示的`--daemon`時のみ）、入力SHA-256重複排除、SQLite完了台帳、原子的なJSONレポート保存、独立再読。標準ライブラリのみ。
- `tests/test_zero_token_strategy_lab.py`, `tests/test_zero_token_strategy_worker.py`：合成データの前後参照・欠測・改ざん・データ鮮度・手数料・署名なし出所フラグ・重複・非公開パス・注文禁止の負例検証。
- `.github/workflows/zero-token-strategy-lab-offline.yml`：Windows/UbuntuとPython 3.11/3.12、Windows日本語パスでの隔離CI。定時クラウド起動ジョブは存在しない。

## 3. 重要なデータ契約

入力CSVは**ヘッダー一致・UTF-8・最大64MiB・40万足以下**。1行 = 1銘柄の**確定15秒足、時間は足の終了時刻**。必須列の順序：

```text
symbol,time,available_at,open,high,low,close,volume,source,quality
```

- `symbol`：例 `285A`または`285A.T`（同一銘柄として正規化、キオクシアホールディングス）。`464A`は別会社（QPSホールディングス）。コードの**発行体同一性は別の台帳で検証すること**。
- `time`：UTCオフセット付きISO8601（例：09:00:15+09:00）。午前09:00～11:30、午後12:30～15:30の15秒確定足のみ。
- `available_at`：実際に足が利用可能になった時刻。足終了より前、または終了から120秒より後は入力異常。シグナル発生足がその時点で利用可能でなければ**その足を使ったトレードは禁止**。
- `source`：現在の契約では`MS2_RSS_15S_CONFIRMED`またはテスト専用`SYNTHETIC_TEST_ONLY`。**文字列がCONFIRMEDでも出所暗号認証ではない**。Collectorが生成するプライベート証跡との一致検証は接続時の必須ゲート。
- `quality`：`CONFIRMED`のみ。欠損、時刻競合、異常OHLCは修復せず拒否。
- 始値・高値・安値・終値は正の有限値、出来高は0以上。重複時刻／旧新銘柄名混同／休日や休場中の価格を混ぜない。
- 現行V10のticks.csv／MS2 CSV形式がこの契約と同じとは仮定しない。**読み取り専用変換アダプタを別途検証するまで実データ接続はNOT_VERIFIED**。

## 4. 探索・検証の方法

- 最初のOR5/OR15の20／60本が時刻順に揃っている場合に限り仮説を実行する。シグナルは確定済み足までのVWAPとOPENING RANGEで評価し、**次の足の始値で仮定約定**。
- 指定した保有期間中の15秒足が1本でも欠けた場合は、仮想の約定価格を補完せず対象を棄却する。
- 同一足で利確／損切り両方到達した場合は**損切り先行**。逆行ギャップの損切り価格は悪い始値を使う。
- 1銘柄／1営業日／1仮説につき最大1トレード。連続保有を暗黙に仮定せず、寄り付き短期研究に限定。
- 取引毎に往復手数料／約定摩擦をbps控除。初期値18bps、10bps未満への引き下げを拒否。検証には1.75倍、隔離テストには2倍の費用ストレスを適用する。実際の銘柄・ロット・空売り料／スリッページは別途較正が必要。
- 営業日ごとに60% TRAIN、20% VALIDATION、20%最終TESTへ時系列分割、境界の各1日をパージする。探索対象64候補は上限固定。
- VALIDATIONの損益が費用込みで正、日付ブロック・ブートストラップの多重検定補正付き下限が正、費用1.75倍で正の候補だけを残す。TRAIN/VALIDATIONで候補を1件選定してから未使用TESTでのみ測定する。
- 結果の分類は`INSUFFICIENT_HISTORY`／`NO_VALIDATED_EDGE`／`EDGE_UNVERIFIED`／`SHADOW_REVIEW_CANDIDATE`。最後でさえ**実注文不可**、レビュー候補。合成データのみから昇格しない。
- 試験期間への再探索で有利に見せる「テストデータの繰り返し覗き見」を防ぐには、新規前向きShadowデータを**別期間・別台帳で**収集する。自動分析ログは前向きShadow検収の代わりではない。
- **統計的な勝率、将来収益の確率、実現利益、100億達成額は未実証であればUNKNOWN**。結果がないときはNO EDGEとして停止する。

## 5. 起動方法（OWNER承認・実機検収後のみ）

*現時点では実装コードがGitHub Draftにあるのみで、以下は将来の手順。PCは起動しておく必要がある。新規Windowsタスク／サービスは登録しない。*

1. Python 3.11以上が利用できる隔離環境と、V10の実動CSVと**競合しない**非公開CSV読み取り経路を用意する。Excelを増やさない。
2. 実PCでOWNER管理のプライベートフォルダ（例：ユーザープロファイルの外部データフォルダ）を作り、Windows ACLと実データ証跡を独立検査する。暗号鍵や利用権限はGitHubへ置かない。
3. まず1回実行：

```powershell
py -3 -m scripts.zero_token_strategy_worker --once --input "C:\PRIVATE\15s_confirmed.csv" --output-dir "C:\PRIVATE\strategy_lab" --roundtrip-cost-bps 18
```

4. 合成受入を終え、正式承認されたら24時間継続に切替（PC／プロセスが起動中のみ）：

```powershell
py -3 -m scripts.zero_token_strategy_worker --daemon --input "C:\PRIVATE\15s_confirmed.csv" --output-dir "C:\PRIVATE\strategy_lab" --poll-seconds 900 --roundtrip-cost-bps 18
```

5. 出力`strategy_lab_latest.json`はその時点の研究統計のみ、`strategy_lab_runs.sqlite3`は入力SHAと検証履歴。実注文やBrainの売買ゲートに送らない。途中停止はCtrl+C。投入データが増えなければ再評価をスキップする。

## 6. 未完了・次段階

- 現行V10のticks.csv／15秒OHLCを、データ欠損と採用時点を残したまま読み取り専用で変換するアダプタの実装。**実データをこのGitHubの公開CIへアップロードしてはいけない。**
- 運用時計の信頼性、東証休場日カレンダー、寄付き/引け特別気配、後場ギャップ、真の板スプレッド・出来高・空売り料、銘柄入替による選定バイアス検査。
- 将来時点のアラート候補は、運用データから発見できる新しいパターンを自律追加する仕組みと別に検証する（v1は64固定仮説）。
- 既存`strategy_evolution.py`や`shadow_forward*`へは**未接続**。結合には独立した前向き受入とOWNER承認が必要。
- Windows実機起動、常駐復旧、実データEV/PF/N測定、費用較正、SHADOW受信：いずれも**NOT_RUN／NOT_VERIFIED**。
- レポート生成時のローカルデータハッシュと再読は保証するが、**元データの企業・証券コードの真実性、外部検証済み配信時刻を保証しない**。MAC/署名は別ゲート。
- クラウドLLMトークンを消費しないことと、電力・システム費用がゼロであることは別である。

**導入禁止：** 実注文、課金、既存V10切替、mainマージ、自動Windowsサービス登録、実運用Excelの複製、無承認スケジュール変更。
