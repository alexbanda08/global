"""CYCLOPS WALLET — LAST 4 DAYS — 2026-06-08
Fresh pull (no cache) of the cyclops executor wallet's Polymarket activity for the
last 4 days; compute trade count, asset/tf mix, notional, WR, and realized PnL.

Wallet = 0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c (Cyclops.exe / Limp-Pitcher)
PnL = net cash over window = Σ REDEEM payout + Σ SELL proceeds − Σ BUY cost.
WR  = fraction of RESOLVED conditionIds (got a redeem) whose payout > 0.
Cross-check: lb-api /profit (4d window approx).

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_wallet_4d_2026_06_08.py
"""
from __future__ import annotations
import sys, io, json, time
import datetime as dt
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
import requests

TAG = "CYCLOPS_WALLET_4D_2026_06_08"
print(TAG, "OUTPUT START", flush=True)

WALLET = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_cyclops_4d"
CACHE.mkdir(parents=True, exist_ok=True)
DATA = "https://data-api.polymarket.com"
LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

NOW = int(time.time())
CUTOFF = NOW - 4 * 86400
print(f"now_utc={dt.datetime.utcfromtimestamp(NOW)}  cutoff_utc={dt.datetime.utcfromtimestamp(CUTOFF)}", flush=True)


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


# ---- 1. paginate /activity until past the 4d cutoff ----
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
print(f"\n=== LAST 4 DAYS: {len(win)} activity events (of {len(df)} pulled) ===")
print("event-type counts:\n" + win["type"].value_counts().to_string())

# slug parse
slug = win.get("slug", pd.Series(["" ] * len(win))).astype(str)
win["asset"] = slug.str.extract(r"^([a-z0-9]+)-updown")[0]
win["tf"] = slug.str.extract(r"-updown-(\d+[mh])-")[0]
win["cond"] = win.get("conditionId", "").astype(str)

trade = win[win["type"] == "TRADE"].copy()
buys = trade[trade["side"] == "BUY"]
sells = trade[trade["side"] == "SELL"]
redeems = win[win["type"] == "REDEEM"]

buy_cost = float(buys["usdcSize"].sum())
sell_proceeds = float(sells["usdcSize"].sum())
redeem_payout = float(redeems["usdcSize"].sum())
realized = redeem_payout + sell_proceeds - buy_cost

print(f"\n=== TRADE ACTIVITY (4d) ===")
print(f"BUY  trades = {len(buys):4d}   cost     = ${buy_cost:10.2f}")
print(f"SELL trades = {len(sells):4d}   proceeds = ${sell_proceeds:10.2f}")
print(f"REDEEM evts = {len(redeems):4d}   payout   = ${redeem_payout:10.2f}")
print(f"\n>>> REALIZED PnL (4d, net cash) = ${realized:+.2f}")

if len(buys):
    print(f"\n-- buys: asset×tf mix --\n" +
          buys.groupby(['asset', 'tf']).size().sort_values(ascending=False).head(10).to_string())
    print(f"\n-- buy notional usdcSize --\n" +
          buys["usdcSize"].describe(percentiles=[.1, .5, .9]).round(2).to_string())
    if "price" in buys:
        print(f"\n-- buy entry price --\n" +
              buys["price"].describe(percentiles=[.05, .5, .95]).round(3).to_string())
        fav = (buys["price"] > 0.5).mean() * 100
        print(f"buys on FAVORITE (price>0.5): {fav:.1f}%")

# WR by resolved conditionId (got a redeem). win if payout>0.
res = defaultdict(float)
for _, r in redeems.iterrows():
    res[r["cond"]] += float(r["usdcSize"] or 0)
if res:
    wins = sum(1 for v in res.values() if v > 0)
    print(f"\n=== WR (resolved conditionIds w/ redeem, 4d) ===")
    print(f"resolved={len(res)}  won={wins}  WR={wins/len(res)*100:.1f}%")

# daily breakdown
win["day"] = win["dt"].dt.strftime("%Y-%m-%d")
daily = []
for day, g in win.groupby("day"):
    gb = g[(g["type"] == "TRADE") & (g["side"] == "BUY")]
    gs = g[(g["type"] == "TRADE") & (g["side"] == "SELL")]
    gr = g[g["type"] == "REDEEM"]
    pnl = float(gr["usdcSize"].sum()) + float(gs["usdcSize"].sum()) - float(gb["usdcSize"].sum())
    daily.append((day, len(gb), len(gs), len(gr), round(pnl, 2)))
print(f"\n=== DAILY (day, buys, sells, redeems, net_cash$) ===")
for d in sorted(daily):
    print(f"  {d[0]}  buys={d[1]:3d}  sells={d[2]:3d}  redeems={d[3]:3d}  net=${d[4]:+.2f}")

# lb-api profit cross-check (best effort)
for wd in ("4d", "1m"):
    lb = _get(f"{LB}/profit", {"window": wd, "address": WALLET})
    print(f"\nlb-api /profit window={wd}: {json.dumps(lb)[:200] if lb else 'n/a'}")

print(TAG, "OUTPUT END")
