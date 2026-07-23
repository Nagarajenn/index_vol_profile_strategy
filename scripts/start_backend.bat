@echo off
title Dashboard Backend (uvicorn :8000)
cd /d D:\Claude_breakout\Claude_vol_profile\backend
venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
echo.
echo Backend stopped (Ctrl+C, crash, or port already in use). Press any key to close...
pause >nul
