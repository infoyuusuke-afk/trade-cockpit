# trade-cockpit STATUS

最終更新: 2026-09-23（GitHub mainを開発・進捗共有の唯一の正本として同期）
役割分担（現行）：GPT/Codex側＝主開発・実装・検証・GitHub連携／Cloud側＝レビュー・診断・補助実装。役割は固定せず、GitHub mainの最新状態を基準に引き継ぐ。
運用体制: GitHub main＝コードと進捗共有の唯一の正本。新しいセッションは必ずmainのSTATUS.mdと関連Issue/PRを確認してから作業し、古いチャット内の役割分担や進捗を正本として扱わない。
同期ルール: GPT/Codex側・Cloud側のどちらで作業しても、共有すべき完了事項・未解決事項・Owner判断待ちはSTATUS.mdまたは関連Issue/PRへ反映する。main未反映の作業は「共有済み」と扱わない。

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
| デイトレ | 稼働中（要改善） | 100銘柄スキャンはLONGブレイクアウトのみ。SHORTはKioxia含む一部銘柄でMVP実弾化完了（scripts/short_candidates.py、LONGとは独立集計） |
| スイング(1週間) | MVP稼働開始 | swing_signal.py新規作成、investor_regime.json＋credit_supply.jsonで判定 |
| 長期(1か月) | MVP稼働開始 | long_signal.py新規作成、信用残高4週トレンド＋自社株買い＋セクター相関で判定 |

> **2026-09-25 整理**：2026-09-14〜09-17分の実装ログ（診断〜Execution Stack Phase 6まで）は
> 容量確保のため [STATUS_ARCHIVE_2026-09-14_to_09-17.md](STATUS_ARCHIVE_2026-09-14_to_09-17.md) へ移動した。
> 内容は削除しておらず、全文をそのまま転記している。以下は2026-09-18以降の実装ログ。


## リアルタイムTOP5チャートをTradingView Lightweight Chartsへ移行（2026-09-18）

手描きSVGだったフォーカスダッシュボードのローソク足チャート（`#focus-chart`）を、
TradingView社のオープンソースChartingライブラリ「Lightweight Charts」（Apache 2.0、
CDN: jsdelivr、v5.2.1）へ置き換えた。TradingView Advanced Charts（無料版）は
「公開リポジトリでの利用禁止」規約があり本リポジトリの構成（公開GitHub Pages）に
使えないことを確認済みのため、再配布制限のないLightweight Chartsを採用。

- `LightweightCharts.createChart()` + `addSeries(CandlestickSeries)` + `setData()`で描画。
- 発動/押し目/撤退/利確1/利確2の5本の水平線は`createPriceLine()`で描画。
  Lightweight Chartsの価格ラインはデフォルトでは自動スケールに影響しないことを
  ローカルCDN実機テストで確認済み（遠い利確ラインで軸が潰れる旧SVGの不具合を回避）。
  `series.applyOptions({autoscaleInfoProvider})`で発動/撤退ラインを含む可視レンジを
  明示指定し、利確ラインのみ除外する形で旧ロジックの意図を再現。
  可視レンジ外の利確ラインは▲/▼バッジ（HTML要素）で代替表示。
- `daily_snapshot()`の日足チャート配列（40本）に`"t":"YYYY-MM-DD"`を新規追加
  （従来は日付フィールドなし）。`live_focus.py`の5分足`"t":"HH:MM"`と合わせて、
  クライアント側`toSeriesData()`/`barTime()`で両形式をLightweight Chartsの時刻値へ変換。
  `"t"`が無い旧データ（次回パイプライン実行まで残る埋め込みJSON）は連番の日付へ
  フォールバック合成し、空白チャートにならないようにした。
- ローカル`.claude/static-server.ps1`＋Claude Browserでの実機確認：CDN読み込み、
  ローソク足描画、5分/15分切替、チャートデータなし時のフォールバック表示、
  実際にコミット済みのindex.html（"t"無し旧データ）での表示、いずれも
  コンソールエラーなし。commit 312dbc9をmainへpush後、GitHub Actions
  「Update Trade Cockpit」run 35287572037がGreenで完走し、実データ再生成後の
  index.htmlに`"t"`フィールドとLightweight Charts読み込みが反映されたことを確認。

キオクシア専用チャート（`kioOneMinuteChart`）は本セッション後半で別途移行（下記参照）。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## キオクシア専用チャートもTradingView Lightweight Chartsへ移行（2026-09-18）

上記フォーカスダッシュボードに続き、キオクシア専用の大判チャート（`#kio-best-path`、
`kioOneMinuteChart`）もLightweight Chartsへ移行した。ユーザー指示「キオクシア専用もお願い」に
対応。こちらは予測経路＋実測1分足＋EMA20＋VWAP＋ピボット/OR15参照線＋転換点・売買サインの
マーカーを、すべて％リターン軸・昼休み圧縮済みの独自セッション分足インデックス上に重ねる
複合チャートで、フォーカスダッシュボードより設計が複雑。

- `series.priceFormat={type:"percent"}`で既存の％リターン軸表現を維持。
- 独自の「セッション分インデックス」（0-150=9:00-11:30、151-331=12:30-15:30、昼休みを
  詰めて表示）はそのまま時刻値として使用し、`timeScale.tickMarkFormatter`でHH:MM表示へ
  変換する形でLightweight Chartsに移植（実時刻タイムスタンプを使うと昼休み分の空白が
  出てしまうため、旧SVGと同じ「詰めた」見た目を維持する必要があった）。
- ローソク足/予測線/EMA20/VWAPは`CandlestickSeries`/`LineSeries`、ピボット・OR15ラインは
  `createPriceLine()`。転換点・売買サインのマーカーはLightweight Charts v5の新API
  `LightweightCharts.createSeriesMarkers()`（v5で`series.setMarkers()`から置き換え）を
  ローカルCDN実機テストで確認した上で採用。
- 旧「実績ここまで」の縦線はv5に直接の代替がないため、最終実測足の位置に打つマーカーへ
  簡略化した。
- 類似日一覧（`kio-match`/`kioxia-calendar-grid`）内のミニプレビューSVG（`miniPath`）は
  小さな一覧表示のみのため対象外（フルインタラクティブ化は過剰と判断）。

ローカル`.claude/static-server.ps1`＋Claude Browserで合成データによる実機確認
（ローソク足・予測線・EMA/VWAP・ピボットライン・転換点/売買サインマーカー、いずれも
ズームして視認）と、実際にコミット済みのindex.htmlの実データでの表示確認
（予測経路は描画、実測1分足は未検証のため重畳なし＝既存仕様通り）を実施、コンソール
エラーなし。commit 23c5f63をmainへpush後、GitHub Actions run 35288740866がGreenで完走し、
実データ再生成後のindex.htmlに新コードが反映されたことを確認。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## Lightweight Charts移行後のタイムフレーム/タブ切替バグを2件修正（2026-09-18）

ユーザー報告「チャートの描写の時間軸がおかしいへんにずれる」を受けて調査・修正。

