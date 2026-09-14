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
# 2回目の失敗（真因）: DASHBOARDシートを明示指定しても改善しなかった。原因は
# `GetActiveObject("Excel.Application")`が、Excelインスタンスが複数（本番＋検証用の残骸等）
# 存在する場合にどのインスタンスへ接続するか不定であること。テスト対象のワークブックを
# 持たない別インスタンスへ接続してしまい、ワークブック名が一致せず何も再計算されていなかった。
# 通常運用ではAUTO_START_MS2_100.ps1がExcel多重起動を防止するが、それでも不定な接続方法に
# 依存するのは危険なため、ファイルパスのモニカーで目的のワークブックへ直接バインドする方式
# （`Marshal.BindToMoniker`）に変更した。これはExcelインスタンスの数に関わらず、目的の
# ワークブックだけを確実に指す。実機の隔離テストで、複数Excelインスタンスが存在する状態でも
# 正しく安全ゲートが更新されることを確認済み。

$bookPath = Join-Path $PSScriptRoot "Kioxia_MS2_RSS_Live_Signals.xlsx"
$dashboardSheetName = "DASHBOARD"
$intervalSeconds = 5

Write-Host "安全ゲート用の心拍プロセスを開始しました（${intervalSeconds}秒ごとに再計算）。終了はCtrl+C。" -ForegroundColor Cyan

while ($true) {
    try {
        # ファイルパスのモニカーで目的のワークブックへ直接バインドする。
        # Excel.Applicationが複数起動していても、このワークブックだけを確実に指す。
        $book = [Runtime.InteropServices.Marshal]::BindToMoniker($bookPath)
        # 安全ゲート数式(NOW()ベース)があるDASHBOARDシートを明示的に指定して再計算する。
        # 別シートを再計算してもDASHBOARDのNOW()は再評価されないため、シート指定が必須。
        $book.Worksheets.Item($dashboardSheetName).Calculate()
    } catch {
        # ワークブック未オープン・COM一時エラー等はすべて無視して次のループへ。
        # このプロセス自体は何があっても止めない。
    }
    Start-Sleep -Seconds $intervalSeconds
}
