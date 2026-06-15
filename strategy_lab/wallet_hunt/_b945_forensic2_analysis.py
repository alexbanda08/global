"""
B945 Forensic2 - Full analysis: fire timing, gates/selectivity, ToD, decay, anomalies.
Outputs structured findings to stdout for report generation.
"""
import pandas as pd
import numpy as np
import json
import os
import sys
import warnings
warnings.filterwarnings('ignore')

BASE = "."
CACHE = "strategy_lab/wallet_hunt/cache/0xb945945d"
PM_CACHE = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d"
sys.path.insert(0, "data/v4/canonical")

print("=" * 70)
print("B945 FORENSIC2 ANALYSIS - 2026-06-13")
print("=" * 70)

# ── Load core data ──────────────────────────────────────────────────────────
ft = pd.read_parquet(f"{CACHE}/fill_tape_full.parquet")
ft['ts_dt'] = pd.to_datetime(ft['ts'], utc=True)  # ts is ISO string
ft['ts_unix'] = ft['ts_dt'].astype(np.int64) // 10**9  # unix seconds
print(f"\n[DATA] fill_tape_full: {len(ft):,} fills, {ft['slug'].nunique()} slugs")
print(f"       date range: {ft['ts_dt'].min().date()} → {ft['ts_dt'].max().date()}")
print(f"       cols: {list(ft.columns)}")

# slug → slot_start: extract from slug string (last part after last '-')
ft['slot_start'] = ft['slug'].apply(lambda s: int(s.rsplit('-', 1)[1]) if isinstance(s, str) and '-' in s else np.nan)
ft['window_s'] = ft['slug'].apply(lambda s: 15 * 60 if '15m' in s else 5 * 60 if '5m' in s else np.nan)

# ── Filter to BTC-15m only ───────────────────────────────────────────────────
btc15 = ft[ft['slug'].str.contains('btc.*15m|15m.*btc', case=False, na=False)].copy()
print(f"\n[DATA] BTC-15m fills: {len(btc15):,} fills, {btc15['slug'].nunique()} slugs")

# ── Load fresh trade activity ────────────────────────────────────────────────
with open(f"{PM_CACHE}/activity_TRADE_2026_06_13.json") as f:
    trade_fresh = json.load(f)
with open(f"{PM_CACHE}/activity_REDEEM_2026_06_13.json") as f:
    redeem_fresh = json.load(f)
with open(f"{PM_CACHE}/activity_SPLIT_2026_06_13.json") as f:
    split_fresh = json.load(f)
with open(f"{PM_CACHE}/activity_MERGE_2026_06_13.json") as f:
    merge_fresh = json.load(f)

print(f"\n[DATA] Fresh TRADE: {len(trade_fresh):,}, REDEEM: {len(redeem_fresh):,}")
print(f"       SPLIT: {len(split_fresh)}, MERGE: {len(merge_fresh)}")

tf = pd.DataFrame(trade_fresh)
tf['ts_dt'] = pd.to_datetime(tf['timestamp'], utc=True)
tf['ts'] = tf['ts_dt'].astype(np.int64) // 10**9
tf['price'] = tf['price'].astype(float)
tf['size'] = tf['size'].astype(float)
tf['usdcSize'] = tf['usdcSize'].astype(float)

# Identify btc-15m in fresh trades by conditionId lookup
print(f"\n[DATA] Fresh trade date range: {tf['ts_dt'].min().date()} → {tf['ts_dt'].max().date()}")
print(f"       unique conditionIds: {tf['conditionId'].nunique()}")
print(f"       type field values: {tf['type'].value_counts().to_dict() if 'type' in tf.columns else 'no type col'}")
# type column is activity type
if 'makerSide' in tf.columns:
    print(f"       makerSide: {tf['makerSide'].value_counts().to_dict()}")
if 'side' in tf.columns:
    print(f"       side: {tf['side'].value_counts().to_dict()}")

print(f"\n[DATA] Fresh trade sample keys: {list(tf.columns)}")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 2: EXACT FIRE START PER WINDOW
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q2: FIRE TIMING - first fill offset from slot_start")
print("=" * 70)

# Per slug: min ts (first fill), slot_start, offset
first_fill = btc15.groupby('slug').agg(
    first_ts=('ts_unix', 'min'),
    n_fills=('ts_unix', 'count'),
    slot_start=('slot_start', 'first')
).reset_index()
first_fill['offset_s'] = first_fill['first_ts'] - first_fill['slot_start']

