param(
    [string]$WorkbookPath = "",
    [int]$ExpectedExcelPid = 0,
    [int]$ControllerPid = 0,
    [string]$ResultPath = "",
    [string]$ProgressPath = "",
    [int]$AttemptBudgetSeconds = 35,
    [switch]$SelfTestHang
)

# Workbook identity probe. This process enumerates the Running Object Table
# and calls IRunningObjectTable.GetObject on the moniker Excel already
# registered. It does not re-parse that display name. Re-parsing cannot open
# the OneDrive item moniker Excel registers for a Desktop workbook. A hung
# COM call stays inside this process. The Controller kills this PID at its
# hard timeout. This process must never stop Excel.

$ErrorActionPreference = "Stop"

function Write-ProbeProgress([string]$Message) {
    $line = (Get-Date).ToString("HH:mm:ss") + " " + $Message
    Write-Output $line
    if ([string]::IsNullOrWhiteSpace($ProgressPath)) { return }
    try { [IO.File]::AppendAllText($ProgressPath, $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false)) } catch {}
}

if ($SelfTestHang) {
    Write-ProbeProgress "Excel identity probe started"
    Write-ProbeProgress "Waiting for workbook ROT registration..."
    Start-Sleep -Seconds 120
    exit 0
}

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

public class ExcelIdentityRotHit {
    public string DisplayName;
    public object Target;
}

public class ExcelIdentityRot {
    [DllImport("ole32.dll")]
    public static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable prot);
    [DllImport("ole32.dll")]
    public static extern int CreateBindCtx(int reserved, out IBindCtx ppbc);

    public static List<ExcelIdentityRotHit> Find(string fullPath, string fileName) {
        var hits = new List<ExcelIdentityRotHit>();
        IRunningObjectTable rot;
        GetRunningObjectTable(0, out rot);
        IEnumMoniker enumMoniker;
        rot.EnumRunning(out enumMoniker);
        enumMoniker.Reset();
        IMoniker[] moniker = new IMoniker[1];
        IntPtr fetched = IntPtr.Zero;
        while (enumMoniker.Next(1, moniker, fetched) == 0) {
            IBindCtx bindCtx;
            CreateBindCtx(0, out bindCtx);
            string displayName = null;
            try { moniker[0].GetDisplayName(bindCtx, null, out displayName); }
            catch { continue; }
            if (!DisplayNameMatches(displayName, fullPath, fileName)) { continue; }
            object target = null;
            try { rot.GetObject(moniker[0], out target); }
            catch { continue; }
            if (target == null) { continue; }
            hits.Add(new ExcelIdentityRotHit { DisplayName = displayName, Target = target });
        }
        return hits;
    }

    static bool DisplayNameMatches(string displayName, string fullPath, string fileName) {
        if (string.IsNullOrEmpty(displayName) || string.IsNullOrEmpty(fileName)) { return false; }
        if (string.Equals(displayName, fullPath, StringComparison.OrdinalIgnoreCase)) { return true; }
        if (displayName.EndsWith("\\" + fileName, StringComparison.OrdinalIgnoreCase)) { return true; }
        if (displayName.EndsWith("/" + fileName, StringComparison.OrdinalIgnoreCase)) { return true; }
        return false;
    }
}

public class ExcelFileIdentity {
    [StructLayout(LayoutKind.Sequential)]
    struct ByHandle {
        public uint FileAttributes;
        public uint CreationLow;
        public uint CreationHigh;
        public uint AccessLow;
        public uint AccessHigh;
        public uint WriteLow;
        public uint WriteHigh;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandle(IntPtr handle, out ByHandle info);

    public static string Key(string path) {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
            ByHandle info;
            if (!GetFileInformationByHandle(stream.SafeFileHandle.DangerousGetHandle(), out info)) {
                throw new IOException("file identity unreadable");
            }
            return info.VolumeSerialNumber.ToString("X8") + ":" + info.FileIndexHigh.ToString("X8") + ":" + info.FileIndexLow.ToString("X8");
        }
    }
}

public class ExcelProcessWindows {
    delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool EnumChildWindows(IntPtr hWnd, EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, StringBuilder lParam, uint flags, uint timeoutMs, out IntPtr result);

    const uint WM_GETTEXT = 0x000D;
    const uint SMTO_ABORTIFHUNG = 0x0002;
    static EnumProc topCallback;
    static EnumProc childCallback;

    public static List<string> VisibleTexts(int processId) {
        var texts = new List<string>();
        topCallback = (hWnd, lParam) => {
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if ((int)pid != processId) { return true; }
            AddText(hWnd, texts);
            if (texts.Count >= 40) { return false; }
            childCallback = (child, childParam) => {
                AddText(child, texts);
                return texts.Count < 40;
            };
            EnumChildWindows(hWnd, childCallback, IntPtr.Zero);
            return texts.Count < 40;
        };
        EnumWindows(topCallback, IntPtr.Zero);
        return texts;
    }

