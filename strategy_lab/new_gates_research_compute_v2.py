"""
New Gates Research v2 — HL Liquidations + Polymarket Trade Flow
2026-05-27

FIXED: HL liq classification corrected for fire window data.
- LONG liq proxy (predicts DOWN): 'Close Long' from hl-userevents-ws source
- SHORT liq proxy (predicts UP): 'Close Short' + method='market' from hl-s3-fills source
  OR 'Open Long' + method='market' (liquidator covering short)

Fire universe: fired_by_sleeve.parquet (18,270 fires, V5/V6/V7)
Sample: 5,000 fires
"""

import sys
import time
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical")

import pandas as pd
import numpy as np
from pathlib import Path

# ─── 0. Load fire universe ────────────────────────────────────────────────────
t0 = time.time()
print("Loading fire universe...", flush=True)
fires = pd.read_parquet(
    "C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/fired_by_sleeve.parquet"
)
fires["dir"] = fires["direction"].map({"UP": "Up", "DOWN": "Down"})

rng = np.random.default_rng(42)
if len(fires) > 5000:
    idx = rng.choice(len(fires), size=5000, replace=False)
    sample = fires.iloc[idx].reset_index(drop=True).copy()
else:
    sample = fires.copy()

sample["fire_us_int"] = sample["fire_us"].astype(np.int64)

print(f"  Fire universe: {len(fires)} rows | Sample: {len(sample)} rows", flush=True)
print(f"  Time range: {pd.Timestamp(sample.fire_us.min(), unit='us')} → {pd.Timestamp(sample.fire_us.max(), unit='us')}", flush=True)
print(f"  WR baseline: {sample['won'].mean():.4f}", flush=True)
BASELINE_WR = sample["won"].mean()

# ─── 1. Load and classify HL Liquidations ─────────────────────────────────────
print("\nLoading HL liquidations...", flush=True)
from load import load_hyperliquid_liquidations_full

hl_raw = load_hyperliquid_liquidations_full()

# LONG liq proxy: 'Close Long' events from WS userEvents = long positions forced closed
# This represents longs being closed by liquidation engine -> downward pressure -> predicts DOWN
hl_long_proxy = hl_raw[
    (hl_raw["coin"].isin(["BTC", "ETH", "SOL"])) &
    (hl_raw["source"] == "hl-userevents-ws") &
    (hl_raw["dir"] == "Close Long")
].copy()
hl_long_proxy["usd"] = hl_long_proxy["size"] * hl_long_proxy["price"]
hl_long_proxy["liq_type"] = "LONG"

# SHORT liq proxy: 'Close Short' market fills from S3 = short positions closed by liq engine
# -> covering of forced shorts -> upward pressure -> predicts UP
# Also include 'Open Long' market (liquidator taking longs to cover forced short)
hl_short_proxy = hl_raw[
    (hl_raw["coin"].isin(["BTC", "ETH", "SOL"])) &
    (hl_raw["source"] == "hl-s3-fills") &
    (hl_raw["method"] == "market") &
    (hl_raw["dir"].isin(["Close Short"]))  # short positions forcibly closed = short squeeze
].copy()
hl_short_proxy["usd"] = hl_short_proxy["size"] * hl_short_proxy["price"]
hl_short_proxy["liq_type"] = "SHORT"

# Sort by time for binary search
hl_long_proxy = hl_long_proxy.sort_values("time_exchange_us").reset_index(drop=True)
hl_short_proxy = hl_short_proxy.sort_values("time_exchange_us").reset_index(drop=True)

print(f"  HL LONG liq proxy rows (BTC/ETH/SOL): {len(hl_long_proxy)}", flush=True)
print(f"  HL SHORT liq proxy rows (BTC/ETH/SOL): {len(hl_short_proxy)}", flush=True)
print(f"  HL LONG USD stats: {hl_long_proxy['usd'].describe().to_dict()}", flush=True)
print(f"  HL SHORT USD stats: {hl_short_proxy['usd'].describe().to_dict()}", flush=True)

