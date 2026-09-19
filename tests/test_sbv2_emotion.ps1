$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../ms2_live/SPEAK_LIVE_EMOTION.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path $source), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Emotion script has syntax errors.' }
foreach ($name in @('Bool','Num','Limit','Get-EmotionState','Should-Speak')) {
    $functionAst = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $functionAst) { throw "Missing function: $name" }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
function Assert($condition, $message) { if (-not $condition) { throw $message } }

$MaxDataAgeSeconds = 30
$CooldownSeconds = 90
$HotRepeatSeconds = 180
$lastKey = ''
$lastScore = 0
$lastSpokenAt = [datetime]::MinValue
$lastHotAt = [datetime]::MinValue
$now = [datetime]'2026-09-18 10:00:00'
$data = [pscustomobject]@{
    updated_at = '2026-09-18 10:00:00'; valid = 100; stale = 'false'; market_state = '地合い強い'; breadth_pct = 72
    kioxia = [pscustomobject]@{
        price = 105; vwap = 100; ema9 = 103; ema20 = 101; or_high = 104; or_low = 90
        volume_burst = 2.1; flow_bias = 22; signal = '買いサイン'; strategy = 'OR15押し目'
        common_decision = 'TREND LONG'; whipsaw = 'false'; chase_guard = 'false'
    }
}
$hot = Get-EmotionState $data $now
Assert ($hot.level -eq 'HOT' -and $hot.side -eq 'LONG') 'Fresh complete long data should be HOT.'
Assert ((Get-EmotionState $null $now).level -eq 'DANGER') 'Missing MS2 data must fail closed.'
Assert (-not (Bool 'false')) 'String false must not enable a safety flag.'
Assert (Should-Speak $hot $now) 'First HOT announcement should be eligible.'
$lastKey = $hot.key
$lastScore = $hot.score
$lastSpokenAt = $now
$lastHotAt = $now
Assert (-not (Should-Speak $hot $now.AddSeconds(10))) 'HOT should respect cooldown.'
$data.updated_at = '2026-09-17 10:00:00'
$stale = Get-EmotionState $data $now
Assert ($stale.level -eq 'DANGER' -and $stale.side -eq 'NONE') 'Yesterday data must not be announced as live.'
$data.updated_at = '2026-09-18 10:00:00'
$data.valid = 50
Assert ((Get-EmotionState $data $now).level -eq 'DANGER') 'Incomplete MS2 data must fail closed.'
Write-Host 'SBV2 emotion state and cooldown tests: OK'
