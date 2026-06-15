import json, re
from pathlib import Path
OUT=Path(r"C:\Users\ALEXAN~1\AppData\Local\Temp\claude\C--Users-alexandre-bandarra-Desktop-global\d9dafe01-7ab7-487b-8651-56cbe3869d3a\tasks\wwohivuyk.output")
REP=Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\reports\SLEEVE_BT_VS_LIVE_AUDIT_2026_06_08.md")
raw=OUT.read_text(encoding="utf-8",errors="replace")
try:
    d=json.loads(raw)
except Exception:
    # try to find the JSON object
    i=raw.find('{"synth"'); d=json.loads(raw[i:]) if i>=0 else {}
d=d.get("result",d)
synth=d.get("synth","")
rows=d.get("master_rows",[]) or []
fades=d.get("fade_candidates",[]) or []
REP.write_text(synth if synth else raw, encoding="utf-8")
print("report bytes:",len(synth))
# verdict tally
from collections import Counter
vc=Counter()
for r in rows:
    v=(r.get("verdict","") or "").upper()
    key=("KEEP" if "KEEP" in v else "WATCH" if "WATCH" in v else "KILL" if "KILL" in v else
         "FADE" if "FADE" in v else "NEEDS-BT" if "BACKTEST" in v or "BT" in v else "OTHER")
    vc[key]+=1
print("master_rows:",len(rows)," verdict tally:",dict(vc))
print("\nKEEP / strong sleeves:")
for r in rows:
    if "KEEP" in (r.get("verdict","") or "").upper():
        print(f"  {r.get('family',''):<12} {r.get('sleeve_id','')[:46]:<46} live n={r.get('live_n')} wr={r.get('live_wr')} $/tr={r.get('live_tr')} fid={r.get('fidelity')}")
print(f"\nFADE candidates (<=35% WR, n>=20): {len(fades)}")
for f in fades:
    print(f"  {f.get('sleeve_id','')[:50]:<50} n={f.get('n')} wr={round(f.get('wr',0),3)} $/tr={round(f.get('dollar_per_tr',0),2)} vwap={round(f.get('entry_vwap',0) or 0,3)}")
# extract go-forward + fade sections from synth
for tag in ["Go-forward","Go-Forward","go-forward","Fade","fade-candidate","Fidelity findings","Counter-edge","CONTINUE"]:
    idx=synth.find(tag)
    if idx>0:
        print(f"\n----- section '{tag}' @ {idx} -----")
        print(synth[idx:idx+1400])
        break