# Filter to reasonable: offset within [0, 900]
valid = first_fill[(first_fill['offset_s'] >= -60) & (first_fill['offset_s'] <= 900)].copy()
print(f"\nBTC-15m slugs with valid first_fill offset: {len(valid)}")
print(f"Offset distribution (seconds from slot_start):")
for pct in [5, 10, 25, 50, 75, 90, 95, 99]:
    v = np.percentile(valid['offset_s'], pct)
    print(f"  p{pct:02d}: {v:.0f}s")

print(f"\nMedian first fill: {valid['offset_s'].median():.0f}s after slot_start")
print(f"Mean:              {valid['offset_s'].mean():.0f}s")
print(f"Std:               {valid['offset_s'].std():.0f}s")
print(f"Pct < 30s:         {(valid['offset_s'] < 30).mean()*100:.1f}%")
print(f"Pct < 60s:         {(valid['offset_s'] < 60).mean()*100:.1f}%")
print(f"Pct < 120s:        {(valid['offset_s'] < 120).mean()*100:.1f}%")
print(f"Pct > 600s:        {(valid['offset_s'] > 600).mean()*100:.1f}%")

# Histogram buckets
bins = [0, 10, 20, 30, 60, 90, 120, 180, 300, 600, 900]
hist, _ = np.histogram(valid['offset_s'].clip(0, 900), bins=bins)
for i, (lo, hi) in enumerate(zip(bins, bins[1:])):
    print(f"  [{lo:4d}-{hi:4d}s]: {hist[i]:4d} slugs ({hist[i]/len(valid)*100:.1f}%)")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 3: GATES / SELECTIVITY
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q3: GATES / SELECTIVITY - how many windows does he skip?")
print("=" * 70)

# Load canonical resolutions to get universe of btc-15m slugs
try:
    from load import load_resolutions
    res = load_resolutions()
    btc15_res = res[res['slug'].str.contains('btc.*15m|15m.*btc', case=False, na=False)].copy()
    btc15_res['ts_dt'] = pd.to_datetime(btc15_res['slot_start'] if 'slot_start' in btc15_res.columns
                                         else btc15_res['slot_start_us'] / 1e6, unit='s', utc=True)
    print(f"\nCanonical BTC-15m slugs: {btc15_res['slug'].nunique()}")

    # Filter to his active period
    his_start = first_fill['slot_start'].min()
    his_end = first_fill['slot_start'].max()
    print(f"His period: {pd.to_datetime(his_start, unit='s', utc=True).date()} → {pd.to_datetime(his_end, unit='s', utc=True).date()}")

    # Slugs he TRADED vs SKIPPED
    his_slugs = set(btc15['slug'].unique())
    if 'slot_start' in btc15_res.columns:
        all_slugs_in_period = btc15_res[
            (btc15_res['slot_start'] >= his_start) &
            (btc15_res['slot_start'] <= his_end)
        ]['slug'].unique()
    else:
        all_slugs_in_period = btc15_res['slug'].unique()

    traded = set(all_slugs_in_period) & his_slugs
    skipped = set(all_slugs_in_period) - his_slugs

    print(f"\nBTC-15m slugs in his period (canonical): {len(all_slugs_in_period)}")
    print(f"He TRADED: {len(traded)}")
    print(f"He SKIPPED: {len(skipped)}")
    print(f"Engagement rate: {len(traded)/len(all_slugs_in_period)*100:.1f}%")

    # Compare traded vs skipped resolutions if outcome available
    if 'outcome' in btc15_res.columns:
        traded_df = btc15_res[btc15_res['slug'].isin(traded)]
        skipped_df = btc15_res[btc15_res['slug'].isin(skipped)]
        print(f"\nTraded slugs - Up win rate: {(traded_df['outcome']=='Up').mean()*100:.1f}%")
        print(f"Skipped slugs - Up win rate: {(skipped_df['outcome']=='Up').mean()*100:.1f}%")

except Exception as e:
    print(f"  Could not load canonical resolutions: {e}")
    # Fall back to fill tape universe
    his_slugs = set(btc15['slug'].unique())
    print(f"His traded BTC-15m slugs: {len(his_slugs)}")
    print(f"  Cannot compute skip rate without canonical universe")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 3b: Entry-side AUC on fresh data
