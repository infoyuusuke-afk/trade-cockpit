$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../downloads/V6_Runtime_Contract.ps1')
function Assert($Condition,[string]$Message) { if(-not $Condition){throw $Message} }
function Must-Fail([scriptblock]$Action) {
    $failed=$false
    try { & $Action | Out-Null } catch { $failed=$true }
    Assert $failed 'Expected fail-closed rejection.'
}
$sandbox=Join-Path ([IO.Path]::GetTempPath()) ('v6-contract-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sandbox | Out-Null
try {
    $root=Join-Path $sandbox 'root'
    $desktop=Join-Path $sandbox 'desktop'
    $first=Join-Path $desktop 'one/MarketSpeed II RSS/files'
    $second=Join-Path $desktop 'two/MarketSpeed II RSS/files'
    foreach($dir in @($root,$first,$second)){New-Item -ItemType Directory -Path $dir -Force | Out-Null}
    foreach($dir in @($first,$second)) {
        foreach($name in $V6RuntimeFiles){
            [IO.File]::WriteAllText((Join-Path $dir $name),("# V6_RUNTIME_BUILD: "+$V6RuntimeBuild+"`n"),(New-Object Text.UTF8Encoding($true)))
        }
    }
    Must-Fail { Resolve-V6InstallRuntime $root '' @($desktop) }
    Assert ((Resolve-V6InstallRuntime $root $first @($desktop)) -eq $first) 'Explicit runtime must win.'
    $entries=@(foreach($name in $V6RuntimeFiles){
        $path=Join-Path $first $name
        @{name=$name;path=$path;sha256=(Get-FileHash -LiteralPath $path).Hash}
    })
    $manifest=Join-Path $root 'V6_RUNTIME.json'
    @{build=$V6RuntimeBuild;runtimeDir=$first;files=$entries}|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $manifest -Encoding UTF8
    Assert ((Resolve-V6InstallRuntime $root '' @($desktop)) -eq $first) 'Saved runtime must win over newer alternate copy.'
    Assert ((Assert-V6InstalledRuntime $root) -eq $first) 'Valid manifest rejected.'
    $collector=Join-Path $first $V6RuntimeFiles[0]
    $original=[IO.File]::ReadAllText($collector)
    [IO.File]::WriteAllText($collector,'# old build')
    Must-Fail { Assert-V6InstalledRuntime $root }
    [IO.File]::WriteAllText($collector,($original+'# tampered'),(New-Object Text.UTF8Encoding($true)))
    Must-Fail { Assert-V6InstalledRuntime $root }
    [IO.File]::WriteAllText($collector,$original,(New-Object Text.UTF8Encoding($true)))
    $entries[0].path=Join-Path $second $V6RuntimeFiles[0]
    @{build=$V6RuntimeBuild;runtimeDir=$first;files=$entries}|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $manifest -Encoding UTF8
    Must-Fail { Assert-V6InstalledRuntime $root }
    Remove-Item -LiteralPath $manifest
    Must-Fail { Assert-V6InstalledRuntime $root }
    foreach($name in $V6RuntimeFiles){
        Assert (Test-V6ManagedProcess ([pscustomobject]@{ProcessId=123456;Name='powershell.exe';CommandLine=('powershell.exe -NoExit -File "C:\old copy\'+$name+'" -WorkbookPath "C:\a.xlsx"')})) 'Managed process missed.'
    }
    foreach($cmd in @('powershell.exe -Command "Get-Content MS2_RSS_100_Collector.ps1"','powershell.exe -File "C:\other.ps1" -Note MS2_RSS_100_Collector.ps1','powershell.exe -File "C:\MS2_RSS_100_Collector.ps1.bak"')) {
        Assert (-not (Test-V6ManagedProcess ([pscustomobject]@{ProcessId=123456;Name='powershell.exe';CommandLine=$cmd}))) 'Unrelated process matched.'
    }
    $app=[pscustomobject]@{Visible=$false;Ready=$true}
    $books=[pscustomobject]@{Count=0};$protected=[pscustomobject]@{Count=0}
    Assert (Test-V6EmptyExcel $app $books $protected) 'Empty hidden idle instance should qualify.'
    $books.Count=1; Assert (-not (Test-V6EmptyExcel $app $books $protected)) 'Open workbook must be preserved.'
    $books.Count=0;$protected.Count=1;Assert (-not (Test-V6EmptyExcel $app $books $protected)) 'Protected workbook must be preserved.'
    $protected.Count=0;$app.Visible=$true;Assert (-not (Test-V6EmptyExcel $app $books $protected)) 'Visible Excel must be preserved.'
    $app.Visible=$false;$app.Ready=$false;Assert (-not (Test-V6EmptyExcel $app $books $protected)) 'Busy Excel must be preserved.'
    foreach($name in $V6RuntimeFiles){Assert-V6Build (Join-Path $PSScriptRoot ('../ms2_live/'+$name))}
    # Execute the actual installer deployment block with local downloads.
    # No Excel, process, network or shortcut operations run in this fixture.
    $repo=Split-Path $PSScriptRoot -Parent
    $installerText=[IO.File]::ReadAllText((Join-Path $repo 'downloads/INSTALL_AI_COCKPIT_V6.ps1'))
    $start=$installerText.IndexOf('Write-Host "[3/6]')
    $end=$installerText.IndexOf('$marker=Join-Path',$start)
    $deploy=[scriptblock]::Create($installerText.Substring($start,$end-$start))
    $Root=$root; $runtimeDir=$first; $runtimeManifest=$manifest
    $base='https://fixture'; $cache=''; $script:wrongBuild=$false
    function Save-RemotePowerShellUtf8Bom([string]$Url,[string]$Destination) {
        $name=($Url -split '/')[-1]
        $text=[IO.File]::ReadAllText((Join-Path $repo ('ms2_live/'+$name)))
        if($script:wrongBuild -and $name -eq 'Kioxia_RSS_Live_Watcher.ps1'){$text=$text.Replace($V6RuntimeBuild,'STALE')}
        [IO.File]::WriteAllText($Destination,$text,(New-Object Text.UTF8Encoding($true)))
    }
    $before=(Get-FileHash -LiteralPath $collector).Hash
    $script:wrongBuild=$true
    Must-Fail { & $deploy }
    Assert (-not(Test-Path -LiteralPath $manifest)) 'Failed download must not publish manifest.'
    Assert ((Get-FileHash -LiteralPath $collector).Hash -eq $before) 'Staging failure must preserve installed files.'
    $script:wrongBuild=$false
    & $deploy
    Assert ((Assert-V6InstalledRuntime $root) -eq $first) 'Installer and launcher disagree on runtime.'
    # Simulate old content reappearing immediately after the destination move.
    Remove-Item -LiteralPath $manifest
    function Move-Item {
        param($LiteralPath,$Destination,[switch]$Force)
        Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
        if($Destination -eq $collector){[IO.File]::WriteAllText($Destination,'# stale destination')}
    }
    Must-Fail { & $deploy }
    Assert (-not(Test-Path -LiteralPath $manifest)) 'Post-copy stale file must not publish success.'
    Remove-Item Function:\Move-Item
    Write-Host 'PASS runtime identity, duplicate candidates, stale/tampered files, missing manifest, process selection, Excel preservation'
} finally {
    # Only remove the unique directory created by this test.
    $resolved=[IO.Path]::GetFullPath($sandbox)
    if($resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolved -Leaf) -like 'v6-contract-*'){
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
