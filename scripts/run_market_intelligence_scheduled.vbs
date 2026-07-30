' Hidden-window launcher for the "SensexNifty-MarketIntel" Windows Task
' Scheduler task. Runs run_market_intelligence_scheduled.bat with no visible
' console window (style 0) -- same reasoning as run_live_loop_daily.vbs: a
' visible console being closed sends CTRL_CLOSE to the whole process group.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """D:\Claude_breakout\Claude_vol_profile\scripts\run_market_intelligence_scheduled.bat""", 0, False
