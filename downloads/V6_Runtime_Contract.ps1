# V6 runtime identity and installation contract. Safe to dot-source in tests.
$V6RuntimeBuild = 'MS2-RUNTIME-20260925-02'
$V6RuntimeFiles = @('MS2_RSS_100_Collector.ps1','Kioxia_RSS_Live_Watcher.ps1','Kioxia_Safety_Heartbeat.ps1')

function Assert-V6Build([string]$Path) {
    $text = [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)
    $pattern = '(?m)^# V6_RUNTIME_BUILD: ' + [regex]::Escape($V6RuntimeBuild) + '\r?$'
    if ([regex]::Matches($text,$pattern).Count -ne 1) { throw "Unexpected runtime build: $Path; expected=$V6RuntimeBuild" }
}

function Resolve-V6InstallRuntime([string]$RootDir,[string]$ExplicitDir,[string[]]$SearchRoots) {
    if ($ExplicitDir) {
        if (-not [IO.Path]::IsPathRooted($ExplicitDir)) { throw 'RuntimeDir must be absolute.' }
        $resolved = [IO.Path]::GetFullPath($ExplicitDir)
    } elseif (Test-Path -LiteralPath (Join-Path $RootDir 'V6_RUNTIME.json')) {
        $saved = [IO.File]::ReadAllText((Join-Path $RootDir 'V6_RUNTIME.json')) | ConvertFrom-Json
        if (-not $saved.runtimeDir -or -not [IO.Path]::IsPathRooted($saved.runtimeDir)) { throw 'Invalid saved RuntimeDir. Reinstall with -RuntimeDir.' }
        $resolved = [IO.Path]::GetFullPath($saved.runtimeDir)
    } else {
        $hits = @(foreach ($dir in ($SearchRoots | Select-Object -Unique)) {
            if ($dir -and (Test-Path -LiteralPath $dir)) {
                Get-ChildItem -LiteralPath $dir -Recurse -File -Filter 'MS2_RSS_100_Collector.ps1' -ErrorAction Stop |
                    Where-Object { $_.Directory.Name -eq 'files' -and $_.Directory.Parent.Name -eq 'MarketSpeed II RSS' } |
                    ForEach-Object { $_.Directory.FullName }
            }
        })
        $hits = @($hits | Sort-Object -Unique)
        if ($hits.Count -ne 1) { throw ('RuntimeDir is ambiguous or missing. Specify -RuntimeDir. Candidates: ' + ($hits -join '; ')) }
        $resolved = $hits[0]
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved 'MS2_RSS_100_Collector.ps1') -PathType Leaf)) { throw "Collector missing in RuntimeDir: $resolved" }
    return $resolved
}

function Assert-V6InstalledRuntime([string]$RootDir) {
    $manifest = [IO.File]::ReadAllText((Join-Path $RootDir 'V6_RUNTIME.json')) | ConvertFrom-Json
    if ($manifest.build -ne $V6RuntimeBuild -or -not $manifest.runtimeDir -or -not [IO.Path]::IsPathRooted($manifest.runtimeDir)) { throw 'Runtime manifest invalid. Reinstall V6.' }
    $dir = [IO.Path]::GetFullPath($manifest.runtimeDir)
    foreach ($name in $V6RuntimeFiles) {
        $path = Join-Path $dir $name
        Assert-V6Build $path
        $entry = @($manifest.files | Where-Object { $_.name -eq $name })
        if ($entry.Count -ne 1 -or $entry[0].path -ne $path -or $entry[0].sha256 -ne (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash) { throw "Runtime path/hash mismatch: $path" }
        Write-Host ("      Runtime: " + $path + " / build=" + $V6RuntimeBuild) -ForegroundColor DarkCyan
    }
    return $dir
}

function Test-V6ManagedProcess($Process) {
    if ($Process.ProcessId -eq $PID -or $Process.Name -notmatch '^(powershell|pwsh)\.exe$') { return $false }
    # Match the script passed to -File, never a name mentioned in -Command.
    $command=[string]$Process.CommandLine
    if ($command -match '(?i)(?:^|\s)-(?:Command|EncodedCommand)\s') { return $false }
    $match=[regex]::Match($command,'(?i)(?:^|\s)-File\s+(?:"([^"]+)"|(\S+))(?=\s|$)')
    if (-not $match.Success) { return $false }
    $path=if($match.Groups[1].Success){$match.Groups[1].Value}else{$match.Groups[2].Value}
    return (($path -split '[\\/]')[-1] -in $V6RuntimeFiles)
}

function Stop-V6RuntimeProcesses {
    $targets = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { Test-V6ManagedProcess $_ })
    foreach ($process in $targets) {
        Write-Host ("Stopping old runtime PID=" + $process.ProcessId) -ForegroundColor Yellow
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        Wait-Process -Id $process.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    if (@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { Test-V6ManagedProcess $_ }).Count -gt 0) { throw 'Old runtime is still running. Installation stopped.' }
}

function Test-V6EmptyExcel($App,$Books,$Protected) {
    # Only an invisible, idle application with no normal/protected workbook.
    return ($Books.Count -eq 0 -and $Protected.Count -eq 0 -and -not $App.Visible -and $App.Ready)
}

function Close-V6OrphanExcel {
    $app=$null; $books=$null; $protected=$null
    try {
        $app=[Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
        $books=$app.Workbooks
        $protected=$app.ProtectedViewWindows
        if (Test-V6EmptyExcel $app $books $protected) {
            # Recheck immediately before Quit; never suppress save prompts.
            if (Test-V6EmptyExcel $app $books $protected) { $app.Quit(); Write-Host 'Quit empty hidden Excel instance.' }
        }
    } catch { Write-Host 'Excel cleanup skipped: no safely identifiable empty instance.' }
    finally {
        foreach ($obj in @($protected,$books,$app)) {
            if ($null -ne $obj -and [Runtime.InteropServices.Marshal]::IsComObject($obj)) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($obj) }
        }
        $protected=$null; $books=$null; $app=$null
        [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    }
}
