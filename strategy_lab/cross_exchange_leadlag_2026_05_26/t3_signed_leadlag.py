"""TASK 3 — Signed directional lead-lag.

For each candidate leader venue X compute:
  P(binance moves UP next 5s | X moved UP last 5s)
  P(binance moves DN next 5s | X moved DN last 5s)
  baseline P(binance UP) — to compute lift.

For HL: use HL 1s VWAP from trades.
For Coinbase/Kraken/OKX 1MIN: only meaningful at 1-minute granularity.

We also test 1s direction lag from binance vs HL — should show that BINANCE direction predicts HL direction (the inverse case).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_trades, load_klines, load_okx_klines

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"

WIN_START_US = int(pd.Timestamp("2026-05-01 00:00", tz="UTC").value // 1000)
WIN_END_US   = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").value // 1000)

def hl_1s(asset: str) -> pd.DataFrame:
    df = load_hyperliquid_trades(asset=asset)
    df = df[(df.time_exchange_us >= WIN_START_US) & (df.time_exchange_us <= WIN_END_US)]
    cols = df.columns.tolist()
    pcol = "px" if "px" in cols else "price"
    qcol = "sz" if "sz" in cols else ("size" if "size" in cols else "qty")
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    px = df[pcol].astype("float64").values
    sz = df[qcol].astype("float64").values
    g = pd.DataFrame({"ts_s": ts_s, "pq": px*sz, "q": sz}).groupby("ts_s", sort=True).agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]
    g["vwap"] = g.pq / g.q
    return g.reset_index()[["ts_s","vwap","q"]]

def binance_1s(asset: str) -> pd.DataFrame:
    df = load_klines_1s(asset=asset)
    df = df[(df.time_period_start_us >= WIN_START_US) & (df.time_period_start_us <= WIN_END_US)].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    df = df.drop_duplicates("ts_s", keep="last").sort_values("ts_s")
    return df[["ts_s","price_close"]].rename(columns={"price_close":"binance_close"}).reset_index(drop=True)

def directional_test(df: pd.DataFrame, leader_col: str, target_col: str, lookback_s: int, forward_s: int, min_move_bp: float = 0.0):
    """
    df is sorted by ts_s, contiguous 1s grid.
    leader_dir[t] = sign(log(leader[t]) - log(leader[t-lookback_s])).
    binance_fwd[t] = sign(log(binance[t+forward_s]) - log(binance[t])).
    Test conditional probabilities.
    """
    px_lead = df[leader_col].values
    px_targ = df[target_col].values
    ts = df.ts_s.values
    # Verify contiguous to within tolerance
    # Build a complete grid:
    min_t, max_t = int(ts.min()), int(ts.max())
    grid = np.arange(min_t, max_t+1)
    # Pad to grid with last-observation-carried-forward
    idx = np.searchsorted(ts, grid)
    idx = np.clip(idx, 0, len(ts)-1)
    # Use forward-fill: where grid[i] < ts[idx[i]], step back
    bad = grid != ts[idx]
    # build mask of which grid points have actual obs
    has_obs = ~bad
    # For lead-lag, we need px at t-lookback and t+forward. We use np.searchsorted with side='right'-1 (asof)
    def asof(target):
        ii = np.searchsorted(ts, target, side="right") - 1
        ii = np.clip(ii, 0, len(ts)-1)
        return ii
    # Subsample to every 5 seconds to reduce overlap correlation
    sample_ts = np.arange(min_t + lookback_s + 1, max_t - forward_s, 5)
    idx_t      = asof(sample_ts)
    idx_lookb  = asof(sample_ts - lookback_s)
    idx_fwd    = asof(sample_ts + forward_s)
    lead_now = px_lead[idx_t]
    lead_old = px_lead[idx_lookb]
    targ_fwd = px_targ[idx_fwd]
    targ_now = px_targ[idx_t]
    # Compute log returns
    lead_ret = np.log(lead_now / lead_old)
    targ_fwd_ret = np.log(targ_fwd / targ_now)
    # Filter by min_move_bp on leader
    bp_thresh = min_move_bp / 10000.0
    keep = np.isfinite(lead_ret) & np.isfinite(targ_fwd_ret) & (np.abs(lead_ret) >= bp_thresh)
    lead_ret = lead_ret[keep]
    targ_fwd_ret = targ_fwd_ret[keep]
    n = len(lead_ret)
    if n < 100:
        return None
    base_up = float(np.mean(targ_fwd_ret > 0))
    base_dn = float(np.mean(targ_fwd_ret < 0))
    p_up_given_up = float(np.mean(targ_fwd_ret[lead_ret > 0] > 0)) if (lead_ret>0).sum()>0 else None
    p_dn_given_dn = float(np.mean(targ_fwd_ret[lead_ret < 0] < 0)) if (lead_ret<0).sum()>0 else None
    n_up = int((lead_ret > 0).sum()); n_dn = int((lead_ret < 0).sum())
    return {
        "n": n, "n_up": n_up, "n_dn": n_dn,
        "base_up": base_up, "base_dn": base_dn,
        "P_binance_up_given_lead_up": p_up_given_up,
        "P_binance_dn_given_lead_dn": p_dn_given_dn,
        "lift_up": (p_up_given_up - base_up) if p_up_given_up else None,
        "lift_dn": (p_dn_given_dn - base_dn) if p_dn_given_dn else None,
    }

rows = []
for asset in ["BTC", "ETH", "SOL"]:
    print(f"\n=== {asset} HL trades vs binance 1s ===", flush=True)
    bn = binance_1s(asset)
    hl = hl_1s(asset)
    m = bn.merge(hl, on="ts_s", how="inner")
    # Test HL leading binance (X = HL):
    for lookback, forward in [(5,5),(5,10),(10,5),(15,5),(15,15),(30,30)]:
        for thresh_bp in [0, 1, 5]:
            r = directional_test(m.rename(columns={"vwap":"leader","binance_close":"target"}),
                                  "leader","target",lookback,forward,thresh_bp)
            if r:
                row = {"asset":asset,"leader":"hyperliquid","target":"binance",
                       "lookback_s":lookback,"forward_s":forward,"min_move_bp":thresh_bp, **r}
                rows.append(row)
    # And test binance leading HL (reverse):
    for lookback, forward in [(5,5),(5,10),(10,5),(15,15),(30,30)]:
        for thresh_bp in [0, 1, 5]:
            r = directional_test(m.rename(columns={"binance_close":"leader","vwap":"target"}),
                                  "leader","target",lookback,forward,thresh_bp)
            if r:
                row = {"asset":asset,"leader":"binance","target":"hyperliquid",
                       "lookback_s":lookback,"forward_s":forward,"min_move_bp":thresh_bp, **r}
                rows.append(row)

# Also test 1MIN venues at 1-minute and 5-minute timescales
def load_1min(asset, venue):
    if venue == "coinbase":
        df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue == "kraken":
        df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue == "okx":
        df = load_okx_klines(asset=asset, period_id="1MIN")
    elif venue == "binance":
        df = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
    df = df[(df.time_period_start_us >= WIN_START_US) & (df.time_period_start_us <= WIN_END_US)].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    return df[["ts_s","price_close"]].rename(columns={"price_close": f"{venue}_close"})

for asset in ["BTC","ETH","SOL"]:
    bn1 = load_1min(asset,"binance")
    for venue in ["coinbase","kraken","okx"]:
        oo = load_1min(asset,venue)
        m = bn1.merge(oo, on="ts_s", how="inner")
        m = m.sort_values("ts_s").reset_index(drop=True)
        # Test if other venue leads binance at lag = 1 min, 2 min
        for lookback_min, forward_min in [(1,1),(2,1),(2,2),(5,5)]:
            r = directional_test(m.rename(columns={f"{venue}_close":"leader","binance_close":"target"}),
                                  "leader","target",lookback_min*60,forward_min*60,0)
            if r:
                rows.append({"asset":asset,"leader":venue,"target":"binance",
                              "lookback_s":lookback_min*60,"forward_s":forward_min*60,"min_move_bp":0, **r})

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / "_signed_leadlag.csv", index=False)
print("\n=== TOP DIRECTIONAL LEAD-LAG ===")
# Sort by lift_up
out_sorted = out.sort_values("lift_up", ascending=False)
print(out_sorted.head(25).to_string(index=False))
print(f"\nWrote {OUT_DIR / '_signed_leadlag.csv'}")
