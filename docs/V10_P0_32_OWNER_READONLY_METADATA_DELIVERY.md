# P0-32｜独立V2・STATE更新日時のみ変化の3点再検査（非停止）

本書は **CI・独立レビューPASS後のOWNER実機再検査候補**。実機実行・切替の承認ではない。
2026-10-17 OWNER画面で P0-31 V1 は `P0_27_RESULT=BLOCKED` / `STATE_CHANGE_CLASS=METADATA_ONLY` / `STATE_CONTENT_UNCHANGED=true`。元のV1のBLOCKED判定は正しい。V1は変更せず、このV2を別ファイルで保持する。

## 固定検証ソース
- entry `downloads/VERIFY_V10_LEGACY_OWNER_READONLY_V2.ps1`
- entry commit: `1e83b5e06efe4ba011a14c066781546f78adcf0c`
- entry Git blob: `e5cae39f48e2c97082702ab8536cf4f440b08e5b`
- entry SHA256: `A0A96CF3A21893A93E5014486C2D302ED195904D4D256B063027BBDECA5C74EC`
- child PREFLIGHT/STOP fixed commit: `4e4b59e4f054cd91d0122f717f0f6d60c28d70d5` (V1と同じ)
- **1ファイルのsource hashが異なれば実行せずBLOCK**。HEADや最新mainを直接参照しない。

## OWNER実行予定のコマンド（CI・独立レビューPASSまで使用禁止）
```powershell
$c='1e83b5e06efe4ba011a14c066781546f78adcf0c'
$h='A0A96CF3A21893A93E5014486C2D302ED195904D4D256B063027BBDECA5C74EC'
$p='4e4b59e4f054cd91d0122f717f0f6d60c28d70d5'
$d=Join-Path $env:TEMP ('v10-owner-v2-'+[guid]::NewGuid().ToString('N'))
try {
  [void](New-Item -ItemType Directory -Path $d -ErrorAction Stop)
  $f=Join-Path $d 'VERIFY_V10_LEGACY_OWNER_READONLY_V2.ps1'
  [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 40 -Uri "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/$c/downloads/VERIFY_V10_LEGACY_OWNER_READONLY_V2.ps1" -OutFile $f -ErrorAction Stop
  if ((Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash -cne $h) {
    'ENTRY_RESULT=BLOCKED_HASH_MISMATCH'
  } else {
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $f -PinnedCommit $p
  }
}
finally {
  if (Test-Path -LiteralPath $d) {
    Remove-Item -LiteralPath $d -Recurse -Force
  }
}
```

## P0-32 追加安全修正
- V2は状態ファイルの検査だけでなく、採用済みプロセスの開始時刻が読み取れない場合も異常として拒否する。旧V1の同経路は修正しない。
- 新しい固定PINはこの修正済みV2のGit blobを参照する。以前のV2固定PINは使わないこと。

## 判定
- `P0_27_RESULT=READONLY_VERIFIED`: 旧V1と同じ完全不変の読取専用診断。
- `P0_27_RESULT=READONLY_METADATA_STABLE`: Stateのバイト列SHA256がBEFORE/AFTER/RECHECKの3点で一致。他の監視対象は全て不変。`STATE_UNCHANGED=false` は正しく保持し、`STATE_RECHECK=PASS` を表示する。
- `P0_27_RESULT=BLOCKED`: 内容変化、State欠落、3点不一致、他の監視対象変更、検証不能、配布不整合など。停止や切替の許可を意味しない。
- **いずれの場合も** `STOP_ALLOWED=false` / `CUTOVER_ELIGIBLE=false` / `REAL_SUBMIT_ALLOWED=false`。Owner Windows上では読取専用。作業用TEMP以外のファイルを書き換えない。未承認の停止・切替・Excel操作・実取引は不可。

### 残留制約
V2のread-only結果は、対象プロセスとLISTENポートの証拠確認のみ。市場価格の鮮度、MS2購読、Excelブックの同時運用可否、WRONG_SOURCE_WORKBOOKの解決、実注文の期待値・許可を意味しない。元のControllerのSTATE更新主体は実機で未証明。
