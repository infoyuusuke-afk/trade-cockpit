
param(
    [string]$Root="C:\AI_Cockpit_OneClick_Starter",
    [string]$RuntimeDir="C:\Users\yusuk\Desktop\デイトレ\MarketSpeed II RSS\files",
    [bool]$StartNow=$true
)

$ErrorActionPreference="Stop"
$Base="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/refs/heads/fix/runtime-supervisor-v7"
$Cache="?v="+(Get-Date -Format "yyyyMMddHHmmss")
$Build="V7-RUNTIME-SUPERVISOR-20260925-01"

function Save-RemotePowerShellUtf8Bom([string]$Url,[string]$Destination){
    $raw=$Destination+".download"
    Invoke-WebRequest ($Url+$Cache) -OutFile $raw -UseBasicParsing
    try{
        $utf8NoBom=New-Object System.Text.UTF8Encoding($false)
        $utf8Bom=New-Object System.Text.UTF8Encoding($true)
        $text=[IO.File]::ReadAllText($raw,$utf8NoBom)
        [IO.File]::WriteAllText($Destination,$text,$utf8Bom)
    }finally{
        Remove-Item -LiteralPath $raw -Force -ErrorAction SilentlyContinue
    }
}

function Assert-Syntax([string]$Path){
    $tokens=$null
    $errors=$null
    [System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors) | Out-Null
    if($errors.Count -gt 0){
        $errors | ForEach-Object{Write-Host ($Path+": "+$_.Message) -ForegroundColor Red}
        throw ("PowerShell syntax validation failed: "+$Path)
    }
}

function Stop-LegacyManaged {
    $patterns=@(
        "MS2_RSS_100_Collector.ps1",
        "Kioxia_Safety_Heartbeat.ps1",
        "Kioxia_RSS_Live_Watcher.ps1",
        "AI_Cockpit_Local_Gateway.ps1",
        "V7_JSON_BRIDGE.ps1",
        "V7_COLLECTOR_STARTER.ps1",
        "V7_SESSION_SUPERVISOR.ps1"
    )
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object{
        $cmd=[string]$_.CommandLine
        if([string]::IsNullOrWhiteSpace($cmd)){return}
        foreach($p in $patterns){
            if($cmd -match [regex]::Escape($p)){
                try{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}catch{}
                break
            }
        }
    }
}

if(-not(Test-Path -LiteralPath $Root)){New-Item -ItemType Directory -Path $Root -Force | Out-Null}
if(-not(Test-Path -LiteralPath $RuntimeDir)){throw "RuntimeDir not found: $RuntimeDir"}
$excelDir=Join-Path $Root "Excel"
if(-not(Test-Path -LiteralPath $excelDir)){New-Item -ItemType Directory -Path $excelDir -Force | Out-Null}
$book=Join-Path $excelDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
if(-not(Test-Path -LiteralPath $book)){throw "Canonical workbook not found: $book"}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " AI COCKPIT V7 CLEAN INSTALL" -ForegroundColor Cyan
Write-Host (" "+$Build) -ForegroundColor DarkCyan
Write-Host "==================================================" -ForegroundColor Cyan

$existingStop=Join-Path $Root "STOP_AI_COCKPIT_V7.ps1"
if(Test-Path -LiteralPath $existingStop){
    try{& $existingStop -Root $Root | Out-Null}catch{}
}
Stop-LegacyManaged
Start-Sleep -Seconds 1

$targetTitle="Kioxia_MS2_RSS_Live_Signals"
foreach($xp in @(Get-Process EXCEL -ErrorAction SilentlyContinue)){
    if($xp.MainWindowHandle -eq 0 -or $xp.MainWindowTitle -like ("*"+$targetTitle+"*")){
        try{Stop-Process -Id $xp.Id -Force -ErrorAction SilentlyContinue}catch{}
    }
}

