param(
    [string]$RuntimeDir = (Join-Path ([Environment]::GetFolderPath("Desktop")) "デイトレ\MarketSpeed II RSS\files"),
    [int]$Port = 28581,
    [string]$RemoteBase = "https://infoyuusuke-afk.github.io/trade-cockpit"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    $runtimeCandidates = @(
        (Join-Path $env:USERPROFILE "Desktop\デイトレ\MarketSpeed II RSS\files"),
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "デイトレ\MarketSpeed II RSS\files"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop\デイトレ\MarketSpeed II RSS\files")
    ) | Select-Object -Unique
    foreach ($candidate in $runtimeCandidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "live_ms2.json")) {
            $RuntimeDir = $candidate
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
        foreach ($candidate in $runtimeCandidates) {
            if (Test-Path -LiteralPath $candidate) {
                $RuntimeDir = $candidate
                break
            }
        }
    }
}
if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    throw "MS2 runtime directory could not be resolved."
}

$liveJson = Join-Path $RuntimeDir "live_ms2.json"
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$Port)
$utf8 = [Text.UTF8Encoding]::new($false)

function Get-ContentType([string]$path) {
    switch -Regex ($path.ToLowerInvariant()) {
        '\.html?$' { return 'text/html; charset=utf-8' }
        '\.css$'   { return 'text/css; charset=utf-8' }
        '\.js$'    { return 'application/javascript; charset=utf-8' }
        '\.json$'  { return 'application/json; charset=utf-8' }
        '\.svg$'   { return 'image/svg+xml' }
        '\.png$'   { return 'image/png' }
        '\.jpe?g$' { return 'image/jpeg' }
        '\.webp$'  { return 'image/webp' }
        '\.ico$'   { return 'image/x-icon' }
        '\.woff2$' { return 'font/woff2' }
        default     { return 'application/octet-stream' }
    }
}

function Send-Response($stream,[string]$status,[string]$contentType,[byte[]]$body) {
    $headers = "HTTP/1.1 $status`r`nContent-Type: $contentType`r`nContent-Length: $($body.Length)`r`nCache-Control: no-store`r`nAccess-Control-Allow-Origin: *`r`nConnection: close`r`n`r`n"
    $hb=[Text.Encoding]::ASCII.GetBytes($headers)
    $stream.Write($hb,0,$hb.Length)
    if($body.Length -gt 0){$stream.Write($body,0,$body.Length)}
    $stream.Flush()
}

Add-Type -AssemblyName System.Net.Http
$handler=[System.Net.Http.HttpClientHandler]::new()
$handler.AutomaticDecompression=[System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
$http=[System.Net.Http.HttpClient]::new($handler)
$http.Timeout=[TimeSpan]::FromSeconds(15)

try {
    $listener.Start()
    Write-Host ("AI Cockpit Local Gateway: http://127.0.0.1:{0}/?live=1" -f $Port) -ForegroundColor Green
    Write-Host ("Local LIVE JSON: " + $liveJson) -ForegroundColor Cyan
    while($true){
        $client=$listener.AcceptTcpClient()
        try {
            $stream=$client.GetStream()
            $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::ASCII,$false,4096,$true)
            $requestLine=$reader.ReadLine()
            while(($line=$reader.ReadLine()) -ne $null -and $line -ne ""){}
            if([string]::IsNullOrWhiteSpace($requestLine)){continue}
            $parts=$requestLine -split ' '
            $method=$parts[0]
            $rawPath=if($parts.Count -ge 2){$parts[1]}else{'/'}
            if($method -eq 'OPTIONS'){
                Send-Response $stream '204 No Content' 'text/plain' ([byte[]]@())
                continue
            }
            if($method -ne 'GET'){
                Send-Response $stream '405 Method Not Allowed' 'text/plain; charset=utf-8' ($utf8.GetBytes('GET only'))
                continue
            }

            $uri=[Uri]("http://127.0.0.1:"+$Port+$rawPath)
            $path=$uri.AbsolutePath
            if($path -eq '/health'){
                $payload=[ordered]@{
                    status='ok'
                    port=$Port
                    live_json_exists=(Test-Path -LiteralPath $liveJson)
                    live_json_mtime=if(Test-Path -LiteralPath $liveJson){(Get-Item -LiteralPath $liveJson).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')}else{$null}
                    now=(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
                } | ConvertTo-Json
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes($payload))
                continue
            }
            if($path -eq '/live_ms2.json'){
                if(Test-Path -LiteralPath $liveJson){
                    $bytes=[IO.File]::ReadAllBytes($liveJson)
                    Send-Response $stream '200 OK' 'application/json; charset=utf-8' $bytes
                } else {
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes('{"status":"waiting","reason":"live_ms2.json not found"}'))
                }
                continue
            }

            $remotePath=if($path -eq '/'){'/index.html'}else{$path}
            $remoteUrl=$RemoteBase.TrimEnd('/')+$remotePath
            if(-not [string]::IsNullOrWhiteSpace($uri.Query)){$remoteUrl += $uri.Query}
            try {
                $resp=$http.GetAsync($remoteUrl).Result
                if(-not $resp.IsSuccessStatusCode){
                    Send-Response $stream ([string]([int]$resp.StatusCode)+' Remote Error') 'text/plain; charset=utf-8' ($utf8.GetBytes("Remote fetch failed: "+$remoteUrl))
                    continue
                }
                $bytes=$resp.Content.ReadAsByteArrayAsync().Result
                $ct=Get-ContentType $remotePath
                if($ct -eq 'application/octet-stream' -and $resp.Content.Headers.ContentType){$ct=[string]$resp.Content.Headers.ContentType}
                Send-Response $stream '200 OK' $ct $bytes
            } catch {
                Send-Response $stream '502 Bad Gateway' 'text/plain; charset=utf-8' ($utf8.GetBytes("Gateway error: "+$_.Exception.Message))
            }
        } catch {
        } finally {
            $client.Close()
        }
    }
}
finally {
    $listener.Stop()
    $http.Dispose()
}