**バグ1：フォーカスダッシュボードのタイムフレーム切替（5分/15分）でチャートが右に
片寄る**。原因：Lightweight Chartsは`setData()`のたびに表示範囲を自動フィットしない
（データが空→非空へ遷移する最初の1回のみ）。同一チャートインスタンスを使い回して
タイムフレーム/銘柄を切り替えると、本数が変わっても表示範囲（ズーム状態）が
そのまま残り、少ない本数のデータが古い広い範囲の中で片寄って表示されていた。
修正：`setData()`直後に`chart.timeScale().fitContent()`を追加（フォーカス・
キオクシア両チャート、update.py/index.html）。

**バグ2（ユーザー指示「他のタイムフレームも全部確認して」で発見）：キオクシア
チャートは上記修正後も、初回表示時（非表示タブ内）に不整合が残ったまま**。
原因：`kioOneMinuteChart()`はページ読み込み時に自動実行されるが、キオクシアタブは
既定で非表示（`display:none`）のため、その時点でのコンテナ幅は0。
`chart.timeScale().getVisibleLogicalRange()`で実測すると`{from:-1076, to:331}`
（本来`{from:0, to:331}`のはずが約1400ロジカル単位分の空白を含む異常値）。
タブを開いた後にLightweight Chartsのautosizeがcanvasを実サイズへリサイズしても、
以前の（幅0時点で計算された）bar spacingを維持したまま表示範囲だけ引き伸ばされる
ため、直らない。修正：タブ切替ハンドラ（`scripts/weekly_tabs.py`の`tabs_block()`と
index.htmlのミラー）で、キオクシアタブがアクティブになった際に
`kioChart.timeScale().fitContent()`を呼ぶよう追加。`kioChart`は元々
別クロージャ内の`let`変数でタブ切替スクリプトから見えないため`window.kioChart`
として公開。さらに、クリック直後の即時呼び出しでは新しいcanvasサイズへの
autosize反映（ResizeObserverによる非同期処理）と競合して直らないことを確認した
ため、`requestAnimationFrame`を二重にネストして遅延実行するよう修正。

ローカル実機（ピクセルスキャンによる描画範囲測定＋`getVisibleLogicalRange()`直接
確認）で両方の修正を検証。フォーカスダッシュボード側は5分/15分×全5銘柄の組合せ、
および合成データによるライブ更新（日足→ザラバ5分足への差し替え）でも回帰なしを
確認。commit 33cb89bをmainへpush後、GitHub Actions run 35293377145がGreenで
完走し、実データでの最終確認も完了。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## リアルタイムTOP5の変動率がライブ中に壊れるバグを修正（2026-09-18）

ユーザー報告「リアルタイムTOP５の変動率もおかしい、株価がリアルタイムにとれないから」。

原因：ピック一覧の変動率バッジ（`pickHtml()`）は`x.chart`の末尾2本
（`bars[-1].c`と`bars[-2].c`）の差分で計算していた。既定状態（非ライブ）では
`x.chart`は日足40本なので`bars[-2]`が実質前日終値となり偶然動いていたが、
ザラバ中に`liveFocusUpdate`が`x.chart`をlive_focus.pyの5分足イントラデイ配列へ
差し替えると、`bars[-2]`は「5分前の足」になり、価格はライブ更新されるのに
変動率だけ数分単位の微小な値（例：+0.02%等）へ壊れていた。

修正：`daily_snapshot()`が既に計算している安定した`prev_close`/`change_pct`を
`build_precision_top5()`→`render_focus_dashboard()`経由でフロントへ渡し、
`pickHtml()`側は`(price - x.prev_close) / x.prev_close * 100`で計算するよう変更。
`x.prev_close`は`liveFocusUpdate`のspreadで上書きされないため、ライブ中も
正しい前日比を維持したまま最新株価に追従する。

ローカルで`render_focus_dashboard()`合成データ検証：prev_close=1000／
chart_last_close=1024で"+2.40%"、その後liveFocusUpdate相当のイベントで
price=1040へ更新すると"+4.00%"に正しく再計算されることを確認
（旧ロジックでは約+0.1%という誤った値になるところ）。commit b746f53を
mainへpush後、GitHub Actionsも正常稼働、実データでの表示も確認済み。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## チャート自動スクロール機能を追加（2026-09-18）

ユーザー要望「自動で時間軸スクロール」（ザラバ中に新しい足が増えるたびに、
最新足が見える位置へ自動で追従してほしい）に対応。

`chart(x)`（フォーカス）・`kioOneMinuteChart()`（キオクシア）の両方に
`isRefresh`フラグを追加：
- 初回表示・銘柄クリック・タイムフレームクリック時（`isRefresh`未指定）は
  従来通り`fitContent()`で全体表示。
- `liveFocusUpdate`によるライブ更新時（`isRefresh=true`）は「追従」動作に切替。

フォーカスチャートは全系列が同一の実時間軸を共有するため
`chart.timeScale().scrollToRealTime()`を使用（ズーム状態を保ったまま
最新足へパンする、`fitContent()`のようにズームをリセットしない）。

キオクシアチャートは予測線が常に09:00〜15:30の全区間（index 0〜331）を
持つため、`scrollToRealTime()`では「全系列中の最新データ点」が常に予測線の
終端（15:30）になってしまい狙った動作にならない。そのため、直近の実測足
（`lastActualIndex`）を中心に`from: lastActualIndex-40, to: lastActualIndex+10`
の可視範囲を明示的に設定する方式にした。

ローカル実機で検証：フォーカスチャートは合成ライブ更新後も全幅描画・
タイムフレーム切替も回帰なしを確認。キオクシアチャートは`window.kioChart`
経由で`getVisibleLogicalRange()`を直接読み取り、合成実測データ（末尾index=85）
での更新後に`{from:45, to:95}`（85-40〜85+10）へ正しく変化することを確認。
非リフレッシュ呼び出しでは従来通り`{from:0, to:331}`の全体表示のまま。
commit 933248dをmainへpush後、GitHub Actionsも正常稼働を確認済み。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## 自動スクロール導入後のラベル重なりを修正（2026-09-18）

ユーザー指摘「利確発動押し目などの文字に被らないように自動スクロールを全部確認して調整して」。

原因（バックグラウンド調査＋実機ピクセル計測で確認）：`createPriceLine()`に
`title`を渡すと、そのテキストは価格軸バッジには付かず、**ペイン内部の右端に
固定表示される別バッジ**として描画される（ズーム・パン位置に関係なく常に
右端）。自動スクロール導入前は`fitContent()`で常に全データ表示していたため
最新足とこの右端バッジの間に余白があったが、`scrollToRealTime()`／
ウィンドウ指定の可視範囲に変えたことで最新足が右端近くに来るようになり、
バッジと重なるようになった。v5には「軸バッジだけ残してペイン内バッジだけ
消す」オプションは存在しない（`axisLabelVisible:false`は両方消してしまう）ため、
`title`を使わず自前でラベルを描画する方式に変更。

`createPriceLine()`からは`title`を外し（`axisLabelVisible:true`の軸バッジは
そのまま維持）、`series.priceToCoordinate(price)`でY座標を取得して、
チャート左端に絶対配置するDOM要素（新規`.lwc-line-labels`/`.lwc-line-label`）
として描画するよう変更（セッション前半の旧SVG版と同じ左側配置に回帰）。
フォーカスチャート・キオクシアチャート両方に適用。あわせてフォーカスチャートに
`timeScale.rightOffset:8`、キオクシアのライブ更新時の可視範囲右マージンを
+10→+18本に拡大（保険的な追加余白）。

