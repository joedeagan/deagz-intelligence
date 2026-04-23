@echo off
title JARVIS - Update and Restart
cd /d "%~dp0"

echo.
echo   =============================================
echo     J.A.R.V.I.S. - Update and Restart
echo   =============================================
echo.

echo [1/4] Killing any running Jarvis processes...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3002" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
ping -n 2 127.0.0.1 >nul 2>&1

echo [2/4] Fetching latest code from GitHub...
git fetch origin

echo [3/4] Switching to brain-upgrade branch and pulling...
git checkout claude/jarvis-status-check-D3yXL
git pull origin claude/jarvis-status-check-D3yXL

echo [4/4] Installing any new dependencies...
pip install -r requirements.txt >nul 2>&1

echo.
echo   Update complete. Starting Jarvis...
echo.

call start_jarvis.bat
