"""Book-verify the DURABLE low-competition gems (dte>=7) and estimate $/day."""
import requests, csv, time
from concurrent.futures import ThreadPoolExecutor, as_completed
CLOB="https://clob.polymarket.com"; GAMMA="https://gamma-api.polymarket.com"
UA={"User-Agent":"global-strategy-lab/1.0"}
def _get(u,p=None,t=5):
    for i in range(t):
        try:
            r=requests.get(u,params=p or {},headers=UA,timeout=25)
            if r.status_code==200: return r.json()
        except Exception: time.sleep(0.5+i)
    return None
rows=list(csv.DictReader(open(r"strategy_lab/wallet_hunt/cache/_lp_gems.csv",encoding="utf-8")))
def f(x):
    try: return float(x)
    except: return None
dur=[r for r in rows if f(r["dte"]) is not None and f(r["dte"])>=7 and f(r["liq"]) is not None and f(r["liq"])<300 and f(r["daily"])>=30]
dur.sort(key=lambda r:-f(r["daily"]))
dur=dur[:14]
# get tokens for these cids via gamma (batch)
cids=[r["cid"] for r in dur]
g=_get(f"{GAMMA}/markets",{"condition_ids":cids,"limit":len(cids)}) or []
tok={}
import json
for gm in g:
    ids=gm.get("clobTokenIds")
    try: ids=json.loads(ids) if isinstance(ids,str) else ids
    except: ids=None
    if ids: tok[gm.get("conditionId")]=ids[0]
def book(tid):
    j=_get(f"{CLOB}/book",{"token_id":tid})
    if not j: return None
    return ([(float(x["price"]),float(x["size"])) for x in j.get("bids",[])],
            [(float(x["price"]),float(x["size"])) for x in j.get("asks",[])])
def qual(bids,asks,vc):
    if not bids or not asks: return None
    bb=max(p for p,_ in bids); ba=min(p for p,_ in asks); mid=(bb+ba)/2; v=vc/100
    Qb=sum(((v-(mid-p))/v)**2*s for p,s in bids if 0<=mid-p<=v)
    Qa=sum(((v-(p-mid))/v)**2*s for p,s in asks if 0<=p-mid<=v)
    return mid,bb,ba,round(Qb,1),round(Qa,1)
print(f"{'daily$':>6} {'dte':>4} {'bid':>5} {'ask':>5} {'spr¢':>5} {'Qexist':>7} {'share%@$250':>11} {'$/day@250':>9} {'$/day@1k':>8}  question")
for r in dur:
    tid=tok.get(r["cid"])
    if not tid: print(f"{r['daily']:>6}  (no token)  {r['q']}"); continue
    bk=book(tid)
    if not bk: print(f"{r['daily']:>6}  (no book)  {r['q']}"); continue
    q=qual(*bk,float(r["max_spread"] or 3))
    if not q: print(f"{r['daily']:>6}  (empty)  {r['q']}"); continue
    mid,bb,ba,Qb,Qa=q; v=float(r["max_spread"] or 3); daily=f(r["daily"])
    S1=((v-1)/v)**2; Qex=min(Qb,Qa)
    def est(stake):
        sh=stake/max(mid,.05); Qme=S1*sh; share=Qme/(Qex+Qme) if (Qex+Qme)>0 else 0
        return share, round(share*daily,1)
    sh250,e250=est(250); _,e1k=est(1000)
    print(f"{daily:>6} {r['dte']:>4} {bb:>5} {ba:>5} {round((ba-bb)*100,1):>5} {Qex:>7} {100*sh250:>10.1f}% {e250:>9} {e1k:>8}  {r['q']}")
    time.sleep(0.05)
