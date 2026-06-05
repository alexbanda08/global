"""Classify ALL sleeves into edge buckets and emit a complete markdown table."""
from pathlib import Path
P = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_sleeve_edge_2026_06_02\sleeve_edge_full.csv")
COLS = ["sleeve_id","n","wr","total","per","tstat","vwap","last","days"]
rows = []
for ln in P.read_text().splitlines():
    if not ln.strip() or ln.startswith("ERROR"): continue
    p = ln.split(",")
    if len(p) != len(COLS): continue
    d = dict(zip(COLS, p))
    def f(x):
        try: return float(x)
        except: return None
    for k in ["n","wr","total","per","tstat","vwap","days"]: d[k]=f(d[k])
    rows.append(d)

def mmdd(x):
    try: m,dd=x.split("-"); return int(m)*100+int(dd)
    except: return 0
for d in rows:
    d["active"] = mmdd(d["last"])>=528   # fired within ~last 5 days
    t=d["tstat"] or 0; per=d["per"] or 0; n=d["n"] or 0; tot=d["total"] or 0
    if not d["active"]:                         b="INACTIVE"
    elif n<30:                                  b="LOW_N"
    elif per>0 and t>=2:                        b="EDGE"
    elif per>0 and t>=1:                        b="PROMISING"
    elif t<=-2 or tot<=-300:                    b="BLEEDER"
    elif per<0 and t<=-1:                        b="NEG"
    else:                                        b="FLAT"
    d["bucket"]=b

ORDER=["EDGE","PROMISING","FLAT","NEG","BLEEDER","LOW_N","INACTIVE"]
EMO={"EDGE":"🟢","PROMISING":"🟡","FLAT":"⚪","NEG":"🟠","BLEEDER":"🔴","LOW_N":"⏸","INACTIVE":"⬛"}
print(f"# Complete Shadow Sleeve Table — {len(rows)} sleeves (45d resolved) — 2026-06-02\n")
print("Source `poly_updown_resolution` on VPS3. n = completed (resolved) FIRES. $/tr after engine fees. "
      "t = PnL t-stat. active = fired in last ~5d. Buckets: EDGE(t≥2,$/tr>0) · PROMISING(1≤t<2,$/tr>0) · "
      "FLAT(insignificant) · NEG · BLEEDER(t≤−2 or ≤−$300) · LOW_N(<30) · INACTIVE.\n")
# distribution
print("## Distribution\n")
print("| bucket | sleeves | Σ total PnL |")
print("|---|--:|--:|")
for b in ORDER:
    sub=[d for d in rows if d["bucket"]==b]
    print(f"| {EMO[b]} {b} | {len(sub)} | {sum(d['total'] or 0 for d in sub):,.0f} |")
print(f"| **ALL** | **{len(rows)}** | **{sum(d['total'] or 0 for d in rows):,.0f}** |")

for b in ORDER:
    sub=sorted([d for d in rows if d["bucket"]==b], key=lambda d:-(d["total"] or 0))
    if not sub: continue
    print(f"\n## {EMO[b]} {b} — {len(sub)} sleeves\n")
    print("| sleeve | fires | WR% | $/tr | total$ | t | vwap | last |")
    print("|---|--:|--:|--:|--:|--:|--:|--:|")
    for d in sub:
        print(f"| {d['sleeve_id']} | {int(d['n'])} | {d['wr']} | {d['per']:+.2f} | {d['total']:+.0f} "
              f"| {('' if d['tstat'] is None else format(d['tstat'],'+.1f'))} | {('' if d['vwap'] is None else format(d['vwap'],'.2f'))} | {d['last']} |")