$stage=Join-Path $env:TEMP ("AI_COCKPIT_V7_STAGE_"+[Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage -Force | Out-Null

try{
    $rootFiles=@(
        "START_AI_COCKPIT_V7.ps1",
        "STOP_AI_COCKPIT_V7.ps1",
        "V7_JSON_BRIDGE.ps1",
        "V7_COLLECTOR_STARTER.ps1",
        "V7_SESSION_SUPERVISOR.ps1",
        "AI_Cockpit_Local_Gateway.ps1"
    )
    $runtimeFiles=@(
        "MS2_RSS_100_Collector.ps1",
        "Kioxia_Safety_Heartbeat.ps1",
        "Kioxia_RSS_Live_Watcher.ps1"
    )

    Write-Host "[1/5] Downloading V7 components..." -ForegroundColor Cyan
    foreach($name in $rootFiles){
        $tmp=Join-Path $stage $name
        Save-RemotePowerShellUtf8Bom ($Base+"/downloads/"+$name) $tmp
        Assert-Syntax $tmp
        Write-Host ("      OK "+$name) -ForegroundColor Green
    }

    foreach($name in $runtimeFiles){
        $tmp=Join-Path $stage $name
        Save-RemotePowerShellUtf8Bom ($Base+"/ms2_live/"+$name) $tmp
        Assert-Syntax $tmp
        $head=Get-Content -LiteralPath $tmp -TotalCount 3 -ErrorAction SilentlyContinue
        if(($head -join " ") -notmatch "MS2-RUNTIME-20260925-02"){
            throw ("Unexpected runtime build: "+$name)
        }
        Write-Host ("      OK "+$name) -ForegroundColor Green
    }

    Write-Host "[2/5] Installing atomically..." -ForegroundColor Cyan
    foreach($name in $rootFiles){
        $src=Join-Path $stage $name
        $dst=Join-Path $Root $name
        if(Test-Path -LiteralPath $dst){
            Copy-Item -LiteralPath $dst -Destination ($dst+".bak."+(Get-Date -Format "yyyyMMddHHmmss")) -Force
        }
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    foreach($name in $runtimeFiles){
        $src=Join-Path $stage $name
        $dst=Join-Path $RuntimeDir $name
        if(Test-Path -LiteralPath $dst){
            Copy-Item -LiteralPath $dst -Destination ($dst+".bak."+(Get-Date -Format "yyyyMMddHHmmss")) -Force
        }
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }

    Write-Host "[3/5] Writing V7 integrity manifest..." -ForegroundColor Cyan
    $entries=@()
    foreach($name in $rootFiles){
        $p=Join-Path $Root $name
        $entries+=[ordered]@{name=$name;path=$p;sha256=(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash}
    }
    foreach($name in $runtimeFiles){
        $p=Join-Path $RuntimeDir $name
        $entries+=[ordered]@{name=$name;path=$p;sha256=(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash}
    }
    $manifest=[ordered]@{
        build=$Build
        installed_at=(Get-Date).ToString("o")
        branch="fix/runtime-supervisor-v7"
        runtime_dir=$RuntimeDir
        files=$entries
    }
    [IO.File]::WriteAllText((Join-Path $Root "V7_RUNTIME.json"),($manifest|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))

    Write-Host "[4/5] Creating desktop shortcuts..." -ForegroundColor Cyan
    $desktop=[Environment]::GetFolderPath("Desktop")
    $ws=New-Object -ComObject WScript.Shell

    foreach($oldName in @("AI Cockpit START V6.lnk","AI Cockpit START V7.lnk","AI Cockpit STOP V7.lnk")){
        $old=Join-Path $desktop $oldName
        if(Test-Path -LiteralPath $old){Remove-Item -LiteralPath $old -Force}
    }

    $startLink=Join-Path $desktop "AI Cockpit START V7.lnk"
    $s=$ws.CreateShortcut($startLink)
    $s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $Root "START_AI_COCKPIT_V7.ps1")+'" -Root "'+$Root+'" -RuntimeDir "'+$RuntimeDir+'"'
    $s.WorkingDirectory=$Root
    $s.WindowStyle=1
    $s.Description="AI Cockpit V7 supervised startup"
    $s.Save()

    $stopLink=Join-Path $desktop "AI Cockpit STOP V7.lnk"
    $q=$ws.CreateShortcut($stopLink)
    $q.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $q.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $Root "STOP_AI_COCKPIT_V7.ps1")+'" -Root "'+$Root+'"'
    $q.WorkingDirectory=$Root
    $q.WindowStyle=1
    $q.Description="Stop AI Cockpit V7 managed session"
    $q.Save()

    Write-Host "[5/5] Re-validating installed files..." -ForegroundColor Cyan
    foreach($e in $entries){
        if(-not(Test-Path -LiteralPath $e.path)){throw ("Installed file missing: "+$e.path)}
        $actual=(Get-FileHash -LiteralPath $e.path -Algorithm SHA256).Hash
        if($actual -ne $e.sha256){throw ("Installed hash mismatch: "+$e.path)}
    }

    Write-Host ""
    Write-Host "V7 INSTALL COMPLETE" -ForegroundColor Green
    Write-Host ("Runtime: "+$RuntimeDir) -ForegroundColor Green
    Write-Host "Desktop: AI Cockpit START V7" -ForegroundColor Yellow

    if($StartNow){
        Write-Host "Starting V7 now..." -ForegroundColor Cyan
        Start-Process -FilePath "powershell.exe" -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $Root "START_AI_COCKPIT_V7.ps1")+'" -Root "'+$Root+'" -RuntimeDir "'+$RuntimeDir+'"')
    }
}finally{
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
