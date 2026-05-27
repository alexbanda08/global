"""
New Gates Research — HL Liquidations + Polymarket Trade Flow
2026-05-27

Uses fired_by_sleeve.parquet as the fire universe (18,270 fires, V5/V6/V7, 3 assets).
Evaluates Gate families A (HL cascade), B (Poly aggressor flow), C (confluence).
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
# direction column is 'UP'/'DOWN' — normalize to 'Up'/'Down' for matching
fires["direction_norm"] = fires["direction"].str.capitalize()  # 'UP'->'Up', 'DOWN'->'Down' — wrong, use title
fires["direction_norm"] = fires["direction"].str.title().str.replace("Up", "Up").str.replace("Down", "Down")
# Simpler:
fires["dir"] = fires["direction"].map({"UP": "Up", "DOWN": "Down"})

# Sample 5000 fires uniformly
rng = np.random.default_rng(42)
if len(fires) > 5000:
    idx = rng.choice(len(fires), size=5000, replace=False)
    sample = fires.iloc[idx].reset_index(drop=True).copy()
else:
    sample = fires.copy()

print(f"  Fire universe: {len(fires)} rows | Sample: {len(sample)} rows", flush=True)
print(f"  Time range: {pd.Timestamp(sample.fire_us.min(), unit='us')} → {pd.Timestamp(sample.fire_us.max(), unit='us')}", flush=True)
print(f"  WR baseline: {sample['won'].mean():.4f}", flush=True)

BASELINE_WR = sample["won"].mean()

# ─── 1. Load HL Liquidations (BTC, ETH, SOL) ─────────────────────────────────
print("\nLoading HL liquidations...", flush=True)
from load import load_hyperliquid_liquidations_full

hl_raw = load_hyperliquid_liquidations_full()
# Filter to only liquidation events for BTC/ETH/SOL
# Use exact coin names
ASSET_TO_COIN = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL"}
LONG_LIQ_DIRS = ["Liquidated Cross Long", "Liquidated Isolated Long"]
SHORT_LIQ_DIRS = ["Liquidated Isolated Short", "Liquidated Cross Short"]

# Keep only true liquidation rows for our 3 assets
hl_liqs = hl_raw[
    hl_raw["coin"].isin(["BTC", "ETH", "SOL"]) &
    hl_raw["dir"].isin(LONG_LIQ_DIRS + SHORT_LIQ_DIRS)
].copy()
hl_liqs["usd"] = hl_liqs["size"] * hl_liqs["price"]
hl_liqs["liq_type"] = hl_liqs["dir"].apply(
    lambda d: "LONG" if d in LONG_LIQ_DIRS else "SHORT"
)
# Sort by time for binary search
hl_liqs = hl_liqs.sort_values("time_exchange_us").reset_index(drop=True)
print(f"  HL liq rows (BTC/ETH/SOL true liqs): {len(hl_liqs)}", flush=True)
print(f"  HL liq LONG count: {(hl_liqs.liq_type=='LONG').sum()} | SHORT: {(hl_liqs.liq_type=='SHORT').sum()}", flush=True)

# ─── 2. Load Polymarket Trades (BTC, ETH, SOL) ───────────────────────────────
print("\nLoading Polymarket trades...", flush=True)
TRADE_DIR = Path("C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket")
trades_by_asset = {}
for asset in ["BTC", "ETH", "SOL"]:
    fp = TRADE_DIR / f"{asset.lower()}.parquet"
    t = pd.read_parquet(fp, columns=["timestamp_us", "slug", "outcome", "side", "size"])
    trades_by_asset[asset] = t.sort_values("timestamp_us").reset_index(drop=True)
    print(f"  {asset}: {len(t)} trades | {pd.Timestamp(t.timestamp_us.min(), unit='us')} → {pd.Timestamp(t.timestamp_us.max(), unit='us')}", flush=True)

# ─── 3. Gate evaluation helpers ──────────────────────────────────────────────

def hl_liq_cascade(fire_us: int, asset: str, window_s: int, liq_type: str, threshold_usd: float) -> bool:
    """True if sum of USD liquidations of liq_type for asset in [fire_us - window_s*1e6, fire_us] > threshold_usd"""
    lo = fire_us - window_s * 1_000_000
    hi = fire_us
    mask = (
        (hl_liqs["coin"] == asset) &
        (hl_liqs["liq_type"] == liq_type) &
        (hl_liqs["time_exchange_us"] >= lo) &
        (hl_liqs["time_exchange_us"] < hi)
    )
    total = hl_liqs.loc[mask, "usd"].sum()
    return total > threshold_usd

def poly_aggressor_flow(fire_us: int, asset: str, slug: str, window_s: int, threshold_shares: float) -> tuple[float, bool, bool]:
    """
    Returns (net_flow, gate_up_true, gate_down_true).
    net_flow > 0 → UP bias, < 0 → DOWN bias.
    gate_up_true = net_flow > threshold_shares
    gate_down_true = net_flow < -threshold_shares
    """
    lo = fire_us - window_s * 1_000_000
    hi = fire_us
    t = trades_by_asset.get(asset)
    if t is None:
        return 0.0, False, False
    mask = (
        (t["slug"] == slug) &
        (t["timestamp_us"] >= lo) &
        (t["timestamp_us"] < hi)
    )
    sub = t.loc[mask]
    if len(sub) == 0:
        return 0.0, False, False
    # UP_buys = taker bought Up token
    up_buy = sub.loc[(sub["outcome"] == "Up") & (sub["side"] == "buy"), "size"].sum()
    up_sell = sub.loc[(sub["outcome"] == "Up") & (sub["side"] == "sell"), "size"].sum()
    dn_buy = sub.loc[(sub["outcome"] == "Down") & (sub["side"] == "buy"), "size"].sum()
    dn_sell = sub.loc[(sub["outcome"] == "Down") & (sub["side"] == "sell"), "size"].sum()
    net_flow = (up_buy - up_sell) - (dn_buy - dn_sell)
    return net_flow, net_flow > threshold_shares, net_flow < -threshold_shares

# ─── 4. Vectorized HL cascade evaluation ─────────────────────────────────────
print("\nBuilding HL cascade features (vectorized by asset+window+type)...", flush=True)

HL_THRESHOLDS = [500_000, 1_000_000, 2_000_000, 5_000_000]
HL_WINDOWS = [300]  # seconds

# Pre-group HL liqs by asset+liq_type for speed
hl_groups = {}
for asset in ["BTC", "ETH", "SOL"]:
    for lt in ["LONG", "SHORT"]:
        sub = hl_liqs[(hl_liqs["coin"] == asset) & (hl_liqs["liq_type"] == lt)].copy()
        hl_groups[(asset, lt)] = sub

# For each fire in sample, compute rolling HL USD for each window
sample["fire_us_int"] = sample["fire_us"].astype(np.int64)

for window_s in HL_WINDOWS:
    for lt in ["LONG", "SHORT"]:
        col_base = f"hl_{lt.lower()}_usd_{window_s}s"
        vals = np.zeros(len(sample), dtype=np.float64)
        for asset in ["BTC", "ETH", "SOL"]:
            asset_mask = (sample["asset"] == asset).values
            if not asset_mask.any():
                continue
            sub_fires = sample.loc[asset_mask, "fire_us_int"].values
            sub_hl = hl_groups.get((asset, lt))
            if sub_hl is None or len(sub_hl) == 0:
                continue
            hl_times = sub_hl["time_exchange_us"].values.astype(np.int64)
            hl_usd = sub_hl["usd"].values
            for i, (fi, asset_match) in enumerate(zip(sample["fire_us_int"].values, asset_mask)):
                if not asset_match:
                    continue
                lo = fi - window_s * 1_000_000
                hi = fi
                idx_lo = np.searchsorted(hl_times, lo, side="left")
                idx_hi = np.searchsorted(hl_times, hi, side="right")
                if idx_lo < idx_hi:
                    vals[i] = hl_usd[idx_lo:idx_hi].sum()
        sample[col_base] = vals
        print(f"  Built {col_base} | non-zero: {(vals > 0).sum()}/{len(sample)}", flush=True)

print(f"  HL features done in {time.time()-t0:.1f}s", flush=True)

# ─── 5. Polymarket aggressor flow features ───────────────────────────────────
print("\nBuilding Polymarket aggressor flow features...", flush=True)

POLY_WINDOWS = [60, 120]
POLY_THRESHOLDS = [500, 1000, 2000]

# Pre-index trades by slug for fast lookup
print("  Indexing trades by slug...", flush=True)
slug_trade_cache = {}
for asset in ["BTC", "ETH", "SOL"]:
    t = trades_by_asset[asset]
    for slug_val, grp in t.groupby("slug"):
        slug_trade_cache[slug_val] = grp.reset_index(drop=True)
print(f"  Cached {len(slug_trade_cache)} slugs", flush=True)

# For each fire, compute net flow for each window
for window_s in POLY_WINDOWS:
    col = f"poly_net_flow_{window_s}s"
    net_flows = np.zeros(len(sample), dtype=np.float64)
    for i, row in sample.iterrows():
        slug = row["slug"]
        fire_us = int(row["fire_us_int"])
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
        net_flows[sample.index.get_loc(i)] = (up_buy - up_sell) - (dn_buy - dn_sell)
    sample[col] = net_flows
    pct_nonzero = (net_flows != 0).mean()
    print(f"  Built {col} | non-zero: {pct_nonzero:.1%}", flush=True)

print(f"  Poly flow features done in {time.time()-t0:.1f}s", flush=True)

# ─── 6. Evaluate gates ───────────────────────────────────────────────────────
print("\nEvaluating gates...", flush=True)

results = []

def eval_gate(gate_true_mask, won, name, params):
    n_true = gate_true_mask.sum()
    n_false = (~gate_true_mask).sum()
    if n_true < 5:
        return None
    wr_true = won[gate_true_mask].mean()
    wr_false = won[~gate_true_mask].mean() if n_false > 0 else np.nan
    lift = wr_true - BASELINE_WR
    return {
        "gate": name,
        **params,
        "n_true": int(n_true),
        "n_false": int(n_false),
        "wr_true": round(wr_true, 4),
        "wr_false": round(wr_false, 4) if not np.isnan(wr_false) else np.nan,
        "wr_lift": round(lift, 4),
    }

won = sample["won"].values

# ─── Family A: HL cascade ─────────────────────────────────────────────────────
for window_s in HL_WINDOWS:
    for thresh in HL_THRESHOLDS:
        # Gate A-LONG: LONG liqs > thresh → predict DOWN (direction=DOWN, liq_type=LONG)
        hl_long_col = f"hl_long_usd_{window_s}s"
        gate_true = sample[hl_long_col].values > thresh
        # For direction-matched: only fires where direction=DOWN
        dir_down = (sample["dir"] == "Down").values
        # Combined: gate=True AND direction=DOWN
        combo_dn = gate_true & dir_down
        r = eval_gate(combo_dn, won, "A_HL_LONG_CASCADE_dir_DOWN",
                      {"window_s": window_s, "thresh_usd": thresh, "liq_type": "LONG"})
        if r: results.append(r)
        # Non-direction: just gate=True
        r = eval_gate(gate_true, won, "A_HL_LONG_CASCADE_any",
                      {"window_s": window_s, "thresh_usd": thresh, "liq_type": "LONG"})
        if r: results.append(r)

        # Gate A-SHORT: SHORT liqs > thresh → predict UP (direction=UP)
        hl_short_col = f"hl_short_usd_{window_s}s"
        gate_true = sample[hl_short_col].values > thresh
        dir_up = (sample["dir"] == "Up").values
        combo_up = gate_true & dir_up
        r = eval_gate(combo_up, won, "A_HL_SHORT_CASCADE_dir_UP",
                      {"window_s": window_s, "thresh_usd": thresh, "liq_type": "SHORT"})
        if r: results.append(r)
        r = eval_gate(gate_true, won, "A_HL_SHORT_CASCADE_any",
                      {"window_s": window_s, "thresh_usd": thresh, "liq_type": "SHORT"})
        if r: results.append(r)

        # Gate A-IMBALANCE: short_cascade - long_cascade (directional alignment)
        # Positive imbalance → more short liqs → predicts UP
        hl_imb = sample[hl_short_col].values - sample[hl_long_col].values
        gate_up = (hl_imb > thresh) & dir_up
        gate_dn = (hl_imb < -thresh) & dir_down
        gate_aligned = gate_up | gate_dn
        r = eval_gate(gate_aligned, won, "A_HL_IMBALANCE_aligned",
                      {"window_s": window_s, "thresh_usd": thresh})
        if r: results.append(r)

# ─── Family B: Poly aggressor flow ───────────────────────────────────────────
for window_s in POLY_WINDOWS:
    col = f"poly_net_flow_{window_s}s"
    for thresh in POLY_THRESHOLDS:
        # net_flow > thresh → UP-biased → gate for UP direction
        dir_up = (sample["dir"] == "Up").values
        dir_down = (sample["dir"] == "Down").values

        # Direction-aligned gate: UP fires when flow favors UP
        gate_up = (sample[col].values > thresh) & dir_up
        r = eval_gate(gate_up, won, "B_POLY_FLOW_UP_aligned",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # Direction-aligned gate: DOWN fires when flow favors DOWN
        gate_dn = (sample[col].values < -thresh) & dir_down
        r = eval_gate(gate_dn, won, "B_POLY_FLOW_DOWN_aligned",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # Combined aligned (both UP and DOWN direction matches)
        gate_aligned = gate_up | gate_dn
        r = eval_gate(gate_aligned, won, "B_POLY_FLOW_ALIGNED_combined",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # Any flow above thresh (regardless of direction)
        gate_any = np.abs(sample[col].values) > thresh
        r = eval_gate(gate_any, won, "B_POLY_FLOW_ABS_any",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

        # Contrarian: flow opposite to direction (like F2 pattern)
        gate_contrarian_up = (sample[col].values < -thresh) & dir_up
        gate_contrarian_dn = (sample[col].values > thresh) & dir_down
        gate_contrarian = gate_contrarian_up | gate_contrarian_dn
        r = eval_gate(gate_contrarian, won, "B_POLY_FLOW_CONTRARIAN",
                      {"window_s": window_s, "thresh_shares": thresh})
        if r: results.append(r)

# ─── Family C: Confluence (A+B) ──────────────────────────────────────────────
print("Building confluence gates...", flush=True)
# Best combination: HL LONG cascade for DOWN + Poly flow DOWN aligned
window_hl = 300
for thresh_usd in [500_000, 1_000_000]:
    for thresh_poly in [500, 1000]:
        for window_poly in POLY_WINDOWS:
            hl_long = sample[f"hl_long_usd_{window_hl}s"].values > thresh_usd
            hl_short = sample[f"hl_short_usd_{window_hl}s"].values > thresh_usd
            poly_col = f"poly_net_flow_{window_poly}s"
            poly_up = sample[poly_col].values > thresh_poly
            poly_dn = sample[poly_col].values < -thresh_poly
            dir_up = (sample["dir"] == "Up").values
            dir_down = (sample["dir"] == "Down").values

            # Confluence UP: short liq cascade + poly flow UP + direction UP
            gate_c_up = hl_short & poly_up & dir_up
            r = eval_gate(gate_c_up, won, "C_CONFLUENCE_UP",
                          {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                           "window_hl_s": window_hl, "window_poly_s": window_poly})
            if r: results.append(r)

            # Confluence DOWN: long liq cascade + poly flow DOWN + direction DOWN
            gate_c_dn = hl_long & poly_dn & dir_down
            r = eval_gate(gate_c_dn, won, "C_CONFLUENCE_DOWN",
                          {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                           "window_hl_s": window_hl, "window_poly_s": window_poly})
            if r: results.append(r)

            # Confluence EITHER
            gate_c_either = gate_c_up | gate_c_dn
            r = eval_gate(gate_c_either, won, "C_CONFLUENCE_EITHER",
                          {"thresh_usd": thresh_usd, "thresh_shares": thresh_poly,
                           "window_hl_s": window_hl, "window_poly_s": window_poly})
            if r: results.append(r)

# ─── 7. Asset-TF breakdown for top gates ──────────────────────────────────────
df_res = pd.DataFrame(results)
df_res = df_res.sort_values("wr_lift", ascending=False)

print(f"\n{'='*70}")
print(f"BASELINE WR: {BASELINE_WR:.4f} | Total gates evaluated: {len(df_res)}")
print(f"\nTop 20 gates by WR lift:")
print(df_res.head(20).to_string(index=False))
print(f"\nBottom 5 gates by WR lift:")
print(df_res.tail(5).to_string(index=False))

# Per-asset breakdown for top gates
print(f"\n{'='*70}")
print("Asset/TF specialization for top gates:")
top_gates = df_res[df_res["wr_lift"] > 0.05].head(5)
for _, row in top_gates.iterrows():
    gate_name = row["gate"]
    params = {k: v for k, v in row.items() if k not in ["gate","n_true","n_false","wr_true","wr_false","wr_lift"]}
    print(f"\n  Gate: {gate_name} {params}")
    for asset in ["BTC", "ETH", "SOL"]:
        asset_mask = (sample["asset"] == asset).values
        if not asset_mask.any():
            continue
        # Re-evaluate gate for this asset subset
        # Reconstruct gate_true for this row
        won_asset = won[asset_mask]
        wr_asset_baseline = won_asset.mean()
        print(f"    {asset}: n={asset_mask.sum()}, baseline WR={wr_asset_baseline:.3f}")

# Save results
out_df = df_res.copy()
out_path = "C:/Users/alexandre bandarra/Desktop/global/strategy_lab/new_gates_results.parquet"
out_df.to_parquet(out_path, index=False)
print(f"\nResults saved to {out_path}")
print(f"\nTotal runtime: {time.time()-t0:.1f}s")
