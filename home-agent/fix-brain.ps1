# One-shot brain repair - pulls EVERY brain/agent file from GitHub raw
# (the per-file raw path is proven on this laptop; the zip/codeload path is
# not), smoke-tests the brain import so errors are visible, restarts, probes.
# Everything is logged to C:\jarvis-agent\fix.log.
# Keep this file pure ASCII (PS 5.1 reads BOM-less files as ANSI).
#   powershell -ExecutionPolicy Bypass -File fix-brain.ps1

$ErrorActionPreference = "Continue"
try { Start-Transcript -Path C:\jarvis-agent\fix.log -Force | Out-Null } catch {}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$raw = "https://raw.githubusercontent.com/joedeagan/deagz-intelligence/main"
$bust = Get-Random
$fails = 0

function Fetch($rel, $dest) {
    $dir = Split-Path $dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    try {
        iwr "$raw/$rel`?$bust" -OutFile $dest -UseBasicParsing
        Write-Host "ok   $rel"
    } catch {
        Write-Host "FAIL $rel : $($_.Exception.Message)"
        $script:fails++
    }
}

Write-Host "=== fetching brain files ==="
$brainFiles = @(
    "jarvis/__init__.py", "jarvis/brain.py", "jarvis/config.py",
    "jarvis/tools/__init__.py", "jarvis/tools/autodj.py", "jarvis/tools/backtester.py",
    "jarvis/tools/base.py", "jarvis/tools/coder.py", "jarvis/tools/contacts.py",
    "jarvis/tools/ears.py", "jarvis/tools/voiceprint.py", "jarvis/tools/mind.py",
    "jarvis/tools/selfbuild.py", "jarvis/tools/housestate.py", "jarvis/tools/gameday.py",
    "jarvis/tools/moments.py", "jarvis/tools/reflection.py", "jarvis/tools/dreams.py",
    "jarvis/tools/image_gen.py", "jarvis/tools/kalshi.py", "jarvis/tools/kalshi_advisor.py",
    "jarvis/tools/memory.py", "jarvis/tools/observer.py", "jarvis/tools/proactive.py",
    "jarvis/tools/routines.py", "jarvis/tools/screen_aware.py", "jarvis/tools/shazam.py",
    "jarvis/tools/sports.py", "jarvis/tools/spotify.py", "jarvis/tools/stems.py",
    "jarvis/tools/study.py", "jarvis/tools/system.py", "jarvis/tools/voice.py",
    "jarvis/voice/__init__.py", "jarvis/voice/listener.py", "jarvis/voice/speaker.py",
    "web/server.py",
    "web/static/wall.html", "web/static/announce.html", "web/static/index.html",
    "web/static/mictest.html", "web/static/orb.js", "web/static/style.css",
    "web/static/sw.js", "web/static/library.json", "web/static/manifest.json"
)
foreach ($f in $brainFiles) { Fetch $f "C:\jarvis-brain\$($f -replace '/', '\')" }

Write-Host "=== fetching agent files ==="
foreach ($f in "home-agent/agent.py", "home-agent/watchdog.py", "home-agent/update.ps1") {
    Fetch $f "C:\jarvis-agent\$(Split-Path $f -Leaf)"
}

Write-Host "=== smoke test: can the brain even import? ==="
Set-Location C:\jarvis-brain
$py = (Get-Command python).Source
& $py -c "import web.server; print('IMPORT OK')" 2>&1 | ForEach-Object { Write-Host $_ }
$importOk = ($LASTEXITCODE -eq 0)

Write-Host "=== restarting services ==="
taskkill /IM python.exe /F 2>$null | Out-Null
taskkill /IM pythonw.exe /F 2>$null | Out-Null
Set-Location C:\jarvis-agent
Start-Process pythonw watchdog.py

Write-Host "=== waiting for the brain (up to 100s) ==="
$up = $false
for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Seconds 2
    foreach ($port in 443, 3012) {
        try {
            $c = New-Object Net.Sockets.TcpClient
            $ar = $c.BeginConnect("127.0.0.1", $port, $null, $null)
            if ($ar.AsyncWaitHandle.WaitOne(1000) -and $c.Connected) { $up = $true }
            $c.Close()
        } catch {}
        if ($up) { break }
    }
    if ($up) { break }
}

Write-Host ""
if ($up -and $importOk -and $fails -eq 0) {
    Write-Host ">>> VERDICT: BRAIN IS UP - reload the wall on the iPad <<<"
} elseif ($up) {
    Write-Host ">>> VERDICT: BRAIN IS UP (with $fails fetch fails - mention this) <<<"
} elseif (-not $importOk) {
    Write-Host ">>> VERDICT: STILL DOWN - IMPORT FAILED, read the lines above the restart section to Claude <<<"
} else {
    Write-Host ">>> VERDICT: STILL DOWN ($fails fetch fails) - read C:\jarvis-agent\fix.log to Claude <<<"
}
try { Stop-Transcript | Out-Null } catch {}
