"""CYCLOPS WALLET 7-DAY PERF — 2026-06-05
Pull the cyclops executor wallet's full Polymarket activity for the last 7 days,
characterize its (possibly NEW) strategy, and compute WR / ROI / PnL.

Wallet = 0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c (CYCLOPS_WALLET_HUNT_2026_06_01.md)

Pulls data-api /activity (TRADE/SELL/REDEEM/MERGE/SPLIT/REWARD) paginated, plus
lb-api /profit + /volume (7d) as an independent cross-check.

Run: py -3 -X utf8 strategy_lab/wallet_hunt/cyclops_wallet_7d_2026_06_05.py
"""
from __future__ import annotations
import sys, io, re, json, time
import datetime as dt
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np
import pandas as pd
import requests

TAG = "CYCLOPS_WALLET_7D_2026_06_05"
print(TAG, "OUTPUT START", flush=True)

WALLET = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
WH = ROOT / "strategy_lab" / "wallet_hunt"
CACHE = WH / "cache" / "_cyclops_7d"
CACHE.mkdir(parents=True, exist_ok=True)
DATA = "https://data-api.polymarket.com"
LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

NOW = int(time.time())
CUTOFF = NOW - 7 * 86400
print(f"now_utc={dt.datetime.utcfromtimestamp(NOW)}  cutoff_utc={dt.datetime.utcfromtimestamp(CUTOFF)}", flush=True)


def _get(url, params=None, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            if r.status_code == 200:
                return r.json()
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    return None


# ---- 1. pull full activity, paginated, until we pass the 7d cutoff ----
acts = []
offset = 0
LIM = 500
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
print(f"pulled {len(acts)} total activity events (all-time available via pagination)", flush=True)

df = pd.DataFrame(acts)
if df.empty:
    print("NO ACTIVITY RETURNED — wallet may be inactive or API blocked.")
    print(TAG, "OUTPUT END"); sys.exit(0)

df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"])
df["ts"] = df["timestamp"].astype(int)
df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)
df["type"] = df.get("type", "").astype(str)
for c in ("price", "size", "usdcSize"):
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

w = df[df["ts"] >= CUTOFF].copy()
print(f"\n=== last 7d window: {len(w)} events ({w['dt'].min()} → {w['dt'].max()}) ===")
print("event type counts:", dict(w["type"].value_counts()))

# ---- 2. characterize markets + sides (detect NEW strategy) ----
def mkind(s):
    mm = re.match(r"([a-z]+)-updown-(\d+[mh])", str(s))
    return f"{mm.group(1)}-{mm.group(2)}" if mm else (str(s)[:24] or "?")

tr = w[w["type"].str.upper() == "TRADE"].copy()
if "slug" not in tr.columns:
    tr["slug"] = ""
tr["mkind"] = tr["slug"].map(mkind)
print(f"\n--- TRADE events: {len(tr)} ---")
print("by market type:", dict(Counter(tr["mkind"]).most_common(10)))
if "side" in tr.columns:
    print("by side:", dict(tr["side"].astype(str).str.upper().value_counts()))
if "outcome" in tr.columns:
    print("by outcome:", dict(tr["outcome"].astype(str).value_counts()))
print(f"trade price: med={tr['price'].median():.3f} mean={tr['price'].mean():.3f}")
print(f"trade size:  med={tr['size'].median():.1f} mean={tr['size'].mean():.1f}")
print(f"trade usdc:  med={tr['usdcSize'].median():.2f} mean={tr['usdcSize'].mean():.2f} sum={tr['usdcSize'].sum():.2f}")

has_sell = (tr["side"].astype(str).str.upper() == "SELL").any() if "side" in tr.columns else False
has_redeem = (w["type"].str.upper() == "REDEEM").any()
print(f"\nSTRATEGY SIGNATURE: SELL trades present={has_sell}  REDEEM present={has_redeem}")
print("  (SELL present  => exits on book / scalp-style;  REDEEM-only => holds to resolution)")

