# C-023 Actions実行検証記録

検証日: 2026-09-15 JST / 実施: Codex（ユーザーの明示的な実装・実行依頼）
対象: infoyuusuke-afk/trade-cockpit / main

## 結論
mainへworkflowを追加し、workflow_dispatchで3回実行。最終実行ではJPX HTTP取得、pandas.read_html、Playwrightフォールバック、再解析、JSON検査、生成物のmainへのpushまで成功をログで確認した。今回は公式の「翌営業日の開示予定会社はございません」を確認した0件結果。銘柄がある日の取得・モメンタム計算まで実証したという意味ではない。

## C-023原文と既存構成の確認
- C-023のエスケープされたYAML全文を確認。初回追加ではcronの曜日だけを 0-4（日〜木）から1-5（月〜金）へ修正。08:30 UTCは17:30 JSTなので日付をずらす必要はない。
- Python 3.12、requirements.txt、追加lxml、Chromium導入、contents:write、trade-cockpit-writerの排他制御、対象JSON2件だけのcommitとpush再試行は既存構成に合わせて維持。
- 既存update.pyはupcoming_earnings.jsonをブラウザから取得する設計。今回update.py、他のworkflow、Claude Routine、MS2収集器は変更していない。
- gh OAuthはrepo/read:org/gistのみ。workflow追加はGitHub連携APIで成功し、認証設定の変更は行っていない。

## 実行記録
| 実行 | 結果 | 証拠 |
|---|---|---|
| 初回 13:51 JST | スクリプト起動・JSON2件作成・mainへpush成功。ただし途中の段階ログなし | [34930413541](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/34930413541)、出力commit c7e75c8 |
| 検証追加後 13:55 JST | 4テスト中2件失敗。本番取得ステップは未実行、pushなし | [34930646385](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/34930646385) |
| 修正後 13:56 JST | 4テスト成功、本番取得・JSON検査・成果物保存・push成功 | [34930745988](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/34930745988)、出力commit c56a102 |

## 発見・修正した問題
1. 表がないHTMLではpandasの自動パーサー切替により ImportError: Missing optional dependency 'html5lib' が発生し、Playwrightへ進めない。既に導入済みのlxmlを flavor="lxml" で明示した。
2. 元コードは取得例外をJSONに記録しても終了コード0だった。例外型・メッセージ・tracebackを出力し、失敗時は終了コード1に変更した。
3. 表抽出0件を無条件に成功扱いしていた。公式の該当なし文言がなければRuntimeErrorとして失敗にした。
4. 各段階の構造化ログ、取得前後HTML、実行元commit、実行ログ、JSONのActions artifact保存（14日）、JSON内容検査を追加した。

実装commit:
- workflow追加: f3172530e140abc762f544b4ba797e6bd2274fd8
- 段階ログと失敗判定: 03b3933fcd6f723ed5c067945cf3b4a1ca3bd8c3
- 回帰テスト: 335c6160143954af5938ea0bfa9c33eb73713ddb
- workflow検査・成果物保存: d5c8134d85c6b5c5f63781114acc16790fe66463
- lxml指定修正（最終実行元）: aa9045f6f7b8717fe401c668a7cb3d122d43f4c6

## 最終実行の段階別証拠
以下の時刻はJST（ActionsのUTCに9時間を加算）。
| 時刻 | 段階 | 実測 |
|---|---|---|
| 13:56:48 | 回帰テスト | 4件、OK。数値/英字コード表、公式0件、想定外HTML、通信例外を確認 |
| 13:56:48 | main起動 | 実際のscripts/upcoming_earnings.py起動 |
| 13:56:49 | JPX HTTP取得 | HTTP 200、23,900文字 |
| 13:56:49 | pandas.read_html | 2表解析、会社0件 |
| 13:56:49 | Playwright開始 | raw HTMLで会社0件のため発動 |
| 13:56:52 | Playwright取得 | HTTP 200、163,569文字 |
| 13:56:52 | pandas再解析 | 2表解析、会社0件 |
| 13:56:52 | 0件根拠 | source_result=confirmed_empty、JPXの明示文言あり |
| 13:56:52 | JSON出力 | upcoming_earnings.json / data/earnings_predictions_log.json、picks=0、履歴0 |
| 13:56:53 | JSON検査 | fetch_error=null、リスト型、診断記録の存在を検査成功 |
| 13:56:53 | artifact | ID 10382065110、HTML2件・実行ログ・実行元commit・JSON2件 |
| 13:56:55 | main保存 | aa9045f..c56a102 main -> main |

[成果物一式](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/34930745988/artifacts/10382065110)
[出力JSON](https://github.com/infoyuusuke-afk/trade-cockpit/blob/main/upcoming_earnings.json)
[予想履歴](https://github.com/infoyuusuke-afk/trade-cockpit/blob/main/data/earnings_predictions_log.json)

最終本番取得では例外なし。テストログ中のTimeoutErrorとRuntimeErrorは、意図的に作った失敗ケースであり、本番取得の障害ではない。2回目のartifact内JSONは初回のcheckout済みファイルであり、2回目に生成できた証拠としては扱わない。

## 確認範囲と残る制約
- 実データでは「公式0件」の経路を検証。銘柄あり日の表構成・価格取得・予想履歴追加/解決・方向精度は未検証。resolved_n=0、試運転表示を維持。
- 13:56の手動実行はJPXの17時頃更新前。翌日分の更新後データを確認したとは扱わない。
- 既存target_dateは翌暦日を設定する実装のまま。金曜・祝日前後や更新前の資料対象日との照合は未実装で、JSONの日付がJPXから確認済みとは扱わない。
- 今回はActionsとmain保存を確認。17:30の定時起動、および公開Pages画面の更新は別途未確認。
- 他の共有シート行を完了扱いせず、C-023原文を保持し追記で報告。Claude側の読了・自動連携稼働を確認したという意味ではない。
