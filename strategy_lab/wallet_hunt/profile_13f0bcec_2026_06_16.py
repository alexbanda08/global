"""PROFILE wallet 0x13f0bcec… — 2026-06-16. Identify + characterize strategy.
Pull /activity, classify markets/tf/side, entry profile, fire-offset into window,
true WR (resolved buys), PnL/ROI, daily, lb-api handle + all-time profit."""
from __future__ import annotations
import sys, io, json, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, requests
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 40)
W = "0x13f0bcec1e2e60ec9acc3bee4d2da2fe9694a50f"
DATA = "https://data-api.polymarket.com"; LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "gsl/1.0", "Accept": "application/json"}
NOW = int(time.time()); DAYS = 7; CUT = NOW - DAYS * 86400
CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache") / W[:10]
CACHE.mkdir(parents=True, exist_ok=True)
print("PROFILE_13f0bcec OUTPUT START", flush=True)


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
print(f"pulled {len(acts)} activity events (cap {DAYS}d window)")
if not acts:
    print("NO ACTIVITY — inactive or API-blocked."); print("PROFILE_13f0bcec OUTPUT END"); sys.exit(0)

df = pd.DataFrame(acts)
for c in ("price", "size", "usdcSize", "timestamp"):
    if c in df:
        df[c] = pd.to_numeric(df[c], errors="coerce")
df["type"] = df.get("type", "").astype(str).str.upper(); df["side"] = df.get("side", "").astype(str).str.upper()
df["slug"] = df.get("slug", "").astype(str); df["cond"] = df.get("conditionId", "").astype(str)
df["outcome"] = df.get("outcome", "").astype(str)
df["dt"] = pd.to_datetime(df.timestamp, unit="s", utc=True)
print(f"full pull span: {df.dt.min()} .. {df.dt.max()}")

