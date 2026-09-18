' Hidden-window launcher for the "SensexNifty-HRCapture" Windows Task
' Scheduler task (same pattern as run_live_loop_daily.vbs): no visible
' console window that could be closed by accident and kill the process.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """D:\Claude_breakout\Claude_vol_profile\scripts\run_hr_capture_daily.bat""", 0, False
