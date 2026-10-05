param(
    [string]$RepoRoot = "",
    [string]$Destination = "",
    [switch]$DryRun,
    [switch]$SelfTest
)

# Copy docs/100oku master files to the Owner PC folder.
# This script does not start or stop Excel, MarketSpeed II, the Collector, the Gateway, or AI SHADOW.
# It does not submit orders. real_submit_allowed is unchanged.
# The Cloud Agent cannot write D:. This file is the Owner PC bridge.
$ErrorActionPreference = "Stop"

function Get-DefaultRepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    return (Split-Path -Parent $PSScriptRoot)
}

function Join-ChildPath([string]$Base, [string]$Name) {
    return [IO.Path]::Combine($Base, $Name)
}

function Read-Utf8Text([string]$Path) {
    return [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
}

function Get-Sha256Hex([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $hash = $sha.ComputeHash($stream)
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    return ([BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
}

function Get-JstNow {
    return [DateTime]::UtcNow.AddHours(9)
}

function Get-JstStamp([datetime]$Jst) {
    return $Jst.ToString("yyyy-MM-ddTHH:mm:ss") + "+09:00"
}

function Resolve-RepoPath([string]$Root, [string]$Relative) {
    $path = $Root
    foreach ($part in ($Relative -split '[\\/]')) {
        if (-not [string]::IsNullOrWhiteSpace($part)) {
            $path = Join-ChildPath $path $part
        }
    }
    return $path
}

function Get-RepoCommit([string]$Root) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $git) { return "" }
    $output = & git -C $Root rev-parse HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { return "" }
    return ([string]$output).Trim()
}

function Write-JsonFile([string]$Path, $Object) {
    $json = ($Object | ConvertTo-Json -Depth 6) + [Environment]::NewLine
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText($Path, $json, $utf8)
}

function Get-Manifest([string]$Root) {
    $path = Resolve-RepoPath $Root "docs/100oku/SYNC_MANIFEST.json"
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    return (Read-Utf8Text $path) | ConvertFrom-Json
}

function Get-SourcePlan([string]$Root, $Manifest) {
    $items = @()
    foreach ($relative in @($Manifest.required)) {
        $items += [ordered]@{
            Relative = [string]$relative
            Source = (Resolve-RepoPath $Root ([string]$relative))
            Required = $true
        }
    }
    $docxDir = Resolve-RepoPath $Root ([string]$Manifest.optional_docx_dir)
    if (Test-Path -LiteralPath $docxDir) {
        foreach ($file in @(Get-ChildItem -LiteralPath $docxDir -Filter *.docx -File -ErrorAction SilentlyContinue)) {
            $items += [ordered]@{
                Relative = ("docs/100oku/" + $file.Name)
                Source = $file.FullName
                Required = $false
            }
        }
    }
    return $items
}

function Test-SourceItem($Item) {
    if (-not (Test-Path -LiteralPath $Item.Source)) {
        return "MISSING"
    }
    $length = ([IO.FileInfo]$Item.Source).Length
    if ($length -le 0) {
        return "EMPTY"
    }
    return "OK"
}

function Test-DestinationDrive([string]$Dest) {
    if ($Dest -match '^[A-Za-z]:\\') {
        $root = $Dest.Substring(0, 2) + "\"
        return (Test-Path -LiteralPath $root)
    }
    return $true
}

function Copy-VerifiedFile([string]$Source, [string]$DestFile, [string]$ArchiveFile, [bool]$ForceBadHash) {
    $directory = [IO.Path]::GetDirectoryName($DestFile)
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    [IO.File]::Copy($Source, $DestFile, $true)
    $expected = Get-Sha256Hex $Source
    $actual = Get-Sha256Hex $DestFile
    if ($ForceBadHash) { $actual = "forced-mismatch" }
    if ([string]::IsNullOrWhiteSpace($actual) -or $actual -ne $expected) {
        if (-not [string]::IsNullOrWhiteSpace($ArchiveFile) -and (Test-Path -LiteralPath $ArchiveFile)) {
            [IO.File]::Copy($ArchiveFile, $DestFile, $true)
        } elseif (Test-Path -LiteralPath $DestFile) {
            Remove-Item -LiteralPath $DestFile -Force
        }
        return $false
    }
    return $true
}

function New-SyncRecord([string]$Commit, [string]$Root, [string]$Dest, [string]$Mode, [string]$Result, [string]$Archive, $Files) {
    return [ordered]@{
        synced_at = (Get-JstStamp (Get-JstNow))
        source_commit = $Commit
        repo_commit = $Commit
        repo_root = $Root
        destination = $Dest
        mode = $Mode
        result = $Result
        archive = $Archive
        written_by = "owner_pc_sync_script"
        cloud_agent_wrote_destination = $false
        files = @($Files)
    }
}

function Invoke-MasterSync([string]$Root, [string]$Dest, [bool]$IsDryRun, [bool]$ForceBadHash) {
    $manifest = Get-Manifest $Root
    if ($null -eq $manifest) {
        Write-Host "MASTER_SPEC_SYNC=FAIL"
        Write-Host "REASON=MANIFEST_MISSING"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        Write-Host "DESTINATION_WRITTEN=0"
        return 1
    }
    if ([string]::IsNullOrWhiteSpace($Dest)) {
        $Dest = [string]$manifest.destination
    }
    $commit = Get-RepoCommit $Root
    if ([string]::IsNullOrWhiteSpace($commit)) {
        Write-Host "MASTER_SPEC_SYNC=FAIL"
        Write-Host "REASON=REPO_COMMIT_MISSING"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        Write-Host "DESTINATION_WRITTEN=0"
        return 1
    }
    $plan = @(Get-SourcePlan $Root $manifest)
    $files = @()
    foreach ($item in $plan) {
        $state = Test-SourceItem $item
        $sha = ""
        $bytes = 0
        if ($state -eq "OK") {
            $sha = Get-Sha256Hex $item.Source
            $bytes = ([IO.FileInfo]$item.Source).Length
        }
        $files += [ordered]@{
            relative = $item.Relative
            name = [IO.Path]::GetFileName($item.Source)
            sha256 = $sha
            bytes = $bytes
            result = $state
        }
        if ($state -ne "OK") {
            Write-Host "MASTER_SPEC_SYNC=FAIL"
            Write-Host ("REASON=" + $state)
            Write-Host ("FILE=" + $item.Relative)
            Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
            Write-Host "DESTINATION_WRITTEN=0"
            return 1
        }
    }
    if ($IsDryRun) {
        $record = New-SyncRecord $commit $Root $Dest "dry-run" "DRY_RUN" "" $files
        Write-Host "MASTER_SPEC_SYNC=DRY_RUN"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        Write-Host "DESTINATION_WRITTEN=0"
        Write-Host ("REPO_COMMIT=" + $commit)
        Write-Host ("DESTINATION=" + $Dest)
        Write-Host "LAST_SYNC_PREVIEW_BEGIN"
        Write-Host (($record | ConvertTo-Json -Depth 6))
        Write-Host "LAST_SYNC_PREVIEW_END"
        return 0
    }
    if (-not (Test-DestinationDrive $Dest)) {
        Write-Host "MASTER_SPEC_SYNC=FAIL"
        Write-Host "REASON=DESTINATION_DRIVE_MISSING"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        Write-Host "DESTINATION_WRITTEN=0"
        return 1
    }
    if (-not (Test-Path -LiteralPath $Dest)) {
        New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    }
    $archiveName = ""
    $needsArchive = $false
    foreach ($item in $plan) {
        $leaf = [IO.Path]::GetFileName($item.Source)
        if (Test-Path -LiteralPath (Join-ChildPath $Dest $leaf)) { $needsArchive = $true }
    }
    if ($needsArchive) {
        $archiveName = (Get-JstNow).ToString("yyyy-MM-dd_HHmm")
        $archiveDir = Join-ChildPath (Join-ChildPath $Dest "archive") $archiveName
        if (Test-Path -LiteralPath $archiveDir) {
            $archiveName = (Get-JstNow).ToString("yyyy-MM-dd_HHmmss")
            $archiveDir = Join-ChildPath (Join-ChildPath $Dest "archive") $archiveName
        }
        New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
        foreach ($item in $plan) {
            $leaf = [IO.Path]::GetFileName($item.Source)
            $existing = Join-ChildPath $Dest $leaf
            if (-not (Test-Path -LiteralPath $existing)) { continue }
            $archived = Join-ChildPath $archiveDir $leaf
            [IO.File]::Copy($existing, $archived, $true)
            if ((Get-Sha256Hex $existing) -ne (Get-Sha256Hex $archived)) {
                Write-Host "MASTER_SPEC_SYNC=FAIL"
                Write-Host "REASON=ARCHIVE_HASH_MISMATCH"
                Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
                Write-Host "DESTINATION_WRITTEN=0"
                return 1
            }
        }
    }
    $copied = @()
    foreach ($item in $plan) {
        $leaf = [IO.Path]::GetFileName($item.Source)
        $destFile = Join-ChildPath $Dest $leaf
        $archiveFile = ""
        if (-not [string]::IsNullOrWhiteSpace($archiveName)) {
            $candidate = Join-ChildPath (Join-ChildPath (Join-ChildPath $Dest "archive") $archiveName) $leaf
            if (Test-Path -LiteralPath $candidate) { $archiveFile = $candidate }
        }
        $bad = $ForceBadHash -and ($copied.Count -eq 0)
        $ok = Copy-VerifiedFile $item.Source $destFile $archiveFile $bad
        if (-not $ok) {
            $fail = New-SyncRecord $commit $Root $Dest "sync" "FAIL" $archiveName $files
            Write-JsonFile (Join-ChildPath $Dest "LAST_SYNC.json") $fail
            Write-Host "MASTER_SPEC_SYNC=FAIL"
            Write-Host "REASON=HASH_MISMATCH"
            Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
            Write-Host "DESTINATION_WRITTEN=0"
            return 1
        }
        $copied += $leaf
    }
    foreach ($file in $files) {
        $file.result = "PASS"
        $file.destination_sha256 = Get-Sha256Hex (Join-ChildPath $Dest ([string]$file.name))
    }
    $pass = New-SyncRecord $commit $Root $Dest "sync" "PASS" $archiveName $files
    Write-JsonFile (Join-ChildPath $Dest "LAST_SYNC.json") $pass
    Write-Host "MASTER_SPEC_SYNC=PASS"
    Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
    Write-Host "DESTINATION_WRITTEN=1"
    Write-Host ("REPO_COMMIT=" + $commit)
    Write-Host ("DESTINATION=" + $Dest)
    if ([string]::IsNullOrWhiteSpace($archiveName)) {
        Write-Host "ARCHIVE=NONE_FIRST_SYNC"
    } else {
        Write-Host ("ARCHIVE=" + $archiveName)
    }
    return 0
}

function Invoke-SelfTest {
    $root = Get-DefaultRepoRoot
    $temp = Join-ChildPath ([IO.Path]::GetTempPath()) ("master-spec-sync-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    try {
        $first = Invoke-MasterSync $root $temp $false $false
        if ($first -ne 0) { return 1 }
        $last = Read-Utf8Text (Join-ChildPath $temp "LAST_SYNC.json") | ConvertFrom-Json
        if ($last.result -ne "PASS") { return 1 }
        if ($last.cloud_agent_wrote_destination -ne $false) { return 1 }
        if ($last.written_by -ne "owner_pc_sync_script") { return 1 }
        $manifest = Get-Manifest $root
        foreach ($relative in @($manifest.required)) {
            $leaf = [IO.Path]::GetFileName((Resolve-RepoPath $root ([string]$relative)))
            $source = Resolve-RepoPath $root ([string]$relative)
            $destFile = Join-ChildPath $temp $leaf
            if ((Get-Sha256Hex $source) -ne (Get-Sha256Hex $destFile)) { return 1 }
        }
        $second = Invoke-MasterSync $root $temp $false $false
        if ($second -ne 0) { return 1 }
        $archiveRoot = Join-ChildPath $temp "archive"
        $archives = @(Get-ChildItem -LiteralPath $archiveRoot -Directory -ErrorAction SilentlyContinue)
        if ($archives.Count -lt 1) { return 1 }
        $sampleLeaf = [IO.Path]::GetFileName((Resolve-RepoPath $root ([string]$manifest.required[0])))
        $archivedSample = Join-ChildPath $archives[0].FullName $sampleLeaf
        if (-not (Test-Path -LiteralPath $archivedSample)) { return 1 }
        if ((Get-Item -LiteralPath $archivedSample).Length -le 0) { return 1 }

        function New-FixtureRepo([string]$Path, [bool]$EmptyFirst, [bool]$DropSecond) {
            $docs = Join-ChildPath (Join-ChildPath $Path "docs") "100oku"
            New-Item -ItemType Directory -Path $docs -Force | Out-Null
            Copy-Item -LiteralPath (Resolve-RepoPath $root "docs/100oku/SYNC_MANIFEST.json") -Destination (Join-ChildPath $docs "SYNC_MANIFEST.json")
            $index = 0
            foreach ($relative in @($manifest.required)) {
                $leaf = [IO.Path]::GetFileName((Resolve-RepoPath $root ([string]$relative)))
                $target = Join-ChildPath $docs $leaf
                if ($EmptyFirst -and $index -eq 0) {
                    [IO.File]::WriteAllText($target, "")
                } elseif ($DropSecond -and $index -eq 1) {
                    $index += 1
                    continue
                } else {
                    Copy-Item -LiteralPath (Resolve-RepoPath $root ([string]$relative)) -Destination $target
                }
                $index += 1
            }
            & git -C $Path init -q 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { return $false }
            & git -C $Path add -- . 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { return $false }
            & git -C $Path -c user.email="sync-selftest@example.com" -c user.name="sync-selftest" commit -q -m "fixture" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { return $false }
            return $true
        }
        $emptyRoot = Join-ChildPath $temp "empty-root"
        if (-not (New-FixtureRepo $emptyRoot $true $false)) { return 1 }
        $emptyDest = Join-ChildPath $temp "empty-dest"
        $emptyCode = Invoke-MasterSync $emptyRoot $emptyDest $false $false
        if ($emptyCode -eq 0) { return 1 }
        if (Test-Path -LiteralPath (Join-ChildPath $emptyDest "LAST_SYNC.json")) { return 1 }
        $missingRoot = Join-ChildPath $temp "missing-root"
        if (-not (New-FixtureRepo $missingRoot $false $true)) { return 1 }
        $missingDest = Join-ChildPath $temp "missing-dest"
        $missingCode = Invoke-MasterSync $missingRoot $missingDest $false $false
        if ($missingCode -eq 0) { return 1 }
        if (Test-Path -LiteralPath (Join-ChildPath $missingDest "LAST_SYNC.json")) { return 1 }

        $mismatchDest = Join-ChildPath $temp "mismatch"
        New-Item -ItemType Directory -Path $mismatchDest -Force | Out-Null
        $seed = Resolve-RepoPath $root ([string]$manifest.required[0])
        $seedLeaf = [IO.Path]::GetFileName($seed)
        [IO.File]::Copy($seed, (Join-ChildPath $mismatchDest $seedLeaf), $true)
        $before = Get-Sha256Hex (Join-ChildPath $mismatchDest $seedLeaf)
        $mismatchCode = Invoke-MasterSync $root $mismatchDest $false $true
        if ($mismatchCode -eq 0) { return 1 }
        $restored = Get-Sha256Hex (Join-ChildPath $mismatchDest $seedLeaf)
        if ($restored -ne $before) { return 1 }
        $failRecord = Read-Utf8Text (Join-ChildPath $mismatchDest "LAST_SYNC.json") | ConvertFrom-Json
        if ($failRecord.result -ne "FAIL") { return 1 }
        if ($failRecord.cloud_agent_wrote_destination -ne $false) { return 1 }

        Write-Host "MASTER_SPEC_SYNC_SELFTEST=PASS"
        Write-Host "SELFTEST_WROTE_D_DRIVE=0"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        return 0
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Recurse -Force
        }
    }
}

$resolvedRoot = Get-DefaultRepoRoot
if ($SelfTest) {
    $selfCode = Invoke-SelfTest
    exit $selfCode
}
$syncCode = Invoke-MasterSync $resolvedRoot $Destination ([bool]$DryRun) $false
exit $syncCode
