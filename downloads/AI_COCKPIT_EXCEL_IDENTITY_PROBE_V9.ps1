param(
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [Parameter(Mandatory = $true)][string]$ResultPath
)

# One-shot COM/ROT workbook identity probe for AI Cockpit Controller V9.
# The controller launches this in a separate powershell.exe process and
# kills it if BindToMoniker blocks. This process only reads workbook
# evidence. It must not stop Excel or any other process.

$ErrorActionPreference = "Stop"

function Write-IdentityProbeResult([string]$Path, $Payload) {
    $json = $Payload | ConvertTo-Json -Compress -Depth 4
    $tmp = $Path + "." + $PID + ".tmp"
    [IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

$payload = @{
    full_name = ""
    app_hwnd  = 0
    owner_pid = 0
    session_id = -1
    error = ""
}
$book = $null
$app = $null

try {
    if (-not (Test-Path -LiteralPath $RequestPath)) {
        throw "Identity probe request file is missing."
    }
    $request = [IO.File]::ReadAllText($RequestPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $workbookPath = [string]$request.workbook_path
    if ([string]::IsNullOrWhiteSpace($workbookPath)) {
        throw "Identity probe request is missing workbook_path."
    }

    $book = [Runtime.InteropServices.Marshal]::BindToMoniker($workbookPath)
    if ($null -eq $book) {
        throw "Workbook moniker not ready."
    }
    $payload.full_name = [string]$book.FullName
    $app = $book.Application
    if ($null -eq $app) {
        throw "Workbook application not ready."
    }
    $payload.app_hwnd = [int64]$app.Hwnd
    if ([int64]$payload.app_hwnd -ne 0) {
        $owners = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object {
            [int64]$_.MainWindowHandle -eq [int64]$payload.app_hwnd
        })
        if ($owners.Count -gt 0) {
            $payload.owner_pid = [int]$owners[0].Id
            $payload.session_id = [int]$owners[0].SessionId
        }
    }
} catch {
    $message = [string]$_.Exception.Message
    if ($message.Length -gt 500) { $message = $message.Substring(0, 500) }
    $payload.error = $message
} finally {
    if ($null -ne $app) {
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch {}
    }
    if ($null -ne $book) {
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book) } catch {}
    }
}

Write-IdentityProbeResult $ResultPath $payload
exit 0
