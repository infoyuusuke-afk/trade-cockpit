# Offline Windows PowerShell 5.1 fault injection against the exact Collector AST.
# Does not execute the Collector startup, Excel, MS2 or any real market file.
param([Parameter(Mandatory=$true)][string]$CollectorPath)
$ErrorActionPreference = 'Stop'
$tests = 0
function Assert-True([bool]$ok, [string]$label) {
    if (-not $ok) { throw "SYNTHETIC_TEST_FAILED: $label" }
    $script:tests++
}
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'PS5_1_REQUIRED' }
$parseErrors = $null
$tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $CollectorPath, [ref]$tokens, [ref]$parseErrors
)
Assert-True ($parseErrors.Count -eq 0) 'COLLECTOR_AST_PARSE'
$matching = @($ast.FindAll({
    param($node)
    ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and
    ($node.Name -eq 'Invoke-MS2SafeCsvAppend')
}, $true))
Assert-True ($matching.Count -eq 1) 'ONE_EXACT_APPEND_HELPER'
# Define ONLY the function body AST; no main script dot-sourcing or runtime.
Invoke-Expression $matching[0].Extent.Text
$source = [IO.File]::ReadAllText($CollectorPath)
Assert-True ($source -match '\$AutoOrderEnabled = \$false') 'REAL_ORDER_DISABLED'
Assert-True ($source -match 'recording_degraded=') 'DEGRADED_STATUS_IN_PUBLIC_OUTPUT'
Assert-True ($source -match 'source_missing_fields=@\(\$sourceMissingFields\)') 'MISSING_PROVENANCE_PRESERVED'
Assert-True ($source -match 'if\(\$script:ms2RecordFaulted') 'DATA_GATE_FAIL_CLOSED'
$direct = @([regex]::Matches(
    $source, 'Add-Content -Encoding UTF8 -Path \$(?:tick|condition|supply|snapshot|credit|preopen|pts|irPts|signal)Csv'
))
Assert-True ($direct.Count -eq 0) 'NO_OLD_DIRECT_APPEND_AT_RISK_SINKS'
$referenced = @([regex]::Matches($source, 'Invoke-MS2SafeCsvAppend -Path \$(?:tick|condition|supply|snapshot|credit|preopen|pts|irPts|signal)Csv'))
Assert-True ($referenced.Count -eq 9) 'NINE_WRITE_CALLS_ROUTED'
$temp = Join-Path ([IO.Path]::GetTempPath()) ('ms2_synthetic_' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $temp -ErrorAction Stop)
try {
    $file = Join-Path $temp 'SYNTHETIC.csv'
    $script:ms2RecordFaulted = $false
    $script:ms2RecordErrors = @{}
    $ok = Invoke-MS2SafeCsvAppend -Path $file -Line 'synth,100' -Stream ticks
    Assert-True ($ok -eq $true) 'NORMAL_APPEND_ACK'
    Assert-True ((Get-Content -LiteralPath $file -Raw) -match 'synth,100') 'NORMAL_APPEND_WRITTEN'
    Assert-True ($script:ms2RecordFaulted -eq $false) 'HEALTHY_AFTER_SUCCESS'

    $calls = 0
    $denied = { param($p,$l) throw 'sensitive private synthetic path should never leak' }
    $captured = @(& { Invoke-MS2SafeCsvAppend -Path $file -Line 'synth,200' -Stream snapshot -Writer $denied } 6>&1)
    Assert-True ($captured[0] -eq $false) 'THROW_RETURN_FALSE'
    Assert-True ($script:ms2RecordFaulted) 'STICKY_DEGRADED_STATE'
    Assert-True ($script:ms2RecordErrors['snapshot'] -eq 1) 'REASON_STREAM_AGGREGATE'
    Assert-True (($captured | Out-String) -notmatch 'sensitive private synthetic path') 'NO_PRIVATE_EXCEPTION_OUTPUT'
    Assert-True (($captured | Out-String) -notmatch [regex]::Escape($temp)) 'NO_PRIVATE_PATH_OUTPUT'
    $noop = {param($p,$l) $script:calls += 1}
    $retry = Invoke-MS2SafeCsvAppend -Path $file -Line 'synth,200' -Stream snapshot -Writer $noop
    Assert-True ($retry -eq $false) 'NO_AUTO_RETRY_AFTER_UNKNOWN'
    Assert-True ($script:calls -eq 0) 'NO_WRITER_CALL_AFTER_FAULT'
    Assert-True ((Get-Content -LiteralPath $file -Raw) -notmatch 'synth,200') 'NO_SILENT_REPLAY'

    $script:ms2RecordFaulted = $false
    $script:ms2RecordErrors = @{}
    $partial = {
        param($p,$l)
        [IO.File]::AppendAllText($p, 'partial')
        throw 'partial-write-fault'
    }
    $partialAck = Invoke-MS2SafeCsvAppend -Path $file -Line 'SYNTHETIC' -Stream condition -Writer $partial 6>$null
    Assert-True ($partialAck -eq $false) 'PARTIAL_WRITE_IS_UNKNOWN'
    Assert-True ($script:ms2RecordFaulted) 'PARTIAL_WRITE_STICKY_HALT'
    Assert-True ((Get-Content -LiteralPath $file -Raw) -match 'partial') 'PARTIAL_DATA_CANNOT_BE_ASSUMED_ABSENT'

    $script:ms2RecordFaulted = $false
    $script:ms2RecordErrors = @{}
    $nonterminating = {param($p,$l) Write-Error -Message 'SYNTHETIC_NONTERMINATING' -ErrorAction Stop}
    $err = Invoke-MS2SafeCsvAppend -Path $file -Line 'NA' -Stream under_over -Writer $nonterminating 6>$null
    Assert-True ($err -eq $false) 'WRITE_ERROR_ACTION_STOP'
    Assert-True ($script:ms2RecordFaulted) 'NONTERMINATING_TURNS_BLOCKED'
    Write-Output "PS5_1_SYNTHETIC_PASS=$tests"
}
finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