ローカル実機で、現在値に近いtrigger/stop/target値を持つ単体チャートページを
生成し、ライブ更新イベントを発火させてラベル位置を検証：`priceToCoordinate()`
の読み取り値とスクリーンショットの両方で、ラベルが左側、ローソク足が右側に
分離し重なりがないことを確認。実データでも確認済み。調査の過程で見つかった
「Uncaught Error: Value is null」というコンソールエラーは、3本足だけの最小
再現ページでも発生する既存のLightweight Charts内部の挙動（今回の変更とは
無関係、表示には影響なし）と切り分け済み。commit 519b5eeをmainへpush後、
GitHub Actionsも正常稼働を確認済み。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## Quick Trade Viewドロワーのチャートも統一（2026-09-18）

ユーザー指示「他の足も同じに統一してね」。フォーカスダッシュボード・
キオクシアに続き、最後に残っていた手描きSVGチャート（`render_trade_drawer()`の
`chartSvg()`）もLightweight Chartsへ移行。このドロワーは全タブの表・銘柄行から
「▥ チャート」ボタンで開ける共通コンポーネントのため、影響範囲は全タブ。

- フォーカスチャートと同じ`createChart()`＋`CandlestickSeries`方式。
  発動/押し目/撤退の3本（元のSVGもこの3本のみ描画、利確1/2は元々サイド
  パネルのテキストのみでチャート上には未描画——その仕様のまま維持）は
  `title`を使わず、`priceToCoordinate()`で自前の左側DOMラベルを描画
  （直前の重なり修正と同じ`lwc-line-labels`パターンを再利用、新しい
  チャートに同じ不具合を持ち込まないため）。
- 旧コードは軸レンジ計算に`levels.target1`を含めていた（表示されない
  利確1のせいで軸が不必要に伸びる、フォーカスチャートで直したのと
  同種のバグ）ため、新実装では発動/撤退のみを軸レンジに使用。
- `#trade-drawer`はCSSの`transform`で画面外へ隠すだけ（`display:none`では
  ない）ため、キオクシアで踏んだ「非表示タブ内で幅0のまま初期化される」
  問題は発生しない（theme.cssの該当ルールを確認した上で判断、追加の
  タブ切替フック等は不要）。

ローカル実機で複数銘柄の「▥ チャート」ボタンを開き、ラベルが左側に正しい
値で表示されること、銘柄切り替えでチャートが正しく再描画されることを確認。
実データでも確認済み。commit 7d243d9をmainへpush後、GitHub Actionsも
正常稼働を確認済み。

trigger/stop/target1/target2の自動算出ロジック（公式シグナルがない銘柄向け
のフォールバック計算）はコード変更なし。発注・シグナル生成・執行系
（RssOrder、broker submit等）には一切触れていない。

## リアルタイムTOP5カードの幅ズレを修正（2026-09-18）

ユーザー報告「幅が今まで揃っていたのにずれたのなおして」（スクリーンショット添付）。
NEXT THEME RADAR等の他カードと比べ、リアルタイムTOP5カードだけ幅が狭く中央寄りに
表示されていた。

原因：`.focus-dashboard{max-width:1480px;margin:0 auto;...}`が以前から存在していた
（今回のチャート作業とは無関係の既存コード）。このセクションは`.tab-pane.active`
（2カラムCSS Grid）内で`grid-column:1/-1`を持つグリッドアイテムだが、**インライン軸の
マージンが`auto`だとCSS Gridの既定のstretch配置が無効になり、代わりにコンテンツの
minmax()下限に基づくshrink-to-fitサイズになる**という仕様がある。実機で`max-width`
だけ外しても幅は変わらず、`margin:0`（autoを外す）だけで即座に約1109px→1416px
（他カードと同じ幅）に広がることを確認して特定した。`max-width:1480px`自体は
1416pxより大きく元々効いていなかったため、`margin:0`のみに変更（`max-width`は
超ワイド画面向けの保険として維持）。

キャッシュなしの新規読み込みで、`.focus-dashboard`と`#next-theme-radar`の幅
（1416px）・左端位置（84.5px）が一致すること、フォーカスチャートのcanvasが新しい
幅へ正しく追従することを確認済み。commit b526abeをmainへpush後、GitHub Actionsも
正常稼働を確認済み。

発注・シグナル生成・執行系（RssOrder、broker submit等）には一切触れていない。

## 現在の未決事項・注意点

- **Stage①（紹介前検出率）の検証は遡って行えない**：過去の株Tube公開時刻を正確に記録したログが
  今まで存在しないため、「紹介前に検出できていたか」を過去に遡って判定すると必然的に後知恵になる。
  ユーザー自身が要求した「後知恵・未来データ混入の回避」を守るには、mentions.json蓄積開始日（今日）
  以降のデータでのみプロスペクティブに検証するのが正しい。数週間〜十数週（日曜が来る回数分）は
  「検証中・データ収集中」であり、それ以前に成績を語ることはできない。
- **Stage②はキオクシア1銘柄・25日分の第一弾比較のみ完了**：上記の比較結果を参照。
  100銘柄ユニバースへの拡張、SHORT側の実売可能性データ、ティック精度への改善が残タスク。
- OR15 vs OR5（レンジ幅・天井底の判断基準）の使い分け → 上記Stage②比較でAが最良という
  結果が出たが、n=13でまだ結論を出せる段階ではない
- **A530（RssTickList数式）が再起動後に空になる現象の根本原因が未特定**：上記10本板セクション参照。
  回避策（手動再設定）はあるが恒久対応ではない
- 建玉・含み損益・注文状況・信用余力・保証金率・自動発注（RssOrder）は引き続き未実装
  （RssOrderはCLAUDE.mdの方針により自動発注には接続しない）

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

## TradingView Pine Script移植（2026-09-18）

ユーザー依頼「今、構築しようとしている売買条件をトレーディングヴューチャートでつかえる
パインスプリクトつくって」を受け、リポジトリ内に既にドキュメント化されている2つの
売買条件をPine Script v5へ移植し、`pinescript/`ディレクトリに追加した。どちらも
TradingViewのストラテジーテスター上でのバックテスト・チャート表示・
`alertcondition()`による人間への通知のみを行い、ブローカー自動発注・Webhook執行は
一切実装していない（CLAUDE.mdの「モデル予測を自動売買注文に直結させない」方針と同じ）。

