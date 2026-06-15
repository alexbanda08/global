"""CYCLOPS STRATEGY DECODE — last 5d entries vs fresh Binance — 2026-06-15
Treat the last-5d favorite-hold as a NEW strategy. For each of the 26 buys, join
to fresh Binance 1s klines (canonical ends Jun 11, entries are Jun 11-15) to
answer: WHEN in the 5m window does it fire, and is the favorite already decided
by Binance at fire time (late favorite premium) or is it an oracle-lag mispricing?

Reads cached activity: cache/_cyclops_5d/activity_raw.json
Fetches Binance 1s per window (spot, no key). Outputs per-entry table + aggregates.
Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_decode_5d_2026_06_15.py
"""
from __future__ import annotations
import sys, io, json, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
import requests

pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 60)
TAG = "CYCLOPS_DECODE_5D_2026_06_15"; print(TAG, "OUTPUT START", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
ACT = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_cyclops_5d" / "activity_raw.json"
UA = {"User-Agent": "global-strategy-lab/1.0"}
BINHOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
SYM = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT"}
WIN_S = {"5m": 300, "15m": 900}


def kl(symbol, start_ms, end_ms):
    for h in BINHOSTS:
        try:
            r = requests.get(h + "/api/v3/klines",
                             params={"symbol": symbol, "interval": "1s", "startTime": start_ms, "endTime": end_ms, "limit": 1000},
                             headers=UA, timeout=20)
            if r.status_code == 200:
                return r.json()
        except Exception:
            time.sleep(0.4)
    return []


def px_at(rows, ts_ms):
    """close of the 1s bar that ended at-or-before ts_ms (causal asof)."""
    last = None
    for k in rows:
        if k[0] <= ts_ms:  # open time
            last = float(k[4])  # close
        else:
            break
    return last


acts = json.load(open(ACT, encoding="utf-8"))
df = pd.DataFrame(acts)
for c in ("price", "size", "usdcSize", "timestamp"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["type"] = df["type"].astype(str).str.upper(); df["side"] = df["side"].astype(str).str.upper()
df["slug"] = df["slug"].astype(str)
NOW = int(time.time()); CUT = NOW - 5 * 86400
buys = df[(df.timestamp >= CUT) & (df.type == "TRADE") & (df.side == "BUY")].copy()
buys["asset"] = buys["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
buys["tf"] = buys["slug"].str.extract(r"-updown-(\d+[mh])-")[0]
buys["slot_start"] = pd.to_numeric(buys["slug"].str.extract(r"-(\d+)\Z")[0], errors="coerce")
buys = buys.sort_values("timestamp")
print(f"decoding {len(buys)} buys\n")

red_conds = set(df[df.type == "REDEEM"]["conditionId"].astype(str))

rows = []
for _, b in buys.iterrows():
    asset, tf = b["asset"], b["tf"]
    ss = int(b["slot_start"]); wlen = WIN_S.get(tf, 300)
    open_ms, close_ms, buy_ms = ss * 1000, (ss + wlen) * 1000, int(b["timestamp"]) * 1000
    offset = int(b["timestamp"]) - ss  # secs into window when it fired
    symbol = SYM.get(asset)
    kdat = kl(symbol, open_ms - 3000, close_ms + 3000) if symbol else []
    time.sleep(0.15)
    p_open = px_at(kdat, open_ms)
    p_buy = px_at(kdat, buy_ms)
    p_close = px_at(kdat, close_ms)
    fav = b["outcome"]  # Up / Down
    won = str(b["conditionId"]) in red_conds
    ret_buy = (p_buy / p_open - 1) * 1e4 if (p_open and p_buy) else None      # bps open->buy
    ret_close = (p_close / p_open - 1) * 1e4 if (p_open and p_close) else None  # bps open->close (realized)
    # is the favorite aligned with binance move AT BUY time?
    align_buy = None
    if ret_buy is not None:
        align_buy = (ret_buy > 0 and fav == "Up") or (ret_buy < 0 and fav == "Down")
    rows.append(dict(asset=asset, tf=tf, off=offset, fav=fav, px=round(b["price"], 2),
                     cost=round(b["usdcSize"], 2), won=won,
                     ret_buy_bps=None if ret_buy is None else round(ret_buy, 1),
                     ret_close_bps=None if ret_close is None else round(ret_close, 1),
                     align=align_buy, slot=ss))

R = pd.DataFrame(rows)
print("=== PER-ENTRY DECODE (off=secs into window at fire; ret_buy=binance bps open->fire; align=fav matches binance@fire) ===")
print(R.to_string(index=False))

ok = R[R.ret_buy_bps.notna()].copy()
print(f"\n=== AGGREGATES (n={len(ok)} with binance data of {len(R)}) ===")
print(f"\noffset into window (secs) — WHEN it fires:")
print(ok["off"].describe(percentiles=[.1, .25, .5, .75, .9]).round(1).to_string())
print(f"\nentry poly price:")
print(ok["px"].describe(percentiles=[.1, .5, .9]).round(3).to_string())
print(f"\n|ret_buy_bps| — how far binance already moved at fire:")
print(ok["ret_buy_bps"].abs().describe(percentiles=[.1, .25, .5, .75, .9]).round(1).to_string())
print(f"\nALIGNMENT: fav side == binance direction at fire = {ok['align'].mean()*100:.1f}%  (n={len(ok)})")
print(f"WR (won): {ok['won'].mean()*100:.1f}%")
# does binance@fire already predict the win?
ok["bin_pred_correct"] = ok.apply(lambda r: (r.ret_close_bps > 0) == (r.ret_buy_bps > 0) if r.ret_close_bps is not None else None, axis=1)
print(f"binance direction@fire == realized close direction: {ok['bin_pred_correct'].mean()*100:.1f}%")
# poly entry vs binance-implied: is the favorite UNDERPRICED given binance already moved?
print(f"\n=== EDGE READ ===")
print(f"median offset = {ok['off'].median():.0f}s into a {ok['tf'].map(WIN_S).median():.0f}s window "
      f"({ok['off'].median()/ok['tf'].map(WIN_S).median()*100:.0f}% through)")
print(f"median |binance move @fire| = {ok['ret_buy_bps'].abs().median():.1f} bps")
print(f"At fire, binance already pointed the winning way {ok['align'].mean()*100:.0f}% of the time, "
      f"poly favorite priced at median {ok['px'].median():.2f}.")

print(TAG, "OUTPUT END")
