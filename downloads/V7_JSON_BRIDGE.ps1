
param(
    [Parameter(Mandatory=$true)][string]$JsonFile,
    [int]$Port = 28580
)

$ErrorActionPreference = "Stop"
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,[int]$Port)
$utf8 = [Text.UTF8Encoding]::new($false)

function Get-ValidJsonBytes {
    param([string]$Path,[Text.UTF8Encoding]$Encoding)
    if(-not (Test-Path -LiteralPath $Path)){ return $null }
    for($attempt=1;$attempt -le 5;$attempt++){
        try{
            $text=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)
            if([string]::IsNullOrWhiteSpace($text)){ throw "empty json" }
            $null=$text | ConvertFrom-Json -ErrorAction Stop
            return $Encoding.GetBytes($text)
        }catch{
            Start-Sleep -Milliseconds 80
        }
    }
    return $null
}

try{
    $listener.Start()
    Write-Host ("V7 JSON BRIDGE READY 127.0.0.1:" + $Port) -ForegroundColor Green
    while($true){
        $client=$listener.AcceptTcpClient()
        try{
            $stream=$client.GetStream()
            $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::ASCII,$false,1024,$true)
            $requestLine=$reader.ReadLine()
            while(($line=$reader.ReadLine()) -ne $null -and $line -ne ""){}
            $method=if($requestLine){($requestLine -split ' ')[0]}else{"GET"}

            if($method -eq "OPTIONS"){
                $body=[byte[]]@()
                $status="204 No Content"
                $contentType="text/plain"
            }else{
                $body=Get-ValidJsonBytes -Path $JsonFile -Encoding $utf8
                if($null -ne $body){
                    $status="200 OK"
                    $contentType="application/json; charset=utf-8"
                }else{
                    $body=$utf8.GetBytes('{"status":"waiting","live":false}')
                    $status="503 Service Unavailable"
                    $contentType="application/json; charset=utf-8"
                }
            }

            $crlf=[Environment]::NewLine
            $headers="HTTP/1.1 "+$status+$crlf+
                "Content-Type: "+$contentType+$crlf+
                "Content-Length: "+$body.Length+$crlf+
                "Cache-Control: no-store"+$crlf+
                "Access-Control-Allow-Origin: *"+$crlf+
                "Access-Control-Allow-Methods: GET, OPTIONS"+$crlf+
                "Access-Control-Allow-Headers: *"+$crlf+
                "Access-Control-Allow-Private-Network: true"+$crlf+
                "Connection: close"+$crlf+$crlf
            $headerBytes=[Text.Encoding]::ASCII.GetBytes($headers)
            $stream.Write($headerBytes,0,$headerBytes.Length)
            if($body.Length -gt 0){$stream.Write($body,0,$body.Length)}
            $stream.Flush()
        }catch{
        }finally{
            try{$client.Close()}catch{}
        }
    }
}finally{
    try{$listener.Stop()}catch{}
}