w = df[df.timestamp >= CUT].copy()
print(f"\n=== LAST {DAYS}d: {len(w)} events  types: {w['type'].value_counts().to_dict()} ===")
# market structure
w["asset"] = w["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
w["tf"] = w["slug"].str.extract(r"-updown-(\d+[mh])-")[0]
# non-updown markets?
nonupdown = w[~w["slug"].str.contains("updown", na=False) & (w["slug"] != "")]
print(f"slug families (first token): {w['slug'].str.extract(r'^([a-z0-9]+)')[0].value_counts().head(10).to_dict()}")
if len(nonupdown):
    print(f"NON-updown markets present: {len(nonupdown)} — sample slugs:")
    for sgl in nonupdown["slug"].dropna().unique()[:8]:
        print("   ", sgl)

b = w[(w.type == "TRADE") & (w.side == "BUY")]; s = w[(w.type == "TRADE") & (w.side == "SELL")]; rd = w[w.type == "REDEEM"]
bc = float(b.usdcSize.sum()); sp = float(s.usdcSize.sum()); rp = float(rd.usdcSize.sum())
net = rp + sp - bc
print(f"\nBUY={len(b)} cost=${bc:.2f}  SELL={len(s)} ${sp:.2f}  REDEEM={len(rd)} ${rp:.2f}")
print(f">>> NET (net cash {DAYS}d)=${net:+.2f}  ROI={net/bc*100:+.1f}%" if bc else ">>> no buys")

if len(b):
    print("\n=== MARKETS (asset×tf) ===")
    m = b.groupby(["asset", "tf"], dropna=False).agg(buys=("usdcSize", "size"), cost=("usdcSize", "sum"))
    rby = rd.groupby(["asset", "tf"], dropna=False).usdcSize.sum().rename("redeem")
    sby = s.groupby(["asset", "tf"], dropna=False).usdcSize.sum().rename("sell")
    m = m.join(rby).join(sby).fillna(0.0); m["pnl"] = m.redeem + m.sell - m.cost
    m["roi%"] = (m.pnl / m.cost * 100).round(1)
    print(m.round(2).to_string())
    print(f"\nentry px: median={b.price.median():.3f} mean={b.price.mean():.3f} "
          f"p10={b.price.quantile(.1):.3f} p90={b.price.quantile(.9):.3f}  fav(>0.5)={(b.price>0.5).mean()*100:.0f}%")
    print(f"size: median={b['size'].median():.2f}  notional median=${b.usdcSize.median():.2f} "
          f"(min ${b.usdcSize.min():.2f} max ${b.usdcSize.max():.2f})")
    print("outcome mix:", b.outcome.value_counts().to_dict())
    # multiple buys per slug? (pair-arb signature = both Up&Down same slug)
    perslug = b.groupby("cond")["outcome"].agg(lambda x: tuple(sorted(set(x))))
    both = (perslug.apply(len) >= 2).sum()
    print(f"slugs with BOTH Up&Down bought (pair signature): {both}/{b['cond'].nunique()}")
    # fire offset into window
    b2 = b.copy()
    b2["slot"] = pd.to_numeric(b2["slug"].str.extract(r"-(\d+)\Z")[0], errors="coerce")
    wlen = b2["tf"].map({"5m": 300, "15m": 900, "1h": 3600})
    b2["off"] = b2.timestamp - b2["slot"]
    okoff = b2["off"].dropna()
    okoff = okoff[(okoff >= -5) & (okoff <= 3700)]
    print(f"fire offset into window (s): median={okoff.median():.0f} p10={okoff.quantile(.1):.0f} p90={okoff.quantile(.9):.0f}")

# true WR resolved buys
if len(b):
    b2 = b.copy(); b2["suf"] = pd.to_numeric(b2["slug"].str.extract(r"-(\d+)\Z")[0], errors="coerce")
    wlen = b2["tf"].map({"5m": 300, "15m": 900, "1h": 3600}).fillna(300)
    b2["resolved"] = (b2["suf"] + wlen) < NOW; rc = set(rd.cond); b2["won"] = b2.cond.isin(rc)
    rb = b2[b2.resolved]
    if len(rb):
        print(f"\n=== TRUE WR ===\nresolved={len(rb)} won={int(rb.won.sum())} lost={int((~rb.won).sum())} "
              f"TRUE_WR={rb.won.mean()*100:.1f}%  pending={len(b2)-len(rb)}")

# daily
w["day"] = w.dt.dt.strftime("%Y-%m-%d")
print("\n=== DAILY (buys, redeems, cost, net, roi) ===")
for day, gdf in w.groupby("day"):
    gb = gdf[(gdf.type == "TRADE") & (gdf.side == "BUY")]; gs = gdf[(gdf.type == "TRADE") & (gdf.side == "SELL")]; gr = gdf[gdf.type == "REDEEM"]
    cost = float(gb.usdcSize.sum()); pnl = float(gr.usdcSize.sum()) + float(gs.usdcSize.sum()) - cost
    print(f"  {day}  buys={len(gb):3d} sells={len(gs):3d} redeems={len(gr):3d} cost=${cost:8.2f} net=${pnl:+8.2f} roi={pnl/cost*100 if cost else 0:+.1f}%")

# latest 30 trades detail
print("\n=== LATEST 30 BUYS ===")
for _, r in b.sort_values("timestamp", ascending=False).head(30).iterrows():
    et = pd.to_datetime(int(r.timestamp) - 4 * 3600, unit="s").strftime("%m-%d %I:%M%p")
    print(f"  {et}ET {str(r.asset):>4}-{str(r.tf):<3} {str(r.outcome):>5} px={r.price:.3f} sz={r['size']:.2f} ${r.usdcSize:.2f} {r.slug}")

# identity
for wd in ("1d", "7d", "all"):
    lb = g(f"{LB}/profit", {"window": wd, "address": W})
    print(f"\nlb /profit {wd}: {json.dumps(lb)[:200] if lb else 'n/a'}")
print("PROFILE_13f0bcec OUTPUT END")
