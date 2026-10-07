# AIコクピット V10 長期化原因・修正記録
保存日時: 2026-10-08 JST

## 1. 結論
今回の長期化は単一障害ではなく、V9→V10切替時に START / Controller / STOP / Excel / Gateway / Brain / Shadow / ローカル反映 の不整合が連鎖していたことが原因。

加えて、設計・実装・実機Acceptanceを最初に一括監査せず、FAILごとに後追い修正したことで同じSTART/STOP試験を繰り返すことになった。

## 2. 構造的な原因
### 2.1 V8 / V9 / V10混在
旧V8/V9のSTART/STOP、Controller、Gateway、旧Brain Root、ACTIVATE系が残り、「現在どの世代のPIDが何を所有しているか」が曖昧だった。

### 2.2 controller_pidの本人確認不整合
RUN_AI_COCKPIT_V10.ps1 が Controller V10 を `&` で同期実行していたため、Stateの controller_pid は実際には RUN PowerShell ホストのPIDだった。
STOP/Gateway側は CommandLine に `AI_COCKPIT_CONTROLLER_V10.ps1` が含まれるPIDだけをController本人と判定していた。
修正: `RUN_AI_COCKPIT_V10.ps1` も正式Controllerホストとして認識。

### 2.3 STOP順序が不正
旧STOPはWorker/Gateway/Shadowを先に止め、Controllerを後で止めていた。
ControllerがSupervisorとして生存しているため、停止途中にGateway / Voice / Shadowを再起動する可能性があった。
修正: Controller/RUNを最初に停止し、その後Worker群を停止。

### 2.4 28584 Brain Gatewayの所有権不明確
V9では28584がController管理外で、旧Brain Root側Gatewayが残ることがあった。
修正: V10 Controller Stateへ `brain_gateway_pid` を追加し、28584をController/STOPの正式管理下へ統合。

## 3. Brain / Gateway関連
### 3.1 HTTP 200だけでBrain PASS判定していた
28584がHTTP 200でも、実際には通常のindex.htmlを表示していた。
修正: BRAINタブ追加、`?brain=1` でBRAIN自動選択、AI BRAIN専用パネル、/health 5秒更新。

### 3.2 Gateway healthにもcontroller_pid本人確認バグ
Gateway /health が Controller script名だけを本人条件にしていた。
修正: `RUN_AI_COCKPIT_V10.ps1` と `AI_COCKPIT_CONTROLLER_V10.ps1` の両方をV10 Controller本人として認識。

## 4. Shadow関連
### 4.1 PowerShell 5.1のArgumentList空白分割
`MarketSpeed II RSS` のような空白入りパスが分割され、ai_shadow_supervisor.py が引数エラーで即終了。
修正: scriptPath / --live / --data-dir / --status を明示的に二重引用符で囲む。

## 5. Excel関連
### 5.1 旧V9 Excelプロセス残留
旧V9が起動した `Kioxia_MS2_RSS_Live_Signals.xlsx` のExcel PIDがSafe Stop後も残り、V10がFail Closedで起動拒否。

### 5.2 旧Workbook履歴の継承
旧WorkbookにはRecovery / Disabled Item / COM不調履歴があり、V10専用クリーンWorkbookをゼロから新規作成。

### 5.3 保存確認ダイアログ
普通のExcel終了では「このファイルの変更内容を保存しますか？」が表示された。
修正: `Workbook.Close(SaveChanges=$false)` + `DisplayAlerts=$false`。

### 5.4 CloseMainWindowでは不十分
Windowsウィンドウ終了ではExcel COM/Workbook状態を安全に制御できなかった。

### 5.5 AccessibleObjectFromWindow方式が実機で安定しなかった
Owner PCではCOM取得が安定せず `could not be closed safely` が継続。

### 5.6 GetActiveObject方式は実機で成功
`[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")` はOwner PCでWorkbook no-save closeに成功。
STOP V10もこの方式へ変更。

### 5.7 Workbookを閉じてもEXCEL.EXEがhidden orphan化
Workbook画面は消えるがEXCEL.EXEだけ残ることがあった。
状態: MainWindowHandle=0 / MainWindowTitle空 / Responding=True。

### 5.8 hidden orphan判定のタイミング競合
Quit直後はMainWindowHandleが残り、数百ms〜数秒後に0へ遷移。
修正: bounded waitを追加。