# ──────────────────────────────────────────────────────────────────────────
print("\n--- Q3b: Entry side AUC on fresh 3500 trades ---")
try:
    mf = pd.read_parquet(f"{CACHE}/ml_features.parquet")
    print(f"ml_features shape: {mf.shape}, cols: {list(mf.columns[:20])}")
    # Check if outcome column exists
    if 'outcome' in mf.columns:
        from sklearn.metrics import roc_auc_score
        y = (mf['outcome'] == 'Up').astype(int)
        if 'delta' in mf.columns:
            auc = roc_auc_score(y, mf['delta'].fillna(0))
            print(f"  Entry-side (delta→Up) AUC: {auc:.4f}")
        if 'up_ask' in mf.columns:
            auc2 = roc_auc_score(y, -mf['up_ask'].fillna(0.5))
            print(f"  up_ask→Up AUC: {auc2:.4f}")
    else:
        print("  No 'outcome' col in ml_features")
        print(f"  Cols: {list(mf.columns)}")
except Exception as e:
    print(f"  ml_features AUC: {e}")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 4: TIME OF DAY - his REAL activity & PnL by hour
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q4: TIME OF DAY - real activity and PnL by UTC hour")
print("=" * 70)

btc15['hour'] = btc15['ts_dt'].dt.hour
btc15['weekday'] = btc15['ts_dt'].dt.dayofweek  # 0=Mon

# Per-hour: fills, unique slugs, mean price (pvs proxy), total usd
by_hour = btc15.groupby('hour').agg(
    n_fills=('ts_unix', 'count'),
    n_slugs=('slug', 'nunique'),
    mean_price=('price', 'mean'),
    total_usd=('usd', 'sum'),
    mean_usd_per_fill=('usd', 'mean'),
    mean_shares=('shares', 'mean')
).sort_index()

print(f"\nBy UTC hour (BTC-15m fills):")
print(f"{'Hour':>5} {'n_fills':>8} {'n_slugs':>8} {'mean_pvs':>9} {'total_usd':>11} {'usd/fill':>9}")
for h, row in by_hour.iterrows():
    print(f"  {h:02d}:00 {row['n_fills']:8.0f} {row['n_slugs']:8.0f} {row['mean_price']:9.4f} {row['total_usd']:11,.0f} {row['mean_usd_per_fill']:9.2f}")

# By weekday
by_dow = btc15.groupby('weekday').agg(
    n_fills=('ts_unix', 'count'),
    n_slugs=('slug', 'nunique'),
).sort_index()
dow_names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
print(f"\nBy weekday:")
for d, row in by_dow.iterrows():
    print(f"  {dow_names[d]}: {row['n_fills']:.0f} fills, {row['n_slugs']:.0f} slugs")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 5: SPLIT/MERGE verification
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q5: SPLIT/MERGE verification")
print("=" * 70)

print(f"\nActivity API results:")
print(f"  SPLIT events: {len(split_fresh)} (data-api 2026-06-13)")
print(f"  MERGE events: {len(merge_fresh)} (data-api 2026-06-13)")
print(f"  CONVERSION events: 0")

# Check tx_taxonomy for any split/merge class
tt = pd.read_parquet(f"{CACHE}/tx_taxonomy.parquet")
print(f"\ntx_taxonomy classes:")
print(tt[['class','n_txs','n_transfers','date_start','date_end']].to_string())

# Merge timing
mt = pd.read_parquet(f"{CACHE}/merge_timing.parquet")
mt['ts_dt'] = pd.to_datetime(mt['ts'], unit='s', utc=True)
mt['slot_start_dt'] = pd.to_datetime(mt['slot_start'], unit='s', utc=True)
mt['merge_after_slot_s'] = mt['ts'] - mt['slot_start']
mt['win_end_s'] = mt['slot_start'] + mt['win_s']
mt['merge_after_win_end_s'] = mt['ts'] - mt['win_end_s']

print(f"\nMerge events: {len(mt)}")
print(f"  merge_after_slot_start distribution:")
for pct in [5, 25, 50, 75, 95]:
    v = np.percentile(mt['merge_after_slot_s'], pct)
    print(f"    p{pct:02d}: {v/60:.1f} min")
