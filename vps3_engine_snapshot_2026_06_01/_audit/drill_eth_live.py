import csv, collections, datetime as dt

SNAP=".."
def load(p): return [r for r in csv.DictReader(open(p,encoding="utf-8")) if r.get("sleeve_id")]
ire=load(f"{SNAP}/ireland_fires_7d.csv")
v3 =load(f"{SNAP}/vps3_shadow_fires_compare_7d.csv")

def i(x):
    try:return int(float(x))
    except:return None
def day_from_ws(ws):
    k=i(ws)
    if k is None:return "?"
    return dt.datetime.utcfromtimestamp(k).strftime("%Y-%m-%d")

LIVE="poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8_LIVE"
BASE="poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8"

live=[r for r in ire if r["sleeve_id"]==LIVE]
shad=[r for r in v3  if r["sleeve_id"]==BASE]

def dirof(r): return str(r.get("direction","")).upper()
def split(rows):
    up=sum(1 for r in rows if dirof(r)=="UP"); dn=sum(1 for r in rows if dirof(r)=="DOWN")
    return up,dn,len(rows)

# live window by ws_s
lws=[i(r["ws_s"]) for r in live if i(r["ws_s"]) is not None]
w0,w1=min(lws),max(lws)
print(f"LIVE _LIVE: n={len(live)} ws_s window [{w0} .. {w1}] = {day_from_ws(w0)} .. {day_from_ws(w1)}")
u,d,n=split(live); print(f"  direction: UP={u} DOWN={d}  (up%={u/n:.2f})")
print("  per-day (UTC by ws_s):")
byday=collections.defaultdict(list)
for r in live: byday[day_from_ws(r['ws_s'])].append(r)
for day in sorted(byday):
    u,d,n=split(byday[day]); print(f"    {day}: UP={u:2d} DOWN={d:2d} n={n}")

print(f"\nSHADOW base {BASE}: n(7d)={len(shad)}")
u,d,n=split(shad); print(f"  7d direction: UP={u} DOWN={d} (up%={u/n:.2f})")
# restrict shadow to LIVE window
shad_w=[r for r in shad if i(r['ws_s']) is not None and w0<=i(r['ws_s'])<=w1]
u,d,n=split(shad_w)
print(f"  IN LIVE WINDOW [{day_from_ws(w0)}..{day_from_ws(w1)}]: n={n} UP={u} DOWN={d} (up%={u/n:.2f} )" if n else "  no shadow in window")
print("  shadow per-day (7d):")
byday=collections.defaultdict(list)
for r in shad: byday[day_from_ws(r['ws_s'])].append(r)
for day in sorted(byday):
    u,d,n=split(byday[day]); print(f"    {day}: UP={u:2d} DOWN={d:2d} n={n}")

# overlap join on ws_s within window
print("\nOVERLAP JOIN (ws_s) live vs shadow in live window:")
lmap={i(r['ws_s']):r for r in live if i(r['ws_s']) is not None}
smap={i(r['ws_s']):r for r in shad if i(r['ws_s']) is not None}
common=set(lmap)&set(smap)
shadow_up_in_win=[k for k in smap if w0<=k<=w1 and dirof(smap[k])=="UP"]
print(f"  common slots={len(common)}")
if common:
    agree=sum(1 for k in common if dirof(lmap[k])==dirof(smap[k]))
    print(f"  same_direction on common = {agree}/{len(common)}")
    disagree=[(k,dirof(lmap[k]),dirof(smap[k])) for k in common if dirof(lmap[k])!=dirof(smap[k])]
    for k,ld,sd in disagree[:10]: print(f"    DISAGREE ws_s={k} {day_from_ws(k)} live={ld} shadow={sd}")
print(f"  shadow fired UP on {len(shadow_up_in_win)} slots inside the live window")
# of those shadow-UP slots, did live fire at all (and which dir)?
live_on_shadowUP=[(k, dirof(lmap[k]) if k in lmap else 'NO-FIRE') for k in shadow_up_in_win]
cnt=collections.Counter(v for _,v in live_on_shadowUP)
print(f"  on shadow-UP slots, live did: {dict(cnt)}")
