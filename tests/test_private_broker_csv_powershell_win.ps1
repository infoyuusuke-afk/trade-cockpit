$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root 'downloads\READ_ONLY_BROKER_CSV_CHECK_WIN.ps1'
if (-not (Test-Path -LiteralPath $script)) { throw 'MISSING_DIAGNOSTIC_SCRIPT' }
$folder = Join-Path $env:TEMP ('synthetic-csv-probe-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($folder)
try {
    $headers = '約定日,銘柄コード,売買区分,数量［株］,単価［円］'
    $lf = [Environment]::NewLine
    $utf8 = Join-Path $folder 'synthetic-utf8.csv'
    [IO.File]::WriteAllText($utf8, $headers + $lf + 'SECRET_ACCOUNT_123,private' + $lf, (New-Object System.Text.UTF8Encoding($true)))
    $cp932 = Join-Path $folder 'synthetic-cp932.csv'
    [IO.File]::WriteAllText($cp932, $headers + $lf + 'SECRET_ACCOUNT_123,private' + $lf, [Text.Encoding]::GetEncoding(932))
    $invalid = Join-Path $folder 'synthetic-invalid.csv'
    [IO.File]::WriteAllText($invalid, 'UNKNOWN,ACCOUNTID' + $lf + 'SECRET_ACCOUNT_123,private' + $lf, [Text.Encoding]::GetEncoding(932))
    foreach ($test in @(
        @{file=$utf8;expected='Encoding: UTF8';code=0},
        @{file=$cp932;expected='Encoding: CP932';code=0},
        @{file=$invalid;expected='Status: BLOCKED';code=2}
    )) {
        $out = & powershell.exe -NoProfile -File $script -TestOnly -FilePath $test.file 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne $test.code) { throw ('WRONG_EXIT_CODE ' + $exitCode + ' expected ' + $test.code + ' output ' + $out) }
        if (-not $out.Contains($test.expected)) { throw ('WRONG_CLASSIFICATION ' + $out) }
        foreach ($secret in @('SECRET_ACCOUNT_123','private',$test.file)) {
            if ($out.Contains($secret)) { throw 'PRIVATE_DATA_LEAK' }
        }
        if ($exitCode -eq 0 -and -not $out.Contains('実約定・証券会社真正性・EV学習は確認していません。')) { throw 'MISSING_UNVERIFIED_WARNING' }
    }
    Write-Output 'WIN_POWERSHELL_OFFLINE_CSV_DIAGNOSTIC_SYNTHETIC_PASS'
} finally {
    if (Test-Path -LiteralPath $folder) { Remove-Item -LiteralPath $folder -Recurse -Force }
}