- **[pinescript/kioxia_rebound_trend.pine](pinescript/kioxia_rebound_trend.pine)**：
  本ファイル直上の「Kioxiaデイトレ（TradingView・45秒足）戦略の要点」（REBOUND LONG /
  TREND SHORT）をそのまま移植したもの。OR15・VWAP（`ta.vwap`）・EMA方向・出来高増加・
  日経平均/半導体指数（`request.security`、シンボルは入力で変更可能）を自動判定し、
  「板・歩み値が買い優勢」だけはPine Scriptから気配値・歩み値を参照できないため
  自動判定せず、右上のチェックリスト表に手動確認項目として残している（満たしたことに
  して自動発注はしない）。損切り（VWAP再割れ/反発起点安値割れ、SHORTはVWAP奪還・定着）、
  利確（OR15高値/直近安値での一部利確）、持ち越し原則なし（時間指定で強制手仕舞い）も
  実装。**未解決の論点を明記**：2026-09-14付の実データ検証（C-002/C-003訂正後）では
  「VWAPを割らずに保持した押し目（entry<VWAP、押し目型）」が「VWAP奪還後の追随
  （entry≥VWAP、追随型）」よりR倍数・勝率で優位という結果が出ている一方、STATUS.md
  正式のREBOUND LONGルールは「VWAP奪還」を発動トリガーにしており定義上は追随型に
  なる。この矛盾はまだ結論が出ていないため、`entryMode`入力でどちらの発動方式も
  切り替えてバックテストできるようにした。
- **[pinescript/day_ifo_breakout.pine](pinescript/day_ifo_breakout.pine)**：参考として、
  サイト本体が毎朝8:55にMS2向けに計算しているIFO（`scripts/update.py`の
  `build_day_ifo_candidates()`：前日高値ブレイクのトリガー＋指値、ATRベース損切り、
  利確1(1.5R)/利確2(2.2R)）も同様にPine化した。ただしこちらは100銘柄横断スキャン
  （売買代金・セクターフェーズ・決算日除外・rotation_group等）を前提にしたロジックで、
  単一銘柄のPineチャートには持ち込めない条件（売買代金の銘柄横断比較、セクター
  フェーズ判定、決算日除外）は移植していない。価格帯・ATR%・MA20乖離率という
  単一銘柄で判定可能な代理フィルターのみ残し、それ以外は省略した旨をコード内コメントに
  明記している。

**正直な制約**：どちらもTradingView Pine Editorへの貼り付け・コンパイルは未実施
（このセッションにPine Editorへのアクセスがないため構文チェックは目視レビューのみ）。
エラーが出た場合はユーザーから内容を共有してもらい修正する前提。

発注・シグナル自動執行系には一切触れていない。

### 実機フィードバックを受けた修正（同日）

ユーザーが実際にTradingView（285A・45秒足）へ貼り付けたスクリーンショットを共有、
「REBOUND/SHORTのシグナルが連射されて実践では使えない」との指摘を受けた。原因は
2点：①`plotshape`/`alertcondition`が「条件が揃った瞬間すべて」に反応しており、
実際に約定した回数とチャート上の表示回数が一致していなかった、②45秒足では
VWAPクロス・EMAの1バー傾き・出来高スパイクがいずれもノイズが大きく、条件の
組み合わせが短時間に何度も偶然一致していた。

`pinescript/kioxia_rebound_trend.pine`を修正：
- クールダウン（既定40バー≒30分）を追加し、直近シグナルから一定バー数未満は
  新規エントリーを一切出さない
- チャート上の▲▼・アラートを「条件成立の瞬間」ではなく「実際にエントリーが
  約定した瞬間」のみに表示するよう変更（`onlyPlotRealEntries`で切替可）
- EMA方向判定を1バー前比較から`emaSlopeBars`（既定3）バー前比較に変更し、
  単発ノイズでの方向反転を抑制
- 日経平均・半導体指数の地合い判定を、チャートと同じ45秒足ではなく明示的に
  上位足（既定1分足、`idxTimeframe`で変更可）でリクエストするよう変更

**正直な制約**：この修正は「連射を抑える」対策であり、戦略そのものの収益性
（勝率・PF・ドローダウン）を検証したものではない。ユーザー側でStrategy
Testerのパフォーマンスサマリーを確認し、必要ならクールダウン秒数・EMA期間・
出来高倍率をさらに調整することを推奨する。またREBOUND LONG/TREND SHORTの
原本ルールはそもそも裁量トレード（板・歩み値等の目視情報込み）を前提にした
ものであり、45秒足という短い時間軸を機械的な条件一致だけで代替すると、
裁量トレーダーが目で弾いているノイズまで拾いやすい点は構造的な限界として
残る。

## MS2 RSSによるキオクシア生ティック永続化＋15秒足リサンプル（2026-09-19）

共有シートC-075（GPTからの回答）に基づく実装。GPTの方針は「過去データは
TradingView、将来データはMS2 RSSを第一候補とし、MS2側はRssTickListの300件
上書きリスク・重複排除・出来高定義・時刻精度を先に実機検証する」というもの。
このうちMS2側の収集基盤をCloud側で実装した。

**実装内容**：
- `ms2_live/Kioxia_RSS_Live_Watcher.ps1`の既存の2秒間隔監視ループ（`RssTickList`を
  毎ループ読んでいる既存コード、A531セル）に相乗りする形で`Write-TickLogDiff`関数を
  追加。300件のローリングウィンドウから、前回ポーリング以降の新規ティックだけを
  差分抽出して`kioxia_ticks_YYYYMMDD.csv`へ追記する（(時刻,価格,出来高)の組で識別、
  直近350件をメモリ保持してリスタート時の重複記録も防止）。
- 前回ポーリングのティックが今回のウィンドウに1件も残っていない場合を
  「300件が2秒間で丸ごと入れ替わった疑い」として`kioxia_tick_diag_YYYYMMDD.csv`へ
  診断ログを毎ループ記録（poll_time, window_size, overlap_with_prev, new_appended,
  suspected_gap）。GPTが要求した「欠損リスクの実機検証」を、ユーザーの手作業ではなく
  スクリプト自身が記録・提示する形にした。
- 新規`ms2_live/Resample_Kioxia_Ticks_15s.ps1`：蓄積した生ティックログをザラバ後に
  15秒足OHLCVへ集約するオフラインバッチ（`-Date`パラメータで日付指定、Watcherの
  監視ループとは独立して手動実行）。

**検証状況**：
- PowerShellの構文パーサー（`[System.Management.Automation.Language.Parser]::ParseFile`）
  で両ファイルの構文エラー無しを確認。新規ファイルはUTF-8 BOM無しだとWindows
  PowerShell 5.1が日本語コメントを誤ったコードページで読み文字化けし構文エラーに
  なることが分かったため、既存ファイル群と同じUTF-8 BOM付きで保存し直した
  （実機で踏むはずだった落とし穴を先に発見・修正できた）
- 合成データ（実市場データではない、ダミーの5ティック）でリサンプルの集計ロジックを
  テストし、バケット境界・OHLCV集計が意図通りであることを確認（`{0:D2}`書式が
  `[math]::Floor`のdouble型を受け付けずエラーになるバグも発見・`[int]`キャストで修正）
- **未検証（今日2026-09-19は土曜で東証休場のため実施不可）**：実際のMS2 RSS接続下で
  ①ティック差分抽出が正しく機能するか、②300件上書きが実際にどの程度の頻度で
  発生するか（`suspected_gap`列）、③RssTickListの時刻精度・出来高定義の実態。
  次の取引日（2026-09-21想定）にWatcherを起動した状態で実機確認が必要

**正直な制約**：CloudにはMS2/Excelへのライブ接続手段が無いため、上記の未検証項目は
次の取引日にユーザー自身がWatcherを起動して確認する必要がある。TradingView側の
Bar Replay＋CSVエクスポート範囲拡張の検証（GPTの回答に含まれる別項目）もユーザー
側での手動確認が前提で、Cloud側では実施できない。