# ---- 3. realized PnL via cash-flow over all window activity ----
# BUY = cash out (-usdc), SELL = cash in (+usdc), REDEEM/REWARD = +amount, SPLIT/MERGE ~ cash neutral
def cashflow(row):
    t = str(row["type"]).upper()
    side = str(row.get("side", "")).upper()
    usdc = row.get("usdcSize", np.nan)
    amt = row.get("usdcSize", np.nan)
    if t == "TRADE":
        if side == "BUY":
            return -usdc
        if side == "SELL":
            return +usdc
        return 0.0
    if t in ("REDEEM", "REWARD"):
        # redeem payout: prefer usdcSize, else size (shares*$1)
        v = row.get("usdcSize", np.nan)
        if pd.isna(v):
            v = row.get("size", np.nan)
        return +v if pd.notna(v) else 0.0
    return 0.0

w["cash"] = w.apply(cashflow, axis=1)
net_cash = w["cash"].sum()
gross_buy = -w.loc[(w["type"].str.upper() == "TRADE") & (w.get("side", "").astype(str).str.upper() == "BUY"), "cash"].sum() if "side" in w.columns else np.nan
print(f"\n--- realized cash-flow PnL (window) ---")
print(f"  net cash flow (≈ realized PnL incl. open-edge effects): {net_cash:+.2f} USDC")
print(f"  gross capital deployed (sum BUY usdc): {gross_buy:.2f} USDC")
if gross_buy and gross_buy > 0:
    print(f"  ROI on deployed capital (net/gross_buy): {net_cash/gross_buy*100:+.2f}%")

# ---- 4. per-slug WR (slug net-positive) ----
# group cash by conditionId/slug; a slug "won" for the wallet if its net cash > 0
key = "conditionId" if "conditionId" in w.columns else "slug"
g = w.groupby(w[key].astype(str))["cash"].sum()
g = g[g.index.notna() & (g.index != "") & (g.index != "nan")]
nslug = len(g)
wins = (g > 0).sum()
print(f"\n--- per-market WR (net-positive markets / traded markets) ---")
print(f"  markets traded (window): {nslug}")
if nslug:
    print(f"  net-positive markets: {wins}/{nslug} = {wins/nslug*100:.1f}%")
    print(f"  per-market PnL: med={g.median():+.3f} mean={g.mean():+.3f} sum={g.sum():+.2f}")
    print(f"  best {g.max():+.2f}  worst {g.min():+.2f}")

# directional WR: for hold-to-resolution, a BUY that won == REDEEM on that market
# approximate per-market: won if a REDEEM/positive payout exists for it
redeemed = w[w["type"].str.upper() == "REDEEM"].groupby(w[key].astype(str))["cash"].sum()
buy_markets = tr[tr.get("side", "").astype(str).str.upper() == "BUY"][key].astype(str).unique() if "side" in tr.columns else tr[key].astype(str).unique()
buy_markets = [m for m in buy_markets if m and m != "nan"]
if not has_sell and len(buy_markets):
    won = sum(1 for m in buy_markets if redeemed.get(m, 0) > 0)
    print(f"\n--- directional WR (hold-to-resolution: market with positive REDEEM) ---")
    print(f"  won {won}/{len(buy_markets)} = {won/len(buy_markets)*100:.1f}%")

# daily breakdown
w["day"] = w["dt"].dt.date
daily = w.groupby("day")["cash"].sum()
print("\n--- daily net cash ---")
for d, v in daily.items():
    print(f"  {d}: {v:+.2f}")

# ---- 5. lb-api independent cross-check ----
print("\n--- lb-api profit/volume cross-check ---")
for win in ["1d", "7d", "30d", "all"]:
    p = _get(f"{LB}/profit", {"window": win, "address": WALLET})
    v = _get(f"{LB}/volume", {"window": win, "address": WALLET})
    def amt(x):
        return x[0].get("amount") if isinstance(x, list) and x and isinstance(x[0], dict) else x
    print(f"  {win}: profit={amt(p)}  volume={amt(v)}")

# save tidy window csv
keep = [c for c in ["dt", "type", "side", "outcome", "slug", "price", "size", "usdcSize", "cash", "conditionId"] if c in w.columns]
w.sort_values("ts")[keep].to_csv(CACHE / "window_7d.csv", index=False)
print(f"\nsaved {CACHE/'window_7d.csv'}")
print("\n", TAG, "OUTPUT END", flush=True)
