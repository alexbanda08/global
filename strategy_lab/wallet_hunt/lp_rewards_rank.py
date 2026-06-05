"""Pull live Polymarket LP-reward markets (CLOB /sampling-markets), enrich top
candidates with gamma competition/liquidity, rank high-reward / low-competition /
slow (long-dated, mid-priced) markets to farm."""
import requests, datetime, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
CLOB="https://clob.polymarket.com"; GAMMA="https://gamma-api.polymarket.com"
UA={"User-Agent":"global-strategy-lab/1.0"}
NOW=datetime.datetime.now(datetime.timezone.utc)

def _get(url,params=None,tries=5):
    for i in range(tries):
        try:
            r=requests.get(url,params=params or {},headers=UA,timeout=25)
            if r.status_code==200: return r.json()
        except Exception as e:
            time.sleep(1.0+i)
    return None

def pull_sampling():
    out=[]; cur=""
    while True:
        j=_get(f"{CLOB}/sampling-markets",{"next_cursor":cur} if cur else {})
        if not j: break
        out.extend(j.get("data",[]))
        cur=j.get("next_cursor")
        if not cur or cur=="LTE=" : break
    return out

ms=pull_sampling()
print(f"sampling-markets total: {len(ms)}")

rows=[]
for m in ms:
    if not (m.get("active") and m.get("accepting_orders") and not m.get("closed")): continue
    rw=m.get("rewards") or {}
    rate=sum(float(x.get("rewards_daily_rate",0) or 0) for x in (rw.get("rates") or []))
    if rate<=0: continue
    end=m.get("end_date_iso")
    try: dte=(datetime.datetime.fromisoformat(end.replace("Z","+00:00"))-NOW).days if end else None
    except: dte=None
    toks=m.get("tokens") or []
    price=None
    for t in toks:
        if t.get("outcome","").lower() in ("yes","up"): price=t.get("price")
    if price is None and toks: price=toks[0].get("price")
    rows.append({"cid":m.get("condition_id"),"q":m.get("question","")[:60],"slug":m.get("market_slug"),
                 "daily":round(rate,2),"min_size":rw.get("min_size"),"max_spread":rw.get("max_spread"),
                 "dte":dte,"price":price})
print(f"reward-active markets: {len(rows)}")
# calibration: find Lula June30 market rate
for r in rows:
    if "lula" in r["q"].lower(): print("  CALIBRATE:",r["q"],"daily_rate=",r["daily"])

# filter: slow (>=10d), mid price 0.10-0.90 (avoid forced two-sided), has pool
import math
def midok(p):
    try: p=float(p); return 0.10<=p<=0.90
    except: return False
cand=[r for r in rows if (r["dte"] is None or r["dte"]>=10) and midok(r["price"]) and r["daily"]>=1]
cand.sort(key=lambda r:-r["daily"])
top=cand[:120]
print(f"slow+midprice+pool>=1 candidates: {len(cand)} | enriching top {len(top)} with gamma competition...")

def enrich(r):
    try:
        g=requests.get(f"{GAMMA}/markets",params={"condition_ids":r["cid"]},headers=UA,timeout=12).json()
        if g:
            gm=g[0]
            r["liq"]=round(float(gm.get("liquidityNum") or 0),0)
            r["competitive"]=round(float(gm.get("competitive") or 0),3)
            r["spread"]=gm.get("spread"); r["vol24"]=round(float(gm.get("volume24hr") or 0),0)
    except: pass
    return r
with ThreadPoolExecutor(max_workers=12) as ex:
    top=[f.result() for f in as_completed([ex.submit(enrich,r) for r in top])]

# score: high daily reward, low competition (low liquidity & low competitive), wider max_spread easier
def score(r):
    liq=r.get("liq",1e9) or 1
    return r["daily"]/ (1+ (liq/1000.0))   # reward per $1k of competing liquidity
for r in top: r["edge"]=round(score(r),3)
top.sort(key=lambda r:-r["edge"])

print("\n=== TOP 30 FARM CANDIDATES (high reward / low competition / slow) ===")
hdr=f"{'daily$':>7} {'liq$':>9} {'comp':>5} {'edge':>7} {'dte':>5} {'maxSpr':>6} {'minSz':>5} {'price':>5}  question"
print(hdr); print("-"*len(hdr))
for r in top[:30]:
    print(f"{r['daily']:>7} {r.get('liq','?'):>9} {str(r.get('competitive','?')):>5} {r['edge']:>7} "
          f"{str(r['dte']):>5} {str(r['max_spread']):>6} {str(r['min_size']):>5} {str(r['price']):>5}  {r['q']}")

import csv,os
out=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\_lp_rewards_ranked.csv"
with open(out,"w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["edge","daily","liq","competitive","dte","max_spread","min_size","price","q","slug","cid","vol24"])
    w.writeheader()
    for r in top: w.writerow({k:r.get(k) for k in w.fieldnames})
print(f"\nsaved full ranked list -> {out}")
