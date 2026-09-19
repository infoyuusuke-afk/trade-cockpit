$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../ms2_live/SPEAK_TODAY_STRATEGY.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path $source), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Strategy voice script has syntax errors.' }
foreach ($name in @('Test-DataFresh','Get-Mode','Get-ModeVoice')) {
    $functionAst = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
function Assert($condition, $message) { if (-not $condition) { throw $message } }
$MaxDataAgeSeconds = 30
$data = [pscustomobject]@{
    updated_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'); valid = 100; stale = $false
    market_state = '地合い強い'; breadth_pct = 75; top5 = @()
}
Assert (Test-DataFresh $data) 'Current data should pass freshness check.'
$data.valid = 50
Assert ((Get-ModeVoice 'NO TRADE' $data) -notmatch '地合い強い|75') 'Incomplete data must not be announced as market facts.'
$data.valid = 100
$data.updated_at = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd HH:mm:ss')
Assert (-not (Test-DataFresh $data)) 'Prior-day data must fail freshness check.'
Assert ((Get-Mode $data) -eq 'NO TRADE') 'Prior-day data must not produce a trade mode.'
$voice = Get-ModeVoice 'NO TRADE' $data
Assert ($voice -notmatch '地合い強い|75') 'Stale voice must not repeat yesterday market facts.'
Write-Host 'SBV2 strategy freshness tests: OK'
