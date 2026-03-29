@echo off
title JARVIS - Deagz Intelligence
chcp 65001 >nul 2>&1
echo.
echo   =============================================
echo     J.A.R.V.I.S. - Deagz Intelligence
echo   =============================================
echo.

:: Kill ALL python processes that might be holding ports
echo Cleaning up old processes...
taskkill /IM python.exe /F >nul 2>&1
taskkill /IM python3.exe /F >nul 2>&1
timeout /t 3 /nobreak >nul

:: Double check — kill anything on port 3002
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3002" ^| findstr LISTENING 2^>nul') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: Start Jarvis web server
cd /d "%~dp0"
echo Starting JARVIS on http://localhost:3002 ...
echo.
start "" http://localhost:3002
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe -m uvicorn web.server:app --host 0.0.0.0 --port 3002
pause
