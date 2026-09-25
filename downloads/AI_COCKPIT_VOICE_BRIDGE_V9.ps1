
param(
    [int]$Port = 28583,
    [string]$SbV2BaseUrl = "http://127.0.0.1:5000",
    [string]$ModelName = "amitaro",
    [string]$SpeakerName = "あみたろ",
    [string]$Style = "Neutral"
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback,$Port)

function Test-TcpPort([int]$p,[int]$timeoutMs=350){
    $c = New-Object Net.Sockets.TcpClient
    try {
        $a=$c.BeginConnect("127.0.0.1",$p,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne($timeoutMs,$false)){ return $false }
        $c.EndConnect($a); return $true
    } catch { return $false }
    finally { try{$c.Close()}catch{} }
}

function Test-Sbv2Ready {
    if(-not (Test-TcpPort 5000 300)){ return $false }
    try {
        $r=Invoke-WebRequest -UseBasicParsing -Uri ($SbV2BaseUrl.TrimEnd("/") + "/status") -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Parse-Query([string]$query){
    $h=@{}
    if([string]::IsNullOrWhiteSpace($query)){ return $h }
    foreach($pair in $query.TrimStart("?").Split("&")){
        if([string]::IsNullOrWhiteSpace($pair)){ continue }
        $kv=$pair.Split("=",2)
        $k=[Uri]::UnescapeDataString(($kv[0] -replace "\+"," "))
        $v=""
        if($kv.Count -gt 1){ $v=[Uri]::UnescapeDataString(($kv[1] -replace "\+"," ")) }
        $h[$k]=$v
    }
    return $h
}

function Normalize-SpeechText([string]$text){
    if([string]::IsNullOrWhiteSpace($text)){ return "" }
    $s=$text
    $repl=[ordered]@{
        "AIコクピット"="えーあいコクピット"
        "キオクシア"="きおくしあ"
        "VWAP上"="ぶいわっぷ、うえ"
        "VWAP下"="ぶいわっぷ、した"
        "VWAP"="ぶいわっぷ"
        "OR15"="おーあーる、じゅうご"
        "OR5"="おーあーる、ご"
        "EMA20"="いーえむえー、にじゅう"
        "EMA9"="いーえむえー、きゅう"
        "EMA"="いーえむえー"
        "GU"="ぎゃっぷあっぷ"
        "GD"="ぎゃっぷだうん"
        "歩み値"="あゆみね"
    }
    foreach($e in $repl.GetEnumerator()){ $s=$s.Replace([string]$e.Key,[string]$e.Value) }
    return $s.Replace("%","パーセント")
}

function Get-Profile([string]$level){
    switch(($level+"").ToUpperInvariant()){
        "HOT"    { return @{length=1.03;weight=0.70;split=0.35} }
        "DANGER" { return @{length=1.10;weight=0.80;split=0.45} }
        "WATCH"  { return @{length=1.13;weight=0.50;split=0.50} }
        default  { return @{length=1.20;weight=0.35;split=0.60} }
    }
}

function To-Inv([double]$v){ return $v.ToString([Globalization.CultureInfo]::InvariantCulture) }

function Invoke-Sbv2Wav([string]$text,[string]$level){
    if(-not (Test-Sbv2Ready)){ throw "SBV2_OFFLINE" }
    $normalized=Normalize-SpeechText $text
    if([string]::IsNullOrWhiteSpace($normalized)){ throw "EMPTY_TEXT" }
    if($normalized.Length -gt 500){ $normalized=$normalized.Substring(0,500) }
    $p=Get-Profile $level
    $q=[ordered]@{
        text=$normalized
        model_name=$ModelName
        speaker_name=$SpeakerName
        language="JP"
        length=(To-Inv ([double]$p.length))
        auto_split="true"
        split_interval=(To-Inv ([double]$p.split))
        style=$Style
        style_weight=(To-Inv ([double]$p.weight))
    }
    $parts=@()
    foreach($e in $q.GetEnumerator()){
        $parts += ([Uri]::EscapeDataString([string]$e.Key)+"="+[Uri]::EscapeDataString([string]$e.Value))
    }
    $uri=$SbV2BaseUrl.TrimEnd("/")+"/voice?"+($parts -join "&")
    $tmp=Join-Path $env:TEMP ("ai_cockpit_voice_bridge_"+[Guid]::NewGuid().ToString("N")+".wav")
    try{
        Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $tmp -TimeoutSec 30 | Out-Null
        if(-not(Test-Path -LiteralPath $tmp) -or (Get-Item -LiteralPath $tmp).Length -lt 1000){ throw "SBV2_EMPTY_AUDIO" }
        return [IO.File]::ReadAllBytes($tmp)
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Send-Response($stream,[string]$status,[string]$contentType,[byte[]]$body){
    $nl=[Environment]::NewLine
    $headers="HTTP/1.1 "+$status+$nl+
      "Content-Type: "+$contentType+$nl+
      "Content-Length: "+$body.Length+$nl+
      "Cache-Control: no-store"+$nl+
      "Access-Control-Allow-Origin: *"+$nl+
      "Access-Control-Allow-Methods: GET, OPTIONS"+$nl+
      "Access-Control-Allow-Headers: *"+$nl+
      "Connection: close"+$nl+$nl
    $hb=[Text.Encoding]::ASCII.GetBytes($headers)
    $stream.Write($hb,0,$hb.Length)
    if($body.Length -gt 0){ $stream.Write($body,0,$body.Length) }
    $stream.Flush()
}

function Send-Json($stream,[string]$status,$obj){
    $json=$obj|ConvertTo-Json -Depth 4 -Compress
    Send-Response $stream $status "application/json; charset=utf-8" ($utf8.GetBytes($json))
}

$listener.Start()
Write-Host ("AI Cockpit Voice Bridge V9 READY / 127.0.0.1:"+$Port) -ForegroundColor Green
try{
    while($true){
        $client=$listener.AcceptTcpClient()
        try{
            $stream=$client.GetStream()
            $reader=New-Object IO.StreamReader($stream,[Text.Encoding]::ASCII,$false,4096,$true)
            $requestLine=$reader.ReadLine()
            while(($line=$reader.ReadLine()) -ne $null -and $line -ne ""){}
            if([string]::IsNullOrWhiteSpace($requestLine)){ continue }
            $parts=$requestLine -split " "
            $method=$parts[0]
            $target=if($parts.Count -ge 2){$parts[1]}else{"/"}
            if($method -eq "OPTIONS"){
                Send-Response $stream "204 No Content" "text/plain" ([byte[]]@()); continue
            }
            if($method -ne "GET"){
                Send-Json $stream "405 Method Not Allowed" @{ok=$false;error="GET_ONLY"}; continue
            }
            $uri=[Uri]("http://127.0.0.1:"+$Port+$target)
            $path=$uri.AbsolutePath
            if($path -eq "/health"){
                $ready=Test-Sbv2Ready
                Send-Json $stream "200 OK" @{ok=$true;backend="Style-Bert-VITS2";model=$ModelName;speaker=$SpeakerName;sbv2_ready=$ready;port=$Port}
                continue
            }
            if($path -notin @("/speak","/announce")){
                Send-Json $stream "404 Not Found" @{ok=$false;error="NOT_FOUND"}; continue
            }
            $q=Parse-Query $uri.Query
            $text=[string]$q["text"]
            $level=[string]$q["level"]
            if([string]::IsNullOrWhiteSpace($level)){ $level="CALM" }
            if([string]::IsNullOrWhiteSpace($text)){
                Send-Json $stream "400 Bad Request" @{ok=$false;error="EMPTY_TEXT"}; continue
            }

            $mutex=$null; $acquired=$false
            try{
                $mutex=New-Object System.Threading.Mutex($false,"Global\KioxiaVoiceMutex")
                $acquired=$mutex.WaitOne(20000)
                if(-not $acquired){ throw "VOICE_BUSY" }
                $wav=Invoke-Sbv2Wav $text $level
                if($path -eq "/announce"){
                    $tmp=Join-Path $env:TEMP ("ai_cockpit_voice_play_"+[Guid]::NewGuid().ToString("N")+".wav")
                    try{
                        [IO.File]::WriteAllBytes($tmp,$wav)
                        $player=New-Object System.Media.SoundPlayer $tmp
                        $player.Load(); $player.PlaySync(); $player.Dispose()
                    } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
                    Send-Json $stream "200 OK" @{ok=$true;backend="Style-Bert-VITS2";level=$level}
                } else {
                    Send-Response $stream "200 OK" "audio/wav" $wav
                }
            } catch {
                $msg=$_.Exception.Message
                $status=if($msg -eq "SBV2_OFFLINE"){"503 Service Unavailable"}elseif($msg -eq "VOICE_BUSY"){"429 Too Many Requests"}else{"500 Internal Server Error"}
                Send-Json $stream $status @{ok=$false;error=$msg;backend="Style-Bert-VITS2"}
            } finally {
                if($acquired -and $null -ne $mutex){try{$mutex.ReleaseMutex()}catch{}}
                if($null -ne $mutex){$mutex.Dispose()}
            }
        } catch {
        } finally {
            try{$client.Close()}catch{}
        }
    }
} finally {
    try{$listener.Stop()}catch{}
}
