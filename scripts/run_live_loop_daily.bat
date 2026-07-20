@echo off
REM Launched by the "SensexNifty-LiveLoop" Windows Task Scheduler task, daily
REM on trading mornings. Starts a fresh live_loop process (avoids a single
REM process staying alive for days/weeks -- see --single-session in
REM pipeline/live_loop.py) which exits on its own once today's session ends
REM (or immediately, on a non-trading day).
cd /d D:\Claude_breakout\Claude_vol_profile
venv\Scripts\python.exe scripts\run_live_loop.py SENSEX NIFTY --single-session >> logs\live_loop_daily.log 2>&1
