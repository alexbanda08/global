"""LP-reward farm analyzer:
 A) Broaden the gem hunt — enrich ALL reward markets with gamma liquidity (batched),
    rank by reward/competition to find more low-liquidity / high-reward pools.
 B) Pull the real CLOB order book for the top picks, compute true qualifying depth
    INSIDE max_spread, and estimate your $/day reward share at a given stake.
"""
import requests, datetime, time, csv, json
from concurrent.futures import ThreadPoolExecutor, as_completed
CLOB="https://clob.polymarket.com"; GAMMA="https://gamma-api.polymarket.com"
UA={"User-Agent":"global-strategy-lab/1.0"}
NOW=datetime.datetime.now(datetime.timezone.utc)
OUT=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache"

def _get(url,params=None,tries=5):
    for i in range(tries):
        try:
            r=requests.get(url,params=params or {},headers=UA,timeout=25)
            if r.status_code==200: return r.json()
        except Exception: time.sleep(0.6+i)
    return None

def pull_sampling():
    out=[]; cur=""
    while True:
        j=_get(f"{CLOB}/sampling-markets",{"next_cursor":cur} if cur else {})
        if not j: break
        out.extend(j.get("data",[])); cur=j.get("next_cursor")
        if not cur or cur=="LTE=": break
    return out

ms=pull_sampling()
cand=[]
tok_by_cid={}
for m in ms:
    if not (m.get("active") and m.get("accepting_orders") and not m.get("closed")): continue
    rw=m.get("rewards") or {}
    rate=sum(float(x.get("rewards_daily_rate",0) or 0) for x in (rw.get("rates") or []))
    if rate<1: continue
    end=m.get("end_date_iso")
    try: dte=(datetime.datetime.fromisoformat(end.replace("Z","+00:00"))-NOW).days if end else None
    except: dte=None
    toks=m.get("tokens") or []
    price=None
    for t in toks:
        if t.get("outcome","").lower() in ("yes","up"): price=t.get("price")
    if price is None and toks: price=toks[0].get("price")
    try: pf=float(price)
    except: continue
    if not (0.10<=pf<=0.90): continue
    cid=m.get("condition_id")
    tok_by_cid[cid]=[(t.get("token_id"),t.get("outcome"),t.get("price")) for t in toks]
    cand.append({"cid":cid,"q":m.get("question","")[:58],"daily":round(rate,2),
                 "min_size":rw.get("min_size"),"max_spread":rw.get("max_spread"),"dte":dte,"price":pf})
print(f"reward-active mid-price candidates (daily>=1): {len(cand)}")

# ---- A) batched gamma liquidity enrichment for ALL candidates ----
def enrich_batch(cids):
    j=_get(f"{GAMMA}/markets",{"condition_ids":cids,"limit":len(cids)})
    res={}
    if isinstance(j,list):
        for gm in j:
            res[gm.get("conditionId")]={"liq":round(float(gm.get("liquidityNum") or 0),0),
                                        "comp":round(float(gm.get("competitive") or 0),3)}
    return res
cids=[c["cid"] for c in cand]
liq_map={}
batches=[cids[i:i+20] for i in range(0,len(cids),20)]
with ThreadPoolExecutor(max_workers=12) as ex:
    for fut in as_completed([ex.submit(enrich_batch,b) for b in batches]):
        liq_map.update(fut.result() or {})
for c in cand:
    e=liq_map.get(c["cid"],{}); c["liq"]=e.get("liq"); c["comp"]=e.get("comp")
enr=[c for c in cand if c.get("liq") is not None]
print(f"enriched with gamma liquidity: {len(enr)}")

# gem score: reward per $1k competing liquidity
for c in enr: c["edge"]=round(c["daily"]/(1+(c["liq"] or 0)/1000.0),2)
gems=sorted(enr,key=lambda c:-c["edge"])
# low-liquidity gems: liq < $500 and daily>=20
lowliq=[c for c in enr if (c["liq"] or 0)<500 and c["daily"]>=20]
lowliq.sort(key=lambda c:-c["daily"])
print(f"\n=== LOW-LIQUIDITY GEMS (book liq<$500, daily>=$20): {len(lowliq)} ===")
print(f"{'daily$':>6} {'liq$':>7} {'comp':>5} {'dte':>5} {'price':>6} {'maxSpr':>6} {'minSz':>5}  question")
for c in lowliq[:30]:
    print(f"{c['daily']:>6} {str(c['liq']):>7} {str(c['comp']):>5} {str(c['dte']):>5} {c['price']:>6} {str(c['max_spread']):>6} {str(c['min_size']):>5}  {c['q']}")

with open(OUT+r"\_lp_gems.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["edge","daily","liq","comp","dte","price","max_spread","min_size","q","cid"])
    w.writeheader()
    for c in gems: w.writerow({k:c.get(k) for k in w.fieldnames})

# ---- B) book analysis of top picks (top low-liq gems + a couple slow long-dated) ----
def book(token_id):
    j=_get(f"{CLOB}/book",{"token_id":token_id})
    if not j: return None
    bids=[(float(x["price"]),float(x["size"])) for x in j.get("bids",[])]
    asks=[(float(x["price"]),float(x["size"])) for x in j.get("asks",[])]
    return bids,asks

def qualifying(bids,asks,v_cents):
    # v in cents; midpoint from best bid/ask
    if not bids or not asks: return None
    bb=max(p for p,_ in bids); ba=min(p for p,_ in asks); mid=(bb+ba)/2; v=v_cents/100.0
    Qbid=sum(((v-(mid-p))/v)**2*s for p,s in bids if 0<=mid-p<=v)
    Qask=sum(((v-(p-mid))/v)**2*s for p,s in asks if 0<=p-mid<=v)
    return mid,bb,ba,round(Qbid,1),round(Qask,1)

# pick targets: top 10 low-liq gems
targets=lowliq[:10]
print(f"\n=== ORDER-BOOK ANALYSIS of top {len(targets)} gems (est. your $/day at $250 two-sided, quote 1 tick inside) ===")
print(f"{'daily$':>6} {'bid':>5} {'ask':>5} {'Qbid':>7} {'Qask':>7} {'yourShare%':>10} {'est$/day':>8}  question")
for c in targets:
    toks=tok_by_cid.get(c["cid"],[])
    if not toks: continue
    yes=toks[0][0]  # YES token book; complement implied
    bk=book(yes)
    if not bk: print(f"{c['daily']:>6}  (no book)  {c['q']}"); continue
    bids,asks=bk
    qual=qualifying(bids,asks,float(c["max_spread"] or 3))
    if not qual: print(f"{c['daily']:>6}  (empty book) {c['q']}"); continue
    mid,bb,ba,Qbid,Qask=qual
    v=float(c["max_spread"] or 3)
    # my order: $250 each side at 1 tick (1c) inside mid -> s=1c
    S1=((v-1)/v)**2
    shares=250.0/max(mid,0.05)
    Qme=S1*shares
    Qexist=min(Qbid,Qask) if (0.10<=mid<=0.90) else min(Qbid,Qask)
    share=Qme/(Qexist+Qme) if (Qexist+Qme)>0 else 0
    est=round(share*c["daily"],2)
    print(f"{c['daily']:>6} {bb:>5} {ba:>5} {Qbid:>7} {Qask:>7} {100*share:>9.1f}% {est:>8}  {c['q']}")
    time.sleep(0.05)
print(f"\nsaved gems -> {OUT}\\_lp_gems.csv")
