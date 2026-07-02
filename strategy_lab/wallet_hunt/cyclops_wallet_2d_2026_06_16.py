"""CYCLOPS WALLET — LAST 2 DAYS — 2026-06-16. Full per-trade detail + true WR."""
from __future__ import annotations
import sys, io, json, time
from pathlib import Path
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, requests
pd.set_option("display.width", 220)
W = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
DATA = "https://data-api.polymarket.com"; LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "gsl/1.0", "Accept": "application/json"}
NOW = int(time.time()); CUT = NOW - 2 * 86400
CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\_cyclops_2d")
CACHE.mkdir(parents=True, exist_ok=True)
print("CYCLOPS_2D OUTPUT START", flush=True)


def g(u, p, t=4):
    for _ in range(t):
        try:
            r = requests.get(u, params=p, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.json()
            time.sleep(.4)
        except Exception:
            time.sleep(.4)
    return None


acts, off = [], 0
while True:
    pg = g(f"{DATA}/activity", {"user": W, "limit": 500, "offset": off})
    if not isinstance(pg, list) or not pg:
        break
    acts += pg
    if min(int(a.get("timestamp", 0)) for a in pg) < CUT or len(pg) < 500:
        break
    off += 500; time.sleep(.2)
(CACHE / "activity_raw.json").write_text(json.dumps(acts, default=str), encoding="utf-8")
df = pd.DataFrame(acts)
for c in ("price", "size", "usdcSize", "timestamp"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["type"] = df["type"].astype(str).str.upper(); df["side"] = df["side"].astype(str).str.upper(); df["slug"] = df["slug"].astype(str)
w = df[df.timestamp >= CUT].copy()
w["asset"] = w["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
w["tf"] = w["slug"].str.extract(r"-updown-(\d+[mh])-")[0]
w["cond"] = w["conditionId"].astype(str)
w["outcome"] = w["outcome"].astype(str)
print(f"now_utc={pd.to_datetime(NOW,unit='s')}  cutoff_utc={pd.to_datetime(CUT,unit='s')}")
print(f"events last 2d: {len(w)}  types: {w['type'].value_counts().to_dict()}")
b = w[(w.type == "TRADE") & (w.side == "BUY")]; s = w[(w.type == "TRADE") & (w.side == "SELL")]; rd = w[w.type == "REDEEM"]
bc = float(b.usdcSize.sum()); sp = float(s.usdcSize.sum()); rp = float(rd.usdcSize.sum())
net = rp + sp - bc
print(f"\nBUY={len(b)} cost=${bc:.2f}   SELL={len(s)} ${sp:.2f}   REDEEM={len(rd)} ${rp:.2f}")
print(f">>> NET=${net:+.2f}   ROI={net/bc*100:+.1f}%" if bc else ">>> no buys")

print("\n=== MARKETS (asset×tf) ===")
m = b.groupby(["asset", "tf"]).agg(buys=("usdcSize", "size"), cost=("usdcSize", "sum"))
rby = rd.groupby(["asset", "tf"]).usdcSize.sum().rename("redeem")
m = m.join(rby).fillna(0.0); m["pnl"] = m.redeem - m.cost; m["roi%"] = (m.pnl / m.cost * 100).round(1)
print(m.round(2).to_string())

if len(b):
    print(f"\nentry px median={b.price.median():.3f}  fav(>0.5)={ (b.price>0.5).mean()*100:.0f}%  "
          f"size median={b['size'].median():.2f}  notional median=${b.usdcSize.median():.2f}")
    print("outcome mix:", b.outcome.value_counts().to_dict())

# true WR on resolved buys
b2 = b.copy(); b2["suf"] = pd.to_numeric(b2["slug"].str.extract(r"-(\d+)\Z")[0], errors="coerce")
b2["resolved"] = (b2["suf"] + 300) < NOW; rc = set(rd.cond); b2["won"] = b2.cond.isin(rc)
rb = b2[b2.resolved]
print(f"\n=== TRUE WR ===\nresolved={len(rb)} won={int(rb.won.sum())} lost={int((~rb.won).sum())} "
      f"TRUE_WR={rb.won.mean()*100:.1f}%  pending={len(b2)-len(rb)}")
los = rb[~rb.won]
if len(los):
    print("LOSERS:")
    for _, r in los.iterrows():
        print(f"   {r['slug']} {r['outcome']} px={r['price']:.2f} ${r['usdcSize']:.2f}")

print("\n=== ALL BUYS last 2d (ET ≈ UTC-4) ===")
for _, r in b.sort_values("timestamp", ascending=False).iterrows():
    et = pd.to_datetime(int(r.timestamp) - 4 * 3600, unit="s").strftime("%m-%d %I:%M%p")
    won = "WON " if r.cond in rc else ("PEND" if (r.suf if False else int(pd.to_numeric(r['slug'].rsplit('-',1)[1]))+300) > NOW else "LOST")
    print(f"  {et}ET {str(r.asset):>3}-{str(r.tf):<3} {str(r.outcome):>4} px={r.price:.2f} sz={r['size']:.2f} ${r.usdcSize:.2f} {won} {r.slug}")

print("\n=== DAILY ===")
w["day"] = pd.to_datetime(w.timestamp, unit="s").dt.strftime("%Y-%m-%d")
for day, gdf in w.groupby("day"):
    gb = gdf[(gdf.type == "TRADE") & (gdf.side == "BUY")]; gr = gdf[gdf.type == "REDEEM"]
    cost = float(gb.usdcSize.sum()); pnl = float(gr.usdcSize.sum()) - cost
    print(f"  {day}  buys={len(gb):2d}  redeems={len(gr):2d}  cost=${cost:7.2f}  net=${pnl:+7.2f}  roi={pnl/cost*100 if cost else 0:+.1f}%")

for wd in ("1d", "all"):
    lb = g(f"{LB}/profit", {"window": wd, "address": W})
    print(f"\nlb /profit {wd}: {json.dumps(lb)[:160] if lb else 'n/a'}")
print("CYCLOPS_2D OUTPUT END")
