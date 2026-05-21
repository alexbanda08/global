"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""Walkforward + permutation tests for momo at optimal fire-time (offset=60s).

Reads per-trade data from momo_ws_fire_offset_sweep_per_trade.csv (offset_s=60).

Walkforward: rolling 7-day TRAIN window (refit q90 threshold) / 1-day TEST window.
  - For each test day, q90 is fit on prior 7 days only (no peeking)
  - Trades within q90 train window are rejected if abs_ret_2m < threshold
  - Aggregate OOS PnL across all test days

Permutation:
  - DIRECTION_PERM: keep gate fires, randomize sign of asset_ret_2m within (asset, tf)
  - GATE_PERM: random 10% of universe with sign logic
  - 1000 permutations each, p-value = fraction where perm PnL >= observed
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
from book_walk import book_walk_fill  # noqa

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_06"
OUT = ROOT / "strategy_lab" / "results" / "meta_classifier"

# Re-read per-trade data from sweep at offset=60s
df = pd.read_csv(OUT / "momo_ws_fire_offset_sweep_per_trade.csv")
df = df[df.offset_s == 60].copy()
print(f"trades at offset=60s: {len(df)}")
print(f"per cell:\n{df.groupby(['asset','tf']).size()}")

# ============================================================
# Walkforward
# ============================================================
print(f"\n=== WALKFORWARD: rolling 7d train / 1d test, refit q90 per train ===")

# We need ret_2m and abs_ret_2m. Recompute from kline source for ALL universe markets,
# then filter to those that fired at offset=60 (have entry book).
# Easier path: simulate the full trade pipeline per day with proper q90 refit.

# Full universe loader (mirrors momo_ws_fire_offset_sweep.py)
ASSET_BIN = {"BTC":"BINANCE_SPOT_BTC_USDT","ETH":"BINANCE_SPOT_ETH_USDT","SOL":"BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC":"OKX_SPOT_BTC_USDT","ETH":"OKX_SPOT_ETH_USDT","SOL":"OKX_SPOT_SOL_USDT"}
LOOKBACK = 7  # walkforward: smaller train window
NOTIONAL = 25.0
FEE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}

