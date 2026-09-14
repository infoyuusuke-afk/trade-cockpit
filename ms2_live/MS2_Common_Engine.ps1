Set-StrictMode -Version Latest

function Get-MS2CommonDecision {
    param(
        [Parameter(Mandatory=$true)][hashtable]$InputData
    )
    $missing = @()
    foreach ($name in @('price','vwap','ema9','ema20','volume_burst','flow_bias','under_ratio','market_alignment')) {
        if (-not $InputData.ContainsKey($name) -or $null -eq $InputData[$name]) { $missing += $name }
    }
    if ($missing.Count -gt 0) {
        return [pscustomobject]@{ decision='NO TRADE'; score=$null; long_score=$null; short_score=$null; coverage='未確認'; missing=$missing; reasons=@('必須データ未確認') }
    }

    $long = 0.0; $short = 0.0; $reasons = @()
    if ([double]$InputData.price -gt [double]$InputData.vwap) { $long += 18; $reasons += 'VWAP上' } else { $short += 18; $reasons += 'VWAP下' }
    if ([double]$InputData.ema9 -gt [double]$InputData.ema20) { $long += 16; $reasons += 'EMA上向き' } elseif ([double]$InputData.ema9 -lt [double]$InputData.ema20) { $short += 16; $reasons += 'EMA下向き' }
    if ([double]$InputData.volume_burst -ge 1.2) {
        if ([double]$InputData.price -ge [double]$InputData.vwap) { $long += 12 } else { $short += 12 }
        $reasons += '出来高加速'
    }
    if ([double]$InputData.flow_bias -ge 5) { $long += 14; $reasons += '歩み値買い優勢' }
    elseif ([double]$InputData.flow_bias -le -5) { $short += 14; $reasons += '歩み値売り優勢' }
    if ([double]$InputData.under_ratio -ge 52) { $long += 10; $reasons += '板買い側優勢' }
    elseif ([double]$InputData.under_ratio -le 48) { $short += 10; $reasons += '板売り側優勢' }
    if ([string]$InputData.market_alignment -eq 'LONG') { $long += 18; $reasons += '地合いLONG一致' }
    elseif ([string]$InputData.market_alignment -eq 'SHORT') { $short += 18; $reasons += '地合いSHORT一致' }
    if ($InputData.ContainsKey('or15_break') -and [string]$InputData.or15_break -eq 'UP') { $long += 12; $reasons += 'OR15上抜け' }
    elseif ($InputData.ContainsKey('or15_break') -and [string]$InputData.or15_break -eq 'DOWN') { $short += 12; $reasons += 'OR15下抜け' }

    $decision = 'RANGE'
    if ($InputData.ContainsKey('rebound') -and [bool]$InputData.rebound) { $decision = 'REBOUND' }
    elseif ($long -ge 62 -and $long -ge $short + 20) { $decision = 'TREND LONG' }
    elseif ($short -ge 62 -and $short -ge $long + 20) { $decision = 'TREND SHORT' }
    elseif ([Math]::Max($long,$short) -lt 35) { $decision = 'NO TRADE' }
    return [pscustomobject]@{ decision=$decision; score=[Math]::Round([Math]::Max($long,$short)); long_score=[Math]::Round($long); short_score=[Math]::Round($short); coverage='確認済み'; missing=@(); reasons=$reasons }
}

function Get-MS2SafetyGate {
    param(
        [bool]$DataFresh,
        [object]$OpenOrders,
        [object]$MarginBuyingPower,
        [object]$MarginRate,
        [object]$ShortableQuantity,
        [bool]$AutoOrderEnabled = $false
    )
    $blocks = @()
    if (-not $DataFresh) { $blocks += 'データ停止または不足' }
    if ($null -eq $OpenOrders) { $blocks += '注文一覧未確認' }
    elseif ([int]$OpenOrders -gt 0) { $blocks += '同銘柄の未完了注文あり（二重注文防止）' }
    if ($null -eq $MarginBuyingPower) { $blocks += '信用余力未確認' }
    if ($null -eq $MarginRate) { $blocks += '保証金率未確認' }
    elseif ([double]$MarginRate -lt 40) { $blocks += '保証金率40%未満' }
    if ($null -eq $ShortableQuantity) { $blocks += '売建可能数量未確認' }
    if (-not $AutoOrderEnabled) { $blocks += '自動発注OFF（既定）' }
    return [pscustomobject]@{ auto_order_enabled=$AutoOrderEnabled; order_allowed=($blocks.Count -eq 0); status=if($blocks.Count -eq 0){'許可'}else{'売買禁止'}; blocks=$blocks }
}
