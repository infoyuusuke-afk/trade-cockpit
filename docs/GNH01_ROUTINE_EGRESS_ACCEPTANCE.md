# 100億PROJECT｜GNH01 毎時Routine自動送信・検収ゲート（準備）

PROJECT_ITEM_ID: `P0-GLOBAL-INTELLIGENCE-TO-SHADOW-INTEGRATION-20261022`

**状態：手順の準備のみ。Grokの設定変更・Run実行・GitHubへのGrok投稿・本番デプロイは未実施。**

## 1. 目的と責任分界

Grok Bot 第1号（GLOBAL NEWS HUNTER 01）の既存Routineについて、「OWNERが承認した毎時30分（JST）」という**希望**と、実際に保存・実行されたRoutineを区別する。既存のPR #490に実装済みのローカル署名付き受信は、実際のクラウドGrokの送信経路が成立したことを意味しない。

- Grok：世界公開ニュース・IR・公開SNSの発見、一次URL/公表時刻/発見時刻/訂正履歴
- PRE-NEXT：独立した会社名・285A等の銘柄同一性、先行性、株価反応前／後追いの判定
- 需給/SQ：信用・空売り・先物／裁定需給の別途検証
- BRAIN：検証済み研究情報のみ受領。実注文は禁止
- 進捗統括：統括台帳Issue #282で各層のACKと未了を監査

## 2. 既存Routineの**読み取り専用**確認（OWNERまたはBot操作）

Grok Botデスクトップで当該Botの**チャット上部のBot名 → Details → Routines**を開く。既存Routineの指示、実行タイムゾーン、毎時30分の予定、Paused/Active、履歴を確認する。画面上で存在が確認できない場合はRoutine登録をUNKNOWNとし、代替Routineを新規作成しない。

- 既存名の候補：`GNH01-1h-patrol`（名前・存在は未検証）
- 時間帯：毎時 `:30` JST、24時間（OWNERの希望、未検証）
- `Test` は実作業および利用枠消費の可能性あり。診断時点では押さない。
- 編集・削除・一時停止・利用枠の拡大・追加契約・タスクの新規登録を行わない。
- 通常のBotチャットへ、次のような**読み取りだけの依頼**を行ってよい：
  「あなたが管理する既存Routine GNH01-1h-patrol の存在、保存済み指示、タイムゾーン、毎時30分のスケジュール、Active状態、直近3回の実行開始/終了時刻とRun ID、GitHubコネクタをRun内で操作する権限を読み取り専用で調査し、リンク付きでVERIFIED/UNKNOWN/BLOCKEDと報告。新規Routine・設定編集・Test実行・GitHub書込・課金は禁止。実行履歴が取れない場合はUNKNOWNとする」

**製品の参照資料**：
- https://prod.cursor.com/help/grok-bot/routines
- https://docs.x.ai/grok-bot/skills-routines-and-automations

## 3. 一回だけの手動送信は無人送信の証拠ではない

GitHub Issue #282上の手動1件：
https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6331373208

上記コメントの存在は、Grok Botを手動で操作した接続経路の検収にしか使えない。投稿者が`infoyuusuke-afk`なのはCursor GitHub連携のためであり、特定Grok Routineの実行を認証するものではない。

Routine検収は**実際の保存済みスケジュールから開始されたRun**で、次の独立証拠を照合する。

1. 実際のGrok Routine画面または実行履歴のRun ID、開始時刻、成功／失敗、使用したRoutine識別子
2. 同じRunのログ内に記録された**送信アクションと成功記録**
3. 非公開受信先で得たイベント・Run ID・受信時刻・改ざん検知・重複拒否・持続確認
4. PRE-NEXT受領者が独立発行した、同じイベントを参照するACK（Grok自身の自己申告、ローカルテストReader ACKや統括台帳の既存ACKは不可）

2回以上の異なる**自然発火スケジュール実行**で受信と再起動復元が確認できるまで、`GROK_UNATTENDED_EGRESS_VERIFIED=false`。手動Testだけの成功では「Routine経由の無人継続成功」としない。

## 4. 安全な実送達テストの境界

現状、Issue #282は公開リポジトリの連携台帳。公開IssueへIR全文・生の市場情報・機密・認証キー・ローカルパス・有料データ・未公開情報を投稿しない。

送信試験を別途OWNERが明示承認した場合のみ、**公開可能な固定形式・短い機器診断メタデータ**を1件投稿し、以下だけ含める（コメント投稿権限、閲覧先、頻度の承認も必須）。

- `project_item_id`, `message_id`, `routine_run_id`, `routine_scheduled_at_jst`（全てアプリから取れた時だけ）、`event_type=DELIVERY_TEST`, `real_submit_allowed=false`
- 公開不能なRun ID・秘密値は書かない
- 投稿前に同じ`message_id`の全件確認、同一IDの再投稿禁止。未知の送信結果は停止

**公開コメントの成功は研究情報の非公開配送ではない**ため、実運用の市場情報配送先は非公開・認証付きの別経路であること。秘密鍵とRawイベントはGitHub Issue・PR・公開ブランチに保存しない。

## 5. 既存コードの実装・検証可能範囲

Draft PR #490:
https://github.com/infoyuusuke-afk/trade-cockpit/pull/490

- JSON入力検査＋私有SQLite耐久保存
- 発見情報の未検証PRE-NEXTレビュー候補
- オフライン署名付きファイル書込と**ローカルリーダー専用**ACK
- archive → signed-envelope → ACK相互一致の独立監査（`scripts/gnh01_delivery_chain_audit_v1.py`）
- 明示的な出力フラグ `grok_unattended_routine_verified=false`, `pre_next_scheduled_task_delivery_verified=false`, `pre_next_scheduled_task_ack_verified=false`, `brain_receiver_ack_verified=false`, `shadow_eligible=false`, `real_submit_allowed=false`

これはGithub CI上の合成試験である。外部送信、PRE-NEXTクラウドタスク、Brain observer、SHADOW、本番V10への組込み、OWNER実機Windows ACLは別途検収が必要。

## 6. 次の開発順序

1. 既存Grok Routineの存在・権限・実行履歴を読み取り専用で確認。
2. 非公開・認証済み送達先を決定。コネクタ／Routineの外部送信実効権限を実証する（変更や投稿にはOWNER承認）。
3. 無人Runから非公開経路に送信 → 受信側で元データとRun IDを独立紐付け。
4. PRE-NEXT独立受領ACK。公開ソースの一次確認と先読み防止評価。
5. 既存PR #481/#482/#483の署名付きBrain研究レーンに、検証済み情報のみ接続。V10既定OFFを維持。
6. SHADOW仮想検証、EV/PF/Nと費用記録、OWNER Windows実機受入。実注文禁止。

**受入判定**：現状`PARTIAL`。既存Routineの登録状態、無人送信、PRE-NEXT実受信、BRAIN、SHADOWをPASSと偽らない。公開Issue #282への報告は認証付き非公開イベント配送そのものではない。
