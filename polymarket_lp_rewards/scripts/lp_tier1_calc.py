"""Tier-1 token-launch LP farms: pull real books, compute existing competing
liquidity inside max_spread, and the SHARE OF POOL + CAPITAL needed to win a
target $/day. Two-sided 50/50 quoting at 1c inside mid.

Capital math (binary mkt): a balanced two-sided book of N shares (YES-bid N @ p,
NO-bid N @ 1-p) costs N*p + N*(1-p) = N dollars. So $capital ~= share count N.
Reward score of that book: Qme = S(v,1c) * N  (min of the two equal sides).
Your pool share = Qme / (Qexist + Qme). $/day = share * pool.
"""
import requests, time, json
CLOB="https://clob.polymarket.com"; GAMMA="https://gamma-api.polymarket.com"
UA={"User-Agent":"global-strategy-lab/1.0"}
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

NAMES=["titan","bulk","3jane","propr","curvance","slingshot"]
ms=pull(); picks=[]
for m in ms:
    q=(m.get("question") or "").lower()
    if "launch a token" not in q: continue
    if not any(n in q for n in NAMES): continue
    rw=m.get("rewards") or {}
    rate=sum(float(x.get("rewards_daily_rate",0) or 0) for x in (rw.get("rates") or []))
    if rate<5: continue
    picks.append({"q":m.get("question"),"cid":m.get("condition_id"),
                  "daily":round(rate,2),"v":float(rw.get("max_spread") or 3),
                  "minsz":rw.get("min_size"),"tokens":[(t.get("token_id"),t.get("outcome"),float(t.get("price",0))) for t in (m.get("tokens") or [])]})
# dedupe by cid, keep one per name+date
seen=set(); P=[]
for p in sorted(picks,key=lambda x:-x["daily"]):
    if p["cid"] in seen: continue
    seen.add(p["cid"]); P.append(p)
print(f"matched {len(P)} Tier-1 token-launch markets\n")

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
    return mid,bb,ba,Qb,Qa

for p in P:
    yes=p["tokens"][0][0] if p["tokens"] else None
    bk=book(yes) if yes else None
    print("="*72)
    print(f"{p['q']}")
    print(f"  pool=${p['daily']}/day | v(max_spread)={p['v']}c | min_size={p['minsz']}")
    if not bk: print("  (no book)"); continue
    qq=qual(*bk,p["v"])
    if not qq: print("  (empty/one-sided book)"); continue
    mid,bb,ba,Qb,Qa=qq
    Qexist=min(Qb,Qa)
    S1=((p["v"]-1)/p["v"])**2   # score multiplier quoting 1c inside mid
    print(f"  book: bid {bb:.2f} / ask {ba:.2f}  (spread {round((ba-bb)*100,1)}c) | mid {mid:.3f}")
    print(f"  existing qualifying score inside band: Q_yes={Qb:.1f} Q_no={Qa:.1f} -> Qexist(min)={Qexist:.1f}")
    print(f"  -> SHARE of pool & CAPITAL needed (two-sided 50/50, quote 1c inside, S={S1:.3f}):")
    print(f"     {'target$/day':>11} {'pool share':>10} {'reqQme':>8} {'capital$':>9}")
    for tgt in [p['daily']*0.25, p['daily']*0.5, p['daily']*0.75]:
        share=tgt/p['daily']
        Qme=Qexist*share/(1-share) if share<1 else float('inf')
        cap=Qme/S1                # $ capital ~= shares = Qme/S1
        # respect min_size: each side must be >= minsz shares
        print(f"     {round(tgt,1):>11} {f'{100*share:.0f}%':>10} {Qme:>8.1f} {cap:>9.0f}")
    # also: what does a fixed $250 / $500 two-sided stake earn?
    print(f"  -> fixed-stake yield (two-sided 50/50, 1c inside):")
    for cap in [250,500,1000]:
        Qme=S1*cap; share=Qme/(Qexist+Qme); print(f"     ${cap:>4} -> share {100*share:>4.1f}%  ${share*p['daily']:>5.2f}/day  (${share*p['daily']*30:.0f}/mo)")
    time.sleep(0.05)