    static void AddText(IntPtr hWnd, List<string> texts) {
        if (texts.Count >= 40) { return; }
        var sb = new StringBuilder(512);
        IntPtr unused;
        SendMessageTimeout(hWnd, WM_GETTEXT, (IntPtr)sb.Capacity, sb, SMTO_ABORTIFHUNG, 200, out unused);
        var text = sb.ToString().Trim();
        if (text.Length > 0) { texts.Add(text); }
    }
}
'@

function Save-ProbeResultFile([hashtable]$Result) {
    if ([string]::IsNullOrWhiteSpace($ResultPath)) { return }
    $json = $Result | ConvertTo-Json -Compress -Depth 4
    [IO.File]::WriteAllText($ResultPath, $json, [Text.UTF8Encoding]::new($false))
}

function Write-ProbeResult([hashtable]$Result) {
    Save-ProbeResultFile $Result
    Write-Output ($Result | ConvertTo-Json -Compress -Depth 4)
}

function Release-ProbeCom($Object) {
    if ($null -eq $Object) { return }
    try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($Object) } catch {}
}

function Test-LocalPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return ($Value -match '^[A-Za-z]:\\')
}

function Test-LaunchedPidAlive {
    try {
        $proc = Get-Process -Id $ExpectedExcelPid -ErrorAction Stop
        return -not $proc.HasExited
    } catch {
        return $false
    }
}

