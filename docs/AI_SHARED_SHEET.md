# AIコクピット 共有シート（ChatGPT ↔ Claude Code ↔ Cloud）

最終確認: 2026-09-25 JST / 記録担当: Claude（Reconciliation、C-091参照）  
正本: [STATUS.md](../STATUS.md)（実装・結果） / このファイル（連携・戦略上の論点）。根拠が矛盾したら実ファイルと実行ログを確認し、未検証として扱う。

> **2026-09-25 役割更新**：STATUS.md冒頭の記載どおり、GitHub main自体が開発・進捗共有の唯一の正本となった（2026-09-23、PR #198）。役割は固定せず、GitHub mainの最新状態を基準に引き継ぐ。新規セッションは作業開始前に必ず `python scripts/bridge_health.py` でorigin/mainとのdrift（ahead/behind）を確認し、大きくdriftしている場合は最新mainから作業をやり直すこと（詳細はC-091参照）。

> このリポジトリは公開です。証券口座、氏名、パスワード、APIキー、保有数量、非公開取引履歴、ローカルPCの絶対パス、未承諾の会話全文は記載しない。

## 運用・役割

- ChatGPT: 戦略・検証設計の壁打ち。実装に関係する確定論点はこの共有シートへ根拠と時点付きで記録する。相談だけで決まっていない案は「提案」と明記。コード・売買注文は変更しない。
- Claude/Claude Code: コーディング、実データ検証、テスト、本番反映を担当。新規セッションの開始時には `git pull` 後に `STATUS.md` とこのファイルを読み、作業後に `STATUS.md` の実装状況と下の処理欄を更新する。
- ゆうすけ: 最終売買判断と、PC上でしか使えないMarketSpeed II/Excel RSSのログイン・起動。連絡文を手作業でAI間に転送する必要はない。ただしClaudeの停止中に新規作業を自動で開始させる仕組みではない。
- このファイルへの記載は「Claudeに命令を送信した」「Claudeが読んだ」「実装が完了した」のいずれも意味しない。受領・実装・公開の確認はそれぞれ別に記録する。

## 共有対象と接続境界

