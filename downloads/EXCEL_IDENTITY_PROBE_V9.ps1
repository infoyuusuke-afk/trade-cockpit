param(
    [string]$WorkbookPath = "",
    [int]$ExpectedExcelPid = 0,
    [string]$ResultPath = "",
    [string]$ProgressPath = "",
    [int]$AttemptBudgetSeconds = 35,
    [switch]$SelfTestHang
)

# Workbook identity probe. This process is the only place that calls
# BindToMoniker. The Controller watches this PID and kills it on a hard
# timeout. This process must never stop Excel.

$ErrorActionPreference = "Stop"

function Write-ProbeProgress([string]$Message) {
    $line = (Get-Date).ToString("HH:mm:ss") + " " + $Message
    Write-Output $line
    if ([string]::IsNullOrWhiteSpace($ProgressPath)) { return }
    try { [IO.File]::AppendAllText($ProgressPath, $line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false)) } catch {}
}

function Write-ProbeResult([hashtable]$Result) {
    $json = $Result | ConvertTo-Json -Compress
    if (-not [string]::IsNullOrWhiteSpace($ResultPath)) {
        [IO.File]::WriteAllText($ResultPath, $json, [System.Text.UTF8Encoding]::new($false))
    }
    Write-Output $json
}

function Release-ProbeCom($Object) {
    if ($null -eq $Object) { return }
    try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($Object) } catch {}
}

if ($SelfTestHang) {
    Write-ProbeProgress "Excel identity probe started"
    Write-ProbeProgress "Waiting for workbook ROT registration..."
    Start-Sleep -Seconds 120
    exit 0
}

Write-ProbeProgress "Excel identity probe started"
if ([string]::IsNullOrWhiteSpace($WorkbookPath) -or $ExpectedExcelPid -le 0) {
    Write-ProbeResult @{ ok = $false; code = "EXCEL_IDENTITY_PROBE_FAILED"; message = "workbook path or expected Excel PID missing" }
    exit 2
}

$started = Get-Date
$loopSeconds = [Math]::Max(1, $AttemptBudgetSeconds - 2)
$deadline = $started.AddSeconds($loopSeconds)
$attempt = 0
$selfSession = [int](Get-Process -Id $PID).SessionId

while ((Get-Date) -lt $deadline) {
    $attempt++
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-ProbeProgress ("Excel identity probe attempt " + $attempt + " / elapsed " + $elapsed + "s")
    Write-ProbeProgress "Waiting for workbook ROT registration..."
    $boundBook = $null
    $boundApp = $null
    try {
        $boundBook = [Runtime.InteropServices.Marshal]::BindToMoniker($WorkbookPath)
        if ($null -eq $boundBook) { throw "Workbook moniker not ready." }
        Write-ProbeProgress "Workbook moniker found"
        $fullName = [string]$boundBook.FullName
        if ($fullName -ine $WorkbookPath) {
            Write-ProbeResult @{
                ok = $false
                code = "EXCEL_IDENTITY_MISMATCH"
                full_name = $fullName
                message = "Canonical workbook mismatch"
            }
            exit 3
        }
        $boundApp = $boundBook.Application
        $hwnd = [Int64]$boundApp.Hwnd
        if ($hwnd -eq 0) { throw "Excel HWND not ready." }
        Write-ProbeProgress "Excel HWND verified"
        $owner = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { [Int64]$_.MainWindowHandle -eq $hwnd } | Select-Object -First 1)
        if ($owner.Count -lt 1 -or [int]$owner[0].Id -ne $ExpectedExcelPid) {
            throw "Excel PID does not match the Controller-launched process."
        }
        if ([int]$owner[0].SessionId -ne $selfSession) {
            Write-ProbeResult @{
                ok = $false
                code = "EXCEL_IDENTITY_MISMATCH"
                full_name = $fullName
                hwnd = $hwnd
                excel_pid = [int]$owner[0].Id
                message = "Excel session does not match the probe process"
            }
            exit 3
        }
        Write-ProbeProgress "Excel PID verified"
        Write-ProbeProgress "Excel identity verified"
        Write-ProbeResult @{
            ok = $true
            code = "VERIFIED"
            full_name = $fullName
            hwnd = $hwnd
            excel_pid = $ExpectedExcelPid
            session_id = $selfSession
            message = "Excel identity verified"
        }
        exit 0
    } catch {
        Write-ProbeProgress ("probe attempt failed: " + $_.Exception.Message)
    } finally {
        Release-ProbeCom $boundApp
        Release-ProbeCom $boundBook
    }
    Start-Sleep -Milliseconds 400
}

Write-ProbeResult @{
    ok = $false
    code = "EXCEL_IDENTITY_PROBE_FAILED"
    message = "Workbook identity was not verified before the helper budget elapsed"
}
exit 2