発注・執行系には一切触れていない。MS2 RSSの生ティックデータは`ms2_live/*.csv`と
して`.gitignore`済みのローカル専用ファイルであり、公開リポジトリへは一切
アップロードしない。

## リアルタイムTOP5チャートの「5分/15分」誤表示を修正（2026-09-19）

ユーザーからマクニカHD（3132）のチャートスクリーンショットで「5分足表示のはずなのに
約1ヶ月分表示されている」との指摘を受けた。調査の結果、`aggregateBars(x.chart||[],
tfMultiplier)`が**日足配列**（`x.chart`）に対してn=1（5分ボタン）／n=3（15分ボタン）で
集約しているだけで、実際には日足そのもの・3日足に日足を束ねたものを「5分」「15分」と
誤表示していたことが判明した（キオクシア専用チャート以外の全銘柄が対象、根本原因は
一般銘柄には元々分足データを取得する仕組みが無かったこと）。

**修正内容**：
- `scripts/update.py`に`chart_bars_5m(ticker, days=2)`を新設。実際に画面に表示される
  「リアルタイムTOP5」の上位5銘柄**のみ**、Yahoo Financeから本物の5分足（直近2日分）を
  取得する。全70銘柄分を保持する版を最初に実装したところdata.jsonが1.7MB→12MB超に
  膨張したため、表示される5銘柄限定に絞った
- フロントエンドのタブ切替ロジックを刷新：`tfMultiplier`（数値）方式から`tf`
  （"5m"/"15m"/"1d"の文字列）方式へ変更。「5分」は本物の5分足、「15分」は5分足を3本
  集約（日足集約と違い数学的に正しい）、新設した「日足」タブは既存の日足配列をそのまま
  使用する
- `barTime()`/`toSeriesData()`を拡張し、"YYYY-MM-DD HH:MM"形式のタイムスタンプを
  Lightweight Charts用のUTCTimestampへ正しく変換できるようにした
- 同じバグの2箇所目を発見：`render_focus_dashboard()`がページ埋め込み用に独自の
  行データを再構築しており、そこで`chart_5m`のコピーが漏れていたため、バックエンド
  修正後もチャートが空のままだった。これも修正

**検証**：このセッションでユーザーがPython 3.11をインストールしたため、初めて
`python scripts/update.py`をローカルで実データに対して最初から最後まで実行できた。
data.jsonが約1.8MB（本番CI実行後は1.72MB）に収まること、ブラウザプレビューで
5分・15分・日足の3タブが実際に異なる本物のローソク足を表示すること、新規の
コンソールエラーが無いことを確認済み。GitHub Actionsでも正常稼働・data.json
1.72MB・chart_5mが表示5銘柄分のみであることを確認済み。

発注・シグナル生成には一切触れていない。表示専用の変更。

### 追記：時間軸が9時間ずれていたバグを修正（同日）

上記の対応直後、ユーザーからマクニカHDの5分足チャートのスクリーンショットで
「時間が日本時間じゃない」との指摘。実際の取引時間帯（12:30・15:00頃）のはずの
ローソク足が「03:30」「06:00」と表示されており、正確に9時間early（ずれ）に
なっていた。

**原因**：Lightweight Chartsは公式ドキュメント通り「タイムゾーン変換を一切せず、
渡したUTCTimestampのUTC表記をそのまま表示する」仕様。バー時刻は既にJST文字列
（例："2026-09-17 09:05"）なので、`Date.UTC(...)`へそのまま渡せば表示は
正しくなるはずだったが、実装では誤って`+dt[4]-9`と9時間分を余分に引いていた
（既存の"HH:MM"専用フォールバック分岐にも同じ誤りが元から存在していたが、
このチャートでは使われていなかったため今まで表面化していなかった）。

**修正**：両分岐から`-9`を削除。`toISOString()`で往復確認し、
"2026-09-17T09:05:00.000Z"のように意図通りJST時刻がそのままUTC表記として
出ることを確認した。mainへpush済み、GitHub Actions正常稼働確認済み。

発注・シグナル生成には一切触れていない。表示専用の修正。

## V6起動体系とC-076の統合方針が確定（共有シートC-088/C-089、2026-09-19）

V6（`C:\AI_Cockpit_OneClick_Starter`）を実機確認し、C-076（15秒足バックテスト用
ティック永続化）が含まれていないことをC-088として報告。GPT/Codex側の回答
（C-089）で以下が確定した：

- C-076は継続。`kioxia_time_stats`（時間帯別UNDER統計）とは目的が別物のため併存
- **Cloud側（Claude）はV6のKioxia_RSS_Live_Watcher.ps1へ直接マージしない**。分岐が
  大きく（365行差分）回帰リスクが高いため、統合はGPT/Codex側が担当し、統合先も
  Watcherではなく`MS2_RSS_100_Collector.ps1`側にする方針
- 3系統の役割を明文化：GitHub main＝唯一のコード正本、
  `C:\AI_Cockpit_OneClick_Starter`＝配備先（開発元にしない）、
  `C:\MS2_Live\...`＝旧系統（新規開発停止、順次廃止）
- 統合完了後、Cloud側へコードレビューと次回営業日の診断結果レビューを依頼予定

Claude側は現在待機。C-080/C-082の相関研究は従来通り独立継続してよいとのこと。

## SCALP 5・OVERNIGHT 5・EVENT 5を同一の銘柄カードUIへ統一（2026-09-19）

ユーザー依頼「EVENT 5とOVERNIGHT 5をSCALP 5と一緒の銘柄タブに変更して」に対応。

**実装**：`weekly_tabs.py`にSCALP 5のカードテンプレートを`window.renderScalpCard(x, sv, tf)`
として共通関数化（`<head>`スクリプトなので`update.py`の本文スクリプトより先に定義される）。
OVERNIGHT 5（`live_ms2.json`の`hold_top5`）とEVENT 5（`signals.json`の
`speculative_theme_watch`）双方からこの共通関数を呼び出すよう`update.py`を改修。

**データ有無の確認と対応**：OVERNIGHT 5はMS2 RSSライブデータ（VWAP・OR・EMA9/20等）を
持つが、EVENT 5は全市場走査専用でMS2ライブ項目を持たない。ユーザーにAskUserQuestionで
確認し「見た目だけ今すぐ合わせる」を選択。EVENT 5では該当項目は未確認時の既存表示に
合わせて「—」のまま表示し、推測で埋めない。

**検証**：構文チェック（`ast.parse`）、ローカルパイプライン実行、ブラウザでEVENT 5の
実データ表示確認、OVERNIGHT 5はテストデータ注入で表示確認。コミット`d913cc7`。

**別件で発覚したCI回帰の修正**：上記push直後、CIが
`PUBLICATION BLOCKED - index.html missing marker: Ver.5.2`で失敗しているのを発見。
`scripts/validate_output.py`が"Ver.5.2"固定文字列を検査していたが、Codex側の作業で
表示バージョンが"Ver.5.4"へ上がった際にこのチェックだけ取り残されていたのが原因
（直前のCodexコミットも同じ理由で失敗していたことを`gh run list`で確認、自分の変更
とは無関係の既存バグと判断）。固定文字列チェックを`re.search(r"Ver\.\d+\.\d+", html)`
という正規表現ベースの検査に置き換え、以後バージョン番号を上げるたびにこのファイルを
更新しなくて済むようにした。コミット`fb42093`→push後`9c45b18`。CI run `35438553538`で
green化を確認済み。