# Pre-group by asset for speed
hl_groups = {}
for asset in ["BTC", "ETH", "SOL"]:
    hl_groups[(asset, "LONG")] = hl_long_proxy[hl_long_proxy["coin"] == asset].copy()
    hl_groups[(asset, "SHORT")] = hl_short_proxy[hl_short_proxy["coin"] == asset].copy()
    long_in_window = len(hl_groups[(asset, "LONG")][
        hl_groups[(asset, "LONG")]["time_exchange_us"].between(
            sample["fire_us_int"].min(), sample["fire_us_int"].max())
    ])
    short_in_window = len(hl_groups[(asset, "SHORT")][
        hl_groups[(asset, "SHORT")]["time_exchange_us"].between(
            sample["fire_us_int"].min(), sample["fire_us_int"].max())
    ])
    print(f"  {asset}: LONG={long_in_window} | SHORT={short_in_window} events in fire window", flush=True)

# ─── 2. Load Polymarket Trades ────────────────────────────────────────────────
print("\nLoading Polymarket trades...", flush=True)
TRADE_DIR = Path("C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket")
trades_by_asset = {}
for asset in ["BTC", "ETH", "SOL"]:
    fp = TRADE_DIR / f"{asset.lower()}.parquet"
    t = pd.read_parquet(fp, columns=["timestamp_us", "slug", "outcome", "side", "size"])
    trades_by_asset[asset] = t.sort_values("timestamp_us").reset_index(drop=True)
    print(f"  {asset}: {len(t)} trades", flush=True)

# ─── 3. Build HL cascade features (vectorized) ───────────────────────────────
print("\nBuilding HL cascade features...", flush=True)

HL_THRESHOLDS = [200_000, 500_000, 1_000_000, 2_000_000, 5_000_000]
HL_WINDOWS = [60, 300]

for window_s in HL_WINDOWS:
    for lt in ["LONG", "SHORT"]:
        col_base = f"hl_{lt.lower()}_usd_{window_s}s"
        vals = np.zeros(len(sample), dtype=np.float64)
        for asset in ["BTC", "ETH", "SOL"]:
            asset_mask = (sample["asset"] == asset).values
            if not asset_mask.any():
                continue
            sub_hl = hl_groups.get((asset, lt))
            if sub_hl is None or len(sub_hl) == 0:
                continue
            hl_times = sub_hl["time_exchange_us"].values.astype(np.int64)
            hl_usd = sub_hl["usd"].values

            fire_us_arr = sample["fire_us_int"].values
            for i in range(len(sample)):
                if not asset_mask[i]:
                    continue
                fi = fire_us_arr[i]
                lo = fi - window_s * 1_000_000
                hi = fi
                idx_lo = np.searchsorted(hl_times, lo, side="left")
                idx_hi = np.searchsorted(hl_times, hi, side="right")
                if idx_lo < idx_hi:
                    vals[i] = hl_usd[idx_lo:idx_hi].sum()
        sample[col_base] = vals
        nonzero = (vals > 0).sum()
        pct = nonzero / len(sample)
        p50 = np.percentile(vals[vals > 0], 50) if nonzero > 0 else 0
        print(f"  {col_base}: non-zero={nonzero}({pct:.1%}), median_when_nonzero=${p50:,.0f}", flush=True)

print(f"  HL features done in {time.time()-t0:.1f}s", flush=True)

# ─── 4. Build Poly aggressor flow features ────────────────────────────────────
print("\nBuilding Polymarket flow features...", flush=True)
POLY_WINDOWS = [60, 120]

# Pre-index trades by slug
print("  Indexing trades by slug...", flush=True)
slug_trade_cache = {}
for asset in ["BTC", "ETH", "SOL"]:
    t = trades_by_asset[asset]
    for slug_val, grp in t.groupby("slug"):
        slug_trade_cache[slug_val] = grp.reset_index(drop=True)
print(f"  Cached {len(slug_trade_cache)} slugs", flush=True)

