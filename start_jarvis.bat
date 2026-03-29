@echo off
title JARVIS - Deagz Intelligence
chcp 65001 >nul 2>&1
echo.
echo   =============================================
echo     J.A.R.V.I.S. - Deagz Intelligence
echo   =============================================
echo.

:: Save our own process group so we can kill children on exit
set "JARVIS_PORT=3002"

:: Kill ALL python processes and anything on our port
echo Cleaning up old processes...
taskkill /IM python.exe /F /T >nul 2>&1
taskkill /IM python3.exe /F /T >nul 2>&1
timeout /t 2 /nobreak >nul

:: Nuclear option — kill by port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%JARVIS_PORT%" ^| findstr LISTENING 2^>nul') do (
    echo   Killing PID %%a on port %JARVIS_PORT%...
    taskkill /PID %%a /F /T >nul 2>&1
)

:: Also kill any stragglers on other ports we've used
for %%p in (3003 3004 3005 3006 3007 3008 3009 3010 3011 3012 3013 3014) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr LISTENING 2^>nul') do (
        taskkill /PID %%a /F /T >nul 2>&1
    )
)
timeout /t 2 /nobreak >nul

:: Verify port is free
netstat -ano | findstr ":%JARVIS_PORT%" | findstr LISTENING >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo   ERROR: Port %JARVIS_PORT% is still in use by a zombie process.
    echo   Please REBOOT your computer to clear it, then run this again.
    echo.
    pause
    exit /b 1
)

:: Start Jarvis
cd /d "%~dp0"
echo Starting JARVIS on http://localhost:%JARVIS_PORT% ...
echo Press Ctrl+C to stop JARVIS cleanly.
echo.

:: Open browser after a short delay
start /min "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:%JARVIS_PORT%"

:: Run uvicorn in THIS window so Ctrl+C kills it properly
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe -m uvicorn web.server:app --host 0.0.0.0 --port %JARVIS_PORT%

:: When uvicorn exits (Ctrl+C or crash), clean up
echo.
echo JARVIS stopped. Cleaning up...
taskkill /IM python.exe /F /T >nul 2>&1
taskkill /IM python3.exe /F /T >nul 2>&1
echo Done.
pause
