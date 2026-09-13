# trade-cockpit STATUS

最終更新: 2026-09-14（Claude・第2弾更新）
役割分担確定：ChatGPT=戦略の壁打ちのみ（リポジトリは変更しない）／Claude=実コーディング担当
運用体制: ChatGPT（戦略・相場観）＋ Claude/Claude Code（コーディング・診断）＋ Genspark（必要時のみ、現在未課金）

新しいスレッド・チャットを始めるときは、このファイルの内容をコピペするか
URL（https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/STATUS.md）
を貼るだけで、これまでの経緯を再説明せずに済みます。

---

## システム概要

- リポジトリ: infoyuusuke-afk/trade-cockpit（GitHub Pages: https://infoyuusuke-afk.github.io/trade-cockpit/）
- 構成: GitHub Actionsで自動実行するPythonパイプライン → JSONデータ生成 → 静的ダッシュボード(index.html)
- 対象銘柄: キオクシアホールディングス(285A)中心＋MS2 RSSで監視する100銘柄
- 証券会社: 楽天証券 マーケットスピード2 RSS

## 目指しているゴール

デイトレ（今日）／スイング（1週間）／長期（1か月）の3階層で、
仕手筋・機関・大口の初動の"足跡"を検知して勝てるシステムを構築する。
3階層は優先順位をつけず並行して育てる方針。

## 現状の3階層の実装状況

| 階層 | 状態 | 詳細 |
|---|---|---|
| デイトレ | 稼働中（要改善） | 100銘柄スキャン、LONGブレイクアウトのみ実弾化。SHORT検知ロジックはあるが未接続（下記参照） |
| スイング(1週間) | MVP稼働開始 | swing_signal.py新規作成、investor_regime.json＋credit_supply.jsonで判定 |
| 長期(1か月) | MVP稼働開始 | long_signal.py新規作成、信用残高4週トレンド＋自社株買い＋セクター相関で判定 |

## 判明した重要な問題点（2026-09-14診断）

1. **デイトレのscoreが機能していない**：paper_trade_history.json（169件）を集計した結果、
   scoreは発動率・勝敗とほとんど相関なし。全体成績は勝率39.5%・平均R+0.03・PF1.17（n=43でまだ弱い）。
2. **SHORTが検知されているのに一度も実弾化されていない**：signal_scan.pyのanalyse_short()は
   SHORTセットアップを実際に検知している（直近80コミットで確認）が、実際に紙トレードを生成する
   update.pyのbuild_day_ifo_candidates()はLONGブレイクアウト専用の別ロジックでSHORT分岐が存在しない。
3. 診断に必要な生データ（rvol/ret20/atr_pct/swing_score等）がpaper_trade_history.jsonに
   残っていなかったため、morning_review.pyをパッチして今後の記録に含めるよう修正済み。

## 直近で完了した作業

- [x] リポジトリ構造の調査、既存ロジックの棚卸し
- [x] paper_trade_history.jsonの統計診断
- [x] SHORT未接続問題の原因特定
- [x] morning_review.pyパッチ（診断用の生データを記録に残す）
- [x] scripts/tag_horizons.py, swing_signal.py, long_signal.py 新規作成（実データで動作検証済み）
- [x] .github/workflows/swing-long-signals.yml 追加（平日15:40 JST自動実行）

## 追加実装（2026-09-14 第2弾）

- **SHORT実弾化を完了**：scripts/short_candidates.py（MVP・下降配列＋出来高＋信用需給で判定、最大5件）を新規作成し、
  scripts/morning_review.py にload_short_candidates()を追加して朝スナップショットにLONGと一緒に混在させるよう修正。
  audit_one()は元々side分岐に対応済みだったため、SHORTのみのバグだった（正確な原因）。
  実データで動作確認済み：LONG1件+SHORT3件が同じスナップショットに混在することを検証済み。
  statistics()もLONG/SHORTを合算せず側別に独立集計するよう変更。
- **信頼度ゲート**：scripts/reliability_report.py新規作成。resolved_n（発動して勝敗確定した件数）が
  30件未満の区分は勝率・PFを「試運転・検証中」として扱い、以降も95%信頼区間を併記する設計。
  現状：LONG resolved_n=43（勝率39.5%、95%CI 26.4-54.4%、まだ結論を出せる精度ではない）、SHORT resolved_n=0。
- **Jumping Point!! 株Tube連携の第一段階**：scripts/mention_tracker.py新規作成。
  チャンネルID UCgDa6dxD3jPElw6eCvL1T2g（毎週日曜20時更新、翌週注目銘柄ランキング形式）の
  YouTube公式RSS（認証不要）を定期ポーリングし、published_atとdetected_atの両方を記録することで
  未来情報の混入を防ぐ設計。タイトル/説明欄からの銘柄コード自動抽出は正規表現によるベストエフォートで、
  confirmed_tickersへの手動確認を前提とする（自動抽出をそのまま分析に使わないこと）。
- **監視TOP5の第1段階**：scripts/watch_top5.py新規作成。前日引け後時点の情報のみでTOP5を確定し、
  decision_asofを記録。株Tubeの紹介有無はスコアに一切使わず、後段の的中率検証用の参考フラグとしてのみ保持。