| 項目 | 正本 / 現在の経路 | 2026-09-14時点で確認した状態 | 注意点 |
|---|---|---|---|
| クラウドAIコクピット | `index.html`、Actions生成JSON、[公開ページ](https://infoyuusuke-afk.github.io/trade-cockpit/) | `STATUS.md`に稼働・課題あり | GitHub PagesをPC上RSSのリアルタイム発注画面と混同しない |
| 戦略と実装状況 | `STATUS.md` | LONG/SHORT、3階層、検証結果を記載 | `STATUS.md`に旧記述と新記述が混在。最新の実行結果を再確認 |
| 100銘柄LIVE | `ms2_live/`、同梱ExcelとPowerShell | ユーザーPCで別途MS2ログイン・Excel接続・収集器起動が必要 | ChatGPT/ActionsからPC内RSS・寄り前板を自動取得できない |
| キオクシア専用DASHBOARD | `Kioxia_MS2_RSS_Live_Signals.xlsx`、`Kioxia_RSS_Live_Watcher.ps1`（配布キット） | Excelリボンが「接続中」でも、別途Watcher未起動なら画面が「接続待ち」の場合がある | 100銘柄収集器とは別の起動処理。価格と最終更新時刻を実機で確認 |
| 需給・板・歩み値・売買統計 | PC内の日別CSVとGitHub上の公開データ | PC内ログの継続取得/アップロードは未確認 | 未取得をゼロ・推定・当日実績として扱わない |
| 戦略案と確認依頼 | 本共有シート下部 | 提案と検証事実を分離 | 結果が出るまで「優位性確立」としない |

## 製品ビジョン・全体要件（2026-09-15・ユーザー確定）

ユーザーから、AIコクピットの大前提となる製品ビジョンが明確に示された。これは提案ではなく
確定した方針であり、今後の実装・戦略設計はすべてこれを土台にする。

### 目指す姿

「自動売買システム」が大前提。TOPページを開けば：
1. **デイトレTOP5**：今日いちばん期待値の高い銘柄が5つ、ひと目でわかる
2. **本日の実現損益**：その日実際に売買した結果が数字で見える
3. **オーバーナイトTOP5**：引けで買い（または売り）、翌朝の寄り付きで反対売買
4. **スイングTOP5**：1週間保有
5. **長期TOP5**：1か月保有
6. **決算スケジュール連動の期待値銘柄**：デイトレで見逃してはいけない、決算に絡む
   期待値の高い銘柄（ロング・ショートどちらでもよい）
7. **注意アラート**：要人発言など、デイトレ中に絶対に忘れてはいけないイベントの時刻を
   通知（音声等）で知らせる
8. **背後の適応ロジック**：日々の地合い変化（トランプ相場の時はこの手法、金利高の時は
   この手法、等）に応じてトレードルールを自動的に切り替える。これは裏側で動いていれば
   よく、画面上に複雑さを出さない
9. **デザイン**：できるだけシンプルでかっこよく。Appleのアプリのような洗練された使用感を
   目標にする
10. **将来のビジネス化**：本当に良いものができれば販売する。トレード日記などを自動配信して
    収益化する全自動システムまで見据える（これは将来構想であり今回の実装対象ではない）

### 自動発注の範囲（ユーザー確定・重要）

**最終目標は完全自動売買。ただし現時点では「サイン生成＋ワンタップ確定（最終判断は人）」**
とする。CLAUDE.mdの「モデルの予測を自律的な売買注文に絶対に変換しない」という制約は
「AIが人の確認なしに勝手に発注する」ことを禁じているものであり、「サインは自動生成し、
発注ボタンを人が押す」という今回の方針とは矛盾しない。完全自動化は将来の到達点として
明記するが、今回の実装対象は「ワンタップ確定」までとする。

### 現状の棚卸し（Claude・正直な評価）

| 項目 | 現状 |
|---|---|
| デイトレTOP5 | LIVE売買タブに原型あり（`MS2_RSS_100_Collector.ps1`の`top5`）。「期待値」の定義・ランキング方法は未整理 |
| 本日の実現損益 | 存在しない。`paper_trade_history.json`は紙トレード（仮想）であり、実際に発注した結果ではない。ワンタップ確定を実装しない限り「実現」損益は作れない |
| オーバーナイトTOP5 | 「15:25確定・翌日持ち越しTOP5」として原型あり（`hold_top5`）。名称・位置づけを整理すれば流用できる |
| スイングTOP5(1週間) | MVPあり（`swing_signal.py`）。実績検証はまだ薄い |
| 長期TOP5(1か月) | MVPあり（`long_signal.py`）。同上 |
| 決算×期待値銘柄 | 2系統の重複はC-030で統合済み。`earnings_calendar.py`（JPX60日分＋TDnet開示分類）を唯一のデータ源とし、`upcoming_earnings.py`独自のモメンタムレーン＋的中率自己検証だけを移植して廃止した。ロング/ショート判定ロジック自体（TDnetキーワード分類止まり）はまだ未設計 |
| 注意アラート | 「重要イベント」タブはあるが、時刻が来た瞬間に音声等でその場で警告する仕組みは未接続 |
| 地合い適応ロジック | `investor_regime.json`等の部品はあるが、「地合いを判定→手法セットを自動切替」という統一エンジンは存在しない。各シグナルロジックに個別のしきい値が散在している状態 |
| ワンタップ確定・発注実行 | 未実装。`RssOrder`（MS2 RSSの発注関数）自体、安全方針によりこれまで一度もコードに組み込んでいない。実装するなら、確認画面・二重発注防止・エラー処理・失敗時のロールバック等、慎重な設計が必要 |
| デザイン（Apple的な洗練さ） | 未着手。現在は情報密度重視の実務画面 |

### ChatGPTへ相談したいこと（戦略設計）

1. **地合い適応ロジックの設計**：「トランプ相場」「金利高」等のレジームをどの指標の
   組み合わせで判定するか、レジームごとに何を変える（しきい値／時間帯／対象銘柄／
   ロングショート比率等）か
2. **決算×期待値銘柄のロング/ショート判定基準**：決算内容だけでなく、地合い・出来高・
   PTS反応等をどう組み合わせて方向を出すか
3. **4階層（デイトレ／オーバーナイト／スイング／長期）の優先順位**：どれから精度を
   高めるべきか。同時並行が良いか、順番につぶすべきか
4. **「期待値」の統一定義**：4階層それぞれで「期待値」を何で計算するか（勝率×平均利益、
   シャープレシオ的な指標、等）を統一したいが、時間軸ごとに違う定義が必要か
5. **注意アラートの対象基準**：どのイベント・どの要人発言を「デイトレ中に絶対見逃しては
   いけない」対象とするか

Claude側は上記が決まり次第、実装可能な範囲から順にコーディングする。ワンタップ確定・
実発注機能は特に安全設計が重要なため、着手前に改めてユーザーの承認を得る。

## 未解決の論点（最初の共有）

| ID | 時点 / 出所 | 内容 | 区分 | 次担当・完了条件 |
|---|---|---|---|---|
| H-001 | 2026-09-14 / ChatGPT | キオクシア専用DASHBOARDはRSSリボンの接続と別にWatcher起動・価格更新の検証が必要。ゆうすけには手順を案内済み | 実機確認待ち | Claude: 将来の起動一本化を検討するなら100銘柄収集器との競合・停止動作・エラー表示を検証して実装。PC実機の動作確認はゆうすけ |
| H-002 | 2026-09-14 / `STATUS.md` | OR5先行のStage②比較は真のOHLC5分足6銘柄・発動184件の記録がある一方、監視銘柄の事後選択、期間・手数料・執行バイアスを除く前向き検証は未完了 | 検証待ち | Claude: 時点固定の対象銘柄・費用・LONG/SHORT別で追試。ChatGPT: 結果の戦略解釈 |
| H-003 | 2026-09-14 / `STATUS.md` | 寄り前気配の実記録が未確認。PC内RSS情報とクラウド実績を混同しない | 未取得 | Claude: CSV有効行・時刻・欠測の健全性表示を検討。外部公開や自動転送には本人の明示承認が必要 |

## 新規情報の追記フォーマット

| ID | 記録日時(JST) | 発信者 | 事実/観測/提案 | 根拠URLまたはファイル | 優先度 | Claude側の対応/理由 | 検証結果 | 公開確認 |
|---|---|---|---|---|---|---|---|---|

> **2026-09-25 整理**：C-001〜C-090（2026-09-14〜2026-09-19分）の詳細記録は容量確保のため
> [docs/AI_SHARED_SHEET_ARCHIVE_2026-09.md](AI_SHARED_SHEET_ARCHIVE_2026-09.md) へ移動した。
> 内容は削除しておらず、全文をそのまま転記している。実装結果の正本は引き続き[STATUS.md](../STATUS.md)。

| （新規） | — | — | — | — | — | 未着手 | 未検証 | 未反映 |

更新原則: 他者の行は勝手に「完了」にしない。確定事実にはリンク・コミット・実行日時を添える。ChatGPTとClaudeが同時更新する場合は直近mainを再取得し、追加行のみ反映して競合を回避する。売買サインや予測を実績として転載しない。

## 定期受け渡しの有効化状況

- ChatGPT側: 共有シートと[Claude返信](CLAUDE_BRIDGE_RESPONSES.md)を確認する定期処理を有効化済み。ただし、直近の実行と返信は未確認。
- Claude側: [Claude Code Routineの設定・実行指示](CLAUDE_ROUTINE_BRIDGE.md)を用意。ClaudeアカウントでのGitHub接続・Routine作成・手動初回実行は未確認。**両方向の自動連携が稼働したとはまだ言えない。**
- C-002はClaude側返信待ち。返答は別ファイルの同じIDに記録し、更新された事実を確認してからユーザーへ報告する。

## 連携の限界

GitHubの共有ページは双方が参照できる受け渡し場所であり、ChatGPTとClaude間の常時接続・自律対話・Claudeセッションの自動起動ではない。GitHub未同期のローカル成果、会話内容、MS2の非公開ライブデータは自動流入しない。本人への完了報告は、書込確認・Claude側の処理確認・公開画面の確認を混ぜずに伝える。

## C-091｜2026-09-25 同期欠落期間のReconciliation（Claude記録）

**目的**：共有シートがC-090（2026-09-19）、返信記録（CLAUDE_BRIDGE_RESPONSES.md）がC-031-GPT（2026-09-15）で止まっていた空白期間を、個別C-IDへ遡って捏造することなく1件でまとめて同期する。GPT指示（2026-09-25）に基づく。**同期完了後は通常の1タスク/1論点＝1C-ID運用へ復帰する。**

### 前提として発覚した事実（重要）

作業していたローカルブランチが実際には**origin/mainより2150コミット遅れ**ていた。この空白期間の間に、別セッション（Cloud、認証はinfoyuusuke-afkアカウント）による大規模な統合作業（2026-09-23〜24）がGitHub main上で既に完了していた。以下はいずれも**「現行originmainに存在することをgit/ghで確認済み」**であり、各項目の実装内容そのものをClaudeが独立に再監査したことは意味しない（区別を明記する）。

- STATUS.mdの「2026-09-24 GPT/Cloud backlog consolidation」「2026-09-24 GPT final-gate consolidation」の2セクションに、C-107〜C-118相当（Shadow Forward非公開永続化、TSE-aware TradingView gap audit、AI Cockpit master spec、AI Strategy LIVE Phase 2、Global Macro Supervisor、KIOXIA ADR/IR/SEC Breaking Radar、main-only auto-commit workflow scope、Local Market Data Gateway、protected-main data-writer hardening等）がmainへ回収・統合されたと記載されている（**STATUS.md記載の存在確認のみ**、個別の中身はClaude未再監査）。
- `scripts/build_ai_strategy_live.py`・`scripts/global_macro_supervisor.py`・`scripts/owner_approval_queue.py`・`scripts/public_event_sanitizer.py`・`scripts/local_source_health_contract.py`・`scripts/tradingview_stitcher.py`とそれぞれのテストファイルの存在を`git ls-tree origin/main`で**直接確認済み**。
- PR #187（SCALP-family配色）は2026-09-22 16:58 JSTに infoyuusuke-afk 本人によりマージ済み（**確認済み**）。
- PR #186・#183（AI Strategy LIVE Phase 1/2）はDraftのまま終了せず、2026-09-23にCLOSEDへ変更されていた。内容はPR #200「C-112: rescue AI Strategy LIVE Phase 2 onto current main」（2026-09-23 13:25 JSTマージ、#186のクローズと同時刻）へ引き継がれてmain反映済み（**確認済み**）。ただし実際のUI（index.html）には`ai_strategy_live.json`への参照が一切なく、**データ層は存在するがカード表示は未実装**であることをコード調査（サブエージェント）で確認した。
- `real_submit_allowed`は現在もmain全体で`false`固定（`config/ai_organization_v1.json`、各スキーマの`const: false`）。実発注・RssOrder・ブローカー接続関連の有効化コードは見当たらない（**確認済み**）。

### 重大な発見：Owner承認ゲートの一時的な無効化

2026-09-23 21:56 JST、PR #198（「Fix GPT / Cloud progress handoff source of truth」）で`.github/workflows/owner-main-approval.yml`の`approve`ジョブから`environment: name: owner-main-approval`の参照が削除されていた。GitHub側のEnvironment保護設定（必須レビュアー=infoyuusuke-afk）自体は存続していたが、ワークフローがそれを参照しなくなったため、実質的にレビュー必須の効力が失われていた。直後の2026-09-23 19:07〜19:36の約30分間にPR #239〜#250等13件以上が連続マージされている（author・mergedByとも同一アカウント）。

**対応済み**：[PR #255](https://github.com/infoyuusuke-afk/trade-cockpit/pull/255)で`environment:`参照を復元し、再発防止の回帰テスト（`tests/test_owner_approval_gate_present.py`）を追加。**マージはせずOwner確認待ちのまま**。

### 今回追加した対応

- [PR #255](https://github.com/infoyuusuke-afk/trade-cockpit/pull/255)：Owner承認ゲート復元（P0-A）。Owner待ち。
- [PR #256](https://github.com/infoyuusuke-afk/trade-cockpit/pull/256)：Bridge Health（`scripts/bridge_health.py`、P1）。origin/mainとのahead/behind・uncommitted・last reconciled等を機械判定し、大きなdrift時はBLOCKED（exit code 2）を返す。今回の「2150コミット遅れ」の再発防止が目的。GPT側が確認したHEADを書き戻す仕組みは本リポジトリ単独では実現できないため、その項目は手動記録のまま（未解決事項として明記）。Owner待ち。
- 本コミット（P2）：本ファイル・STATUS.md・CLAUDE_BRIDGE_RESPONSES.mdの容量整理と本Reconciliationエントリ・製品ビジョン追加要件・P0優先順位の追記。

### 未解決・次回以降の課題

- P0-B（全面カード化）は対象タブの棚卸しのみ完了（下記参照）。実装は未着手。
- Bridge HealthのGPT側フィールド（GPT確認済みHEAD）は仕組み上自動化できず、要相談。
- 9/24の統合作業（backlog consolidation）自体の安全性・品質は、STATUS.mdの記載を確認したのみで、Claudeによる独立再監査は行っていない。必要であればGPT側で個別に検証依頼してほしい。

**安全境界**：本エントリの作業はドキュメント整理とCI/CDワークフローの復元（PR、未マージ）のみ。発注・ブローカー・RssOrder・real_submit・Windows Scheduled Taskには一切触れていない。

## 製品ビジョン追加要件（2026-09-19〜25確定分、2026-09-25追記・GPT指示）

2026-09-15版の基本ビジョン（上記）は維持した上で、その後ユーザーが確定した要件を追加する。

- 最終到達点は完全自動売買。現フェーズでは実発注は人の最終承認を残す（2026-09-15版と同じ）。
- AIコクピットは単なる分析支援ではなく、銘柄選定・分析・監視・検証をAI側が主体的に実行する。
- 古い現在値・古いシグナルを表示して売買判断に使わせることは禁止。リアルタイム性・鮮度・Fail-Closedを最優先する。
- 現在値、場中決算、ニュース、ファンダ情報についても鮮度保証が必要。
- 優位性のある銘柄はカードの点灯＋音声で知らせる（音声だけの通知は禁止）。
- UIはキオクシア予測チャートを除き、原則カードタイプへ統一する。
- リアルタイムタブにも不要なチャートは置かない。
- 実況銘柄カードを設け、音声を聞き逃しても画面で確認できるようにする。
- TradingView＋Apple系の簡潔なUIを基調とする。

**明確化（誤解防止）**：PR #187のSCALP-family配色変更（黒基調化）だけを「カードUI完成」として扱わない。実機ではまだカード統一が完了していない（下記P0-B棚卸し参照）。同様に、Excel/Watcher起動時のFail-Closed追加だけを「ライフサイクル問題解決」として扱わない。本来の要件は「Excelを閉じる→Watcherも終了→COM参照を完全解放→EXCEL.EXE自体が自然終了する」ところまでで、これは実機（Windows/MS2側）の課題として継続する。

## 現在の最優先事項（P0、2026-09-25・GPT指示）

- **P0-A（Owner承認ゲート復元）**：完了・[PR #255](https://github.com/infoyuusuke-afk/trade-cockpit/pull/255)としてOwner待ち。
- **P0-B（AIコクピット全面カード化）**：棚卸し完了、実装未着手。対象タブと現状UI型（サブエージェント調査、2026-09-25）：
  - 既にカード化済み：SCALP 5、EVENT 5（`.scalp-card`系共通）、OVERNIGHT（同系統）、MS2 LIVE TOP5（`.ms2-live-card`、別系統のカードCSSで要統一）
  - 未着手・旧テーブル型：SWING（⑤-A〜D等の静的table群）、LONG（⑤-E/F、配当・自社株買い監視）、ランキング（Yahoo/TradingViewスクリーナー、各4段table）、監視銘柄（`#watchlist-100`、`#premarket-gap-ranking`）、FLOW/需給系（`#investor-regime`、`#large-lot-accumulation`、`#sector-rotation`、`#correlation-monitor`）、決算勝負候補table（tab未接続）、7つのpolicy-*テーマタブ（各大型table）
  - 独自パネル型（table主体ではないが未カード化）：EVENT/決算カレンダー（`#event-calendar`、専用カレンダーグリッド）
  - **AI Strategy LIVEはデータ層のみmain反映済みでUI未実装**（index.htmlに参照なし）。カード化ではなく新規実装が必要。
  - 例外として維持：キオクシア予測チャート（`#kio-best-path`、独立したLightweight Chartsコンポーネント、確認済み）
  - `scripts/update.py`（3662行）が大半のtable HTML生成元と推定されるが未調査。着手前に読む必要あり。
- **P0-C（カード化Acceptance Test）**：P0-B実装後に着手。desktop/mobile(375px)双方でスクリーンショットまたはHTML検証証跡をPR本文へ残す方針。
- **P0-D（Bridge Health）**：完了・[PR #256](https://github.com/infoyuusuke-afk/trade-cockpit/pull/256)としてOwner待ち。
- **P0-E（Excel/WatcherライフサイクルP0-1相当）**：Cloud側では対応しない（実機Windows/MS2が必要なため）。ChatGPT Work・実機側で継続。


