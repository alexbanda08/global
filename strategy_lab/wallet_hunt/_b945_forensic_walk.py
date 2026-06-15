"""
Per-trade forensic walk of 0xb945945d fresh tape (3,500 trades, Jun 10-12 2026).

Lenses:
(a) Oracle burst timing — fill time vs nearest RTDS |ret5| spike
(b) Size laddering — clip distribution per price level
(c) Level selection — fill price vs microprice / best bid at fill time
(d) Cancel/replace cadence — fill-spacing and price migration within market
(e) EV layering — simultaneous multi-level fills
(f) Anomalies — sub-second clusters, side symmetry per market
"""
import sys, os
sys.path.insert(0, "data/v4/canonical")

import json
import numpy as np
import pandas as pd
import datetime
from pathlib import Path

# ── Load the fresh tape ──────────────────────────────────────────────────────
TAPE_FILE = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/activity_TRADE_2026_06_12.json"
with open(TAPE_FILE) as f:
    raw = json.load(f)

df = pd.DataFrame(raw)
df["ts_us"] = df["timestamp"] * 1_000_000
df["ts_dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
df = df.sort_values("timestamp").reset_index(drop=True)

print(f"=== FRESH TAPE ===")
print(f"Total trades: {len(df)}")
print(f"Date range: {df.ts_dt.min()} to {df.ts_dt.max()}")
print(f"Unique slugs: {df['slug'].nunique()}")
print(f"Unique conditionIds: {df['conditionId'].nunique()}")
print(f"Side distribution: {df['side'].value_counts().to_dict()}")
print(f"Unique tx hashes: {df['transactionHash'].nunique()}")
print()

# Parse slug to get slot_start_s and window_start
df["slot_start_s"] = df["slug"].str.extract(r"-(\d+)$").astype(float)
df["off_s"] = df["timestamp"] - df["slot_start_s"]  # seconds into the 15-min window
df["window_frac"] = df["off_s"] / 900.0  # 0-1

print(f"=== TIMING IN WINDOW ===")
print(f"off_s percentiles: {np.percentile(df['off_s'].dropna(), [5,25,50,75,95]).astype(int)}")
print(f"Fills in first 2 min (0-120s): {(df['off_s'] < 120).mean():.1%}")
print(f"Fills in first 30s: {(df['off_s'] < 30).mean():.1%}")
print()

# ── Load RTDS (BTC) for oracle burst timing ──────────────────────────────────
RTDS_CUTOFF_US = 1749622860 * 1_000_000  # Jun 11 06:21 UTC approx

try:
    from load import load_chainlink_rtds
    print("Loading RTDS...")
    rtds = load_chainlink_rtds("BTC")
    rtds = rtds.sort_values("timestamp_us").reset_index(drop=True)
    print(f"RTDS rows: {len(rtds)}, max ts: {pd.Timestamp(rtds['timestamp_us'].max(), unit='us', tz='UTC')}")

    # Only trades with RTDS coverage
    df_rtds = df[df["ts_us"] <= rtds["timestamp_us"].max()].copy()
    print(f"Trades with RTDS coverage: {len(df_rtds)} / {len(df)}")

    # Compute |ret5| at each oracle print (1-second resolution)
    rtds_s = rtds.copy()
    rtds_s["ts_s"] = rtds_s["timestamp_us"] // 1_000_000
    # group by second, take last price
    rtds_s = rtds_s.groupby("ts_s")["answer"].last().reset_index()
    rtds_s["ret5"] = rtds_s["answer"].pct_change(5)
    rtds_s["abs_ret5"] = rtds_s["ret5"].abs()

    # For each fill, find the oracle state at fill time
    df_rtds["ts_s"] = df_rtds["timestamp"]
    df_rtds = df_rtds.sort_values("ts_s")

    merged = pd.merge_asof(
        df_rtds[["ts_s", "price", "size", "usdcSize", "outcomeIndex", "off_s", "slug", "conditionId"]].sort_values("ts_s"),
        rtds_s[["ts_s", "answer", "abs_ret5"]].sort_values("ts_s"),
        on="ts_s", direction="backward"
    )

    print(f"\n=== ORACLE BURST TIMING (a) ===")
    print(f"Merged fills with RTDS state: {len(merged)}")
    print(f"abs_ret5 percentiles at fill time: {np.percentile(merged['abs_ret5'].dropna(), [25,50,75,90,95])}")

    # Split by oracle intensity
    med_ret5 = merged["abs_ret5"].median()
    high_oracle = merged[merged["abs_ret5"] > med_ret5]
    low_oracle = merged[merged["abs_ret5"] <= med_ret5]
    print(f"\nHigh oracle (abs_ret5 > {med_ret5:.4f}): n={len(high_oracle)}")
    print(f"Low oracle (abs_ret5 <= {med_ret5:.4f}): n={len(low_oracle)}")
    print(f"High oracle mean fill size: ${high_oracle['usdcSize'].mean():.3f} vs low: ${low_oracle['usdcSize'].mean():.3f}")
    print(f"High oracle fill rate (share of all): {len(high_oracle)/len(merged):.1%}")

    # Is fill intensity U-shaped in oracle?
    # Bin oracle by quintile
    merged["ret5_qnt"] = pd.qcut(merged["abs_ret5"].fillna(0), 5, labels=False)
    qnt_counts = merged.groupby("ret5_qnt")["ts_s"].count()
    qnt_size = merged.groupby("ret5_qnt")["usdcSize"].mean()
    print(f"\nFill count by |ret5| quintile (0=low, 4=high):")
    for q in range(5):
        print(f"  Q{q}: n={qnt_counts.get(q,0)}, mean_usdcSize=${qnt_size.get(q,0):.3f}")

except Exception as e:
    print(f"RTDS load failed: {e}")
    merged = None

print()

# ── Size laddering (b) ───────────────────────────────────────────────────────
print("=== SIZE LADDERING (b) ===")
price_buckets = pd.cut(df["price"], bins=[0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.01],
                        labels=["0-10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100"])
df["price_bucket"] = price_buckets

print("Size distribution by price bucket (median clip $):")
for bucket in price_buckets.cat.categories:
    sub = df[df["price_bucket"] == bucket]
    if len(sub) == 0:
        continue
    print(f"  {bucket}¢: n={len(sub):4d}, med=${sub['usdcSize'].median():.2f}, "
          f"mean=${sub['usdcSize'].mean():.2f}, max=${sub['usdcSize'].max():.2f}")

print()
print("Clip size distribution overall:")
print(df["usdcSize"].describe())

# Unique clip sizes (reveals ladder rungs)
top_sizes = df["size"].round(4).value_counts().head(20)
print(f"\nTop 20 fill sizes (shares):")
print(top_sizes)

print()
top_usdc = df["usdcSize"].round(3).value_counts().head(20)
print(f"Top 20 fill usdcSizes ($):")
print(top_usdc)

# ── Per-market analysis (c, d, e, f) ────────────────────────────────────────
print("\n=== PER-MARKET ANALYSIS ===")

# Group by market (conditionId)
mkt_stats = []
for cid, grp in df.groupby("conditionId"):
    grp = grp.sort_values("timestamp")
    n_fills = len(grp)
    n_up = (grp["outcomeIndex"] == 0).sum()
    n_dn = (grp["outcomeIndex"] == 1).sum()
    n_tx = grp["transactionHash"].nunique()
    total_usdc = grp["usdcSize"].sum()

    # Intra-market timing spread (seconds between consecutive fills)
    if n_fills > 1:
        gaps = grp["timestamp"].diff().dropna()
        min_gap = gaps.min()
        med_gap = gaps.median()
    else:
        min_gap = np.nan
        med_gap = np.nan

    # Price migration across fills
    price_range = grp["price"].max() - grp["price"].min()

    # Multi-level simultaneity: how many distinct prices in same second?
    by_second = grp.groupby("timestamp")["price"].nunique()
    max_levels_per_second = by_second.max()
    mean_levels_per_second = by_second.mean()

    # Time of first fill in window
    first_off = grp["off_s"].min()

    mkt_stats.append({
        "conditionId": cid,
        "n_fills": n_fills,
        "n_up": n_up,
        "n_dn": n_dn,
        "n_tx": n_tx,
        "total_usdc": total_usdc,
        "min_gap_s": min_gap,
        "med_gap_s": med_gap,
        "price_range": price_range,
        "max_levels_s": max_levels_per_second,
        "mean_levels_s": mean_levels_per_second,
        "first_off_s": first_off,
        "slug": grp["slug"].iloc[0],
    })

mkt_df = pd.DataFrame(mkt_stats)
print(f"Markets in tape: {len(mkt_df)}")
print(f"\nFills per market: {mkt_df['n_fills'].describe().astype(int)}")
print(f"\nSide symmetry per market (n_up / (n_up+n_dn)):")
mkt_df["up_frac"] = mkt_df["n_up"] / (mkt_df["n_up"] + mkt_df["n_dn"])
print(f"  mean={mkt_df['up_frac'].mean():.3f}, median={mkt_df['up_frac'].median():.3f}, "
      f"std={mkt_df['up_frac'].std():.3f}")
print(f"  Truly symmetric (0.4-0.6): {((mkt_df['up_frac'] > 0.4) & (mkt_df['up_frac'] < 0.6)).mean():.1%}")

# (c) Level selection — fill price distribution
print(f"\n=== LEVEL SELECTION (c) ===")
print(f"Fill price distribution:")
print(df["price"].describe())
print(f"\nFill price percentiles: {np.percentile(df['price'], [5,10,25,50,75,90,95])}")

# Price at opening fill vs later fills
df_first = df.groupby("conditionId").first().reset_index()
df_rest = df[~df.index.isin(df.groupby("conditionId").first().index)]
print(f"\nFirst fill price per market: mean={df_first['price'].mean():.3f}, med={df_first['price'].median():.3f}")
print(f"Subsequent fill prices: mean={df['price'].mean():.3f}, med={df['price'].median():.3f}")

# (d) Cancel/replace cadence
print(f"\n=== CANCEL/REPLACE CADENCE (d) ===")
print(f"Min intra-market gap (seconds): {mkt_df['min_gap_s'].describe()}")
print(f"\nMarkets with sub-1s intra-fill gaps: {(mkt_df['min_gap_s'] < 1).sum()} / {len(mkt_df)}")
print(f"Markets with sub-0.1s gaps: {(mkt_df['min_gap_s'] < 0.1).sum()} / {len(mkt_df)}")

# Same-second fills
same_second = df.groupby(["conditionId", "timestamp"]).size()
print(f"\nSame-second (same-market) fill clusters:")
print(f"  Seconds with 1 fill: {(same_second == 1).sum()}")
print(f"  Seconds with 2-5 fills: {((same_second >= 2) & (same_second <= 5)).sum()}")
print(f"  Seconds with 6-10 fills: {((same_second >= 6) & (same_second <= 10)).sum()}")
print(f"  Seconds with >10 fills: {(same_second > 10).sum()}")
print(f"  Max fills in one second (one market): {same_second.max()}")

# (e) EV layering — multiple price levels per second
print(f"\n=== EV LAYERING (e) ===")
print(f"Max simultaneous price levels in 1 second (per market): {mkt_df['max_levels_s'].describe()}")
print(f"Markets with >1 level per second on average: {(mkt_df['mean_levels_s'] > 1).sum()} / {len(mkt_df)}")

# Check for simultaneous fills on BOTH tokens in same second
by_ts = df.groupby(["slug", "timestamp"])
two_token_seconds = by_ts["outcomeIndex"].nunique()
print(f"\nSeconds with fills on BOTH tokens (same slug, same second): {(two_token_seconds == 2).sum()}")
print(f"Total seconds with any fills (per slug): {len(two_token_seconds)}")
print(f"Two-token fill rate: {(two_token_seconds == 2).mean():.1%}")

# (f) Anomalies — sub-second patterns
print(f"\n=== ANOMALIES (f) ===")
# Transaction hash reuse (batched fills)
tx_counts = df["transactionHash"].value_counts()
print(f"Tx hash distribution:")
print(f"  Unique txs: {len(tx_counts)}")
print(f"  Max fills per tx: {tx_counts.max()}")
print(f"  Tx with >1 fill: {(tx_counts > 1).sum()} ({(tx_counts > 1).mean():.1%})")
print(f"  Tx with >10 fills: {(tx_counts > 10).sum()}")
print(f"\nTop tx hashes by fill count:")
print(tx_counts.head(10))

# Price patterns: fills at very round prices vs non-round
df["price_round_cent"] = (df["price"] * 100).round(0) / 100
df["is_round"] = (df["price"] == df["price_round_cent"])
print(f"\nFills at round cent prices: {df['is_round'].mean():.1%}")
print(f"Fill price fractional distribution (mod 0.01):")
mod_vals = (df["price"] * 100) % 1
print(f"  Exactly 0 (round cents): {(mod_vals == 0).mean():.1%}")
print(f"  Near 0 (<0.01): {(mod_vals < 0.01).mean():.1%}")
print(f"  Near 0.5 (0.45-0.55): {((mod_vals > 0.45) & (mod_vals < 0.55)).mean():.1%}")

# First fill timing distribution (how many seconds after window open)
print(f"\n=== FIRST FILL TIMING ===")
print(f"First fill offset within 15m window (seconds):")
print(f"  {np.percentile(mkt_df['first_off_s'].dropna(), [5,10,25,50,75,90,95]).astype(int)}")
print(f"  Markets with first fill <10s: {(mkt_df['first_off_s'] < 10).mean():.1%}")
print(f"  Markets with first fill <30s: {(mkt_df['first_off_s'] < 30).mean():.1%}")
print(f"  Markets with first fill <60s: {(mkt_df['first_off_s'] < 60).mean():.1%}")
print(f"  Markets with first fill <120s: {(mkt_df['first_off_s'] < 120).mean():.1%}")

# Save summary parquet
out_path = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/fresh_tape_analysis.parquet"
df.to_parquet(out_path, index=False)
print(f"\nSaved per-trade df to {out_path}")

mkt_out = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/fresh_tape_mkt_stats.parquet"
mkt_df.to_parquet(mkt_out, index=False)
print(f"Saved per-market stats to {mkt_out}")

# ── Oracle-gated quoting test (residual hypothesis a from handoff) ────────────
if merged is not None:
    print(f"\n=== ORACLE-GATED QUOTING (HYPOTHESIS a from handoff) ===")
    # Does he quote MORE or use LARGER clips when |oracle_ret5| is elevated?

    # Define "oracle burst" as |ret5| > 75th percentile
    p75 = merged["abs_ret5"].quantile(0.75)
    burst = merged[merged["abs_ret5"] > p75]
    calm = merged[merged["abs_ret5"] <= p75]

    print(f"Oracle burst threshold (|ret5| > {p75:.4f}):")
    print(f"  During burst: n={len(burst)}, mean_clip=${burst['usdcSize'].mean():.3f}")
    print(f"  During calm: n={len(calm)}, mean_clip=${calm['usdcSize'].mean():.3f}")
    print(f"  Ratio (burst/calm clips): {burst['usdcSize'].mean()/calm['usdcSize'].mean():.2f}x")

    # t-test
    from scipy import stats as sp_stats
    if len(burst) > 30 and len(calm) > 30:
        t, p = sp_stats.ttest_ind(burst["usdcSize"], calm["usdcSize"])
        print(f"  t-test: t={t:.2f}, p={p:.4f}")

    # Price level during oracle bursts
    print(f"\nFill price during oracle burst: mean={burst['price'].mean():.3f}")
    print(f"Fill price during calm: mean={calm['price'].mean():.3f}")

    # Specifically: does he trade EXTREMES more during bursts?
    burst_extreme = ((burst["price"] < 0.20) | (burst["price"] > 0.80)).mean()
    calm_extreme = ((calm["price"] < 0.20) | (calm["price"] > 0.80)).mean()
    print(f"\nExtreme price (<0.20 or >0.80) fills:")
    print(f"  During burst: {burst_extreme:.1%}")
    print(f"  During calm: {calm_extreme:.1%}")

print("\n=== DONE ===")
