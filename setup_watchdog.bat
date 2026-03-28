@echo off
echo Setting up Kalshi Watchdog scheduled task...
echo This will run every 2 hours, even when Jarvis is closed.
echo.

schtasks /create /tn "Kalshi Watchdog" /tr "C:\Users\brian\AppData\Local\Python\pythoncore-3.14-64\python.exe C:\Users\brian\Desktop\jarvis\kalshi_watchdog.py" /sc HOURLY /mo 2 /st 00:00 /f

echo.
echo Done! The watchdog will run every 2 hours.
echo Reports saved to: C:\Users\brian\Desktop\jarvis\data\kalshi_reports\
echo.
echo To remove: schtasks /delete /tn "Kalshi Watchdog" /f
pause
