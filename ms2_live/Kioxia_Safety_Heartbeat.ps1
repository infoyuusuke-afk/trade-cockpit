# Kioxia安全ゲート用の独立した最小限プロセス（2026-09-15 未明・ChatGPT C-011指摘への対応）。
#
# 背景: DASHBOARD!A5等のNOW()ベースの鮮度ゲートは、Excelの仕様上「時間が経過しただけ」では
# 再評価されない（volatile関数は再計算がトリガーされた時にだけ再評価される）。
# これまではKioxia_RSS_Live_Watcher.ps1自身が2秒ごとに再計算を呼んでいたため気づかなかったが、
# 実機の独立テストで、メインWatcherが完全に停止すると安全ゲートも一緒に凍結し、
# 古い「買いサイン」等が「現在も有効」に見え続けることを確認した（本番Excelは操作していない）。
#
# 対策: この最小限プロセスは「再計算を呼び続けること」だけを行う。メインWatcher
# （複雑な売買ロジック・RSS読み取り等）がどんな理由で落ちても、これが生きている限り
# NOW()ベースの鮮度判定は正しく動く。ロジックを極限まで単純化し、このプロセス自体が
# 落ちる可能性を最小化することが目的（$ErrorActionPreferenceもStopにしない）。
#
# このプロセスは売買判定・表示内容には一切関与しない。再計算をトリガーするだけ。
#
# 実機の隔離テストで判明した重要な修正（2026-09-15未明、2回の実機失敗を経て特定）:
#
# 1回目の失敗: 当初「どのシートでも良い、Worksheet.Calculate()を1回呼べばブック内の
# volatile関数が全て再評価される」と想定して計算シート（Worksheets.Item(1)）を再計算して
# いたが、これはシート指定を誤っている可能性があるため、安全ゲート数式があるDASHBOARDシート
# を明示指定する形に修正した。
#
# 2回目の失敗: DASHBOARDシートを明示指定しても改善しなかった。原因は
# `GetActiveObject("Excel.Application")`が、Excelインスタンスが複数（本番＋検証用の残骸等）
# 存在する場合にどのインスタンスへ接続するか不定であること。テスト対象のワークブックを
# 持たない別インスタンスへ接続してしまい、ワークブック名が一致せず何も再計算されていなかった。
# ファイルパスのモニカーで目的のワークブックへ直接バインドする方式（`Marshal.BindToMoniker`）
# に変更し、非OneDrive同期のローカルテストブックでは正しく機能することを確認した。
#
# 3回目の失敗（本番実機で判明）: 本番ワークブックはOneDriveで同期されたフォルダーにあるため、
# ExcelはROT(Running Object Table)へローカルファイルパスではなく
# `https://d.docs.live.net/...`形式のOneDriveクラウドURLで登録することを実機で確認した。
# 隔離テストではOneDrive同期されない一時フォルダーを使っていたため、この問題を検知できて
# いなかった。
#
# 4回目の失敗（真因）: 見つけたクラウドURL文字列を`Marshal.BindToMoniker(文字列)`へ渡しても
# 「クラスが登録されていません」で失敗し続けた。これは`BindToMoniker(string)`が内部で
# `MkParseDisplayName`により文字列を毎回IMonikerへ**再解釈**する処理をしており、
# OneDrive/Office共同編集機能が使う独自のアイテムモニカー形式はこの汎用パーサーに
# 対応していないためと考えられる。
#
# 最終修正（本番実機で動作確認）: 文字列を介した再解釈をやめ、ROTから見つけたIMonikerを
# `IRunningObjectTable.GetObject(moniker)`へ直接渡して、生きているCOMオブジェクト参照を
# そのまま取得する方式に変更した。これは文字列解析を経由しないため、モニカーの種類
# （ローカルパスかOneDriveクラウドURLか）に関わらず機能する。

# ChatGPT C-013指摘への対応（2026-09-15）: 当初のcatchは全例外を黙殺しており、この心拍プロセス
# 自体がExcelへ接続できなくなっても何も分からなかった（「監視されていない状態」が「正常稼働」と
# 見分けがつかない）。連続失敗を診断ログへ記録し、一定回数続いたら音声でも警告するようにした。
#
# なお、C-013で指摘された通りの根本的な限界が残る：ExcelのNOW()は再計算のトリガーなしには
# 自走しないため、Watcherとこの心拍プロセスの**両方**が同時に停止した場合、Excel数式だけでは
# 表示（DASHBOARD!A5等）を自動的に無効化できない。この心拍プロセスの役目は「Watcherだけが
# 落ちたケース」への対策であり、「両方落ちたケース」への対策ではない。両方落ちた場合に備える
# には、このPC自体を定期的に見るか、心拍プロセスとは別の外部監視の仕組みが必要（未実装、
# 次の課題としてSTATUS.md/共有シートに記載）。

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Collections.Generic;

