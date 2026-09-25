param(
    [int]$Port = 28583,
    [string]$SbV2BaseUrl = "http://127.0.0.1:5000",
    [string]$ModelName = "amitaro",
    [string]$SpeakerName = "あみたろ",
    [string]$Style = "Neutral"
)

# AI Cockpit Voice Bridge V8
#
# 2026-09-25: retires window.speechSynthesis from the web UI's voice path.
# Runs as its OWN process/port (28583 by default), deliberately separate
# from AI_COCKPIT_GATEWAY_V8.ps1 (28581), so voice synthesis - which can
# take a few real seconds against SBV2 - never blocks the Gateway's live
# cockpit data serving (requirement: 28580/28581/28582 updates must never
# stall on voice generation).
#
# Never falls back to any other TTS. If SBV2 is unreachable, /speak
# returns 503 and the browser goes silent (UI shows VOICE OFFLINE) - it
# does not fall back to the old browser speechSynthesis voice.
#
# Reuses the exact text-normalization table and CALM/WATCH/HOT/DANGER
# voice profile values already in production use by
# ms2_live/SPEAK_LIVE_EMOTION.ps1 / TEST_SBV2_EMOTION_VOICE.ps1 - kept in
# sync deliberately (not re-derived), so the web UI's voice reads
# identically to the existing PC-side voice scripts. Does not touch those
# scripts, MS2_RSS_100_Collector.ps1, the Watcher, or any order/signal
# logic - this is a presentation-only, read-only bridge to SBV2's HTTP API.

$ErrorActionPreference = "Stop"

function Get-VoiceProfile([string]$level) {
    switch ($level) {
        "HOT"    { return @{ length = 1.03; style_weight = 0.70; split_interval = 0.35 } }
        "DANGER" { return @{ length = 1.10; style_weight = 0.80; split_interval = 0.45 } }
        "WATCH"  { return @{ length = 1.13; style_weight = 0.50; split_interval = 0.50 } }
        default  { return @{ length = 1.20; style_weight = 0.35; split_interval = 0.60 } }
    }
}

# Same table as ms2_live/SPEAK_LIVE_EMOTION.ps1's Normalize-SpeechText -
# order matters for a couple of entries (VWAP上/VWAP下 before bare VWAP),
# matched here for the same reason noted there.
function Convert-ToSpeechText([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return $text }
    $result = $text
    $replacements = [ordered]@{
        "AIコクピット" = "えーあいコクピット"
        "キオクシア"   = "きおくしあ"
        "VWAP上"       = "ぶいわっぷ、うえ"
        "VWAP下"       = "ぶいわっぷ、した"
        "VWAP"         = "ぶいわっぷ"
        "OR15"         = "おーあーる、じゅうご"
        "OR5"          = "おーあーる、ご"
        "EMA20"        = "いーえむえー、にじゅう"
        "EMA9"         = "いーえむえー、きゅう"
        "EMA"          = "いーえむえー"
        "GU"           = "ぎゃっぷあっぷ"
        "GD"           = "ぎゃっぷだうん"
        "歩み値"       = "あゆみね"
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $result = $result.Replace([string]$entry.Key, [string]$entry.Value)
    }
    $result = $result.Replace("%", "パーセント")
    return $result
}

function Test-Sbv2Ready {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($SbV2BaseUrl.TrimEnd('/') + '/status') -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Invoke-Sbv2Voice([string]$text, [string]$level) {
    $profile = Get-VoiceProfile $level
    $speechText = Convert-ToSpeechText $text
    $q = [ordered]@{
        text           = $speechText
        model_name     = $ModelName
        speaker_name   = $SpeakerName
        language       = 'JP'
        length         = $profile.length.ToString([Globalization.CultureInfo]::InvariantCulture)
        auto_split     = 'true'
        split_interval = $profile.split_interval.ToString([Globalization.CultureInfo]::InvariantCulture)
        style          = $Style
        style_weight   = $profile.style_weight.ToString([Globalization.CultureInfo]::InvariantCulture)
    }
    $pairs = @()
    foreach ($entry in $q.GetEnumerator()) {
        $pairs += ([Uri]::EscapeDataString([string]$entry.Key) + '=' + [Uri]::EscapeDataString([string]$entry.Value))
    }
    $uri = $SbV2BaseUrl.TrimEnd('/') + '/voice?' + ($pairs -join '&')
    $tmpWav = [IO.Path]::GetTempFileName() + ".wav"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $tmpWav -TimeoutSec 30 | Out-Null
        return [IO.File]::ReadAllBytes($tmpWav)
    } finally {
        Remove-Item -LiteralPath $tmpWav -Force -ErrorAction SilentlyContinue
    }
}

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
$utf8 = [Text.UTF8Encoding]::new($false)

