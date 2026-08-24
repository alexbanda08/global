"""Puxa fills 2026-08-14..18 das 6 wallets (janela com ladder_tick na Ireland)."""
import requests, json, time, os, sys
WALLETS = {
    "PBot-6":"0x21d0a97aac03917e752857a551bbe5103a00e8d7",
    "PBot-2":"0x095fd7cc9ddf7110586d1bda3974eccc52155f24",
    "PBot-3":"0x74a2b82f079e12bcc25cd0d479f17979fb62e32f",
    "PBot-5":"0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11",
    "b945":"0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
    "b27":"0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
}
BASE="https://data-api.polymarket.com/activity"
SINCE=1786665600   # 2026-08-14 00:00 UTC
OUT=os.path.dirname(os.path.abspath(__file__))
def key(r): return (r.get("transactionHash"), r.get("asset"), r.get("side"),
                    int(float(r.get("size") or 0)*100), r.get("timestamp"))
def fetch(w, typ, cap):
    seen,out,end,stall=set(),[],None,0
    while len(out)<cap:
        got=0
        for off in range(0,3500,500):
            url=f"{BASE}?user={w}&type={typ}&limit=500&offset={off}"+(f"&end={end}" if end else "")
            b=[]
            for a in range(4):
                try:
                    r=requests.get(url,timeout=30); r.raise_for_status(); b=r.json(); break
                except Exception as e:
                    print("   retry",a,e,flush=True); time.sleep(2*(a+1))
            if not b: break
            for rec in b:
                k=key(rec)
                if k not in seen: seen.add(k); out.append(rec); got+=1
            if len(b)<500: break
            time.sleep(0.15)
        if not out: break
        oldest=min(r["timestamp"] for r in out)
        print(f"  {typ}: {len(out)} oldest {time.strftime('%m-%d %H:%M',time.gmtime(oldest))}",flush=True)
        if oldest<=SINCE: break
        if got==0:
            stall+=1
            if stall>=2: break
        else: stall=0
        end=oldest
    return [r for r in out if r["timestamp"]>=SINCE]
for nm,w in WALLETS.items():
    print(f"=== {nm} ===",flush=True)
    for typ,cap in (("TRADE",40000),("REDEEM",20000)):
        recs=fetch(w,typ,cap)
        json.dump(recs,open(os.path.join(OUT,f"recent_{typ}_{nm}.json"),"w"))
        print(f"  SAVED {typ}: {len(recs)}",flush=True)
