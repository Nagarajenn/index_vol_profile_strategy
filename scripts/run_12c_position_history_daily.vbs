' Hidden-window launcher for the "SensexNifty-Scalp12CHistory" Windows Task
' Scheduler task (same pattern as run_scalp12a_shadow_daily.vbs).
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """D:\Claude_breakout\Claude_vol_profile\scripts\run_12c_position_history_daily.bat""", 0, False
