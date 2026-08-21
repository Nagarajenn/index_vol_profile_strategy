@echo off
REM Launched daily post-market by the "SensexNifty-CASIntelligence" Windows
REM Task Scheduler task. One-shot: recomputes CAS Intelligence for every
REM post-CAS trading day (idempotent upsert) then exits. Runs after session
REM close (15:40) with a buffer for Dhan to finalize the day's 1-min data.
cd /d D:\Claude_breakout\Claude_vol_profile
venv\Scripts\python.exe scripts\run_cas_intelligence.py >> logs\cas_intelligence.log 2>&1