function Send-Response($stream, [string]$status, [string]$contentType, [byte[]]$body) {
    $headers = "HTTP/1.1 $status`r`nContent-Type: $contentType`r`nContent-Length: $($body.Length)`r`nCache-Control: no-store`r`nAccess-Control-Allow-Origin: *`r`nAccess-Control-Allow-Methods: GET, POST, OPTIONS`r`nAccess-Control-Allow-Headers: *`r`nConnection: close`r`n`r`n"
    $hb = [Text.Encoding]::ASCII.GetBytes($headers)
    $stream.Write($hb, 0, $hb.Length)
    if ($body.Length -gt 0) { $stream.Write($body, 0, $body.Length) }
    $stream.Flush()
}

# Reads one CRLF-terminated header line directly off the socket, one byte
# at a time - deliberately NOT via IO.StreamReader. .NET's StreamReader
# constructor silently clamps any requested bufferSize below ~128 up to
# 128, so a "bufferSize=1" StreamReader still reads ahead up to ~128 bytes
# into its own internal buffer - on a small POST (headers + a short JSON
# body both well under 128 bytes) that swallows part or all of the body,
# and the raw $stream.Read() used for the body below then waits forever
# for bytes the client already sent but the StreamReader already consumed.
# Byte-at-a-time reads avoid any hidden read-ahead entirely.
function Read-HttpLine([IO.Stream]$stream) {
    $bytes = New-Object Collections.Generic.List[byte]
    while ($true) {
        $b = $stream.ReadByte()
        if ($b -eq -1) { break }
        if ($b -eq 10) { break }
        if ($b -eq 13) { continue }
        $bytes.Add([byte]$b)
    }
    return [Text.Encoding]::ASCII.GetString($bytes.ToArray())
}

try {
    $listener.Start()
    Write-Host ("AI Cockpit Voice Bridge V8: http://127.0.0.1:{0}" -f $Port) -ForegroundColor Green
    Write-Host ("SBV2 base: " + $SbV2BaseUrl) -ForegroundColor Cyan

    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            $requestLine = Read-HttpLine $stream
            $contentLength = 0
            while ($true) {
                $line = Read-HttpLine $stream
                if ([string]::IsNullOrEmpty($line)) { break }
                if ($line -match '^Content-Length:\s*(\d+)') { $contentLength = [int]$Matches[1] }
            }
            if ([string]::IsNullOrWhiteSpace($requestLine)) { continue }
            $parts = $requestLine -split ' '
            $method = $parts[0]
            $rawPath = if ($parts.Count -ge 2) { $parts[1] } else { '/' }

            if ($method -eq 'OPTIONS') {
                Send-Response $stream '204 No Content' 'text/plain' ([byte[]]@())
                continue
            }

            if ($rawPath -eq '/status' -and $method -eq 'GET') {
                $ready = Test-Sbv2Ready
                $payload = (@{ status = 'ok'; sbv2_ready = $ready; port = $Port } | ConvertTo-Json -Compress)
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes($payload))
                continue
            }

            if ($rawPath -eq '/speak' -and $method -eq 'POST') {
                $bodyText = ""
                if ($contentLength -gt 0) {
                    $bodyBytes = New-Object byte[] $contentLength
                    $totalRead = 0
                    while ($totalRead -lt $contentLength) {
                        $n = $stream.Read($bodyBytes, $totalRead, $contentLength - $totalRead)
                        if ($n -le 0) { break }
                        $totalRead += $n
                    }
                    $bodyText = [Text.Encoding]::UTF8.GetString($bodyBytes, 0, $totalRead)
                }
                $req = $null
                try { $req = $bodyText | ConvertFrom-Json } catch {}
                $text = if ($null -ne $req) { [string]$req.text } else { "" }
                $level = if ($null -ne $req -and $req.level) { [string]$req.level } else { "CALM" }
                if ([string]::IsNullOrWhiteSpace($text)) {
                    Send-Response $stream '400 Bad Request' 'application/json; charset=utf-8' ($utf8.GetBytes('{"error":"text is required"}'))
                    continue
                }
                if (-not (Test-Sbv2Ready)) {
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes('{"error":"sbv2_unreachable"}'))
                    continue
                }
                try {
                    $wavBytes = Invoke-Sbv2Voice $text $level
                    Send-Response $stream '200 OK' 'audio/wav' $wavBytes
                } catch {
                    Send-Response $stream '502 Bad Gateway' 'application/json; charset=utf-8' ($utf8.GetBytes('{"error":"sbv2_synthesis_failed"}'))
                }
                continue
            }

            Send-Response $stream '404 Not Found' 'text/plain; charset=utf-8' ($utf8.GetBytes('Not found'))
        } catch {
        } finally {
            $client.Close()
        }
    }
} finally {
    $listener.Stop()
}