public class KioxiaRotFinder {
    [DllImport("ole32.dll")]
    public static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable prot);
    [DllImport("ole32.dll")]
    public static extern int CreateBindCtx(int reserved, out IBindCtx ppbc);

    // ROT(Running Object Table)を毎回列挙し、表示名の末尾がbookFileNameと一致するモニカーを
    // 見つけたら、そのモニカーの指す生きているCOMオブジェクトをIRunningObjectTable.GetObject()で
    // 直接取得して返す。文字列を介した再解釈(BindToMoniker(string))はOneDriveのクラウドURL形式の
    // モニカーに対応していないため使わない。ローカルパス・クラウドURLのどちらでも対応できる。
    public static object FindLiveObject(string bookFileName) {
        IRunningObjectTable rot;
        GetRunningObjectTable(0, out rot);
        IEnumMoniker enumMoniker;
        rot.EnumRunning(out enumMoniker);
        enumMoniker.Reset();
        IMoniker[] moniker = new IMoniker[1];
        IntPtr fetched = IntPtr.Zero;
        while (enumMoniker.Next(1, moniker, fetched) == 0) {
            IBindCtx bindCtx;
            CreateBindCtx(0, out bindCtx);
            string displayName;
            try {
                moniker[0].GetDisplayName(bindCtx, null, out displayName);
                if (displayName != null && displayName.EndsWith(bookFileName, StringComparison.OrdinalIgnoreCase)) {
                    object obj;
                    rot.GetObject(moniker[0], out obj);
                    return obj;
                }
            } catch { }
        }
        return null;
    }
}
'@ -ErrorAction SilentlyContinue

$bookFileName = "Kioxia_MS2_RSS_Live_Signals.xlsx"
$dashboardSheetName = "DASHBOARD"
$intervalSeconds = 5
$diagLogPath = Join-Path $PSScriptRoot "heartbeat_diag.csv"
$alertThreshold = 3           # 連続失敗3回（約15秒）で音声警告
$alertRepeatMinutes = 5       # 警告が続く間、再警告する間隔

if (-not (Test-Path $diagLogPath)) {
    "日時,状態,連続失敗回数,詳細" | Out-File -FilePath $diagLogPath -Encoding utf8
}

$speaker = $null
try { $speaker = New-Object -ComObject SAPI.SpVoice } catch {}

$consecutiveFailures = 0
$lastAlertAt = Get-Date "2000-01-01"
$lastLoggedOk = Get-Date "2000-01-01"

Write-Host "安全ゲート用の心拍プロセスを開始しました（${intervalSeconds}秒ごとに再計算）。終了はCtrl+C。" -ForegroundColor Cyan

while ($true) {
    $failed = $false
    $errorDetail = ""
    try {
        # ROTを毎回列挙し、ファイル名が一致するモニカーの指す生きているCOMオブジェクトを
        # 直接取得する（文字列の再解釈はしない。ローカルパス・OneDriveクラウドURLのどちらでも対応）。
        $book = [KioxiaRotFinder]::FindLiveObject($bookFileName)
        if ($null -eq $book) { throw "ワークブックがROTに見つかりません（Excel未起動またはブック未オープン）" }
        # 安全ゲート数式(NOW()ベース)があるDASHBOARDシートを明示的に指定して再計算する。
        # 別シートを再計算してもDASHBOARDのNOW()は再評価されないため、シート指定が必須。
        $book.Worksheets.Item($dashboardSheetName).Calculate()
    } catch {
        $failed = $true
        $errorDetail = $_.Exception.Message
    }

    if ($failed) {
        $consecutiveFailures++
        Add-Content -Path $diagLogPath -Encoding UTF8 -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss")+",失敗,"+$consecutiveFailures+","+($errorDetail -replace ",","；"))
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 心拍失敗（連続${consecutiveFailures}回）: $errorDetail" -ForegroundColor Yellow
        if ($consecutiveFailures -ge $alertThreshold -and ((Get-Date) - $lastAlertAt).TotalMinutes -ge $alertRepeatMinutes) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 心拍プロセスがExcelへ接続できない状態が続いています。安全ゲートが更新されていない可能性があります。" -ForegroundColor Red
            if ($speaker) { try { $speaker.Speak("心拍プロセスがエクセルへ接続できていません。安全ゲートが古いままの可能性があります。確認してください。",1) | Out-Null } catch {} }
            $lastAlertAt = Get-Date
        }
    } else {
        # 成功時は毎回ログに書かず、1分に1回だけ「生存記録」を残す（ログ肥大化防止、
        # かつ「ログが止まっている＝プロセス自体が落ちた」ことも見分けられるようにする）。
        if ($consecutiveFailures -gt 0) {
            Add-Content -Path $diagLogPath -Encoding UTF8 -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss")+",復帰,0,")
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 心拍復帰（連続失敗${consecutiveFailures}回から回復）" -ForegroundColor Green
        }
        $consecutiveFailures = 0
        if (((Get-Date) - $lastLoggedOk).TotalMinutes -ge 1) {
            Add-Content -Path $diagLogPath -Encoding UTF8 -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss")+",正常,0,")
            $lastLoggedOk = Get-Date
        }
    }
    Start-Sleep -Seconds $intervalSeconds
}
