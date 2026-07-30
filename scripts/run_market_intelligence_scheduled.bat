@echo off
REM Launched every 5 minutes by the "SensexNifty-MarketIntel" Windows Task
REM Scheduler task. One-shot: collects RSS, classifies unclassified items
REM (capped), then exits -- unlike the price live_loop, this has no
REM market-hours restriction since market-moving news (Fed, geopolitics,
REM tariffs) can break at any time of day.
cd /d D:\Claude_breakout\Claude_vol_profile
venv\Scripts\python.exe scripts\run_market_intelligence.py --max-new 20 >> logs\market_intelligence.log 2>&1
