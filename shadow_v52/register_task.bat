@echo off
REM Register the V52 shadow tick as an hourly Windows scheduled task.
REM Run once (double-click or `cmd /c register_task.bat`). Idempotent via /F.
schtasks /Create /TN "V52Shadow" /SC HOURLY /MO 1 /ST 00:05 /TR "\"C:\Users\alexandre bandarra\Desktop\global\shadow_v52\shadow_tick.bat\"" /F
echo.
echo To verify:   schtasks /Query /TN V52Shadow
echo To run now:  schtasks /Run /TN V52Shadow
echo To remove:   schtasks /Delete /TN V52Shadow /F
