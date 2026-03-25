@echo off
title JARVIS Web
chcp 65001 >nul 2>&1
cd /d "C:\Users\brian\Desktop\jarvis"
echo Starting JARVIS web server...
echo Open http://localhost:3001 in your browser
echo.
start "" "http://localhost:3001"
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe web\server.py
pause
