' Hidden-window launcher for the "SensexNifty-Scalp12AShadow" Windows Task
' Scheduler task (same pattern as run_hr_capture_daily.vbs).
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """D:\Claude_breakout\Claude_vol_profile\scripts\run_scalp12a_shadow_daily.bat""", 0, False