発注・執行系には一切触れていない。表示・検証スクリプトのみの修正。

発注・執行系には一切触れていない。

## Issue #171 (C-111) 自律実行キュー：P0-P4着手（2026-09-22）

`docs/AI_COCKPIT_MASTER_SPEC.md`（Draft PR #170）とIssue #171の指示に従い、
main SHA `1e856eeacdf71006fa095da27e1aa6e46862fb7b` を基準に自律実行を開始した。

**P0（オープンDraft PR監査）**：20件のオープンDraft PRを全件監査した（サブエージェントに
調査させた上で、結論に影響する主張はClaude本体が個別にgit/diffで裏取りした）。
サブエージェントの一次報告には2件の誤り（PR #168が既にmainへ直接マージ済みと誤認、
PR #155のCIが失敗中と誤認——実際は本リポジトリにこの2件を含めPR上でpytestを走らせる
GitHub Actionsワークフローが存在せず、両PRとも`get_check_runs`はcheck run 0件だった）
があり、`git merge-base --is-ancestor`と実ファイル比較で検出・訂正した。マージ・
クローズは一切行っていない。

| PR | タイトル | 現在mainへクリーンマージ可能か | 実質的にmain済みか | 推奨 |
|---|---|---|---|---|
| #170 | C-110 master spec | Yes（現行mainがbase） | No（新規docs） | keep-as-is（GPT/Owner確認待ち） |
| #168 | C-108 TSE session gap audit | Yes（本セッションでreconcile済み、`034c0cd`） | No（寄り付き空白分類は本セッションで追加するまで未実装） | **keep-as-is**（サブエージェントの「既にmain」判定は誤り、検証済み） |
| #166 | Fill Model calibration v2 | Yes（本セッションでreconcile済み、`ce01f2c`） | No | keep-as-is / GPT review待ち |
| #165 | Fill Model calibration v1 | Yes | No | **#166に厳密に上位互換されている**（diff確認済み）→close-as-obsolete相当 |
| #163/#161/#159/#157 | Shadow fill診断・数量保存テスト・fill-modelバージョン系譜・known-orderレジャー境界強化 | Yes（各々`git merge-tree`でコンフリクト0件を確認） | No | keep-as-is / rebase |
| #155 | C-107 private Shadow Forward path policy | Yes（本セッションでreconcile済み、`bf5f072`。加えてWindowsシミュレーション用テストがpathlib内部の`os.name`参照を壊す不具合を発見・修正、`7194ee7`） | No（mainは`shadow_forward_acceptance.py`内のinlineチェックのみ） | keep-as-is |
| #121/#119/#117/#116/#114/#113/#107 | Event/Entertainment時刻境界・コンテンツ境界・Owner承認 terminal/immutable 系の古いdraft群 | No（git merge-treeでコンフリクト確認済み） | **Yes、実質的に** — Owner承認系4件（#107→#113→#114→#117）はmainの`scripts/owner_approval_queue.py`（C-095, 実コミット`cfa825f`/#140統合）が同等以上の要件（terminal decision・重複ID拒否・aware timestamp・actor/time audit）を実装済みであることをdiff確認。Entertainment系2件（#116/#119）はmainの`scripts/public_event_sanitizer.py`+`entertainment_pipeline.py`（C-096, `7875017`/#144統合）が同等の機微データ境界を実装済み。#121もC-097（`cf9bc0d`/#145統合）で同種の時刻境界強化がmain済み | **close-as-obsolete相当**（Owner最終判断待ち、本セッションではクローズしない） |
| #71 | Claude handoff contract drift guard | Yes | No | keep-as-is / rebase |
| #25 | C-076グロース株OR15監視設計 | No（大幅に古いbase） | No | rebase推奨。**注意**：AI_SHARED_SHEET.mdの既存C-076（MS2ティック永続化）とC番号が衝突しており別件、Owner側で採番整理が必要 |
| #24 | C-075 VWAP根拠訂正 | No | 内容はSTATUS.mdの訂正記述と一致する可能性が高い（未確定、一意な内容が失われないか要確認） | close候補（要最終確認） |
| #20 | Phase 6状況表示・音声SBV2統一 | No（389コミット遅れ） | No | rebase必要（index.html等の自動更新で頻繁に競合） |
| #19 | SBV2音声ブリッジ・MS2自動起動統合 | Yes（コンフリクトなし） | No | keep-as-is / rebase。MS2自動起動スクリプトに触れるが発注・Scheduled Task登録コードは含まれないことをdiff確認 |

いずれのPRも本セッションではマージ・クローズしていない。「close-as-obsolete相当」と
記載した行はOwner/GPTの最終確認を推奨する。

**P1（Issue #169 TradingView証跡意味論）**：PR #168は`LUNCH_RECESS`/`CLOSING_AUCTION`の
中断のみ分類しており、Issue #169が実例として挙げる「寄り付き09:00:00 JSTから最初の
観測バーまでの空白」（2026-09-11 09:08:45初観測、09-17 09:02:30、09-18 09:03:00等）を
一切検査していないことをコード確認した。`scripts/tradingview_stitcher.py`に
opening-interval検査を追加し、`UNRESOLVED_NO_BAR_INTERVAL`（既定・データ消失とも
無取引とも断定しない）／`VERIFIED_ACQUISITION_GAP`（独立取得ソースが当該区間に
バーを持つ場合のみ）／`EXPECTED_SESSION_BREAK`の3分類をIssue #169の要求通り実装した。
`or_promotion_blocked_dates`フィールドで、寄り付き空白のある日付（検証済み・未解決
問わず）を下流のOR5/OR15昇格ロジックが機械的にブロックできるようにした。
OHLCVの合成・補間は一切行っていない（`synthesized_bars: False`を監査出力に追加）。
アドバーサリアルテスト11件追加、`tests/test_tradingview_stitcher.py`は19件全通過。
PR #168のブランチ（`fix/tradingview-tse-session-gap-audit`）へ現在mainをマージ
（クリーンマージ、コンフリクトなし）した上でpush済み（`034c0cd`）。Draftのまま維持。

**P2（Issue #57 TradingView 15秒足ハンドオフ）**：本セッションの実行環境から
`www.tradingview.com`（および他の一般外部サイト）への送信ネットワークがエージェント
プロキシの組織ポリシーにより拒否されること（`CONNECT tunnel failed, response 403`）を
実機確認した。したがって実際のTSE:285A 15秒足を取得する手段がこのセッションには
存在しない。**BLOCKED**として報告する（理由：本セッションはネットワーク的に
TradingViewへ到達できない）。代替タイムフレームへの差し替えやペイロードの捏造は
行っていない。ローカルWindows環境でのTradingView Replay手動取得が引き続き唯一の
経路である。

