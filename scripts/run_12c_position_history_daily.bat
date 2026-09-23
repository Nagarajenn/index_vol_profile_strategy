@echo off
REM Launched by the "SensexNifty-Scalp12CHistory" Windows Task Scheduler task at
REM 16:10 on weekdays, after the live loop has stopped capturing (15:40).
REM SIMULATION ONLY: replays the day's existing 12C decisions, hands them to the
REM position simulator and upserts every CLOSED hypothetical position (including
REM which decision closed it) into sim12c_positions. It places no order, touches
REM no paper account and changes no decision. Idempotent -- a re-run updates the
REM day's rows instead of duplicating them, so a missed day can be back-filled
REM with: venv\Scripts\python.exe scripts\run_12c_position_history.py YYYY-MM-DD
cd /d D:\Claude_breakout\Claude_vol_profile
if not exist logs\scalp12c mkdir logs\scalp12c
venv\Scripts\python.exe scripts\run_12c_position_history.py >> logs\scalp12c\position_history.log 2>&1
