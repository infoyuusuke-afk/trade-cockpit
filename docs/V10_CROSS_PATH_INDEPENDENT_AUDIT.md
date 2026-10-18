# V10横断独立監査｜起動・STOP・旧状態復旧

**対象:** Draft PR #444（統合）および派生Draft PR #445（安全改修）。この報告はソース監査とGitHub合成CIであり、OWNER Windows実機のAcceptanceではない。

## 今回発見した不整合と修正

旧状態アーカイブの `Test-NoUntrackedV10Process` はV10 Controller/RUNやWatcher/Collector等を検出する一方、V10起動側の `Assert-NoUnmanagedLegacyRuntimeProcesses` が検出する旧V6〜V9 Controller/RUN/Gatewayや旧音声Workerの一部を照合していなかった。

この差異により、**旧V9がポート未使用で生存していても、復旧アーカイブだけは成功する経路**が存在した。結果として直後のV10起動では拒否され得るが、復旧が安全と宣言されること自体が誤りである。

PR #445のSTOPに旧V6〜V9のRUN/Controller/Gateway/STOP、旧音声Worker、Heartbeatの実行引数パターンを追加。既存の記録済みPID、通信ポート、V10 Worker、状態SHA、ライフサイクルMutex検査は維持。残留旧V9 Controllerの合成生存プロセスを起動し、アーカイブ拒否・状態原本のバイト列保全・プロセス生存を検証する。

## Gate判定

| Gate | 判定 | 根拠・留保 |
|---|---|---|
| コード実装・保存 | 完了 | #445 Draft HEADの修正コミット |
| 起動前の旧プロセス監査 | 合成テスト済み | 監査不能時はFail-closed。無関係なPowerShell/Pythonで誤拒否する可能性あり |
| STOP所有権・無関係Excel保護 | 合成テスト済み | ROT/CIM/Excelの実機動作は未検証 |
| 旧状態アーカイブ | 合成テスト済み | 検出対象整合化。ただし外部プロセスの最終チェック〜Rename間の非原子的競合は残る |
| 独立者によるコード・権限検収 | **PENDING** | 実装者の自己検証は独立検収を代替しない |
| Windows実機Acceptance | **NOT_RUN** | OWNERの仕事用Excel、MS2、実セッションを一切停止・変更していない |
| マージ・本番切替 | **BLOCKED** | 上記Gateに加えOWNER承認が必要 |

## 実機Acceptanceの判定条件（実行は別途正式承認後）

1. V10の配備バンドルと固定SHAがレビューしたコミットと一致する。
2. 読み取り専用 `-LegacyRuntimeAuditOnly` により、旧プロセス・正常な業務用Interpreter・監査不能を区別して根拠を保存する。UNKNOWNなら起動しない。
3. `-InspectOnly` によりV10全PID、他社Excelの排他性、28580〜28584の全アドレス待受、状態ファイルSHAを保存する。業務用Excelに触らない。
4. 合成・隔離環境で正常起動、起動拒否、停止、失敗時台帳保全、承認制アーカイブ、再起動を一連で再現する。
5. 実機で異常があった場合、状態ファイルを手作業で削除・古いV8/V9を自動停止する運用は行わない。
6. 独立検収記録とOWNERによる明示承認がなければCUTOVERを許可しない。

**固定禁止:** `REAL_SUBMIT_ALLOWED=false`、`STOP_ALLOWED=false`、`CUTOVER_ELIGIBLE=false`。#444/#445はDraft・未マージ。

