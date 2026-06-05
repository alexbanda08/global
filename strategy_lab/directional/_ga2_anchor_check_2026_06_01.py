"""Confirm 60s>>300s for the HL short-cascade at the gate's ACTUAL anchor.
Live g_a2 reads [fire_us-W, fire_us]. Test window ending at slot_start (≈ earliest sleeve fire)
AND at slot_start+offset, predict UP, BTC+ETH, directional WR vs base rate."""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_hyperliquid_liquidations_full

WIN = {"5m": 300, "15m": 900}
LO = int(pd.Timestamp("2026-04-24", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27 13:30", tz="UTC").timestamp())


def ncdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
def zp(k, n, p0):
    if n == 0: return (np.nan, np.nan)
    ph = k / n; se = math.sqrt(p0 * (1 - p0) / n)
    z = (ph - p0) / se if se else np.nan
    return ph, (1 - ncdf(z))


def stream(coin):
    hl = load_hyperliquid_liquidations_full(coin)
    hl = hl[(hl["dir"].isin(["Close Short", "Open Long"])) & (hl["method"] == "market")]
    ts = (hl.time_exchange_us.values / 1e6).astype(float)
    val = (hl.price.astype(float) * hl["size"].astype(float)).values
    o = np.argsort(ts); return ts[o], val[o]


r = load_resolutions()
r = r[r.ticker.isin(["BTC", "ETH"]) & r.timeframe.isin(["5m", "15m"])].copy()
r["ss"] = (r.slot_start_us // 1_000_000).astype(np.int64)
r["won_up"] = (r.outcome.astype(str).str.lower() == "up")
r = r[(r.ss >= LO) & (r.ss < HI)]
base = float(r.won_up.mean())
S = {c: stream(c) for c in ["BTC", "ETH"]}
print(f"base P(Up)={base:.4f} n={len(r)}")
print("anchor   W    T      n     WR    lift_pp   p")
for anchor_off in [0, 60]:   # window ends at slot_start (0) or slot_start+60
    for W in [60, 120, 300]:
        for T in [10000, 50000, 100000]:
            k = n = 0
            for c in ["BTC", "ETH"]:
                ts, val = S[c]; cs = np.concatenate([[0.0], np.cumsum(val)])
                sub = r[r.ticker == c]
                a = (sub.ss.values + anchor_off).astype(float)
                hi = np.searchsorted(ts, a, side="right"); lo = np.searchsorted(ts, a - W, side="right")
                s = cs[hi] - cs[lo]; q = s > T
                n += int(q.sum()); k += int(sub.won_up.values[q].sum())
            wr, p = zp(k, n, base)
            print(f"+{anchor_off:<5d} {W:<4d} {int(T):<6d} {n:<5d} {wr*100:5.1f}  {(wr-base)*100:+6.2f}  {p:.4f}")
