@echo off
REM V52 shadow tick wrapper for Windows Task Scheduler.
REM Refreshes HL data + runs the paper shadow runner. Idempotent (safe hourly).
cd /d "C:\Users\alexandre bandarra\Desktop\global"
py "C:\Users\alexandre bandarra\Desktop\global\shadow_v52\shadow_tick.py" >> "C:\Users\alexandre bandarra\Desktop\global\shadow_v52\tick.log" 2>&1