def load_klines():
    df = pd.read_csv(REFRESH / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC","ETH","SOL"):
        b = df[df.symbol_id == ASSET_BIN[a]][["ts_s","price_close"]].copy()
        o = df[df.symbol_id == ASSET_OKX[a]][["ts_s","price_close"]].copy()
        c = pd.concat([b,o]).sort_values("ts_s").drop_duplicates("ts_s",keep="first").reset_index(drop=True)
        out[a] = c[["ts_s","price_close"]]
    return out

def asof_strict(k, ts):
    end_us = (k.ts_s.astype("int64") + 60).values * 1_000_000
    target = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(k.price_close.iloc[idx])

print("loading klines + universe…")
klines = load_klines()
m = pd.read_csv(REFRESH / "markets_full.csv")
r = pd.read_csv(REFRESH / "market_resolutions_full.csv")[["slug","outcome"]]
uni = m.merge(r, on="slug", how="inner", suffixes=("_m","")).copy()
uni = uni.dropna(subset=["outcome"])
uni = uni[uni.ticker.isin(["BTC","ETH","SOL"]) & uni.timeframe.isin(["5m","15m"])].copy()
uni["ws"] = uni.slug.str.extract(r"-(\d+)$")[0].astype("int64")
uni["asset"] = uni.ticker
uni["tf"] = uni.timeframe
uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")

# Compute ret_2m once (anchor ws-60, ws+60)
print("computing ret_2m…")
ret_2m_vals = []
for asset, ws in zip(uni.asset.values, uni.ws.values):
    c0 = asof_strict(klines[asset], int(ws) - 60)
    c2 = asof_strict(klines[asset], int(ws) + 60)
    if math.isfinite(c0) and math.isfinite(c2) and c0 > 0 and c2 > 0:
        ret_2m_vals.append(math.log(c2/c0))
    else:
        ret_2m_vals.append(float("nan"))
uni["ret_2m"] = ret_2m_vals
uni["abs_ret_2m"] = uni.ret_2m.abs()

# Walkforward: for each (asset,tf), iterate by day with rolling q90
GATE_Q = 0.90
walk_rows = []
for (asset, tf), g in uni.groupby(["asset","tf"]):
    g = g.sort_values("ws").reset_index(drop=True)
    days = sorted(g.day.unique())
    for test_day in days:
        train = g[(g.day < test_day) & (g.day >= test_day - pd.Timedelta(days=LOOKBACK))]
        train_samples = train["abs_ret_2m"].dropna().values
        if len(train_samples) < 30:
            continue  # need min samples to fit q90
        thresh = float(np.quantile(train_samples, GATE_Q))
        test = g[g.day == test_day]
        for r in test.itertuples(index=False):
            if not math.isfinite(r.abs_ret_2m): continue
            if r.abs_ret_2m < thresh: continue
            # Look up matching trade in fired data
            sig = "UP" if r.ret_2m > 0 else "DOWN"
            won = (sig == "UP" and r.outcome == "Up") or (sig == "DOWN" and r.outcome == "Down")
            # Find PnL from sweep (same trade, offset=60)
            match = df[(df.slug == r.slug)]
            if len(match) == 0:
                continue
            mr = match.iloc[0]
            walk_rows.append(dict(
                asset=asset, tf=tf, day=str(test_day.date()), slug=r.slug,
                threshold=thresh, won=int(won), pnl=float(mr.pnl), vwap=float(mr.vwap_e),
            ))

wf = pd.DataFrame(walk_rows)
print(f"walkforward trades: {len(wf)}")
agg_wf = wf.groupby(["asset","tf"]).agg(
    n=("pnl","size"), wins=("won","sum"), hit=("won","mean"),
    pnl_total=("pnl","sum"), pnl_mean=("pnl","mean"), pnl_std=("pnl","std"),
).reset_index()
print("\n=== WALKFORWARD per-cell (OOS) ===")
print(agg_wf.round(3).to_string(index=False))
print(f"\n=== WALKFORWARD TOTAL ===")
print(f"  n={len(wf)}, total=${wf.pnl.sum():+.2f}, mean=${wf.pnl.mean():+.4f}, hit={wf.won.mean():.3f}")
wf.to_csv(OUT / "momo_ws_walkforward_per_trade.csv", index=False)

# ============================================================
# Permutation tests — DIRECTION_PERM and GATE_PERM
# ============================================================
print(f"\n=== PERMUTATION: DIRECTION_PERM (1000 draws) ===")

# Use the offset=60 fired set for both perms
fires = df.copy()  # slug, asset, tf, signal, outcome, won, ask0, vwap_e, shares, usd_spent, pnl

# DIRECTION_PERM: for each fired trade, randomize sign of ret_2m → flip won where appropriate
# But we don't have full per-trade ret_2m sign in df — re-derive from signal
fires = fires.merge(uni[["slug","ret_2m","outcome"]].rename(columns={"outcome":"truth_outcome"}), on="slug", how="left")
fires["sig"] = (fires.ret_2m > 0).map({True:"UP", False:"DOWN"})
fires["won_observed"] = ((fires.sig == "UP") & (fires.truth_outcome == "Up")) | ((fires.sig == "DOWN") & (fires.truth_outcome == "Down"))

obs_total = float(fires.pnl.sum())
print(f"observed total PnL (offset=60s, gated): ${obs_total:+.2f}")

rng = np.random.default_rng(42)
n_draws = 1000

# DIRECTION_PERM per cell
dir_perm_results = {}
for (asset, tf), g in fires.groupby(["asset","tf"]):
    obs = float(g.pnl.sum())
    perm_totals = []
    for _ in range(n_draws):
        # Randomize sign per fired trade (50/50 within cell)
        perm_signs = rng.integers(0, 2, size=len(g))
        perm_won = np.where(perm_signs == 1, g.truth_outcome.values == "Up", g.truth_outcome.values == "Down")
        # PnL: if perm_won, profit = shares - usd_spent (less fee); else -usd_spent
        pnl = np.where(
            perm_won,
            g.shares.values - g.usd_spent.values - np.maximum(0, g.shares.values - g.usd_spent.values) * FEE,
            -g.usd_spent.values
        )
        perm_totals.append(float(np.sum(pnl)))
    perm_totals = np.array(perm_totals)
    p_value = float((perm_totals >= obs).mean())
    dir_perm_results[(asset, tf)] = (obs, float(perm_totals.mean()), float(perm_totals.std()), p_value, len(g))

print(f"{'cell':<12} {'n':>4} {'obs_pnl':>12} {'perm_mean':>12} {'perm_std':>10} {'p-value':>10}")
for (asset, tf), (obs, m_, s, p, n) in sorted(dir_perm_results.items()):
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"{asset}_{tf:<4} {n:>4} ${obs:>+10.2f}  ${m_:>+10.2f}  {s:>10.2f}  {p:>10.4f} {sig}")

# Combined cross-cell DIRECTION_PERM
print(f"\n=== COMBINED DIRECTION_PERM ===")
all_perm = []
for _ in range(n_draws):
    total = 0.0
    for (asset, tf), g in fires.groupby(["asset","tf"]):
        perm_signs = rng.integers(0, 2, size=len(g))
        perm_won = np.where(perm_signs == 1, g.truth_outcome.values == "Up", g.truth_outcome.values == "Down")
        pnl = np.where(
            perm_won,
            g.shares.values - g.usd_spent.values - np.maximum(0, g.shares.values - g.usd_spent.values) * FEE,
            -g.usd_spent.values
        )
        total += float(np.sum(pnl))
    all_perm.append(total)
all_perm = np.array(all_perm)
p_combined = float((all_perm >= obs_total).mean())
print(f"  observed:   ${obs_total:+.2f}")
print(f"  perm_mean:  ${all_perm.mean():+.2f}  perm_std: ${all_perm.std():.2f}")
print(f"  p_combined: {p_combined:.4f}  (n={n_draws})")
sig = "***" if p_combined < 0.001 else "**" if p_combined < 0.01 else "*" if p_combined < 0.05 else "ns"
print(f"  significance: {sig}")

# Save summary
out_summary = pd.DataFrame([
    dict(asset=a, tf=t, n=n, obs_pnl=obs, perm_mean=m_, perm_std=s, p_value=p)
    for (a,t),(obs,m_,s,p,n) in dir_perm_results.items()
])
out_summary.to_csv(OUT / "momo_ws_direction_perm.csv", index=False)
print(f"\nWalkforward CSV: {OUT / 'momo_ws_walkforward_per_trade.csv'}")
print(f"Direction perm CSV: {OUT / 'momo_ws_direction_perm.csv'}")