function Get-SeriousErrorPrompt {
    $texts = @()
    try { $texts = @([ExcelProcessWindows]::VisibleTexts($ExpectedExcelPid)) } catch { return "" }
    foreach ($text in $texts) {
        $value = [string]$text
        if ($value.IndexOf("重大なエラー", [StringComparison]::Ordinal) -ge 0) { return $value }
        if ($value.IndexOf("このドキュメントを開きますか", [StringComparison]::Ordinal) -ge 0) { return $value }
        if ($value.IndexOf("serious problem", [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $value }
        if ($value.IndexOf("serious error", [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $value }
    }
    return ""
}

function Stop-ProbeForProcessExit {
    $last.code = "EXCEL_PROCESS_EXITED"
    $last.ok = $false
    $last.last_error = "LAUNCHED_PID_EXITED"
    $last.excel_pid = $ExpectedExcelPid
    $last.message = "launched Excel PID " + $ExpectedExcelPid + " exited before identity verification"
    Write-ProbeProgress $last.message
    Write-ProbeResult $last
    exit 4
}

function Stop-ProbeForSeriousErrorPrompt([string]$DialogText) {
    $last.code = "EXCEL_SERIOUS_ERROR_PROMPT"
    $last.ok = $false
    $last.last_error = "PREVIOUS_SERIOUS_ERROR_DIALOG"
    $last.excel_pid = $ExpectedExcelPid
    if ($DialogText.Length -gt 300) { $DialogText = $DialogText.Substring(0, 300) }
    $last.dialog_text = $DialogText
    $last.message = "Excel showed the previous-serious-error prompt before identity verification. The dialog was not answered. COM identity was not called."
    Write-ProbeProgress ($last.message + " / dialog=" + $DialogText)
    Write-ProbeResult $last
    exit 5
}

function Test-WorkbookOpenBlocker {
    if (-not (Test-LaunchedPidAlive)) { Stop-ProbeForProcessExit }
    $prompt = Get-SeriousErrorPrompt
    if (-not [string]::IsNullOrWhiteSpace($prompt)) { Stop-ProbeForSeriousErrorPrompt $prompt }
}

Write-ProbeProgress "Excel identity probe started"
if ([string]::IsNullOrWhiteSpace($WorkbookPath) -or $ExpectedExcelPid -le 0 -or $ControllerPid -le 0) {
    Write-ProbeResult @{
        ok = $false
        code = "EXCEL_IDENTITY_PROBE_FAILED"
        message = "workbook path, launched Excel PID, or controller PID missing"
        last_error = "PROBE_ARGUMENTS_MISSING"
        expected_excel_pid = $ExpectedExcelPid
        parent_match = $false
        command_line_match = $false
        session_match = $false
        full_name_same_file = $false
        hwnd = 0
        excel_pid = 0
        rot_candidate_count = 0
        attempts = 0
    }
    exit 2
}

$bookFileName = [IO.Path]::GetFileName($WorkbookPath)
$started = Get-Date
$loopSeconds = [Math]::Max(1, $AttemptBudgetSeconds - 2)
$deadline = $started.AddSeconds($loopSeconds)
$attempt = 0
$selfSession = [int](Get-Process -Id $PID).SessionId
$last = @{
    ok = $false
    code = "EXCEL_IDENTITY_PROBE_FAILED"
    message = "Workbook identity was not verified before the helper budget elapsed"
    full_name = ""
    full_name_same_file = $false
    hwnd = 0
    excel_pid = 0
    expected_excel_pid = $ExpectedExcelPid
    session_match = $false
    command_line_match = $false
    command_line = ""
    parent_pid = 0
    parent_match = $false
    rot_candidate_count = 0
    last_error = "NOT_STARTED"
    attempts = 0
    dialog_text = ""
    real_submit_allowed = $false
}

while ((Get-Date) -lt $deadline) {
    $attempt++
    $last.attempts = $attempt
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-ProbeProgress ("Excel identity probe attempt " + $attempt + " / elapsed " + $elapsed + "s")
    Test-WorkbookOpenBlocker
    if ($attempt -eq 1) {
        Write-ProbeProgress "Watching launched Excel before COM identity"
        $warmupDeadline = (Get-Date).AddSeconds(3)
        while ((Get-Date) -lt $warmupDeadline -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 200
            Test-WorkbookOpenBlocker
        }
    }
    Write-ProbeProgress "Waiting for workbook ROT registration..."
    $hits = @()
    try {
        $hits = @([ExcelIdentityRot]::Find($WorkbookPath, $bookFileName))
    } catch {
        $last.last_error = "ROT_ENUMERATION_FAILED"
        $last.message = "unmatched: rot_moniker / last_error=ROT_ENUMERATION_FAILED / " + $_.Exception.Message
        Write-ProbeProgress ("probe attempt failed: " + $last.message)
        try { Save-ProbeResultFile $last } catch {}
        Start-Sleep -Milliseconds 400
        continue
    }
    $last.rot_candidate_count = @($hits).Count
    if ($last.rot_candidate_count -lt 1) {
        Test-WorkbookOpenBlocker
        $last.last_error = "ROT_MONIKER_NOT_REGISTERED"
        $last.message = "unmatched: rot_moniker,hwnd,pid,session,command_line,parent / last_error=" + $last.last_error + " / hwnd=" + $last.hwnd + " / excel_pid=" + $last.excel_pid
        Write-ProbeProgress ("probe attempt failed: " + $last.message)
        try { Save-ProbeResultFile $last } catch {}
        Start-Sleep -Milliseconds 400
        continue
    }
    Write-ProbeProgress "Workbook moniker found"
    $terminal = ""
    foreach ($hit in @($hits)) {
        $book = $null
        $app = $null
        $disposition = "next"
        try {
            $book = $hit.Target
            $name = [string]$book.Name
            if ($name -ine $bookFileName) {
                $last.last_error = "WORKBOOK_NAME_MISMATCH"
            } else {
                $fullName = [string]$book.FullName
                $last.full_name = $fullName
                $app = $book.Application
                $hwnd = [Int64]$app.Hwnd
                $last.hwnd = $hwnd
                if ($hwnd -eq 0) {
                    $last.last_error = "HWND_NOT_READY"
                } else {
                    Write-ProbeProgress "Excel HWND verified"
                    $owner = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { [Int64]$_.MainWindowHandle -eq $hwnd } | Select-Object -First 1)
                    if ($owner.Count -lt 1) {
                        $last.last_error = "HWND_PROCESS_NOT_READY"
                    } else {
                        $ownerPid = [int]$owner[0].Id
                        $last.excel_pid = $ownerPid
                        if ($ownerPid -ne $ExpectedExcelPid) {
                            $last.last_error = "PID_MISMATCH"
                        } else {
                            $last.session_match = ([int]$owner[0].SessionId -eq $selfSession)
                            if (-not $last.session_match) {
                                $last.last_error = "SESSION_MISMATCH"
                                $last.code = "EXCEL_IDENTITY_MISMATCH"
                                $last.message = "Excel session does not match the probe process"
                                $disposition = "fail"
                            } else {
                                $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ownerPid) -ErrorAction SilentlyContinue
                                if ($null -eq $info -or [string]::IsNullOrWhiteSpace([string]$info.CommandLine)) {
                                    $last.last_error = "COMMAND_LINE_NOT_VISIBLE"
                                    $last.command_line_match = $false
                                } else {
                                    $last.command_line = [string]$info.CommandLine
                                    $last.command_line_match = ($last.command_line.IndexOf($WorkbookPath, [StringComparison]::OrdinalIgnoreCase) -ge 0)
                                    $last.parent_pid = [int]$info.ParentProcessId
                                    $last.parent_match = ($last.parent_pid -eq $ControllerPid)
                                    $sameFile = $false
                                    $identityReady = $true
                                    if (Test-LocalPath $fullName) {
                                        if ([string]::Equals($fullName, $WorkbookPath, [StringComparison]::OrdinalIgnoreCase)) {
                                            $sameFile = $true
                                        } else {
                                            try {
                                                $sameFile = ([ExcelFileIdentity]::Key($WorkbookPath) -eq [ExcelFileIdentity]::Key($fullName))
                                            } catch {
                                                $last.last_error = "FULL_NAME_IDENTITY_UNREADABLE"
                                                $last.message = $_.Exception.Message
                                                $identityReady = $false
                                            }
                                            if ($identityReady -and -not $sameFile) {
                                                $last.full_name_same_file = $false
                                                $last.last_error = "FULL_NAME_DIFFERENT_FILE"
                                                $last.code = "EXCEL_IDENTITY_MISMATCH"
                                                $last.message = "Opened workbook is not the canonical file"
                                                $disposition = "fail"
                                            }
                                        }
                                    }
                                    if ($disposition -ne "fail" -and $identityReady) {
                                        $last.full_name_same_file = $sameFile
                                        if (-not $last.command_line_match) {
                                            $last.last_error = "COMMAND_LINE_MISMATCH"
                                        } elseif (-not $last.parent_match) {
                                            $last.last_error = "PARENT_MISMATCH"
                                        } elseif ((Test-LocalPath $fullName) -and -not $sameFile) {
                                            $last.last_error = "FULL_NAME_DIFFERENT_FILE"
                                        } else {
                                            Write-ProbeProgress "Excel PID verified"
                                            Write-ProbeProgress "Excel identity verified"
                                            $last.ok = $true
                                            $last.code = "VERIFIED"
                                            $last.last_error = ""
                                            $last.message = "Excel identity verified"
                                            $disposition = "ok"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } catch {
            $hresult = [uint32]0
            try { $hresult = [uint32]$_.Exception.HResult } catch {}
            # 0x80010001 RPC_E_CALL_REJECTED, 0x8001010A RPC_E_SERVERCALL_RETRYLATER,
            # 0x800AC472 Excel is in a dialog or edit. All three are startup races.
            if ($hresult -eq 0x80010001 -or $hresult -eq 0x8001010A -or $hresult -eq 0x800AC472) { $last.last_error = "EXCEL_BUSY" }
            else { $last.last_error = "COM_READ_FAILED" }
            $last.message = $_.Exception.Message
            $disposition = "next"
        } finally {
            Release-ProbeCom $app
            Release-ProbeCom $book
        }
        if ($disposition -eq "ok" -or $disposition -eq "fail") { $terminal = $disposition; break }
    }
    if ($terminal -eq "ok") {
        Write-ProbeResult $last
        exit 0
    }
    if ($terminal -eq "fail") {
        Write-ProbeResult $last
        exit 3
    }
    $unmatched = @()
    if ($last.rot_candidate_count -lt 1) { $unmatched += "rot_moniker" }
    if ([int64]$last.hwnd -eq 0) { $unmatched += "hwnd" }
    if ([int]$last.excel_pid -ne $ExpectedExcelPid) { $unmatched += "pid" }
    if (-not $last.session_match) { $unmatched += "session" }
    if (-not $last.command_line_match) { $unmatched += "command_line" }
    if (-not $last.parent_match) { $unmatched += "parent" }
    if ((Test-LocalPath ([string]$last.full_name)) -and -not $last.full_name_same_file) { $unmatched += "full_name" }
    $last.message = "unmatched: " + ($unmatched -join ",") + " / last_error=" + $last.last_error + " / full_name=" + $last.full_name + " / hwnd=" + $last.hwnd + " / excel_pid=" + $last.excel_pid + " / parent_pid=" + $last.parent_pid
    Write-ProbeProgress ("probe attempt failed: " + $last.message)
    try { Save-ProbeResultFile $last } catch {}
    Start-Sleep -Milliseconds 400
}

$last.code = "EXCEL_IDENTITY_PROBE_FAILED"
if ([string]$last.last_error -eq "LAUNCHED_PID_EXITED") {
    $last.code = "EXCEL_PROCESS_EXITED"
} elseif ([string]$last.last_error -eq "PREVIOUS_SERIOUS_ERROR_DIALOG") {
    $last.code = "EXCEL_SERIOUS_ERROR_PROMPT"
} elseif ([string]$last.last_error -in @("FULL_NAME_DIFFERENT_FILE", "SESSION_MISMATCH", "PID_MISMATCH")) {
    $last.code = "EXCEL_IDENTITY_MISMATCH"
}
Write-ProbeResult $last
exit 2