- ワークフロー変更：.github/workflows/update.ymlに short_candidates.py と reliability_report.py の
  実行ステップを追加（update.pyの直後、morning_review.pyの直前）。swing-long-signals.ymlにwatch_top5.pyを追加。
  新規 .github/workflows/mention-tracker.yml を追加（日曜18-22時は15分おき、平日は07:50に1回）。

## SNS/メディア全般の話題化銘柄監視（2026-09-14 第3弾・方針転換）

Jumping Point!! は一例に過ぎず、それに固執しない方針に変更。狙いは
「SNS・多メディア全般で仕手化・拡散されそうな銘柄」を横断監視し、
"次のキオクシア"を早期発見すること。

- **mention_tracker.pyを複数チャンネル対応に一般化**：WATCHED_CHANNELSリストに
  チャンネルを追加していく方式に変更（Jumping Pointはその1つ）。
- **board_buzz_ranking.py新規作成**：Yahoo!ファイナンスが公式に毎日発表している
  「掲示板投稿数ランキング」（全市場、認証不要、
  https://finance.yahoo.co.jp/stocks/ranking/bbs?market=all ）を取得。
  特定の配信者に依存しない、最も入手性の良い汎用SNS注目度シグナル。
  新規ランクイン・順位急上昇を観測用フラグとして記録（売買判断には使わない）。
  .github/workflows/board-buzz.yml で平日07:00 JSTに自動実行。
- **正直な制約**：board_buzz_ranking.pyの正規表現パーサーは実際のYahoo側HTML構造を
  完全な形では検証できておらず（開発環境からアクセス不可のため）、
  mention_tracker.pyのRSS方式より壊れやすい。導入後は必ず最初の数回、
  Actionsのログとboard_buzz_history.jsonの中身を目視確認すること。
  抽出0件が続く場合はHTML構造変更を疑う。

## デプロイ状況（2026-09-14 全て本番反映・稼働確認済み）

STATUS.md含む全14ファイルをGitHub Web UIから手動アップロードし、各ワークフローを手動実行して
以下を確認済み：
- signals_day.json / signals_swing.json / signals_long.json / watch_top5.json（スイング&ロング系）
- mentions.json（180件、12チャンネル分のRSS取得成功。Jumping Pointの本日9/14公開分も検知済み）
- board_buzz_history.json（Yahoo!ファイナンス掲示板投稿数ランキング、285Aが1位で取得成功）
- day_ifo_candidates_short.json / reliability_report.json（LONG/SHORT混在の朝スナップショット）

デプロイ中に見つけたバグ2件を修正済み：
1. swing-long-signals.yml / mention-tracker.yml / board-buzz.yml の3ワークフローで、
   `git diff --quiet`が新規ファイル（リポジトリに一度も存在しないファイル）を検知できず、
   コミット処理がスキップされていた。`git add`してから`git diff --cached --quiet`で判定する方式に修正。
2. board_buzz_ranking.pyの初版は正規表現でHTMLをパースする方式だったが、実際のYahoo側HTML構造と
   合わず0件抽出だった。pandas.read_html()で`<table>`要素を直接読む方式に変更し、対応する
   `pip install pandas lxml`ステップもboard-buzz.ymlに追加して解決。

## 現在の未決事項・注意点

- **Stage①（紹介前検出率）の検証は遡って行えない**：過去の株Tube公開時刻を正確に記録したログが
  今まで存在しないため、「紹介前に検出できていたか」を過去に遡って判定すると必然的に後知恵になる。
  ユーザー自身が要求した「後知恵・未来データ混入の回避」を守るには、mentions.json蓄積開始日（今日）
  以降のデータでのみプロスペクティブに検証するのが正しい。数週間〜十数週（日曜が来る回数分）は
  「検証中・データ収集中」であり、それ以前に成績を語ることはできない。
- **Stage②（売買ルールの実利益検証）のバックテスト基盤は未着手**：GU/GD・OR5・VWAP・出来高・流動性を
  使った約定可能価格ベースの検証エンジン（手数料・スリッページ込み、LONG/SHORT別のR・PF・最大DD集計）は
  まだ設計・実装していない。これは次の優先着手事項。
- OR15 vs OR5（レンジ幅・天井底の判断基準）の使い分け → 「OR5=早期ウォッチ、OR15=正式トリガー」の
  2段構え案は出したが、実データでの検証はまだ

## 役割分担

- **Claude/Claude Code**: リポジトリの実コーディング・デバッグ・診断・バックテスト等の長時間作業
- **ChatGPT**: 相場観・戦略の壁打ち、マクロ（金利・FOMC等）の定性的な状況整理、意思決定の相談相手
- **Genspark**: 現在未課金。複数ソースのリサーチエージェントや監視ダッシュボードが必要になった時点で検討

## Kioxiaデイトレ（TradingView・45秒足）戦略の要点

- REBOUND LONG条件: OR15安値維持→VWAP奪還→EMA上向き→出来高増加→日経/半導体指数も上向き→
  板・歩み値が買い優勢、全部揃ってからのみエントリー
- REBOUND破棄→TREND SHORT: OR15安値割れ＋VWAP下＋EMA下向き＋出来高増加＋半導体全体が再び弱い場合
- 損切り: REBOUNDはVWAP再割れ or 反発起点安値割れ／SHORTはVWAP明確奪還・定着
- 利確: LONGはOR15高値/直近戻り高値でまず利確、出来高伴う突破のみ伸ばす／SHORTは直近安値で一部利確
- 持ち越し原則なし（米金利・FOMC意識のため）
