# V10｜旧ランタイム監査・Windows実機Acceptance仕様

**対象：Draft PR #445。OWNER PCでの実行は独立検収完了・正式承認まで禁止。**

## 目的

通常のV10起動前に、旧V6〜V9のController・RUN・Gateway、旧Watcher/Collector/Heartbeat、旧音声Workerを調べる。旧プロセスがポート28580〜28584をまだ開いていなくても、Windowsのプロセス起動引数から検出する。PowerShell/Python実行引数の取得不能は「存在しない」ではなく**UNKNOWN**として扱い、起動を拒否する。

## 読み取り専用の検収コマンド（承認後のみ）

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\downloads\AI_COCKPIT_CONTROLLER_V10.ps1 -LegacyRuntimeAuditOnly
```

このモードはStateRoot作成、Mutex取得、Runtime配備、Worker起動、Excel起動、状態ファイル書換、プロセス終了を実行しない。表示される `V10_LEGACY_RUNTIME_AUDIT=READONLY`、`STATE_MUTATED=0`、`PROCESS_TERMINATED=0`、`EXCEL_STARTED=0`、`CONTROLLER_STARTED=0` を検収証拠とする。マシンに対する本番操作は行わない。

## 判定

- `CLEAR_OBSERVED_INTERPRETERS`（終了コード0）：今回のCIM監査で確認できる対象には旧スクリプトが検出されなかった。**正常起動・切替許可ではない。**
- `BLOCKED`（終了コード2）、`UNMANAGED_LEGACY_RUNTIME_PROCESS`：旧ランタイムと一致するスクリプトを検出。元のPIDと起動引数の検証が必要。勝手に終了しない。
- `BLOCKED`（終了コード2）、`UNMANAGED_RUNTIME_COMMANDLINE_UNAVAILABLE`：PowerShell/Pythonのコマンドラインが見えない。無関係な業務アプリか旧ランタイムか区別できないため、起動不可。自動除外・ホワイトリスト追加はしない。
- `BLOCKED`（終了コード2）、`UNMANAGED_RUNTIME_INVENTORY_UNAVAILABLE`：CIMインベントリ取得自体が失敗。監査不可。
- その他の終了コード、表示欠落、矛盾：Acceptance FAIL。

## 独立検収・実機受入条件

1. GitHub Windows CIで実Controllerの専用監査モード、AST関数モック、既存STOP/復旧がPASS。
2. OWNER実機で、業務用Excel・MS2・無関係なPowerShell/Pythonを起動・停止・書換せずに診断可能であること。
3. 起動引数を隠す業務プロセスが原因でBLOCKEDになった場合、そのPID・実行ファイル・起動時刻・所有者を別途読み取り専用に監査して問題を分類する。**本仕様ではBLOCKEDを自動解除しない。**
4. 通信ポート全アドレス監査、旧状態ファイル・V10 Mutex・Excel本人確認が別途合格して初めて次の検収へ進む。
5. 実機のPASS、CUTOVER、およびマージはOWNERの別途承認を要する。

**未了：** 独立検収とOWNER Windows実機Acceptance。現時点の `REAL_SUBMIT_ALLOWED=false`、`STOP_ALLOWED=false`、`CUTOVER_ELIGIBLE=false` を維持する。