**P3（Shadow Forward非公開永続化）**：PR #155（`feat/c107-shadow-forward-private-path-policy`）
が既にappend-only・非公開ignoreルート限定・ランナー刻印時刻・バックフィルAPIなし・
finalized terminal・不整合時BLOCKという要件をほぼ満たす実装
（`shadow_forward_private_path.py`/`_private_commit.py`/`_persistence_pair.py`/
`_resume.py`/`_trusted_ingest.py`）を含んでいることを確認した。テスト実行中に
`test_shadow_forward_private_commit.py`の`test_unverified_windows_durability_never_publishes_final`
が、このLinux実行環境で`NotImplementedError: cannot instantiate 'WindowsPath' on your
system`により失敗することを発見した。原因は、テストが
`shadow_forward_private_commit.os.name`を直接mockしていたため、`os`モジュール自体の
属性がプロセス全体で書き換わり、pathlibの内部`os.name`参照まで巻き込んで
`Path()`構築が壊れていたこと（本番コードの不具合ではなくテストの分離不足）。
`_platform_name()`という間接関数を追加し、テスト側もそれをmockする方式に修正
（本番の実際の`os.name`参照は変更なし）。修正後、対象5ファイル計43件全通過、
mainマージ後のフルスイートも同じ（既存・無関係の）3件のimportエラーのみで
新規リグレッションなし。ブランチへpush済み（`7194ee7`→マージ`bf5f072`）。Draftのまま維持。

**P4（PR #166 Fill Model calibration）**：`feat/fill-model-calibration-contract-v2`は
現行main（`1e856ee`）へクリーンマージ可能であることを確認（コンフリクトなし）。
Fill Modelの挙動・パラメータ自動更新ロジックには一切触れていない
（`parameter_update_allowed`/`real_submit_allowed`は引き続き常時False）。
mainマージ後、テスト91件全通過。ブランチへpush済み（`ce01f2c`）。GPTレビュー待ちの
Draftのまま維持。

**安全境界**：本セッションの変更はすべてpure関数・テスト・非公開パス検証ロジックの
範囲に留まる。発注・ブローカー・RssOrder・Windows Scheduled Task・real_submitには
一切触れていない。非公開MS2/Excel/口座/建玉データは読み書きしていない。カノニカル
ハッシュ（Execution Contract等）は変更していない。PRのマージ・クローズは行っていない。

## Issue #171 (C-111) 続き：action_required原因特定とC-116修正PR #175（2026-09-22）

main SHA `40f15ad7a71444fda5d43fa911ac4e1930849d7b` を基準に、Issue #171の
2026-09-22T00:39 GPT検証コメントが指摘した「PR #168/#155/#166のMobile Control Tests
がaction_requiredで止まっている」件を調査した。

**根本原因（コード確認・実機ログ確認済み）**：`mobile-approval-feed.yml`は
`permissions: contents: write`かつ自己コミット→pushするステップを持つが、
`push:`トリガーに`branches:`指定がなかった。前回セッションが各Draft PRブランチへ
mainをマージした際、mainの変更が同ワークフローの監視パス（`signals.json`等）に
触れたため、**PRブランチ自身の上で**このワークフローが発火し、
`github-actions[bot]`名義で`Update mobile approval feed`コミットをそのPRブランチへ
push した。このbot起源のpushがPRの必須チェック（Mobile Control Tests）の
再実行をGitHub側で承認待ち扱いにし、`conclusion=action_required`・ジョブ0件のまま
凍結することを`actions_list`/`get_workflow_run`で確認した
（PR #168: run `35671493607`＝直前の検証済みgreenコミット`034c0cd`＋
`Update mobile approval feed`、PR #155: run `35671652081`＝`bf5f072`＋同上、
PR #166: run `35671559018`＝`ce01f2c`＋同上。いずれもjob 0件）。
`calibrate-ev.yml`・`ev-learning-loop.yml`も同型（書き込み権限＋自己push＋
branches未指定）で同じ潜在バグを持つことも確認した。

**対応**：3ワークフローすべてに`branches: [main]`を追加し、本リポジトリの
他ワークフロー（`earnings-calendar.yml`等）と同じ規約に揃えた。回帰防止テスト
`tests/test_autocommit_workflow_scope.py`を追加（修正前は3件とも検出して失敗、
修正後は通過することを確認済み）。フルスイート970件実行、既存・無関係の
インポートエラー3件（このサンドボックスに`pandas`/`lxml`が入っていないことによる
もの）のみで新規リグレッションなし。ブランチ
`fix/scope-autocommit-workflows-to-main`へpush、Draft PR #175としてOpen
（mainへは直接pushしていない）。

**未解決**：本PRはPR #168/#155/#166の既に凍結済みのヘッドを遡って直さない
（bot起源のコミットを取り消すforce-pushは行っていない）。凍結解除には
Owner/GPTがGitHub Actions UIで該当runを手動承認するか、PR #175マージ後に
改めてmainを各ブランチへ安全にマージし直す（今後は同じ形では再発しない）
必要がある。マージ・クローズは本セッションでも一切行っていない。

**安全境界**：発注・ブローカー・RssOrder・Windows Scheduled Task・real_submit・
Fill Model挙動・カノニカルハッシュには一切触れていない。非公開MS2/Excel/口座/
建玉データは読み書きしていない。

## Issue #173 (C-114) Semiconductor GU Continuation LIVE MVP R1（2026-09-22）

main SHA `b945f22212d0208230e8ab672d69be268e6db67d` を基準に、Issue #173（半導体GU
継続監視LIVE MVP、固定ユニバース285A/6857/8035/6146/6920）のR1として、既存の
OR5/OR15/VWAP/EMA/出来高/歩み値フィールドのみを消費する純粋関数の判定ロジックを
新規実装した：`scripts/semiconductor_gu_continuation.py`。

**実装範囲（意図的に最小化）**：
- 銘柄別アドバイザリー状態機械（PREOPEN_GU_WATCH/OR5_FORMING/
  GU_CONTINUATION_CANDIDATE/PULLBACK_RECLAIM_CANDIDATE/OR15_CONFIRMATION/
  GU_EXHAUSTION_WARNING/LONG_INVALIDATED/WAIT_DATA/UNKNOWN）。OHLCVは一切
  合成しない。既存収集器が計算済みのOR5/OR15/VWAP/EMA9/EMA20/出来高加速/
  歩み値バイアスのみを読む契約とし、値が`None`（未取得）の場合は「未確定」と
  明示し、ブレイクアウト等を推測しない。
- 鮮度失敗はfail closed：`updated_at`欠落・未来タイムスタンプ（`time_utils.
  assert_observed_by`で検出）・60秒超の陳腐化はいずれも`WAIT_DATA`または
  `UNKNOWN`へ倒し、`fail_closed=True`と理由を明示する。
- セクター横断幅（above_open/above_vwap/above_or5_high/invalidated/stale件数）
  は文脈情報としてのみ提供し、多数決で発注判断へ変換しない旨を`note`で明記。
- マクロ（Nikkei先物/SOX・Nasdaq/USDJPY/米金利/VIX）は渡された値のみ
  `AVAILABLE`として通過させ、未提供フィールドは値を捏造せず`UNKNOWN`のまま。
  Global Macro Supervisor（C-113, PR #181）が未マージのためデフォルトは
  全項目UNKNOWN。
