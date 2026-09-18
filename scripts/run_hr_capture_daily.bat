@echo off
REM Launched by the "SensexNifty-HRCapture" Windows Task Scheduler task at
REM 14:50 on weekdays. HR-1 High-Resolution Option Intelligence Capture ONLY:
REM an independent process with its own WebSocket and DB connection. It does
REM not start, stop, read from or write to the live loop or 11d-paper-v1.
REM Exits immediately on non-trading days; persists 14:55:00-15:30:00;
REM hard-stops itself at 15:35.
cd /d D:\Claude_breakout\Claude_vol_profile
if not exist logs\hr mkdir logs\hr
venv\Scripts\python.exe scripts\run_hr_capture.py >> logs\hr\hr_capture_daily.log 2>&1
