param([string]$Root = "C:\AI_Cockpit_OneClick_Starter")

$ErrorActionPreference = "Stop"
$base = "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main"
$cache = "?x=" + (Get-Date -Format "yyyyMMddHHmmss")

function Resolve-RuntimeDir {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $hits = foreach($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $preferred = @($hits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($preferred.Count -gt 0) { return $preferred[0].Directory.FullName }

    $any = @($hits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($any.Count -gt 0) { return $any[0].Directory.FullName }

    throw "MS2 runtime folder not found."
}

$RuntimeDir = Resolve-RuntimeDir
$collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
$stats = Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1"

Write-Host "[1/4] Stopping current Collector..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
Where-Object { $_.CommandLine -and $_.CommandLine -match 'MS2_RSS_100_Collector\.ps1' } |
ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "[2/4] Downloading data-quality update..." -ForegroundColor Cyan
Invoke-WebRequest ($base + "/ms2_live/MS2_RSS_100_Collector.ps1" + $cache) -OutFile $collector -UseBasicParsing
Invoke-WebRequest ($base + "/ms2_live/BUILD_KIOXIA_TIME_STATS.ps1" + $cache) -OutFile $stats -UseBasicParsing

Write-Host "[3/4] Re-saving as UTF-8 BOM and validating syntax..." -ForegroundColor Cyan
$utf8bom = New-Object System.Text.UTF8Encoding($true)
foreach($p in @($collector,$stats)) {
    $txt = [IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($p,$txt,$utf8bom)
    $tokens=$null
    $errors=$null
    [System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors) | Out-Null
    if($errors.Count -gt 0) {
        $errors | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
        throw ("Syntax validation failed: " + $p)
    }
}

Write-Host "[4/4] Rebuilding KIOXIA time stats..." -ForegroundColor Cyan
& $stats -RecordsRoot (Join-Path $RuntimeDir "records") -OutputJson (Join-Path $RuntimeDir "kioxia_time_stats.json") -OutputCsv (Join-Path $RuntimeDir "kioxia_time_stats.csv")

Write-Host ""
Write-Host "DATA QUALITY V1 APPLIED" -ForegroundColor Green
Write-Host ("Runtime: " + $RuntimeDir) -ForegroundColor Cyan
Write-Host "Next: start AI Cockpit with AI Cockpit START V6." -ForegroundColor Yellow
