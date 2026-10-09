param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [ValidateSet("main","fix/live-session-state-v1")]
    [string]$Channel = "main",
    [string]$RuntimeDir = ""
)

$ErrorActionPreference="Stop"
$ref = if($Channel -eq "main"){"main"}else{"fix/live-session-state-v1"}
$rawRef = if($Channel -eq "main"){"refs/heads/main"}else{"refs/heads/fix/live-session-state-v1"}
$base="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/"+$rawRef
$cache="?x="+(Get-Date -Format "yyyyMMddHHmmss")
Write-Host ("Install channel: "+$Channel+" / ref: "+$ref) -ForegroundColor Yellow
$launcher=Join-Path $Root "START_AI_COCKPIT_V6.ps1"
$gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$diag=Join-Path $Root "DIAG_AI_COCKPIT_V6_EXCEL.ps1"

# Windows PowerShell 5.1 treats UTF-8 without BOM as the active ANSI code page.
# GitHub raw files are UTF-8 without BOM, so Japanese string literals can be
# misparsed and produce fake syntax errors. Always normalize downloaded .ps1
# files to UTF-8 with BOM before parsing or executing them.
function Save-RemotePowerShellUtf8Bom([string]$Url,[string]$Destination) {
    $raw = $Destination + ".download"
    Invoke-WebRequest $Url -OutFile $raw -UseBasicParsing
    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        $text = [IO.File]::ReadAllText($raw,$utf8NoBom)
        [IO.File]::WriteAllText($Destination,$text,$utf8Bom)
    } finally {
        Remove-Item -LiteralPath $raw -Force -ErrorAction SilentlyContinue
    }
}

if(-not(Test-Path -LiteralPath $Root)){ New-Item -ItemType Directory -Path $Root -Force | Out-Null }

$contract=Join-Path $Root "V6_Runtime_Contract.ps1"
Save-RemotePowerShellUtf8Bom ($base+"/downloads/V6_Runtime_Contract.ps1"+$cache) $contract
. $contract
if ($V6RuntimeBuild -ne 'MS2-RUNTIME-20260925-02') { throw 'Runtime contract build mismatch.' }
$runtimeDir=Resolve-V6InstallRuntime $Root $RuntimeDir @([Environment]::GetFolderPath("Desktop"),(Join-Path $env:USERPROFILE "Desktop"),(Join-Path $env:USERPROFILE "OneDrive\Desktop"))
Write-Host ("Install RuntimeDir: "+$runtimeDir) -ForegroundColor Yellow
Stop-V6RuntimeProcesses
Close-V6OrphanExcel
$runtimeManifest=Join-Path $Root "V6_RUNTIME.json"
if(Test-Path -LiteralPath $runtimeManifest){
    Copy-Item -LiteralPath $runtimeManifest -Destination ($runtimeManifest+".bak") -Force
    Remove-Item -LiteralPath $runtimeManifest -Force
}

Write-Host "[1/6] Downloading V6 launcher, gateway, and Excel diagnostic..." -ForegroundColor Cyan
Save-RemotePowerShellUtf8Bom ($base+"/downloads/START_AI_COCKPIT_V6.ps1"+$cache) $launcher
Save-RemotePowerShellUtf8Bom ($base+"/downloads/AI_Cockpit_Local_Gateway.ps1"+$cache) $gateway
Save-RemotePowerShellUtf8Bom ($base+"/downloads/DIAG_AI_COCKPIT_V6_EXCEL.ps1"+$cache) $diag
$launcherText=[IO.File]::ReadAllText($launcher,[Text.Encoding]::UTF8)
if($launcherText -notmatch "V6-PS51-ASCII-20260925-01" -or $launcherText -notmatch "MS2-RUNTIME-20260925-02"){
    throw "Downloaded launcher is not the expected PS5.1-safe build. Ref/cache mismatch."
}

Write-Host "[2/6] Validating launcher/gateway/diagnostic syntax..." -ForegroundColor Cyan
$tokens=$null
$errors=$null
[System.Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$errors) | Out-Null
if($errors.Count -gt 0){
    $errors | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "V6 launcher syntax validation failed."
}
$gt=$null
$ge=$null
[System.Management.Automation.Language.Parser]::ParseFile($gateway,[ref]$gt,[ref]$ge) | Out-Null
if($ge.Count -gt 0){
    $ge | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "Local gateway syntax validation failed."
}
$dt=$null
$de=$null
[System.Management.Automation.Language.Parser]::ParseFile($diag,[ref]$dt,[ref]$de) | Out-Null
if($de.Count -gt 0){
    $de | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "Excel diagnostic syntax validation failed."
}

