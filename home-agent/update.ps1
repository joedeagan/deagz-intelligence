# JARVIS home updater - thin wrapper around fix-brain.ps1, which owns the
# ONE canonical file list and fetches per-file from GitHub raw (the only
# transport proven reliable on this laptop; the codeload zip route fails
# silently here - suspected AV/family filter).
# Keep this file pure ASCII (PS 5.1 reads BOM-less files as ANSI).
#   powershell -ExecutionPolicy Bypass -File C:\jarvis-agent\update.ps1

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# resolve HEAD's commit sha so every fetched file is from ONE immutable
# snapshot - the mutable 'main' path once served a stale agent.py mid-update
try {
    $sha = (iwr "https://api.github.com/repos/joedeagan/deagz-intelligence/commits/main" -UseBasicParsing | ConvertFrom-Json).sha
} catch {
    $sha = "main"
}
$raw = "https://raw.githubusercontent.com/joedeagan/deagz-intelligence/$sha"
$bust = Get-Random
iwr "$raw/home-agent/fix-brain.ps1?$bust" -OutFile C:\jarvis-agent\fix-brain.ps1 -UseBasicParsing
powershell -ExecutionPolicy Bypass -File C:\jarvis-agent\fix-brain.ps1
