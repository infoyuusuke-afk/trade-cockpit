param([string]$MapName)
$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\ms2_ps_python_bridge_producer.ps1")
if ($PSVersionTable.PSVersion.Major -ne 5) { throw "PS51_REQUIRED" }
$capture = @{
    symbol = "285A.T"; market = "TSE"; poll_seq = [int]3
    source = "offline-harness"; data_freshness = "STALE"
    watcher_observed_at = "2026-10-14T01:00:00.000+09:00"
    levels = @(
        @{ Level = [int]1; BidPrice = [double]100; AskPrice = [double]101; BidQty = $null; AskQty = [int]0; read_at = "2026-10-14T01:00:00.010+09:00" },
        @{ Level = [int]2; BidPrice = [double]100; AskPrice = [double]101; read_at = "2026-10-14T01:00:00.050+09:00" }
    )
}
$packed = ConvertTo-Ms2PsBridgeRecord $capture
if (-not $packed.Ok) { throw "PACK_REFUSED" }
$session = Open-Ms2PsBridge -MapName $MapName -Size 20480
if (-not $session.Ok) { throw "MAP_REFUSED" }
try {
    $result = Submit-Ms2PsBridgeRecord -Session $session -Record $packed.Record
    # Aggregate status only; never output record bytes.
    @{ status = $result.Status; elapsed_ms = $result.ElapsedMs; ps_major = $PSVersionTable.PSVersion.Major } | ConvertTo-Json -Compress
    if ($result.Status -ne "ACCEPTED") { exit 2 }
} finally { Close-Ms2PsBridge $session }
