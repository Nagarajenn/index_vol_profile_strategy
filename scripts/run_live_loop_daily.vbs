' Hidden-window launcher for the "SensexNifty-LiveLoop" Windows Task
' Scheduler task. Runs run_live_loop_daily.bat with no visible console
' window (style 0) so there is nothing a user/process can accidentally
' close -- a visible console being closed sends CTRL_CLOSE to the whole
' process group, killing python.exe with STATUS_CONTROL_C_EXIT before it
' ever reaches market open (observed 2026-07-21 09:10).
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """D:\Claude_breakout\Claude_vol_profile\scripts\run_live_loop_daily.bat""", 0, False