- Issue #173への追加コメント（NO-PULLBACK→OVERNIGHT/SWING継続レーン）に対応し、
  `evaluate_no_pullback_lane()`でDAYTRADE/OVERNIGHT/SWINGを独立した状態として
  保持。ただしP5のEV/PF/DD・OOS検証データベースはまだ配線していないため、
  R1では原則として常に`INSUFFICIENT_SAMPLE`を返し、日中で`LONG_INVALIDATED`/
  `GU_EXHAUSTION_WARNING`に達した銘柄のみ`OVERNIGHT_BLOCK`/`SWING_BLOCK`とする。
  単一スナップショットからEVランキングを捏造することは意図的に避けた
  （`OVERNIGHT_CONTINUATION_CANDIDATE`/`SWING_CONTINUATION_CANDIDATE`は
  スキーマ上定義のみで、R1のロジックからは一度も出力されないことをテストで
  固定した）。
- ユニバースは`load_universe()`で設定ファイル差し替え可能。ただし設定ファイルが
  存在して壊れている場合は黙って直さずValueErrorで失敗する。

**未実装・意図的にスコープ外（次段R2の課題）**：
- 実際のMS2ライブJSON（`scripts/update.py`が生成するダッシュボード用フィールド、
  例: `x.or5_high`/`x.or_high`(=OR15)等）への配線・Owner向けHTMLパネル表示は
  未着手。本セッションのサンドボックスは実際のMS2ライブ収集器・本番JSON出力へ
  アクセスできないため、フィールド名の完全一致を実機検証できていない。次段は
  実機側で本契約とMS2ライブ出力の対応表を確認し、`build_panel()`の出力を
  既存ダッシュボードJSON/HTMLへ接続する作業。
- Issue追加コメントが要求するランキング入力（close location value、RVOL持続、
  セクター内リーダー/フォロワー関係、ATR比、20D高値からの距離等）を使った
  「provisional condition ranking」は未実装（EVデータベースが無い状態で
  ヒューリスティックスコアだけを提示すると誤認を招くため、R1では明示的に
  見送った）。

**テスト**：`tests/test_semiconductor_gu_continuation.py`を新規追加、33件。
Issue #173が要求する10種類の対抗テスト（新鮮な強いGU継続／VWAP・寄り付き
喪失後の警告・無効化／OR5未完成でブレイクアウト主張なし／OR15未完成で確定
主張なし／陳腐化データでWAIT_DATA／歩み値欠落を推測しない／混在幅で
MIXED／大半陳腐化でWAIT_DATA／同一入力で同一出力／未来タイムスタンプで
fail closed）をすべて含む。`python3 -m unittest tests.test_semiconductor_gu_
continuation -v`で33件全通過を確認済み。フルスイート
`python3 -m unittest discover -s tests -p "test_*.py"`は1006件中、既存・
無関係のimportエラー3件（このサンドボックスに`pandas`/`lxml`が未導入のため。
`test_investor_regime`/`test_market_ranking_watch`等、過去セッションから
継続する既知の環境差異）のみで新規リグレッションなし。

**ブランチ/PR**：`claude/admiring-noether-x1bhil`へ2ファイル追加をpush。
Draft PRを作成しGPTレビュー待ちとする（本文にexact SHA・ファイル一覧・
テスト結果を記載）。

**安全境界**：本変更は純粋関数とテストのみ。発注・ブローカー・RssOrder・
Windows Scheduled Task・real_submitには一切触れていない
（`research_only=True`/`auto_execute=False`を出力契約に固定）。非公開MS2/
Excel/口座/建玉/歩み値の実データは読み書きしていない（テストは全て合成
フィクスチャ）。カノニカルハッシュ・既存の正式BUY/SHORTシグナル定義は
変更していない。PRのマージ・クローズ・Issueへの新規コメントは行っていない。


## 2026-09-24 GPT/Cloud backlog consolidation

Canonical state is current `main`; older sections below/above are historical logs and may describe then-unmerged work.

- Progress handoff is unified on `STATUS.md`; the owner approval workflow is a non-blocking check rather than an Environment wait gate.
- Rescued and merged onto current main: C-195 international cockpit presentation contract, C-193 AI 100-share validation lane, C-191 behavior-coach primitives, C-189 KIOXIA DEX research collector, C-114 semiconductor GU continuation R1, C-112 AI Strategy LIVE Phase 2, C-113 Global Macro Supervisor, KIOXIA ADR/IR/SEC Breaking Radar, C-116 main-only auto-commit workflow scope, C-108 TSE-aware TradingView 15s gap audit, C-110 AI Cockpit master specification, Fill Model calibration evidence contract, Shadow safety fail-closed invariants, and C-107 private Shadow Forward persistence boundary.
- C-071 TradingView handoff schema/runtime drift guard and C-076 growth/theme OR15 forward-validation spec were rescued through PR #209.
- C-075 VWAP evidence wording was corrected on current main through PR #210: the historical classification is a proxy comparison and does not establish superiority/profitability of either entry mode.
- SBV2 voice/emotion documentation, local voice assets, workbook-readiness check, and validation scripts were rescued through PR #211 without replacing newer collector/startup scripts or auto-activating voice/trading execution.
- Stale/duplicate PRs were closed only after comparison with current main. Old generated approval data, stale `AI_SHARED_SHEET.md` / `STATUS.md` snapshots, old shared-script replacements, and the static 2026-09-17 Phase 6 status snapshot were not replayed.
- Safety remains fail-closed: no broker submit, RssOrder, real-submit activation, Scheduled Task activation, or private-data publication was enabled by this consolidation.


## 2026-09-24 GPT final-gate consolidation

Current repository-only backlog has been reduced to external/actual-machine acceptance gates.

- C-109 TradingView gap classification is merged through PR #213: expected TSE session breaks, unresolved no-bar intervals, and independently verified acquisition gaps remain distinct; no bars are synthesized.
- C-115 Local Market Data Gateway repository contract is merged through PR #214. The gateway normalizes already-observed local inputs, fails closed on stale/future data, preserves source disagreement, does not infer missing flow, rejects private/order fields, and fixes `real_submit_allowed=false`. Issue #174 remains open only for Windows/MS2/TradingView-local wiring and actual-machine acceptance.
- C-118 protected-main data-writer hardening is accepted. PR #215 added fail-closed regression coverage across self-committing workflows. Active ruleset `main-protection` targets `main`, requires PR/status gate, and grants bypass to DeployKey. A protected-main Build Mobile Approval Feed run completed successfully through the dedicated data-writer path. Issue #177 is closed.
- Issue #57 remains open by design: Replay 15-second evidence exists, but the required separate real Claude/MCP `TSE:285A` / `15S` / `Asia/Tokyo` handoff payload and sanitized intake receipt have not been evidenced. Do not substitute another timeframe or synthesize bars.
- Issue #17 remains open by design: code separates TSE `285A.T` from JNX reference handling and prevents JNX from driving TSE OR/VWAP/EMA signals, but the four-scenario Windows/MS2 acceptance matrix still requires actual-machine evidence.
- No remaining repository-only step authorizes broker submission, RssOrder, Scheduled Task/autostart activation, private-data publication, or LIVE promotion.
