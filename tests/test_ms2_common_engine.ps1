$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\ms2_live\MS2_Common_Engine.ps1')

$long = Get-MS2CommonDecision @{price=105;vwap=100;ema9=104;ema20=101;volume_burst=1.8;flow_bias=18;under_ratio=57;market_alignment='LONG';or15_break='UP';rebound=$false}
if ($long.decision -ne 'TREND LONG') { throw "TREND LONG expected, got $($long.decision)" }
$short = Get-MS2CommonDecision @{price=95;vwap=100;ema9=96;ema20=99;volume_burst=1.5;flow_bias=-18;under_ratio=43;market_alignment='SHORT';or15_break='DOWN';rebound=$false}
if ($short.decision -ne 'TREND SHORT') { throw "TREND SHORT expected, got $($short.decision)" }
$missing = Get-MS2CommonDecision @{price=100}
if ($missing.decision -ne 'NO TRADE' -or $missing.coverage -ne '未確認') { throw 'Missing data must fail closed' }
$gate = Get-MS2SafetyGate -DataFresh $true -OpenOrders $null -MarginBuyingPower $null -MarginRate $null -ShortableQuantity $null
if ($gate.order_allowed -or $gate.auto_order_enabled) { throw 'Order gate must default to disabled' }
Write-Host 'MS2 common engine tests passed.' -ForegroundColor Green
