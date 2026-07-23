@echo off
REM Double-click this any time to (re)start the dashboard: opens the
REM backend and frontend each in their own visible console window, fully
REM independent of any Claude Code session -- closing a window stops that
REM server, running this file again starts it back up.
cd /d D:\Claude_breakout\Claude_vol_profile
start "Dashboard Backend" scripts\start_backend.bat
start "Dashboard Frontend" scripts\start_frontend.bat
echo Started both dashboard servers in separate windows:
echo   - Backend  : http://localhost:8000
echo   - Frontend : http://localhost:5173
echo.
echo To stop either one, close its window (or Ctrl+C inside it).
echo To restart, just run this file again.