print(f"\n  Pct merged BEFORE window end:  {(mt['merge_after_win_end_s'] < 0).mean()*100:.1f}%")
print(f"  Pct merged 0-60s after end:    {((mt['merge_after_win_end_s'] >= 0) & (mt['merge_after_win_end_s'] < 60)).mean()*100:.1f}%")
print(f"  Pct merged > 1h after end:     {(mt['merge_after_win_end_s'] > 3600).mean()*100:.1f}%")
print(f"  Median merge lag after win end: {mt['merge_after_win_end_s'].median()/60:.1f} min")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 6: EDGE OVER TIME / DECAY
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q6: EDGE OVER TIME / DECAY by ISO week")
print("=" * 70)

btc15['isoweek'] = btc15['ts_dt'].dt.strftime('%Y-W%V')
by_week = btc15.groupby('isoweek').agg(
    n_fills=('ts_unix', 'count'),
    n_slugs=('slug', 'nunique'),
    mean_price=('price', 'mean'),
    total_usd=('usd', 'sum'),
    mean_shares=('shares', 'mean'),
).sort_index()

# fills per slug per week
by_week['fills_per_slug'] = by_week['n_fills'] / by_week['n_slugs']
by_week['usd_per_slug'] = by_week['total_usd'] / by_week['n_slugs']

print(f"\nBy ISO week (BTC-15m):")
print(f"{'Week':>8} {'n_fills':>8} {'n_slugs':>8} {'fills/slug':>10} {'mean_pvs':>9} {'usd/slug':>9}")
for wk, row in by_week.iterrows():
    print(f"  {wk} {row['n_fills']:8.0f} {row['n_slugs']:8.0f} {row['fills_per_slug']:10.1f} {row['mean_price']:9.4f} {row['usd_per_slug']:9.2f}")

# Correlation of week-number with fills_per_slug (decay check)
week_nums = np.arange(len(by_week))
if len(week_nums) > 2:
    corr_fills = np.corrcoef(week_nums, by_week['fills_per_slug'].values)[0,1]
    corr_pvs = np.corrcoef(week_nums, by_week['mean_price'].values)[0,1]
    print(f"\nTrend: fills_per_slug vs time corr = {corr_fills:.3f}")
    print(f"Trend: mean_pvs vs time corr = {corr_pvs:.3f}")

# ──────────────────────────────────────────────────────────────────────────
# QUESTION 7: ANOMALY HUNT
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q7: ANOMALY HUNT")
print("=" * 70)

# 7a: clip size quantization
print("\n--- 7a: Clip size (USD) distribution ---")
sz = btc15['usd'].dropna()
print(f"  mean={sz.mean():.2f}, median={sz.median():.2f}, std={sz.std():.2f}")
print(f"  Unique USD amounts (top 20 by freq):")
top_usd = btc15['usd'].value_counts().head(20)
for val, cnt in top_usd.items():
    print(f"    ${val:.2f}: {cnt} fills ({cnt/len(btc15)*100:.1f}%)")

# 7b: price level quantization
print("\n--- 7b: Price level patterns ---")
price_rounds = (btc15['price'] * 100).round(0) / 100
top_prices = price_rounds.value_counts().head(15)
print("  Top 15 price levels (rounded to 0.01):")
for val, cnt in top_prices.items():
    print(f"    {val:.2f}: {cnt} fills ({cnt/len(btc15)*100:.1f}%)")

# 7c: sub-second clusters (fills within 1s of each other in same slug)
print("\n--- 7c: Sub-second fill clustering ---")
slug_fills = btc15.sort_values(['slug', 'ts_unix'])
slug_fills['ts_gap'] = slug_fills.groupby('slug')['ts_unix'].diff()
gaps = slug_fills['ts_gap'].dropna()
print(f"  Fill-to-fill gap within slug:")
print(f"  Pct gap < 1s:  {(gaps < 1).mean()*100:.1f}%")
print(f"  Pct gap < 10s: {(gaps < 10).mean()*100:.1f}%")
print(f"  Pct gap 0s (same second): {(gaps == 0).mean()*100:.1f}%")
print(f"  Median gap: {gaps.median():.0f}s")

