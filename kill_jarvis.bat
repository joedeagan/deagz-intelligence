@echo off
echo Killing ALL Jarvis processes...
echo.

:: Kill all Python
taskkill /IM python.exe /F /T >nul 2>&1
taskkill /IM python3.exe /F /T >nul 2>&1

:: Kill by port — every port we've ever used
for %%p in (3002 3003 3004 3005 3006 3007 3008 3009 3010 3011 3012 3013 3014 3015) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr LISTENING 2^>nul') do (
        echo   Killing PID %%a on port %%p
        taskkill /PID %%a /F /T >nul 2>&1
    )
)

:: Also kill cloudflared tunnels
taskkill /IM cloudflared.exe /F >nul 2>&1

timeout /t 2 /nobreak >nul

:: Check what's left
echo.
echo Checking for remaining processes...
set "FOUND=0"
for %%p in (3002 3003 3004 3005 3006 3007 3008 3009 3010 3011 3012 3013 3014 3015) do (
    netstat -ano 2>nul | findstr ":%%p" | findstr LISTENING >nul 2>&1
    if !errorlevel!==0 (
        echo   WARNING: Port %%p still in use (zombie - needs reboot)
        set "FOUND=1"
    )
)

if "%FOUND%"=="0" (
    echo   All clear! You can run start_jarvis.bat now.
) else (
    echo.
    echo   Some zombie processes survived. Reboot to clear them.
)

echo.
pause
