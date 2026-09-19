# Manual Windows audio check: /status is healthy, but /voice is forced to fail.
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../ms2_live/SPEAK_LIVE_EMOTION.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path $source), [ref]$tokens, [ref]$errors)
foreach ($name in @('Normalize-SpeechText','To-Invariant','Get-VoiceProfile','Test-SbV2Ready','Invoke-Voice')) {
    $functionAst = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
$DryRun = $false
$SbV2BaseUrl = 'http://127.0.0.1:5000'
$SbV2ModelName = '__missing_model_for_fallback_test__'
$SbV2SpeakerName = 'amitaro'
$SbV2Style = 'Neutral'
$sapi = New-Object -ComObject SAPI.SpVoice
$sapi.Rate = -1
if (-not (Test-SbV2Ready)) { throw 'SBV2 API is not ready for the synthesis-failure test.' }
if (-not (Invoke-Voice 'SAPI fallback test.' 'WATCH')) { throw 'SAPI fallback failed.' }
Write-Host 'SBV2 synthesis failure to SAPI fallback: OK'
