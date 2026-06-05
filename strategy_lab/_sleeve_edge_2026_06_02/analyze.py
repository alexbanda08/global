"""Analyze per-sleeve shadow edge from VPS3 poly_updown_resolution aggregates."""
import csv, math
from pathlib import Path

P = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_sleeve_edge_2026_06_02\sleeve_edge_raw.csv")
COLS = ["sleeve_id","n","wr","total_pnl","pnl_per","pnl_sd","tstat","mean_vwap","pct_up","first","last","days"]
rows = []
for line in P.read_text().splitlines():
    if not line.strip() or line.startswith("ERROR"):
        continue
    parts = line.split(",")
    if len(parts) != len(COLS):
        continue
    d = dict(zip(COLS, parts))
    def f(x):
        try: return float(x)
        except: return None
    for k in ["n","wr","total_pnl","pnl_per","pnl_sd","tstat","mean_vwap","pct_up","days"]:
        d[k] = f(d[k])
    rows.append(d)

def fam(s):
    if s.startswith("poly_mint_sell"): return "mint_sell(maker)"
    if s.startswith("kalshi"): return "kalshi"
    if s.startswith("shadow_poly_updown"): return "prewindow"
    if "fast_taker" in s: return "fast_taker"
    if s.startswith("poly_sniper_v5"): return "sniper_v5"
    if s.startswith("poly_updown") or "_v3" in s: return "momo_v3"
    return "other"

for d in rows:
    d["fam"] = fam(d["sleeve_id"])

# ACTIVE = fired within last ~3 days (last >= 05-30) AND span >= 5 days (firing a while)
def mmdd(x):
    try:
        m,dd = x.split("-"); return int(m)*100+int(dd)
    except: return 0
active = [d for d in rows if d["last"] and mmdd(d["last"])>=530 and (d["days"] or 0)>=5]
print(f"total sleeves n>=15: {len(rows)} | currently-active (last>=05-30, span>=5d): {len(active)}")
print(f"families (active): " + ", ".join(f"{fa}={sum(1 for d in active if d['fam']==fa)}" for fa in sorted(set(d['fam'] for d in active))))

# EDGE candidates: positive pnl_per, significant, adequate n, directional (exclude maker)
def is_dir(d): return d["fam"] not in ("mint_sell(maker)",)
cand = [d for d in active if is_dir(d) and (d["pnl_per"] or -9)>0 and (d["tstat"] or 0)>=2.0 and (d["n"] or 0)>=30]
cand.sort(key=lambda d: -(d["tstat"] or 0))
print(f"\n=== REAL-EDGE CANDIDATES (active, directional, pnl/tr>0, t>=2, n>=30): {len(cand)} ===")
print(f"{'sleeve':<52}{'n':>5}{'WR':>6}{'$/tr':>8}{'tot$':>9}{'t':>6}{'vwap':>6}{'up%':>5}{'days':>6}")
for d in cand:
    print(f"{d['sleeve_id'][:51]:<52}{int(d['n']):>5}{d['wr']:>6}{d['pnl_per']:>8.3f}{d['total_pnl']:>9.1f}{d['tstat']:>6.1f}"
          f"{(d['mean_vwap'] or 0):>6.2f}{int(d['pct_up'] or 0):>5}{d['days']:>6.0f}")

# TRAP watch: high WR but pnl_per<=0 (priced-in) among active directional
trap = [d for d in active if is_dir(d) and (d["wr"] or 0)>=70 and (d["pnl_per"] or 0)<=0]
trap.sort(key=lambda d: d["pnl_per"] or 0)
print(f"\n=== HIGH-WR-but-LOSING (priced-in trap, WR>=70% & $/tr<=0): {len(trap)} ===")
for d in trap[:15]:
    print(f"{d['sleeve_id'][:51]:<52}{int(d['n']):>5}{d['wr']:>6}{(d['pnl_per'] or 0):>8.3f}{d['total_pnl']:>9.1f}{(d['mean_vwap'] or 0):>6.2f}")

# worst losers (active)
los = [d for d in active if is_dir(d) and (d["total_pnl"] or 0) < -50]
los.sort(key=lambda d: d["total_pnl"] or 0)
print(f"\n=== BIGGEST LOSERS (active, total<-$50): {len(los)} ===")
for d in los[:12]:
    print(f"{d['sleeve_id'][:51]:<52}{int(d['n']):>5}{d['wr']:>6}{(d['pnl_per'] or 0):>8.3f}{d['total_pnl']:>9.1f}{(d['tstat'] or 0):>6.1f}")

# borderline positives (pnl>0 but t<2) — watchlist
watch = [d for d in active if is_dir(d) and (d["pnl_per"] or -9)>0 and 1.0<=(d["tstat"] or 0)<2.0 and (d["n"] or 0)>=30]
watch.sort(key=lambda d:-(d["tstat"] or 0))
print(f"\n=== WATCHLIST (pnl/tr>0, 1<=t<2, n>=30): {len(watch)} ===")
for d in watch[:12]:
    print(f"{d['sleeve_id'][:51]:<52}{int(d['n']):>5}{d['wr']:>6}{d['pnl_per']:>8.3f}{d['total_pnl']:>9.1f}{d['tstat']:>6.1f}{int(d['pct_up'] or 0):>5}")
