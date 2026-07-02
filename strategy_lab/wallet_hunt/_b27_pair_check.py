import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, numpy as np, requests
W = "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"
UA = {"User-Agent": "gsl/1.0", "Accept": "application/json"}


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
while off < 3000:
    pg = g("https://data-api.polymarket.com/activity", {"user": W, "limit": 500, "offset": off})
    if not isinstance(pg, list) or not pg:
        break
    acts += pg; off += 500; time.sleep(.15)
df = pd.DataFrame(acts)
for c in ("price", "size", "usdcSize", "timestamp"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["type"] = df["type"].astype(str).str.upper(); df["side"] = df["side"].astype(str).str.upper()
df["cond"] = df["conditionId"].astype(str); df["slug"] = df["slug"].astype(str); df["outcome"] = df["outcome"].astype(str)
b = df[(df.type == "TRADE") & (df.side == "BUY")].copy()
print("sample buys", len(b), "span", pd.to_datetime(b.timestamp.min(), unit="s"), "->", pd.to_datetime(b.timestamp.max(), unit="s"))
print("event types:", df.type.value_counts().to_dict(), "sides:", df.side.value_counts().to_dict())

# per-cond both-sides + side vwaps
rows = []
for cond, gdf in b.groupby("cond"):
    up = gdf[gdf.outcome == "Up"]; dn = gdf[gdf.outcome == "Down"]
    rows.append(dict(cond=cond, nbuys=len(gdf), has_up=len(up) > 0, has_dn=len(dn) > 0,
                     up_vwap=np.average(up.price, weights=up.usdcSize) if len(up) else np.nan,
                     dn_vwap=np.average(dn.price, weights=dn.usdcSize) if len(dn) else np.nan,
                     up_usd=up.usdcSize.sum(), dn_usd=dn.usdcSize.sum()))
G = pd.DataFrame(rows)
both = G[G.has_up & G.has_dn].copy()
print(f"conds with buys={len(G)}  BOTH Up&Down={len(both)} ({len(both)/len(G)*100:.0f}%)")
print(f"avg buys/cond={G.nbuys.mean():.1f} max={G.nbuys.max()}  median={G.nbuys.median():.0f}")
if len(both):
    both["sum_vwap"] = both.up_vwap + both.dn_vwap
    print("paired sum_vwap (up+dn):")
    print(both.sum_vwap.describe(percentiles=[.1, .25, .5, .75, .9]).round(3).to_string())
    print("share sum_vwap<1.00: %.0f%%  <0.99: %.0f%%  <0.98: %.0f%%  <0.97: %.0f%%" % (
        (both.sum_vwap < 1.0).mean() * 100, (both.sum_vwap < 0.99).mean() * 100,
        (both.sum_vwap < 0.98).mean() * 100, (both.sum_vwap < 0.97).mean() * 100))
    # balanced size? min(up,dn)/max = how hedged
    both["bal"] = both[["up_usd", "dn_usd"]].min(axis=1) / both[["up_usd", "dn_usd"]].max(axis=1)
    print("size balance min/max per paired cond: median=%.2f" % both.bal.median())
b["asset"] = b.slug.str.extract(r"^([a-z0-9]+)-updown")[0]; b["tf"] = b.slug.str.extract(r"-updown-(\d+[mh])-")[0]
print("\nasset x tf buys:")
print(b.groupby(["asset", "tf"]).size().sort_values(ascending=False).head(8).to_string())