for window_s in POLY_WINDOWS:
    col = f"poly_net_flow_{window_s}s"
    col_vol = f"poly_volume_{window_s}s"
    net_flows = np.zeros(len(sample), dtype=np.float64)
    volumes = np.zeros(len(sample), dtype=np.float64)
    for i in range(len(sample)):
        slug = sample.at[i, "slug"]
        fire_us = int(sample.at[i, "fire_us_int"])
        if slug not in slug_trade_cache:
            continue
        t = slug_trade_cache[slug]
        lo = fire_us - window_s * 1_000_000
        hi = fire_us
        idx_lo = t["timestamp_us"].searchsorted(lo)
        idx_hi = t["timestamp_us"].searchsorted(hi)
        sub = t.iloc[idx_lo:idx_hi]
        if len(sub) == 0:
            continue
        up_buy = sub.loc[(sub["outcome"] == "Up") & (sub["side"] == "buy"), "size"].sum()
        up_sell = sub.loc[(sub["outcome"] == "Up") & (sub["side"] == "sell"), "size"].sum()
        dn_buy = sub.loc[(sub["outcome"] == "Down") & (sub["side"] == "buy"), "size"].sum()
        dn_sell = sub.loc[(sub["outcome"] == "Down") & (sub["side"] == "sell"), "size"].sum()
        net_flows[i] = (up_buy - up_sell) - (dn_buy - dn_sell)
        volumes[i] = up_buy + up_sell + dn_buy + dn_sell
    sample[col] = net_flows
    sample[col_vol] = volumes
    pct_nonzero = (net_flows != 0).mean()
    print(f"  {col}: non-zero={pct_nonzero:.1%} | vol non-zero={(volumes>0).mean():.1%}", flush=True)

print(f"  Poly flow features done in {time.time()-t0:.1f}s", flush=True)

# ─── 5. Evaluate gates ────────────────────────────────────────────────────────
print("\nEvaluating gates...", flush=True)

results = []

def eval_gate(gate_mask, won, name, params, asset_filter=None):
    if asset_filter:
        amask = (sample["asset"] == asset_filter).values
        gate_mask = gate_mask & amask
    n_true = gate_mask.sum()
    n_false = (~gate_mask).sum()
    if n_true < 10:
        return None
    wr_true = won[gate_mask].mean()
    wr_false = won[~gate_mask].mean() if n_false > 0 else np.nan
    # Compute baseline for this asset subset if filtering
    if asset_filter:
        amask2 = (sample["asset"] == asset_filter).values
        baseline = won[amask2].mean() if amask2.sum() > 0 else BASELINE_WR
    else:
        baseline = BASELINE_WR
    lift = wr_true - baseline
    return {
        "gate": name,
        "asset": asset_filter or "ALL",
        **params,
        "n_true": int(n_true),
        "n_false": int(n_false),
        "wr_baseline": round(baseline, 4),
        "wr_true": round(wr_true, 4),
        "wr_false": round(wr_false, 4) if not np.isnan(wr_false) else np.nan,
        "wr_lift": round(lift, 4),
    }

won = sample["won"].values

# ─── Family A: HL cascade ─────────────────────────────────────────────────────
for window_s in HL_WINDOWS:
    for thresh in HL_THRESHOLDS:
        hl_long_col = f"hl_long_usd_{window_s}s"
        hl_short_col = f"hl_short_usd_{window_s}s"
        long_gate = sample[hl_long_col].values > thresh
        short_gate = sample[hl_short_col].values > thresh
        dir_up = (sample["dir"] == "Up").values
        dir_down = (sample["dir"] == "Down").values

        # A1: LONG liq cascade aligned with DOWN direction
        r = eval_gate(long_gate & dir_down, won, "A1_HL_LONG_dir_DOWN",
                      {"window_s": window_s, "thresh_usd": thresh})
        if r: results.append(r)

        # A2: SHORT liq cascade aligned with UP direction
        r = eval_gate(short_gate & dir_up, won, "A2_HL_SHORT_dir_UP",
                      {"window_s": window_s, "thresh_usd": thresh})
        if r: results.append(r)

        # A3: either LONG cascade (down) or SHORT cascade (up) — direction aligned
        r = eval_gate((long_gate & dir_down) | (short_gate & dir_up), won,
                      "A3_HL_EITHER_aligned",
                      {"window_s": window_s, "thresh_usd": thresh})
        if r: results.append(r)

        # A4: any cascade regardless of direction
        r = eval_gate(long_gate | short_gate, won, "A4_HL_ANY",
                      {"window_s": window_s, "thresh_usd": thresh})
        if r: results.append(r)

        # A5: LONG liq -> upward bounce (contrarian: maybe DOWN cascade creates dip-buy)
        r = eval_gate(long_gate & dir_up, won, "A5_HL_LONG_CONTRARIAN_UP",
                      {"window_s": window_s, "thresh_usd": thresh})
        if r: results.append(r)

        # Per-asset variants for top thresholds
        if thresh in [500_000, 1_000_000]:
            for asset in ["BTC", "ETH", "SOL"]:
                r = eval_gate(long_gate & dir_down, won, "A1_HL_LONG_dir_DOWN",
                              {"window_s": window_s, "thresh_usd": thresh}, asset_filter=asset)
                if r: results.append(r)
                r = eval_gate(short_gate & dir_up, won, "A2_HL_SHORT_dir_UP",
                              {"window_s": window_s, "thresh_usd": thresh}, asset_filter=asset)
                if r: results.append(r)

