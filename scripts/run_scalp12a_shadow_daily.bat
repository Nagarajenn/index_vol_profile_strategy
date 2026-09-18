@echo off
REM Launched by the "SensexNifty-Scalp12AShadow" Windows Task Scheduler task at
REM 14:53 on weekdays. 12A-scalp-v1 LIVE SHADOW RECORDER ONLY: observation, no
REM orders, no paper positions, no interaction with 11d-paper-v1 or the HR
REM capture process (reads HR tables, writes only scalp12a_* tables).
REM Exits immediately on non-trading days; runs 14:55-15:36, then refreshes the
REM 12A research report.
cd /d D:\Claude_breakout\Claude_vol_profile
if not exist logs\scalp12a mkdir logs\scalp12a
venv\Scripts\python.exe scripts\run_scalp12a_shadow.py >> logs\scalp12a\shadow_daily.log 2>&1
