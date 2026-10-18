# V10 Safe Stop — 読み取り専用復旧診断（Draft #445）

**状態：開発候補。OWNERのWindows実機で未実施。導入・本番STOP・本番切替の承認ではない。**

## 目的

V10は `V10_CONTROLLER_STATE.json` が残ると、旧セッションのプロセスを無条件に停止・削除せず、新しいControllerを起動しない。この制限は仕事用Excel・MS2・外部プロセスの誤停止を防ぐが、STOPを拒否されたときの原因調査が難しかった。

`STOP_AI_COCKPIT_V10.ps1 -InspectOnly` は、保存された管理台帳とWindowsのプロセス・ポート状態を**読み取るだけ**で、後続のSTOP・Controllerへの操作は行わない。

## 実行コマンド（正式な検収・配布後だけ）

レビュー済みV10 checkoutのルートで、次の1行を実行する。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\downloads\STOP_AI_COCKPIT_V10.ps1 -InspectOnly -Root "C:\AI_Cockpit_OneClick_Starter"
```

**今すぐOWNER PC上で実行する指示ではない。** Draft #445の合成検収と正式な実機承認を完了してから使う。現在の作業では実機STOP・Excel操作・MS2操作・マージ・実発注を禁止する。

## 診断結果の読み方

- `V10_STOP_INSPECTION=READONLY`：診断モードを選択。プロセス終了・Excel保存/終了・台帳書換は実行しない。
- `PID_<field>=ALIVE_OWNED`：記録済みのPID・実行引数等の一致を確認。**停止許可の証明ではない**。
- `PID_<field>=ABSENT`：CIMで対象PIDの不在を確認。
- `PID_<field>=ALIVE_FOREIGN_OR_UNVERIFIED`：生存しているがV10所有物として認証できない。触れてはいけない。
- `PID_<field>=UNKNOWN`：CIM・プロセスハンドル等を検証できない。消失とは扱わない。
- `PORT_28580`〜`PORT_28584`：LISTEN / FREE / UNKNOWN。LISTENとUNKNOWNは原因監査の対象。
- `RECOVERY_CLASS=ACTIVE_V10_PROCESS`：V10所有プロセスの生存を検出。停止処理を自動的には実行しない。
- `RECOVERY_CLASS=STALE_STATE_REVIEW_REQUIRED`：台帳内の記録済みPIDが不在で、対象ポートのLISTENも確認されない。**状態ファイルを削除してよいという意味ではない**。追跡できない子プロセスなどは独立レビューする。
- `RECOVERY_CLASS=REQUIRES_INDEPENDENT_REVIEW`：不明、外国PID、不正台帳、LISTEN等が残る。作業を拒否。
- `RECOVERY_CLASS=INVALID_STATE`：台帳のJSONまたはController IDに不整合。元ファイルを保全。
- `RECOVERY_CLASS=NO_STATE`：台帳ファイル不在。対象のプロセスがないことの包括的な証明ではない。

常に `STATE_MUTATED=0`、`PROCESS_TERMINATED=0`、`EXCEL_CLOSED=0`、`REAL_SUBMIT_ALLOWED=0`、`AUTOMATIC_STATE_DELETION_ALLOWED=0`（台帳がある場合）を守る。診断は最新のSTOP合成テストを代替するものではない。

## 禁止と復旧境界

診断の結果だけで `Remove-Item V10_CONTROLLER_STATE.json`、`taskkill`、`Stop-Process`、Excel強制終了、ポート所有者の一括停止、手動での旧V8/V9再起動を行わない。

`STOP_ALLOWED=false`、`CUTOVER_ELIGIBLE=false`、`REAL_SUBMIT_ALLOWED=false` を維持。OWNER実機Acceptanceと独立検収が完了するまで、停止・再起動の実操作は不許可。

## 検証

Windows GitHub Actionsでは、非公開の一時フォルダに作成した合成Controller / BRAIN / 外国プロセスと状態ファイルを使用し、`-InspectOnly` の非停止・非更新を検証する。実Excel、MS2、実注文は使用しない。**本番環境の復旧完了ではない。**
