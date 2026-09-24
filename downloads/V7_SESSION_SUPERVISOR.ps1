
param(
    [Parameter(Mandatory=$true)][string]$StateFile,
    [int]$PollMilliseconds = 500
)

$ErrorActionPreference="SilentlyContinue"

function Read-State {
    try{
        if(-not(Test-Path -LiteralPath $StateFile)){return $null}
        return (Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json)
    }catch{
        return $null
    }
}

function Stop-Pid([int]$Pid){
    if($Pid -le 0 -or $Pid -eq $PID){return}
    try{Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue}catch{}
}

$misses=0
while($true){
    $s=Read-State
    if($null -eq $s){break}

    $excelPid=[int]$s.excel_pid
    $workbookName=[string]$s.workbook_name
    $xp=Get-Process -Id $excelPid -ErrorAction SilentlyContinue

    $closed=$false
    if($null -eq $xp){
        $closed=$true
    }elseif($xp.MainWindowHandle -eq 0){
        $misses++
    }elseif([string]::IsNullOrWhiteSpace($xp.MainWindowTitle)){
        $misses++
    }elseif($xp.MainWindowTitle -notlike ("*"+$workbookName+"*")){
        $misses++
    }else{
        $misses=0
    }

    if($misses -ge 6){$closed=$true}

    if($closed){
        foreach($name in @("collector_pid","collector_starter_pid","watcher_pid","heartbeat_pid","bridge_pid","gateway_pid")){
            try{
                $value=$s.PSObject.Properties[$name].Value
                if($null -ne $value){Stop-Pid ([int]$value)}
            }catch{}
        }

        Start-Sleep -Seconds 2

        $xp=Get-Process -Id $excelPid -ErrorAction SilentlyContinue
        if($null -ne $xp){
            if($xp.MainWindowHandle -eq 0 -or [string]::IsNullOrWhiteSpace($xp.MainWindowTitle) -or $xp.MainWindowTitle -notlike ("*"+$workbookName+"*")){
                Stop-Pid $excelPid
            }
        }

        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
        break
    }

    Start-Sleep -Milliseconds $PollMilliseconds
}
