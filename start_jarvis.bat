@echo off
title JARVIS - Deagz Intelligence

echo.
echo   =============================================
echo     J.A.R.V.I.S. - Deagz Intelligence
echo   =============================================
echo.

cd /d "%~dp0"

echo Cleaning up port 3002...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3002" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
ping -n 3 127.0.0.1 >nul 2>&1

echo Starting JARVIS...
echo.

start "" "http://localhost:3002"

C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe -m uvicorn web.server:app --host 0.0.0.0 --port 3002
if errorlevel 1 (
    echo.
    echo Trying alternate Python path...
    python -m uvicorn web.server:app --host 0.0.0.0 --port 3002
)
if errorlevel 1 (
    echo.
    echo Trying python3...
    python3 -m uvicorn web.server:app --host 0.0.0.0 --port 3002
)

echo.
echo JARVIS stopped.
pause
