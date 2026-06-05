"""Healthy LP farms: markets with a REAL tight book (price discovery -> low adverse
selection) that are still slow + not overcrowded. Avoids the empty-book trap where
you'd be the sole MM in an illiquid binary."""
import requests, datetime, time, csv, json
from concurrent.futures import ThreadPoolExecutor, as_completed
CLOB="https://clob.polymarket.com"; GAMMA="https://gamma-api.polymarket.com"
UA={"User-Agent":"global-strategy-lab/1.0"}; NOW=datetime.datetime.now(datetime.timezone.utc)
OUT=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache"
def _get(u,p=None,t=5):
    for i in range(t):
        try:
            r=requests.get(u,params=p or {},headers=UA,timeout=25)
            if r.status_code==200: return r.json()
        except Exception: time.sleep(0.5+i)
    return None
def pull():
    out=[];cur=""
    while True:
        j=_get(f"{CLOB}/sampling-markets",{"next_cursor":cur} if cur else {})
        if not j: break
        out.extend(j.get("data",[]));cur=j.get("next_cursor")
        if not cur or cur=="LTE=": break
    return out
ms=pull(); cand=[]
for m in ms:
    if not (m.get("active") and m.get("accepting_orders") and not m.get("closed")): continue
    rw=m.get("rewards") or {}
    rate=sum(float(x.get("rewards_daily_rate",0) or 0) for x in (rw.get("rates") or []))
    if rate<10: continue
    end=m.get("end_date_iso")
    try: dte=(datetime.datetime.fromisoformat(end.replace("Z","+00:00"))-NOW).days if end else None
    except: dte=None
    if dte is None or dte<10: continue            # slow only
    toks=m.get("tokens") or []; price=None
    for t in toks:
        if t.get("outcome","").lower() in ("yes","up"): price=t.get("price")
    if price is None and toks: price=toks[0].get("price")
    try: pf=float(price)
    except: continue
    if not (0.12<=pf<=0.88): continue
    cand.append({"cid":m.get("condition_id"),"q":m.get("question","")[:56],"daily":round(rate,2),
                 "min_size":rw.get("min_size"),"max_spread":rw.get("max_spread"),"dte":dte,"price":pf})
print(f"slow (dte>=10) reward>= $10 mid-price candidates: {len(cand)}")
def eb(cids):
    j=_get(f"{GAMMA}/markets",{"condition_ids":cids,"limit":len(cids)}); r={}
    if isinstance(j,list):
        for gm in j:
            r[gm.get("conditionId")]={"liq":round(float(gm.get("liquidityNum") or 0),0),
                "comp":round(float(gm.get("competitive") or 0),3),
                "spread":float(gm.get("spread") or 9),"vol24":round(float(gm.get("volume24hr") or 0),0)}
    return r
cids=[c["cid"] for c in cand]; em={}
with ThreadPoolExecutor(max_workers=12) as ex:
    for fut in as_completed([ex.submit(eb,cids[i:i+20]) for i in range(0,len(cids),20)]):
        em.update(fut.result() or {})
for c in cand: c.update(em.get(c["cid"],{}))
# HEALTHY: real tight book (spread <= max_spread band, i.e. price discovery exists),
# decent volume (active), not insanely crowded. spread in price units; max_spread in cents.
healthy=[c for c in cand if c.get("spread") is not None and c.get("max_spread")
         and c["spread"]<= (float(c["max_spread"])/100.0)         # real quotes inside qualifying band
         and (c.get("vol24") or 0)>=200                            # actually trading
         and (c.get("liq") or 0)>=300]                             # real depth (not empty-book trap)
# rank: reward per unit competition (liquidity), prefer lower competitive score
for c in healthy: c["edge"]=round(c["daily"]/(1+(c["liq"] or 0)/1000.0),2)
healthy.sort(key=lambda c:-c["edge"])
print(f"\n=== HEALTHY FARMS (tight real book + active + slow): {len(healthy)} ===")
print(f"{'daily$':>6} {'liq$':>7} {'spr¢':>5} {'comp':>5} {'dte':>4} {'price':>6} {'vol24':>7} {'edge':>6}  question")
for c in healthy[:30]:
    print(f"{c['daily']:>6} {str(c['liq']):>7} {round(c['spread']*100,1):>5} {str(c['comp']):>5} {c['dte']:>4} {c['price']:>6} {str(c.get('vol24')):>7} {c['edge']:>6}  {c['q']}")
with open(OUT+r"\_lp_healthy_farms.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["edge","daily","liq","spread","comp","dte","price","vol24","max_spread","min_size","q","cid"])
    w.writeheader()
    for c in healthy: w.writerow({k:c.get(k) for k in w.fieldnames})
print(f"\nsaved -> {OUT}\\_lp_healthy_farms.csv")
