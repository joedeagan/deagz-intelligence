@echo off
title JARVIS Web
chcp 65001 >nul 2>&1
cd /d "C:\Users\brian\Desktop\jarvis"

:: Kill any existing Jarvis server and tunnel
taskkill /IM python.exe /F 2>nul
taskkill /IM cloudflared.exe /F 2>nul

:: Wait for port to free
timeout /t 2 /nobreak >nul

:: Clear Python cache
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q *.pyc 2>nul

echo ============================================
echo   JARVIS - Deagz Intelligence
echo ============================================
echo.

:: Start Cloudflare tunnel and capture URL
echo Starting Cloudflare tunnel for phone access...
start "" /B "C:\Users\brian\Desktop\jarvis\cloudflared.exe" tunnel --url http://localhost:3002 2>tunnel_log.txt
timeout /t 5 /nobreak >nul

:: Extract tunnel URL from log
for /f "tokens=*" %%a in ('findstr "trycloudflare.com" tunnel_log.txt 2^>nul') do (
    echo   PHONE URL: %%a
)
echo   LOCAL URL: http://localhost:3002
echo.
echo ============================================
echo.

start "" "http://localhost:3002"
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe -B -m uvicorn web.server:app --host 0.0.0.0 --port 3002
pause
