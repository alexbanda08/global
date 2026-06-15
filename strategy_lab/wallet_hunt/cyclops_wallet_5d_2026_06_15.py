"""CYCLOPS WALLET — LAST 5 DAYS — 2026-06-15
Fresh pull (no cache) of the cyclops executor wallet's Polymarket activity for the
last 5 days. Verify vs operator's screenshot (BTC 5m favorite-hold Jun 14), then
produce a complete handoff: markets traded, ROI per market, trade counts, WR,
entry-price profile, per-slug detail, daily breakdown.

Wallet = 0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c (Cyclops.exe / Limp-Pitcher)
PnL  = net cash over window = Σ REDEEM payout + Σ SELL proceeds − Σ BUY cost.
ROI  = realized PnL / BUY cost (per asset×tf bucket).
WR   = fraction of RESOLVED conditionIds (got a redeem) whose payout > 0.

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_wallet_5d_2026_06_15.py
"""
from __future__ import annotations
import sys, io, json, time
import datetime as dt
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
import requests

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

TAG = "CYCLOPS_WALLET_5D_2026_06_15"
print(TAG, "OUTPUT START", flush=True)

WALLET = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_cyclops_5d"
CACHE.mkdir(parents=True, exist_ok=True)
DATA = "https://data-api.polymarket.com"
LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

NOW = int(time.time())
DAYS = 5
CUTOFF = NOW - DAYS * 86400
print(f"now_utc={dt.datetime.utcfromtimestamp(NOW)}  cutoff_utc={dt.datetime.utcfromtimestamp(CUTOFF)} ({DAYS}d)", flush=True)


def _get(url, params=None, tries=4):
    for _ in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.json()
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    return None


# ---- 1. paginate /activity until past the 5d cutoff ----
acts, offset, LIM = [], 0, 500
while True:
    page = _get(f"{DATA}/activity", {"user": WALLET, "limit": LIM, "offset": offset})
    if not isinstance(page, list) or not page:
        break
    acts.extend(page)
    oldest = min(int(a.get("timestamp", 0)) for a in page)
    if oldest < CUTOFF or len(page) < LIM:
        break
    offset += LIM
    time.sleep(0.25)

(CACHE / "activity_raw.json").write_text(json.dumps(acts, default=str), encoding="utf-8")
print(f"pulled {len(acts)} total activity events", flush=True)
if not acts:
    print("NO ACTIVITY — wallet inactive or API blocked."); print(TAG, "OUTPUT END"); sys.exit(0)

df = pd.DataFrame(acts)
df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"])
df["ts"] = df["timestamp"].astype(int)
for c in ("price", "size", "usdcSize"):
    if c in df:
        df[c] = pd.to_numeric(df[c], errors="coerce")
df["type"] = df.get("type", "").astype(str).str.upper()
df["side"] = df.get("side", "").astype(str).str.upper()
df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)

win = df[df["ts"] >= CUTOFF].copy()
print(f"\n=== LAST {DAYS} DAYS: {len(win)} activity events (of {len(df)} pulled) ===")
print("event-type counts:\n" + win["type"].value_counts().to_string())

# slug parse
slug = win.get("slug", pd.Series([""] * len(win))).astype(str)
win["slug_s"] = slug
win["asset"] = slug.str.extract(r"^([a-z0-9]+)-updown")[0]
win["tf"] = slug.str.extract(r"-updown-(\d+[mh])-")[0]
win["cond"] = win.get("conditionId", "").astype(str)
win["outcome"] = win.get("outcome", "").astype(str)

trade = win[win["type"] == "TRADE"].copy()
buys = trade[trade["side"] == "BUY"].copy()
sells = trade[trade["side"] == "SELL"].copy()
redeems = win[win["type"] == "REDEEM"].copy()

buy_cost = float(buys["usdcSize"].sum())
sell_proceeds = float(sells["usdcSize"].sum())
redeem_payout = float(redeems["usdcSize"].sum())
realized = redeem_payout + sell_proceeds - buy_cost

print(f"\n=== TRADE ACTIVITY ({DAYS}d) ===")
print(f"BUY  trades = {len(buys):4d}   cost     = ${buy_cost:10.2f}")
print(f"SELL trades = {len(sells):4d}   proceeds = ${sell_proceeds:10.2f}")
print(f"REDEEM evts = {len(redeems):4d}   payout   = ${redeem_payout:10.2f}")
print(f"\n>>> REALIZED PnL ({DAYS}d, net cash) = ${realized:+.2f}")
if buy_cost > 0:
    print(f">>> OVERALL ROI = {realized/buy_cost*100:+.2f}%  (PnL / buy cost)")

