# JARVIS home updater - pulls the latest brain + wall + agent + watchdog
# from GitHub (cache-busted) and restarts everything hidden.
# NOTE: keep this file pure ASCII - PowerShell 5.1 reads BOM-less files as
# ANSI and fancy dashes/quotes become phantom string terminators.
#   powershell -ExecutionPolicy Bypass -File C:\jarvis-agent\update.ps1

$raw = "https://raw.githubusercontent.com/joedeagan/deagz-intelligence/main"
$bust = Get-Random

Write-Host "Fetching latest..."
iwr "$raw/web/server.py?$bust"           -OutFile C:\jarvis-brain\web\server.py
iwr "$raw/web/static/wall.html?$bust"    -OutFile C:\jarvis-brain\web\static\wall.html
iwr "$raw/web/static/library.json?$bust" -OutFile C:\jarvis-brain\web\static\library.json
iwr "$raw/jarvis/config.py?$bust"        -OutFile C:\jarvis-brain\jarvis\config.py
iwr "$raw/home-agent/agent.py?$bust"     -OutFile C:\jarvis-agent\agent.py
iwr "$raw/home-agent/watchdog.py?$bust"  -OutFile C:\jarvis-agent\watchdog.py
iwr "$raw/home-agent/update.ps1?$bust"   -OutFile C:\jarvis-agent\update.ps1

Write-Host "Restarting services..."
taskkill /IM python.exe /F 2>$null | Out-Null
taskkill /IM pythonw.exe /F 2>$null | Out-Null
Set-Location C:\jarvis-agent
Start-Process pythonw watchdog.py
Write-Host "Done - watchdog will have brain + agent back within ~30s."
