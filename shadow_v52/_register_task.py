"""Register (or refresh) the V52 shadow hourly Windows scheduled task.
Uses subprocess list-form to avoid shell-quoting issues with the spaced path.
Run:  py shadow_v52/_register_task.py   (add  --delete  to remove)
"""
import subprocess, sys
from pathlib import Path

BAT = Path(__file__).resolve().parent / "shadow_tick.bat"

if "--delete" in sys.argv:
    r = subprocess.run(["schtasks", "/Delete", "/TN", "V52Shadow", "/F"],
                       capture_output=True, text=True)
    print(r.stdout or r.stderr)
    sys.exit(r.returncode)

cmd = ["schtasks", "/Create", "/TN", "V52Shadow",
       "/SC", "HOURLY", "/MO", "1", "/ST", "00:05",
       "/TR", f'"{BAT}"', "/F"]
r = subprocess.run(cmd, capture_output=True, text=True)
print("CREATE:", r.stdout.strip() or r.stderr.strip())
# Verify
q = subprocess.run(["schtasks", "/Query", "/TN", "V52Shadow", "/FO", "LIST"],
                   capture_output=True, text=True)
print(q.stdout.strip() or q.stderr.strip())
