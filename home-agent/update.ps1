# JARVIS home updater - syncs the ENTIRE repo (zip snapshot from GitHub) so
# new files can never be forgotten, then restarts everything hidden.
# The per-file list this replaced took the brain down on v44: server.py
# imported jarvis/tools/sports.py + observer.py that the list never fetched.
# NOTE: keep this file pure ASCII - PowerShell 5.1 reads BOM-less files as
# ANSI and fancy dashes/quotes become phantom string terminators.
#   powershell -ExecutionPolicy Bypass -File C:\jarvis-agent\update.ps1
# Never overwritten by the sync: C:\jarvis-brain\.env, data\, .spotify_cache,
# C:\jarvis-agent\config.json (they live outside the copied trees).

$zip = "$env:TEMP\deagz-main.zip"
$dst = "$env:TEMP\deagz-main"

Write-Host "Fetching repo snapshot..."
iwr "https://codeload.github.com/joedeagan/deagz-intelligence/zip/refs/heads/main" -OutFile $zip
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
Expand-Archive $zip -DestinationPath $dst -Force
$src = "$dst\deagz-intelligence-main"

Write-Host "Syncing brain + agent files..."
Copy-Item "$src\web\*"    "C:\jarvis-brain\web\"    -Recurse -Force
Copy-Item "$src\jarvis\*" "C:\jarvis-brain\jarvis\" -Recurse -Force
Copy-Item "$src\home-agent\agent.py"    "C:\jarvis-agent\agent.py"    -Force
Copy-Item "$src\home-agent\watchdog.py" "C:\jarvis-agent\watchdog.py" -Force
Copy-Item "$src\home-agent\update.ps1"  "C:\jarvis-agent\update.ps1"  -Force

Write-Host "Restarting services..."
taskkill /IM python.exe /F 2>$null | Out-Null
taskkill /IM pythonw.exe /F 2>$null | Out-Null
Set-Location C:\jarvis-agent
Start-Process pythonw watchdog.py
Write-Host "Done - watchdog will have brain + agent back within ~30s."