# ─── Family B: Poly aggressor flow ────────────────────────────────────────────
POLY_THRESHOLDS = [250, 500, 1000, 2000]

for window_s in POLY_WINDOWS:
    col = f"poly_net_flow_{window_s}s"
    vol_col = f"poly_volume_{window_s}s"
    flow_arr = sample[col].values
    vol_arr = sample[vol_col].values
    dir_up = (sample["dir"] == "Up").values
    dir_down = (sample["dir"] == "Down").values

    for thresh in POLY_THRESHOLDS:
        # B1: flow aligned with direction (UP when flow>thresh, DOWN when flow<-thresh)
        gate_up_aligned = (flow_arr > thresh) & dir_up
        gate_dn_aligned = (flow_arr < -thresh) & dir_down
        r = eval_gate(gate_up_aligned | gate_dn_aligned, won, "B1_POLY_FLOW_ALIGNED",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # B2: flow contrarian to direction (UP when flow<-thresh, DOWN when flow>thresh)
        gate_contrarian = ((flow_arr < -thresh) & dir_up) | ((flow_arr > thresh) & dir_down)
        r = eval_gate(gate_contrarian, won, "B2_POLY_FLOW_CONTRARIAN",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # B3: any strong flow signal
        r = eval_gate(np.abs(flow_arr) > thresh, won, "B3_POLY_FLOW_ABS",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # B4: high volume with direction-aligned flow
        vol_med = np.median(vol_arr[vol_arr > 0]) if (vol_arr > 0).any() else 1
        high_vol = vol_arr > vol_med
        r = eval_gate((gate_up_aligned | gate_dn_aligned) & high_vol, won,
                      "B4_POLY_FLOW_ALIGNED_HIGHVOL",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # Per-asset breakdowns for key thresholds
        if thresh in [500, 1000]:
            for asset in ["BTC", "ETH", "SOL"]:
                r = eval_gate(gate_up_aligned | gate_dn_aligned, won,
                              "B1_POLY_FLOW_ALIGNED",
                              {"window_s": window_s, "thresh_shares": thresh},
                              asset_filter=asset)
                if r: results.append(r)
                r = eval_gate(gate_contrarian, won, "B2_POLY_FLOW_CONTRARIAN",
                              {"window_s": window_s, "thresh_shares": thresh},
                              asset_filter=asset)
                if r: results.append(r)

# ─── Family C: Confluence ─────────────────────────────────────────────────────
print("Building confluence gates...", flush=True)

for window_hl in HL_WINDOWS:
    for window_poly in POLY_WINDOWS:
        for thresh_usd in [500_000, 1_000_000]:
            for thresh_poly in [500, 1000]:
                hl_long = sample[f"hl_long_usd_{window_hl}s"].values > thresh_usd
                hl_short = sample[f"hl_short_usd_{window_hl}s"].values > thresh_usd
                poly_col = f"poly_net_flow_{window_poly}s"
                poly_up = sample[poly_col].values > thresh_poly
                poly_dn = sample[poly_col].values < -thresh_poly
                dir_up = (sample["dir"] == "Up").values
                dir_down = (sample["dir"] == "Down").values

                # C1: both HL SHORT cascade AND poly flow confirm UP
                gate_c_up = hl_short & poly_up & dir_up
                r = eval_gate(gate_c_up, won, "C1_CONF_HL_SHORT_POLY_UP",
                              {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                               "window_hl_s": window_hl, "window_poly_s": window_poly})
                if r: results.append(r)

                # C2: both HL LONG cascade AND poly flow confirm DOWN
                gate_c_dn = hl_long & poly_dn & dir_down
                r = eval_gate(gate_c_dn, won, "C2_CONF_HL_LONG_POLY_DOWN",
                              {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                               "window_hl_s": window_hl, "window_poly_s": window_poly})
                if r: results.append(r)

                # C3: either direction confluence
                gate_c_either = gate_c_up | gate_c_dn
                r = eval_gate(gate_c_either, won, "C3_CONF_EITHER",
                              {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                               "window_hl_s": window_hl, "window_poly_s": window_poly})
                if r: results.append(r)

                # C4: HL cascade alone vs Poly flow alone (for comparison)
                # HL cascade any direction vs poly contrarian
                gate_hl_poly_contrarian = (hl_long | hl_short) & (
                    ((sample[poly_col].values < -thresh_poly) & dir_up) |
                    ((sample[poly_col].values > thresh_poly) & dir_down)
                )
                r = eval_gate(gate_hl_poly_contrarian, won, "C4_HL_CASCADE_POLY_CONTRARIAN",
                              {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                               "window_hl_s": window_hl, "window_poly_s": window_poly})
                if r: results.append(r)

# ─── 6. Results ──────────────────────────────────────────────────────────────
df_res = pd.DataFrame(results)
df_res = df_res.sort_values("wr_lift", ascending=False)

print(f"\n{'='*80}")
print(f"BASELINE WR: {BASELINE_WR:.4f} | Total gates evaluated: {len(df_res)}")

# Focus on ALL-asset results
df_all = df_res[df_res["asset"] == "ALL"].sort_values("wr_lift", ascending=False)
print(f"\nTop 25 ALL-asset gates by WR lift:")
print(df_all.head(25).to_string(index=False))

print(f"\n{'='*80}")
print("Asset-specific WR breakdown for top 5 gate families:")
top_names = df_all.head(5)["gate"].unique()
for gname in top_names:
    sub = df_res[(df_res["gate"] == gname)].sort_values(["asset", "wr_lift"], ascending=False)
    print(f"\n  {gname}:")
    print(sub[["asset", "window_s" if "window_s" in sub.columns else "window_hl_s",
               "n_true", "wr_baseline", "wr_true", "wr_lift"]].head(12).to_string(index=False))

print(f"\n{'='*80}")
print("Bottom 5 ALL gates by WR lift (anti-patterns):")
print(df_all.tail(5).to_string(index=False))

# HL gate diagnostic
print(f"\n{'='*80}")
print("HL cascade feature summary (non-zero count per feature):")
for col in [c for c in sample.columns if c.startswith("hl_")]:
    nz = (sample[col] > 0).sum()
    print(f"  {col}: {nz} non-zero fires ({nz/len(sample):.1%})")

print(f"\nPoly flow feature summary:")
for col in [c for c in sample.columns if c.startswith("poly_net")]:
    nz = (sample[col] != 0).sum()
    q90 = np.percentile(np.abs(sample[col].values[sample[col].values != 0]), 90) if nz > 0 else 0
    print(f"  {col}: {nz} non-zero ({nz/len(sample):.1%}), |flow| p90=${q90:.0f}")

# Save results
out_path = "C:/Users/alexandre bandarra/Desktop/global/strategy_lab/new_gates_results_v2.parquet"
df_res.to_parquet(out_path, index=False)
print(f"\nResults saved to {out_path}")
print(f"\nTotal runtime: {time.time()-t0:.1f}s")