# 7d: side symmetry per window (Up vs Down fills per slug)
print("\n--- 7d: Side symmetry per window ---")
if 'outcome' in btc15.columns:
    side_sym = btc15.groupby('slug')['outcome'].value_counts().unstack(fill_value=0)
    if 'Up' in side_sym.columns and 'Down' in side_sym.columns:
        side_sym['ratio_up'] = side_sym['Up'] / (side_sym['Up'] + side_sym['Down']).clip(lower=1)
        print(f"  Slugs with BOTH Up+Down fills: {((side_sym['Up'] > 0) & (side_sym['Down'] > 0)).sum()}")
        print(f"  Slugs with ONLY Up: {((side_sym['Up'] > 0) & (side_sym['Down'] == 0)).sum()}")
        print(f"  Slugs with ONLY Down: {((side_sym['Up'] == 0) & (side_sym['Down'] > 0)).sum()}")
        print(f"  Mean fills_Up per paired slug: {side_sym[side_sym['Up']>0]['Up'].mean():.1f}")
        print(f"  Mean fills_Down per paired slug: {side_sym[side_sym['Down']>0]['Down'].mean():.1f}")

# 7e: Price range per slug (ladder evidence)
print("\n--- 7e: Intra-slug price range (ladder spread evidence) ---")
slug_prices = btc15.groupby('slug')['price'].agg(['min','max','std','count'])
slug_prices['range'] = slug_prices['max'] - slug_prices['min']
print(f"  Median price range per slug: {slug_prices['range'].median():.4f}")
print(f"  Mean price range per slug:   {slug_prices['range'].mean():.4f}")
print(f"  Pct slugs with range > 0.05: {(slug_prices['range'] > 0.05).mean()*100:.1f}%")
print(f"  Pct slugs with range > 0.10: {(slug_prices['range'] > 0.10).mean()*100:.1f}%")
print(f"  Pct slugs single-price:      {(slug_prices['range'] == 0).mean()*100:.1f}%")
print(f"  Median fills per slug:       {slug_prices['count'].median():.0f}")
print(f"  p90 fills per slug:          {slug_prices['count'].quantile(0.90):.0f}")
print(f"  p99 fills per slug:          {slug_prices['count'].quantile(0.99):.0f}")
print(f"  Max fills in one slug:       {slug_prices['count'].max():.0f}")

# 7f: orderfilled_sample - maker/taker breakdown
print("\n--- 7f: OrderFilled sample maker/taker ---")
try:
    ofs = pd.read_parquet(f"{CACHE}/orderfilled_sample.parquet")
    print(f"  Sample: {len(ofs)} fills")
    if 'b945_role' in ofs.columns:
        print(f"  b945_role: {ofs['b945_role'].value_counts().to_dict()}")
    if 'b945_dir' in ofs.columns:
        print(f"  b945_dir: {ofs['b945_dir'].value_counts().to_dict()}")
    if 'maker_asset_is_cash' in ofs.columns:
        print(f"  maker_asset_is_cash: {ofs['maker_asset_is_cash'].value_counts().to_dict()}")
    # Is his role consistent over time?
    if 'b945_role' in ofs.columns and 'ts' in ofs.columns:
        ofs['ts_dt'] = pd.to_datetime(ofs['ts'], utc=True)
        ofs['month'] = ofs['ts_dt'].dt.strftime('%Y-%m')
        print(f"  Role by month: {ofs.groupby('month')['b945_role'].value_counts().to_dict()}")
except Exception as e:
    print(f"  orderfilled error: {e}")

# 7g: Fresh trades - check newest timestamps vs prior (expansion?)
print("\n--- 7g: Date coverage comparison ---")
with open(f"{PM_CACHE}/activity_TRADE.json") as f:
    trade_old = json.load(f)
tf_old = pd.DataFrame(trade_old)
tf_old['ts_dt'] = pd.to_datetime(tf_old['timestamp'], utc=True)
print(f"  OLD activity_TRADE.json: {len(tf_old)} records, max={tf_old['ts_dt'].max().date()}")
tf_new = pd.DataFrame(trade_fresh)
tf_new['ts_dt'] = pd.to_datetime(tf_new['timestamp'], utc=True)
print(f"  NEW activity_TRADE_2026_06_13.json: {len(tf_new)} records, max={tf_new['ts_dt'].max().date()}")
print(f"  New records (after old max): {(tf_new['ts_dt'] > tf_old['ts_dt'].max()).sum()}")

