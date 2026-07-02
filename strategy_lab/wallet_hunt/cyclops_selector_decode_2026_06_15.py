"""CYCLOPS SLUG-SELECTOR decode — 2026-06-15
Cyclops fired only 26 times in 5d (~5/day) but the entry SIGNAL (binance aligned
move) triggers on ~36% of slugs (~100/day). So a SLUG SELECTOR picks ~5% of
signaling slugs. Decode it: build the universe of ALL BTC/ETH 5m slugs in the
Cyclops window (Jun 10->15) with fresh Binance 1m+1s context, mark the 26 fired,
and contrast feature distributions (fired vs not) to find the discriminator(s).

Features per window (causal, at/just-before the fire moment):
  hour_utc, fire_offset, move_bps@fire, move_bps@120,
  prev1/prev2/prev3 window direction == favorite (trend persistence),
  run_len (consecutive prior same-dir windows), realized_vol_12w,
  mins_since_last_cyclops_trade, |move| vs rolling-vol z-score,
  monotonic (did binance move one-way open->fire, no opposite spike).

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_selector_decode_2026_06_15.py
"""
from __future__ import annotations
import sys, io, json, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np, pandas as pd, requests
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 50)
TAG = "CYCLOPS_SELECTOR_DECODE_2026_06_15"; print(TAG, "OUTPUT START", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
ACT = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_cyclops_5d" / "activity_raw.json"
UA = {"User-Agent": "global-strategy-lab/1.0"}
HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
SYM = {"btc": "BTCUSDT", "eth": "ETHUSDT"}
WIN = 300

# ---- fired slugs from cache ----
acts = json.load(open(ACT, encoding="utf-8"))
adf = pd.DataFrame(acts)
for c in ("price", "size", "usdcSize", "timestamp"):
    adf[c] = pd.to_numeric(adf[c], errors="coerce")
adf["type"] = adf["type"].astype(str).str.upper(); adf["side"] = adf["side"].astype(str).str.upper()
adf["slug"] = adf["slug"].astype(str)
buys = adf[(adf.type == "TRADE") & (adf.side == "BUY")].copy()
buys["asset"] = buys["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
buys["slot_start"] = pd.to_numeric(buys["slug"].str.extract(r"-(\d+)\Z")[0], errors="coerce").astype("Int64")
buys["buy_ts"] = buys["timestamp"].astype("Int64")
# scope to last N days (the NEW strategy regime); set DAYS=999 for full history
DAYS = int(__import__("os").environ.get("CYC_DAYS", "5"))
CUT = int(time.time()) - DAYS * 86400
buys = buys[buys.buy_ts >= CUT]
print(f"[scope last {DAYS}d] buys={len(buys)}", flush=True)
# poly entry-price band of FIRED (candidate selector — we have price for fired)
_b = buys[buys.asset.isin(["btc", "eth"])]
print("FIRED poly entry price:\n" + _b["price"].describe(percentiles=[.05,.1,.25,.5,.75,.9,.95]).round(3).to_string())
fired = buys[buys.asset.isin(["btc", "eth"])][["asset", "slot_start", "buy_ts", "outcome", "price"]].dropna()
fired_set = {(r.asset, int(r.slot_start)) for _, r in fired.iterrows()}
buy_ts_sorted = sorted(int(x) for x in fired.buy_ts)
print(f"fired slugs: {len(fired)} ({fired.asset.value_counts().to_dict()})")
ss_min = int(fired.slot_start.min()); ss_max = int(fired.slot_start.max())
print(f"fired slot_start range: {pd.to_datetime(ss_min,unit='s')} .. {pd.to_datetime(ss_max,unit='s')}")

# ---- fetch binance 1s for the universe window (need a few prior windows) ----
T0 = (ss_min // 300 * 300) - 6 * WIN   # 6 windows before first fire
T1 = ss_max + 2 * WIN


def fetch_1m(symbol, t0, t1):
    out = {}
    cur = t0
    while cur < t1:
        end = min(cur + 60000, t1)  # 1000 1m-bars = 60000s
        rows = None
        for h in HOSTS:
            try:
                r = requests.get(h + "/api/v3/klines",
                                 params={"symbol": symbol, "interval": "1m",
                                         "startTime": cur * 1000, "endTime": end * 1000, "limit": 1000},
                                 headers=UA, timeout=20)
                if r.status_code == 200:
                    rows = r.json(); break
            except Exception:
                time.sleep(0.3)
        if rows:
            for k in rows:
                out[k[0] // 1000] = float(k[4])  # close, keyed by bar-open sec
        cur = end
        time.sleep(0.05)
    k = np.array(sorted(out), dtype=np.int64); v = np.array([out[x] for x in k], dtype=np.float64)
    return k, v


print(f"fetching binance 1m {pd.to_datetime(T0,unit='s')} .. {pd.to_datetime(T1,unit='s')} …", flush=True)
KL = {a: fetch_1m(s, T0, T1) for a, s in SYM.items()}
for a in SYM:
    print(f"  {a}: {len(KL[a][0])} secs")


def px(a, sec):
    """causal asof: close of the last 1m bar that CLOSED at-or-before sec.
    idx are bar-open secs; a bar opening at o closes at o+60."""
    idx, vals = KL[a]
    i = np.searchsorted(idx, sec - 60, side="right") - 1
    return float(vals[i]) if i >= 0 else np.nan


def win_dir(a, ss):
    """realized window direction: sign(close@ss+300 - close@ss). 1=Up,0=Down,nan."""
    o, c = px(a, ss), px(a, ss + WIN)
    if np.isnan(o) or np.isnan(c):
        return np.nan
    return 1 if c > o else 0


# ---- build universe: all 5m slugs in [ss_min .. ss_max] per asset, every 300s ----
THR = 8.0; SCAN = list(range(60, 241, 60))
rows = []
for a in ("btc", "eth"):
    ss = ss_min // 300 * 300
    while ss <= ss_max:
        o = px(a, ss)
        if not np.isnan(o):
            # find fire (first offset |ret|>=THR)
            fire_off, fav = np.nan, np.nan
            for t in SCAN:
                pt = px(a, ss + t)
                if np.isnan(pt):
                    continue
                ret = (pt / o - 1) * 1e4
                if abs(ret) >= THR:
                    fire_off = t; fav = 1 if ret > 0 else 0; break
            signaled = not np.isnan(fire_off)
            # features
            fired_here = (a, ss) in fired_set
            # use actual buy_ts offset if fired, else hypothetical fire
            actual_off = np.nan
            if fired_here:
                bt = int(fired[(fired.asset == a) & (fired.slot_start == ss)].buy_ts.iloc[0])
                actual_off = bt - ss
                fav = int(fired[(fired.asset == a) & (fired.slot_start == ss)].outcome.map({"Up": 1, "Down": 0}).iloc[0])
            off = actual_off if fired_here and not np.isnan(actual_off) else fire_off
            move_fire = ((px(a, ss + int(off)) / o - 1) * 1e4) if not np.isnan(off) else np.nan
            move_120 = (px(a, ss + 120) / o - 1) * 1e4 if not np.isnan(px(a, ss + 120)) else np.nan
            # prior window dirs + run length (consecutive prior same as fav)
            pdirs = [win_dir(a, ss - WIN * k) for k in range(1, 4)]
            run = 0
            kk = 1
            while True:
                d = win_dir(a, ss - WIN * kk)
                if np.isnan(d) or np.isnan(fav) or d != fav:
                    break
                run += 1; kk += 1
            # realized vol: std of last 12 window returns (bps)
            wr = []
            for k in range(1, 13):
                oo, cc = px(a, ss - WIN * k), px(a, ss - WIN * k + WIN)
                if not np.isnan(oo) and not np.isnan(cc):
                    wr.append((cc / oo - 1) * 1e4)
            vol12 = np.std(wr) if len(wr) >= 6 else np.nan
            zmove = (abs(move_fire) / vol12) if (vol12 and not np.isnan(move_fire) and vol12 > 0) else np.nan
            # monotonic: did binance stay one side of open from start to fire (no opposite excursion > 2bps)?
            mono = np.nan
            if not np.isnan(off) and not np.isnan(fav):
                seg = []
                for tt in range(5, int(off) + 1, 5):
                    p = px(a, ss + tt)
                    if not np.isnan(p):
                        seg.append((p / o - 1) * 1e4)
                if seg:
                    if fav == 1:
                        mono = 1 if min(seg) > -2.0 else 0
                    else:
                        mono = 1 if max(seg) < 2.0 else 0
            hour = pd.to_datetime(ss, unit="s").hour
            mins_since = np.nan
            if fired_here:
                prev = [t for t in buy_ts_sorted if t < (ss + (off if not np.isnan(off) else 120))]
                if len(prev) >= 1:
                    mins_since = ((ss + (off if not np.isnan(off) else 120)) - prev[-1]) / 60.0
            rows.append(dict(asset=a, slot_start=ss, fired=fired_here, signaled=signaled,
                             off=off, move_fire=move_fire, move_120=move_120,
                             prev1=pdirs[0], run_len=run, vol12=vol12, zmove=zmove,
                             mono=mono, hour=hour, mins_since=mins_since, fav=fav))
        ss += WIN

U = pd.DataFrame(rows)
print(f"\nuniverse slugs: {len(U)}  signaled: {int(U.signaled.sum())}  fired: {int(U.fired.sum())}")

# ---- CONTRAST: fired vs signaled-but-not-fired ----
sig = U[U.signaled].copy()
F = sig[sig.fired]; NF = sig[~sig.fired]
print(f"\n=== CONTRAST among SIGNALING slugs: fired (n={len(F)}) vs not-fired (n={len(NF)}) ===")
feats = ["off", "move_fire", "move_120", "run_len", "vol12", "zmove", "mono", "hour"]
tab = []
for f in feats:
    fv = F[f].dropna(); nv = NF[f].dropna()
    if len(fv) and len(nv):
        tab.append(dict(feat=f, fired_med=round(fv.median(), 2), notfired_med=round(nv.median(), 2),
                        fired_mean=round(fv.mean(), 2), notfired_mean=round(nv.mean(), 2),
                        fired_min=round(fv.min(), 2), fired_max=round(fv.max(), 2)))
print(pd.DataFrame(tab).to_string(index=False))

print(f"\n=== run_len distribution (consecutive prior same-dir windows) ===")
print("FIRED:\n" + F.run_len.value_counts().sort_index().to_string())
print("NOT-FIRED:\n" + NF.run_len.value_counts(normalize=True).sort_index().round(3).to_string())
print(f"\nFIRED run_len>=1: {(F.run_len>=1).mean()*100:.0f}%   NOT-FIRED run_len>=1: {(NF.run_len>=1).mean()*100:.0f}%")

print(f"\n=== mono (binance moved one-way to fire, no opposite >2bps) ===")
print(f"FIRED mono=1: {F.mono.mean()*100:.0f}%   NOT-FIRED mono=1: {NF.mono.mean()*100:.0f}%")

print(f"\n=== hour-of-day (UTC) of fires ===")
print(F.hour.value_counts().sort_index().to_string())

print(f"\n=== mins since last cyclops trade (rate-limit?) ===")
print(F.mins_since.describe(percentiles=[.1,.25,.5,.75]).round(1).to_string())

print(f"\n=== zmove (|move@fire| / rolling vol) — conviction vs noise ===")
print(f"FIRED median z={F.zmove.median():.2f}  NOT-FIRED median z={NF.zmove.median():.2f}")

print(TAG, "OUTPUT END")
