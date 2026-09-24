
param(
    [Parameter(Mandatory=$true)][string]$WorkbookPath,
    [Parameter(Mandatory=$true)][string]$CollectorPath,
    [Parameter(Mandatory=$true)][string]$StateFile,
    [Parameter(Mandatory=$true)][string]$LogDir
)

$ErrorActionPreference="Stop"
$bookName=[IO.Path]::GetFileName($WorkbookPath)
$stdout=Join-Path $LogDir "collector_v7_stdout.log"
$stderr=Join-Path $LogDir "collector_v7_stderr.log"

function Release-ComObjectSafe($obj){
    if($null -eq $obj){return}
    try{
        if([Runtime.InteropServices.Marshal]::IsComObject($obj)){
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($obj)
        }
    }catch{}
}

function Update-State([string]$Status,[int]$CollectorPid=0){
    try{
        if(-not(Test-Path -LiteralPath $StateFile)){return}
        $s=Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        $s.collector_status=$Status
        if($CollectorPid -gt 0){$s.collector_pid=$CollectorPid}
        $tmp=$StateFile+".tmp"
        [IO.File]::WriteAllText($tmp,($s|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $tmp -Destination $StateFile -Force
    }catch{}
}

Update-State "WAIT_DATA"

while($true){
    $state=$null
    try{$state=Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json}catch{break}
    $excelPid=[int]$state.excel_pid
    $xp=Get-Process -Id $excelPid -ErrorAction SilentlyContinue
    if($null -eq $xp){break}
    if($xp.MainWindowHandle -eq 0){break}

    $app=$null;$book=$null;$sheet=$null;$cell=$null
    $price=0.0
    try{
        $app=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        foreach($b in @($app.Workbooks)){
            if($b.Name -ieq $bookName){$book=$b;break}
            Release-ComObjectSafe $b
        }
        if($null -ne $book){
            $sheet=$book.Worksheets.Item("RSS接続")
            $cell=$sheet.Range("B3")
            $v=$cell.Value2
            [void][double]::TryParse([string]$v,[ref]$price)
        }
    }catch{
        $price=0.0
    }finally{
        Release-ComObjectSafe $cell
        Release-ComObjectSafe $sheet
        Release-ComObjectSafe $book
        Release-ComObjectSafe $app
        $cell=$null;$sheet=$null;$book=$null;$app=$null
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }

    if($price -gt 0){break}
    Start-Sleep -Seconds 1
}

if($price -le 0){
    Update-State "STOPPED_NO_QUOTE"
    exit 0
}

Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
$args='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$CollectorPath+'" -WorkbookPath "'+$WorkbookPath+'"'
$p=Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Update-State "STARTING" $p.Id

$livePath=Join-Path (Split-Path -Parent $CollectorPath) "live_ms2.json"
$started=Get-Date
while(-not $p.HasExited -and ((Get-Date)-$started).TotalSeconds -lt 90){
    if(Test-Path -LiteralPath $livePath){
        $age=((Get-Date)-(Get-Item -LiteralPath $livePath).LastWriteTime).TotalSeconds
        if($age -le 5){
            Update-State "LIVE" $p.Id
            exit 0
        }
    }
    Start-Sleep -Milliseconds 500
}

if($p.HasExited){
    Update-State ("FAILED_EXIT_"+$p.ExitCode) $p.Id
}else{
    Update-State "RUNNING_NO_FRESH_JSON" $p.Id
}
