@echo off
echo Setting up JARVIS Daily Digest at 8:00 AM...
schtasks /create /tn "Jarvis Daily Digest" /tr "C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe C:\Users\brian\Desktop\jarvis\daily_digest.py" /sc daily /st 08:00 /f
echo.
echo Done! JARVIS will email you a daily digest every morning at 8:00 AM.
echo To remove: schtasks /delete /tn "Jarvis Daily Digest" /f
echo.

:: Test it now
echo Sending a test digest now...
C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe C:\Users\brian\Desktop\jarvis\daily_digest.py
pause