Write-Host "[3/6] Updating coherent MS2 runtime scripts..." -ForegroundColor Cyan
$runtimeFiles=@(
    "MS2_RSS_100_Collector.ps1",
    "Kioxia_Safety_Heartbeat.ps1",
    "Kioxia_RSS_Live_Watcher.ps1"
)
$stagedHashes=@{}
foreach($name in $runtimeFiles){
    $target=Join-Path $runtimeDir $name
    $tmp=$target+".new"
    Save-RemotePowerShellUtf8Bom ($base+"/ms2_live/"+$name+$cache) $tmp
    Assert-V6Build $tmp
    $rt=$null; $re=$null
    [System.Management.Automation.Language.Parser]::ParseFile($tmp,[ref]$rt,[ref]$re) | Out-Null
    if($re.Count -gt 0){ Remove-Item $tmp -Force -ErrorAction SilentlyContinue; throw ($name+" syntax validation failed.") }
    $stagedHashes[$name]=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash
}
# All downloads passed build and syntax checks before replacing any runtime file.
foreach($name in $runtimeFiles){
    $target=Join-Path $runtimeDir $name
    $tmp=$target+".new"
    if(Test-Path -LiteralPath $target){
        $backup=$target+".bak."+(Get-Date -Format "yyyyMMddHHmmss")
        Copy-Item -LiteralPath $target -Destination $backup -Force
    }
    Move-Item -LiteralPath $tmp -Destination $target -Force
    Assert-V6Build $target
    if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $stagedHashes[$name]){throw ("Installed file differs from download: "+$target)}
    Write-Host ("      Updated: "+$target+" / build="+$V6RuntimeBuild) -ForegroundColor Green
}

$entries=@(foreach($name in $runtimeFiles){
    $target=Join-Path $runtimeDir $name
    Assert-V6Build $target
    @{name=$name; path=$target; sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash}
})
@{build=$V6RuntimeBuild; runtimeDir=$runtimeDir; files=$entries} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath ($runtimeManifest+".new") -Encoding UTF8
Move-Item -LiteralPath ($runtimeManifest+".new") -Destination $runtimeManifest -Force
[void](Assert-V6InstalledRuntime $Root)
$marker=Join-Path $Root "V6_INSTALL_CHANNEL.txt"
@(
    "channel="+$Channel
    "ref="+$ref
    "installed_at="+(Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
    "launcher="+$launcher
) | Set-Content -LiteralPath $marker -Encoding UTF8

Write-Host "[4/6] Replacing startup shortcut..." -ForegroundColor Cyan
$desktop=[Environment]::GetFolderPath("Desktop")
$old=Join-Path $desktop "AI Cockpit START V5.lnk"
if(Test-Path -LiteralPath $old){ Remove-Item -LiteralPath $old -Force }
$lnk=Join-Path $desktop "AI Cockpit START V6.lnk"
$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut($lnk)
$s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$launcher+'" -Root "'+$Root+'"'
$s.WorkingDirectory=$Root
$s.WindowStyle=1
$s.Description="AI Cockpit V6 startup - auto closes on success"
$s.Save()

Write-Host "[5/6] Creating Excel diagnostic shortcut..." -ForegroundColor Cyan
$diagLnk=Join-Path $desktop "AI Cockpit DIAG V6.lnk"
$d=$ws.CreateShortcut($diagLnk)
$d.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$d.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "'+$diag+'"'
$d.WorkingDirectory=$Root
$d.WindowStyle=1
$d.Description="AI Cockpit V6 Excel startup diagnostic"
$d.Save()

Write-Host "[6/6] Install metadata complete." -ForegroundColor Cyan
Write-Host ""
Write-Host ("V6 INSTALL COMPLETE / "+$Channel) -ForegroundColor Green
Write-Host "Startup: AI Cockpit START V6" -ForegroundColor Yellow
Write-Host "Diagnostic: AI Cockpit DIAG V6" -ForegroundColor Yellow
