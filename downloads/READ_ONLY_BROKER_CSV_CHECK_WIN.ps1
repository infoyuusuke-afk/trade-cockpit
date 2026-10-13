# Offline, read-only broker CSV header candidate diagnostic for Windows PowerShell 5.1.
# No Python, no network, no broker credentials, no logging or filesystem writes.
# Does not authenticate broker records or inspect row contents beyond the first CSV header.
param([switch]$TestOnly, [string]$FilePath)
Add-Type -AssemblyName Microsoft.VisualBasic
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-HeaderCandidate([string]$SelectedPath) {
    if ([string]::IsNullOrWhiteSpace($SelectedPath)) { throw 'EMPTY_PATH' }
    $full = [System.IO.Path]::GetFullPath($SelectedPath)
    if ($full.StartsWith('\\') -or $full.StartsWith('//')) { throw 'REMOTE_PATH' }
    if ([System.IO.Path]::GetExtension($full).ToLowerInvariant() -ne '.csv') { throw 'NON_CSV' }
    $item = Get-Item -LiteralPath $full -ErrorAction Stop
    if ($item.PSIsContainer -or $item.Length -gt 8388608) { throw 'BAD_OR_LARGE_FILE' }
    $at = $item
    while ($null -ne $at) {
        if (($at.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'LINKED_PATH'
        }
        $at = $at.Parent
    }
    # Read once; only the first CSV record is parsed. No transaction rows are returned.
    $raw = [System.IO.File]::ReadAllBytes($full)
    if ($raw.Length -gt 8388608) { throw 'BAD_OR_LARGE_FILE' }
    $encodings = @(
        [System.Text.UTF8Encoding]::new($false, $true),
        [System.Text.Encoding]::GetEncoding(932, [System.Text.EncoderFallback]::ExceptionFallback, [System.Text.DecoderFallback]::ExceptionFallback)
    )
    $header = $null
    $encName = 'UNKNOWN'
    foreach ($enc in $encodings) {
        try {
            $sourceText = $enc.GetString($raw)
            $reader = [System.IO.StringReader]::new($sourceText)
            $parser = [Microsoft.VisualBasic.FileIO.TextFieldParser]::new($reader)
            try {
                $parser.TextFieldType = [Microsoft.VisualBasic.FileIO.FieldType]::Delimited
                $parser.SetDelimiters(',')
                $parser.HasFieldsEnclosedInQuotes = $true
                if (-not $parser.EndOfData) { $header = @($parser.ReadFields()) }
            } finally {
                $parser.Close()
                $reader.Close()
            }
            if ($null -ne $header) {
                $encName = if ($enc.CodePage -eq 65001) { 'UTF8' } else { 'CP932' }
                break
            }
        } catch [System.Text.DecoderFallbackException] {
            continue
        } catch [Microsoft.VisualBasic.FileIO.MalformedLineException] {
            continue
        }
    }
    if ($null -eq $header) {
        return @{ Status='BLOCKED'; Family='UNKNOWN'; Encoding='UNKNOWN'; ColumnCount=0; Authenticated=$false }
    }
    # A BOM is metadata, not part of the first column name.
    $names = @($header | ForEach-Object { [string]$_ -replace '^\uFEFF', '' })
    $known = @('約定日','銘柄コード','売買区分','数量［株］','単価［円］')
    $inquiry = @('約定時刻','約定数量','約定単価','コード')
    $legacy = $true
    foreach ($field in $known) { if ($names -cnotcontains $field) { $legacy=$false } }
    $inquiryPresent=$false
    foreach ($field in $inquiry) { if ($names -ccontains $field) { $inquiryPresent=$true } }
    $unique = @($names | Select-Object -Unique).Count -eq $names.Count
    $family = if ($legacy -and $inquiryPresent) { 'AMBIGUOUS' }
              elseif ($legacy) { 'LEGACY_HISTORY_CANDIDATE' }
              elseif ($inquiryPresent) { 'EXECUTION_INQUIRY_CANDIDATE' }
              else { 'UNKNOWN' }
    return @{
        Status = if ($family -eq 'LEGACY_HISTORY_CANDIDATE' -and $unique) { 'CANDIDATE_ONLY' } else { 'BLOCKED' }
        Family = $family
        Encoding = $encName
        ColumnCount = $names.Count
        Authenticated = $false
    }
}

function Format-SafeSummary($Result) {
    # Only output enum values derived from fixed code and a bounded count.
    $allowed = @('BLOCKED','CANDIDATE_ONLY')
    $families = @('UNKNOWN','AMBIGUOUS','LEGACY_HISTORY_CANDIDATE','EXECUTION_INQUIRY_CANDIDATE')
    $encodings = @('UNKNOWN','UTF8','CP932')
    if ($allowed -cnotcontains $Result.Status -or $families -cnotcontains $Result.Family -or
        $encodings -cnotcontains $Result.Encoding -or $Result.ColumnCount -lt 0 -or $Result.ColumnCount -gt 1000) {
        return 'BLOCKED'
    }
    return ('Status: ' + $Result.Status + [Environment]::NewLine +
            'Family: ' + $Result.Family + [Environment]::NewLine +
            'Encoding: ' + $Result.Encoding + [Environment]::NewLine +
            'Columns: ' + [int]$Result.ColumnCount + [Environment]::NewLine +
            '実約定・証券会社真正性・EV学習は確認していません。')
}

if ($TestOnly) {
    try {
        $result = Get-HeaderCandidate -SelectedPath $FilePath
        Write-Output (Format-SafeSummary $result)
        if ($result.Status -ne 'CANDIDATE_ONLY') { exit 2 }
        exit 0
    } catch {
        Write-Output 'Status: BLOCKED'
        exit 2
    }
}
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName Microsoft.VisualBasic
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'CSV形式のみ診断（完全ローカル・送信なし）'
    $dialog.Filter = 'CSVファイル (*.csv)|*.csv'
    $dialog.Multiselect = $false
    $dialog.CheckFileExists = $true
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $result = Get-HeaderCandidate -SelectedPath $dialog.FileName
    [System.Windows.Forms.MessageBox]::Show((Format-SafeSummary $result),'CSV形式診断') | Out-Null
    if ($result.Status -eq 'CANDIDATE_ONLY') { exit 0 }
    exit 2
} catch {
    [System.Windows.Forms.MessageBox]::Show('形式診断を完了できません。実績照合・EV学習・発注は実行していません。','CSV形式診断｜保留') | Out-Null
    exit 2
}