# PvS achieved in fresh trades
print(f"\n--- Fresh TRADE PvS stats ---")
tf_new['price'] = tf_new['price'].astype(float)
print(f"  Mean price: {tf_new['price'].mean():.4f}")
print(f"  Median price: {tf_new['price'].median():.4f}")
print(f"  p10/p90: {tf_new['price'].quantile(0.10):.4f} / {tf_new['price'].quantile(0.90):.4f}")
print(f"  Price dist:")
bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
hist_p, _ = np.histogram(tf_new['price'].clip(0,1), bins=bins)
for i, (lo, hi) in enumerate(zip(bins, bins[1:])):
    print(f"    [{lo:.1f}-{hi:.1f}]: {hist_p[i]} ({hist_p[i]/len(tf_new)*100:.1f}%)")

# ──────────────────────────────────────────────────────────────────────────
# SELECTIVITY DEEPER: load canonical to get full slug universe
# ──────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Q3 DEEP: Canonical universe engagement rate")
print("=" * 70)

try:
    from load import load_resolutions
    res = load_resolutions()
    # Filter to BTC 15m
    btc15_univ = res[res['slug'].str.contains('btc.*15m|15m.*btc', case=False, na=False)].copy()

    # Column names
    print(f"  Resolution cols: {list(btc15_univ.columns[:12])}")

    if 'slot_start_us' in btc15_univ.columns:
        btc15_univ['slot_start'] = btc15_univ['slot_start_us'] / 1e6
    elif 'slot_start' in btc15_univ.columns:
        pass

    # His period
    his_period_start = btc15['ts_dt'].min()
    his_period_end = btc15['ts_dt'].max()
    his_ss = pd.Timestamp(his_period_start).timestamp()
    his_se = pd.Timestamp(his_period_end).timestamp()

    univ_in_period = btc15_univ[
        (btc15_univ['slot_start'] >= his_ss) &
        (btc15_univ['slot_start'] <= his_se)
    ].copy()

    his_slugs = set(btc15['slug'].unique())
    univ_slugs = set(univ_in_period['slug'].unique())
    traded_slugs = his_slugs & univ_slugs
    skipped_slugs = univ_slugs - his_slugs

    print(f"  Universe BTC-15m in his period: {len(univ_slugs)}")
    print(f"  He traded:  {len(traded_slugs)} ({len(traded_slugs)/len(univ_slugs)*100:.1f}%)")
    print(f"  He skipped: {len(skipped_slugs)} ({len(skipped_slugs)/len(univ_slugs)*100:.1f}%)")

    # What makes traded different?
    if 'outcome' in univ_in_period.columns:
        t_df = univ_in_period[univ_in_period['slug'].isin(traded_slugs)]
        s_df = univ_in_period[univ_in_period['slug'].isin(skipped_slugs)]
        print(f"\n  Traded windows - Up outcome: {(t_df['outcome']=='Up').mean()*100:.1f}%")
        print(f"  Skipped windows - Up outcome: {(s_df['outcome']=='Up').mean()*100:.1f}%")

    # Check if he engages sequentially or skips batches
    univ_sorted = univ_in_period.sort_values('slot_start')
    univ_sorted['engaged'] = univ_sorted['slug'].isin(his_slugs)

    # Run lengths of skips
    skip_runs = []
    current_run = 0
    for engaged in univ_sorted['engaged']:
        if not engaged:
            current_run += 1
        else:
            if current_run > 0:
                skip_runs.append(current_run)
            current_run = 0
    if current_run > 0:
        skip_runs.append(current_run)

    if skip_runs:
        print(f"\n  Skip runs: {len(skip_runs)} gaps, median={np.median(skip_runs):.0f}, max={max(skip_runs)}")
        print(f"  Skip runs hist: 1={sum(r==1 for r in skip_runs)}, 2={sum(r==2 for r in skip_runs)}, 3-5={sum(2<r<=5 for r in skip_runs)}, >5={sum(r>5 for r in skip_runs)}")

    # Check time of day of skipped vs traded
    univ_sorted['hour'] = pd.to_datetime(univ_sorted['slot_start'], unit='s', utc=True).dt.hour
    print(f"\n  Engagement by hour:")
    eng_by_hour = univ_sorted.groupby('hour')['engaged'].agg(['sum','count','mean'])
    print(f"  {'Hour':>5} {'traded':>8} {'total':>7} {'pct':>7}")
    for h, row in eng_by_hour.iterrows():
        print(f"    {h:02d}:00 {row['sum']:8.0f} {row['count']:7.0f} {row['mean']*100:6.1f}%")

except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