### 5.9 hidden orphanのPID限定cleanup
以下条件を満たす時だけそのPIDを停止:
- State記録PID
- ProcessName=EXCEL
- canonical WorkbookPathがCommandLineに存在
- 同一Windows Session
- MainWindowHandle=0
- 他Excelプロセス=0

この最終STOPで `closed without save prompt and no orphan remains` まで自動成功。

### 5.10 RSS未接続テスト
MarketSpeed II RSSを手動で未接続にしてもExcel残留が発生。RSS接続自体は主要因ではない。

## 6. ローカル反映問題
GitHubでは修正済みでもOwner PCが旧版のままのケースが複数回あった。
改善手順:
1. commit固定
2. raw URLから対象1ファイルだけ取得
3. Select-Stringで修正シグネチャ確認
4. PowerShell AST Parseで構文エラー0
5. 実機Acceptance

## 7. Cloud / 指示運用上の問題
Cloudへ曖昧な判断を残しすぎた。
正しい責任分担:
- 設計 / 原因判定 / コード修正 / Acceptance定義 = ChatGPT
- Owner PCローカル操作 = Cloud または Owner
- Cloudに設計判断をさせない

今後:
- 固定手順
- FAILした1点だけ差分修正
- START→STOP→RESTARTまで通る前に完成扱いしない

## 8. 主要修正commit
- Controller Shadow引数クォート: `fce22c7b7f1fd0aa171f31473b3a30d368d83365`
- Brain UI: `144620d2f164b13b8f4fe7c49a83749b39aa1cc9`
- Gateway Controller本人確認: `b67078030a84f3760a9bfd4d5bf2c1c0d3b39bc8`
- STOP Controller/RUN本人確認 + Controller先停止 + no-save Excel cleanup: `2ffc5b973a46e0453c771ea8ac94f59cb108cda9`
- STOP hidden orphan cleanup: `19670a2d581cea37ce22718c6d908791bd4af249`
- STOP hidden orphan遷移待ち: `4cb89c18155ce0d2fdc3b75c9af9104c4f0e635a`
- STOP GetActiveObject方式: `60e5c01bcbce3c3c7c61e271b8c9b5d58ad1a4f7`

## 9. 現在の確定状態
### START
確認済み:
- Excel identity verified=True
- isolated=True
- Watcher LIVE / 28582
- Collector LIVE / 28580
- Shadow RUNNING
- SBV2 LIVE / 5000
- Brain Gateway 28584 ONLINE
- RSS Excel VERIFIED
- Price Source OK
- Data Conflict FALSE
- REAL ORDER LOCKED
- BRAIN STATE LIVE

判定: `V10_START_ACCEPTANCE=PASS`

### STOP
確認済み:
- Controller / Collector / Watcher / Heartbeat / Control Gateway / Brain Gateway / Voice Bridge / SBV2 / Shadow Supervisor 停止
- Workbook no-save close
- hidden orphan検出
- PID限定cleanup
- `closed without save prompt and no orphan remains`
- `managed processes and verified managed Excel stopped`

判定: `V10_STOP_ACCEPTANCE=PASS`

### RESTART
再STARTでも Excel identity verified / Watcher LIVE / Collector LIVE / Shadow alive / SBV2 LIVE まで確認済み。
`V10_LIFECYCLE_ACCEPTANCE=PASS` は再START後のBrain画面全項目を最終確認してから確定。

## 10. 再発防止ルール
1. V10ライフサイクルを1本として扱う
2. V8/V9を本番経路へ戻さない
3. Startupでgit mutationしない
4. real_submit_allowed=falseを維持
5. Excel一括kill禁止
6. PowerShell一括kill禁止
7. MarketSpeed II強制kill禁止
8. Owner PC反映後は修正シグネチャ確認
9. AST Parse=0を確認してから実行
10. STARTだけで完成判定しない
11. STOPだけで完成判定しない
12. START→STOP→RESTARTを1セットでAcceptance
13. FAIL時はその1点だけ最小修正
14. Cloudへ判断を投げない
15. Ownerへ同じデバッグ操作を反復させない

## 11. 最大の反省点
V10ライフサイクル全体を最初に静的監査せず、実機で1点ずつ後追いしたこと。
今後は RUN → Controller → State → Gateway → Brain → Shadow → Excel → STOP → Restart の順で、
PID所有権 / 親子プロセス / 起動順 / 停止順 / Excel COM終了 / 空白入りパス / UI routing / health判定 / ローカルファイル版 / duplicate / fail-closed / real_submit_allowed=false を先に静的監査する。
