@echo off
title JARVIS
chcp 65001 >nul 2>&1
mode con: cols=80 lines=30
color 0F
cd /d "C:\Users\brian\Desktop\jarvis"
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe main.py
pause >nul