# ---- 2. markets traded + ROI per asset×tf ----
print(f"\n=== MARKETS TRADED (asset×tf) ===")
b_by = buys.groupby(["asset", "tf"]).agg(buys=("usdcSize", "size"), cost=("usdcSize", "sum")).reset_index()
# redeem payout + sell proceeds per asset×tf
r_by = redeems.groupby(["asset", "tf"])["usdcSize"].sum().rename("redeem").reset_index()
s_by = sells.groupby(["asset", "tf"])["usdcSize"].sum().rename("sell").reset_index()
m = b_by.merge(r_by, on=["asset", "tf"], how="left").merge(s_by, on=["asset", "tf"], how="left").fillna(0.0)
m["pnl"] = m["redeem"] + m["sell"] - m["cost"]
m["roi%"] = (m["pnl"] / m["cost"] * 100).round(2)
m = m.sort_values("cost", ascending=False)
print(m.round(2).to_string(index=False))

# ---- 3. entry-price profile ----
if len(buys) and "price" in buys:
    print(f"\n=== ENTRY PRICE PROFILE (buys) ===")
    print(buys["price"].describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())
    fav = (buys["price"] > 0.5).mean() * 100
    print(f"buys on FAVORITE (price>0.5): {fav:.1f}%")
    print(f"buy notional usdcSize:\n" + buys["usdcSize"].describe(percentiles=[.1, .5, .9]).round(2).to_string())
    print(f"buy size (shares):\n" + buys["size"].describe(percentiles=[.1, .5, .9]).round(2).to_string())
    # side mix
    print(f"\nbuy outcome (Up/Down) mix:\n" + buys["outcome"].value_counts().to_string())

# ---- 4. WR by resolved conditionId ----
res = defaultdict(float)
cond_cost = defaultdict(float)
for _, r in redeems.iterrows():
    res[r["cond"]] += float(r["usdcSize"] or 0)
for _, r in buys.iterrows():
    cond_cost[r["cond"]] += float(r["usdcSize"] or 0)
if res:
    wins = sum(1 for v in res.values() if v > 0)
    print(f"\n=== WR (resolved conditionIds w/ redeem, {DAYS}d) ===")
    print(f"resolved={len(res)}  won={wins}  WR={wins/len(res)*100:.1f}%")
    # avg win / avg loss per slug (cost vs payout)
    matched = [(c, cond_cost.get(c, 0.0), res[c]) for c in res]
    won_pnl = [pay - cost for c, cost, pay in matched if pay > 0]
    lost_pnl = [pay - cost for c, cost, pay in matched if pay <= 0]
    if won_pnl:
        print(f"avg WIN  pnl/slug = ${sum(won_pnl)/len(won_pnl):+.3f}  (n={len(won_pnl)})")
    if lost_pnl:
        print(f"avg LOSS pnl/slug = ${sum(lost_pnl)/len(lost_pnl):+.3f}  (n={len(lost_pnl)})")

# ---- 5. per-slug detail (latest 30, for image verification) ----
print(f"\n=== PER-SLUG DETAIL (latest 40 BUYs — verify vs screenshot) ===")
det = buys.sort_values("ts", ascending=False).head(40)
for _, r in det.iterrows():
    et = (r["dt"] - pd.Timedelta(hours=4)).strftime("%m-%d %I:%M%p")  # approx ET (EDT = UTC-4)
    print(f"  {et}ET  {str(r['asset']):>4}-{str(r['tf']):<3} {str(r['outcome']):>4} "
          f"px={r['price']:.2f} sz={r['size']:.2f} cost=${r['usdcSize']:.2f}  {r['slug_s']}")

# ---- 6. daily breakdown ----
win["day"] = win["dt"].dt.strftime("%Y-%m-%d")
daily = []
for day, g in win.groupby("day"):
    gb = g[(g["type"] == "TRADE") & (g["side"] == "BUY")]
    gs = g[(g["type"] == "TRADE") & (g["side"] == "SELL")]
    gr = g[g["type"] == "REDEEM"]
    cost = float(gb["usdcSize"].sum())
    pnl = float(gr["usdcSize"].sum()) + float(gs["usdcSize"].sum()) - cost
    roi = (pnl / cost * 100) if cost > 0 else 0.0
    daily.append((day, len(gb), len(gs), len(gr), round(cost, 2), round(pnl, 2), round(roi, 1)))
print(f"\n=== DAILY (day, buys, sells, redeems, cost$, net$, roi%) ===")
for d in sorted(daily):
    print(f"  {d[0]}  buys={d[1]:3d}  sells={d[2]:3d}  redeems={d[3]:3d}  cost=${d[4]:8.2f}  net=${d[5]:+8.2f}  roi={d[6]:+.1f}%")

# ---- 7. lb-api profit cross-check ----
for wd in ("1d", "7d", "1m", "all"):
    lb = _get(f"{LB}/profit", {"window": wd, "address": WALLET})
    print(f"\nlb-api /profit window={wd}: {json.dumps(lb)[:200] if lb else 'n/a'}")

# pseudonym / leaderboard handle
prof = _get(f"{DATA}/profile", {"address": WALLET}) or _get(f"{LB}/profile", {"address": WALLET})
if prof:
    print(f"\nprofile: {json.dumps(prof)[:300]}")

print(TAG, "OUTPUT END")
