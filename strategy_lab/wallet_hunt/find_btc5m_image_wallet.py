"""
Identify the wallet behind the screenshotted BTC 5m up/down activity feed
(June 2 2026, ~$3 buys, favorite side, hold-to-resolution).

Method: resolve the 12 slug conditionIds shown in the image -> pull EVERY trade
per market from data-api -> rank proxyWallets by how many of the 12 markets they
BOUGHT in -> print per-market buy fingerprint (outcome/size/price) so we can
match it to the image (Down 4.1sh, Up 5.1sh, etc.).

Run:  py -3 strategy_lab/wallet_hunt/find_btc5m_image_wallet.py
"""
import requests, calendar, datetime, json, time
from collections import defaultdict
from pathlib import Path

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
OUT = Path(__file__).resolve().parent / "cache"
OUT.mkdir(exist_ok=True)

# ET start times (June 2 2026, AM). EDT = UTC-4.
SLOTS_ET = ["2:20","3:40","3:55","5:05","5:15","6:15","6:40","6:45","6:55","7:00","7:25","7:40"]
# image buys: et -> (outcome, shares, cost_usd).  price = cost/shares.
IMG = {"7:40":("Down",4.1,3.02),"7:25":("Down",4.6,3.04),"7:00":("Down",4.0,3.36),
       "6:55":("Up",4.0,2.98),"6:45":("Up",5.1,3.04),"6:40":("Down",4.0,3.36),
       "6:15":("Up",3.5,2.91),"5:15":("Up",3.0,2.69),"5:05":("Up",4.0,2.98),
       "3:55":("Down",4.2,3.22),"3:40":("Up",3.1,2.69),"2:20":("Up",4.1,3.10)}
def img_price(et):
    o,sh,c = IMG[et]; return o,sh,c/sh

def slug_for(et):
    h,m = map(int, et.split(":")); dt = datetime.datetime(2026,6,2,h+4,m,0)
    return et, calendar.timegm(dt.timetuple())

def cid_for_slug(slug):
    r = requests.get(f"{GAMMA}/events", params={"slug": slug}, headers=UA, timeout=15)
    if r.status_code != 200 or not r.json(): return None
    mk = r.json()[0].get("markets", [])
    return mk[0].get("conditionId") if mk else None

def all_trades(cid, page=500):
    out=[]; off=0
    while True:
        r = requests.get(f"{DATA}/trades", params={"market":cid,"limit":page,"offset":off},
                         headers=UA, timeout=15)
        if r.status_code!=200: break
        j=r.json()
        if not isinstance(j,list) or not j: break
        out.extend(j)
        if len(j)<page: break
        off+=len(j); time.sleep(0.05)
    return out

RAW = OUT/"_btc5m_image_rawtrades.json"
markets={}   # et -> {slug,cid,ts}
trades_by_et={}
if RAW.exists():
    cached=json.loads(RAW.read_text())
    markets=cached["markets"]; trades_by_et=cached["trades"]
    print(f"[cache] loaded {sum(len(v) for v in trades_by_et.values())} trades from {RAW.name}")
else:
    for et in SLOTS_ET:
        _,ts = slug_for(et); slug=f"btc-updown-5m-{ts}"
        cid = cid_for_slug(slug)
        markets[et]={"slug":slug,"cid":cid,"ts":ts}
        if not cid:
            print(f"[WARN] no conditionId for {et} ({slug})"); trades_by_et[et]=[]; continue
        tr = all_trades(cid)
        # keep only fields we need to bound file size
        trades_by_et[et]=[{"w":str(t.get("proxyWallet","")).lower(),"side":str(t.get("side","")).upper(),
                           "o":t.get("outcome"),"sz":float(t.get("size",0)),"px":float(t.get("price",0)),
                           "ts":t.get("timestamp")} for t in tr]
        print(f"{et}AM ET  {slug}  cid={cid[:14]}..  trades={len(tr)}")
    RAW.write_text(json.dumps({"markets":markets,"trades":trades_by_et},default=str))
    print(f"[cache] saved raw trades -> {RAW.name}")

# PRECISE fingerprint match: per slot, a wallet "matches" if it has a BUY with
# outcome==image, size within ±0.25 sh, price within ±0.03.
match_markets=defaultdict(set)     # wallet -> set(et) matched on fingerprint
wallet_buys=defaultdict(lambda: defaultdict(list))  # wallet -> et -> [(o,sz,px)]
for et,tr in trades_by_et.items():
    o_img,sh_img,px_img = img_price(et)
    for t in tr:
        w=t["w"]
        if not w.startswith("0x"): continue
        if t["side"]!="BUY": continue
        wallet_buys[w][et].append((t["o"],t["sz"],t["px"]))
        if (t["o"]==o_img and abs(t["sz"]-sh_img)<=0.25 and abs(t["px"]-px_img)<=0.03):
            match_markets[w].add(et)

ranked=sorted(match_markets.items(), key=lambda kv:-len(kv[1]))
print(f"\n=== wallets ranked by FINGERPRINT match (outcome+size±0.25+price±0.03) ===")
for w,ets in ranked[:15]:
    print(f"{w}  matched={len(ets)}/12   {sorted(ets)}")

print("\n=== top-3 candidate per-market match vs image ===")
for w,ets in ranked[:3]:
    print(f"\nWALLET {w}  ({len(ets)}/12 matched)")
    print(f"{'ET':>6} | {'image (o,sh,px)':>22} | {'wallet matching buy':>26}")
    for et in SLOTS_ET:
        o,sh,px=img_price(et)
        cand=[b for b in wallet_buys[w].get(et,[]) if b[0]==o and abs(b[1]-sh)<=0.25 and abs(b[2]-px)<=0.03]
        cs=f"{cand[0][0]} {cand[0][1]:.3f}sh @{cand[0][2]:.3f}" if cand else "—"
        print(f"{et:>6} | {o+' '+str(sh)+'sh @'+format(px,'.3f'):>22} | {cs:>26}")

best = ranked[0][0] if ranked else None
res={"markets":markets,
     "ranked":[{"wallet":w,"matched":sorted(list(ets)),"n":len(ets)} for w,ets in ranked[:15]],
     "best_wallet":best}
(OUT/"_btc5m_image_wallet.json").write_text(json.dumps(res,default=str,indent=2))
print(f"\nbest_wallet = {best}  (matched {len(ranked[0][1]) if ranked else 0}/12)")
print(f"saved: {OUT/'_btc5m_image_wallet.json'}")
