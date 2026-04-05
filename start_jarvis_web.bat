@echo off
title JARVIS Web
chcp 65001 >nul 2>&1
cd /d "C:\Users\brian\Desktop\jarvis"

taskkill /IM python.exe /F 2>nul
taskkill /IM cloudflared.exe /F 2>nul
timeout /t 2 /nobreak >nul

echo ============================================
echo   JARVIS - Deagz Intelligence
echo ============================================
echo.
echo   LOCAL: http://localhost:3002
echo.

start /min "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:3002"

:restart
echo [%time%] Starting JARVIS...
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe -B -m uvicorn web.server:app --host 0.0.0.0 --port 3002
echo.
echo [%time%] Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto restart
