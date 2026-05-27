"""Topic 4: Slot-end OFI for BTC 15m late offsets.

For each BTC 15m slug, compute OFI (buy_size - sell_size) in last 60s before slot_end.
Then for fires at offset >= 840 (= slot_end - 60 for 900-second slot), test if
sign(OFI) predicts outcome.

trades_polymarket has side='buy'/'sell' and size. Stream via pyarrow.
"""
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 1) load BTC 15m fires + filter to late offsets
fires = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet",
                         columns=['slug','slot_start_us','slot_end_us','fire_offset_s','direction','outcome','won','pnl_legacy_usd','entry_vwap'])
late = fires[fires['fire_offset_s'].isin([840])].copy()  # only valid window for slot-end OFI without lookahead
late_slugs = set(late['slug'].unique())
print(f"BTC 15m fires offset>=840 (i.e. 840 only in our grid): {len(late):,} fires, {len(late_slugs):,} slugs")

# Get slot_end_us per slug
slot_ends = late[['slug','slot_end_us']].drop_duplicates().set_index('slug')['slot_end_us'].to_dict()

# 2) stream trades_polymarket/btc.parquet — pull side, price, size, slug, timestamp
print("\n[2] Streaming trades_polymarket/btc.parquet...")
p = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket/btc.parquet"
pf = pq.ParquetFile(p)
print(f"  row groups: {pf.num_row_groups}")

cols_needed = ['timestamp_us', 'slug', 'side', 'size', 'price', 'outcome']
ofi_rows = []  # one per slug
slug_buy_size = {s: 0.0 for s in late_slugs}
slug_sell_size = {s: 0.0 for s in late_slugs}
n_trades_seen = 0
n_trades_matched = 0

# only need trades whose slug is in late_slugs AND timestamp_us is in [slot_end-60s, slot_end]
# pre-make ranges as dict
ranges = {s: (slot_ends[s] - 60_000_000, slot_ends[s]) for s in late_slugs}

for rg_idx in range(pf.num_row_groups):
    if rg_idx % 5 == 0:
        print(f"  row group {rg_idx}/{pf.num_row_groups}  matched so far: {n_trades_matched:,}")
    rg = pf.read_row_group(rg_idx, columns=cols_needed).to_pandas()
    # filter to slugs in our set
    rg = rg[rg['slug'].isin(late_slugs)]
    if len(rg) == 0:
        continue
    n_trades_seen += len(rg)
    for slug, grp in rg.groupby('slug', sort=False):
        lo, hi = ranges[slug]
        m = (grp['timestamp_us'] >= lo) & (grp['timestamp_us'] <= hi)
        if not m.any(): continue
        sub = grp[m]
        n_trades_matched += len(sub)
        # buy on UP outcome = bullish, sell on UP outcome = bearish
        # treat outcome=='0' or 'Up' as UP token, outcome=='1' or 'Down' as DOWN
        for outc_val, oc_grp in sub.groupby('outcome'):
            # UP token side='buy' is bullish; DOWN token side='buy' is bearish
            up_token = (outc_val == 'Up' or outc_val == '0')
            for sd, ss_grp in oc_grp.groupby('side'):
                tot = ss_grp['size'].sum()
                if up_token:
                    if sd=='buy': slug_buy_size[slug] += tot
                    else: slug_sell_size[slug] += tot
                else:
                    if sd=='buy': slug_sell_size[slug] += tot
                    else: slug_buy_size[slug] += tot

print(f"  matched trades: {n_trades_matched:,}")

# build OFI dataframe
ofi_df = pd.DataFrame([
    {'slug': s, 'buy_size_60s': slug_buy_size[s], 'sell_size_60s': slug_sell_size[s]}
    for s in late_slugs
])
ofi_df['ofi'] = ofi_df['buy_size_60s'] - ofi_df['sell_size_60s']
ofi_df['ofi_total'] = ofi_df['buy_size_60s'] + ofi_df['sell_size_60s']
ofi_df['ofi_pct'] = ofi_df['ofi'] / (ofi_df['ofi_total'] + 1e-9)
print(f"  OFI built for {len(ofi_df):,} slugs (some may have 0 trades)")
print(ofi_df['ofi_total'].describe())

# 3) join to fires (only need slug, direction, outcome)
late_with_ofi = late.merge(ofi_df, on='slug', how='inner')
late_with_ofi = late_with_ofi[late_with_ofi['ofi_total'] > 0].copy()
print(f"\nFires with OFI: {len(late_with_ofi):,}")

# baseline outcome rates
print(f"\nBaseline (all 840 fires): outcome UP rate = {(late_with_ofi['outcome']=='Up').mean():.4f}")

# Test: OFI > threshold predicts UP, OFI < -threshold predicts DOWN
print("\n=== OFI-percentile based gates ===")
for q in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]:
    thr = late_with_ofi['ofi'].quantile(q)
    thr_neg = late_with_ofi['ofi'].quantile(1-q)
    pos = late_with_ofi[late_with_ofi['ofi'] > thr]
    neg = late_with_ofi[late_with_ofi['ofi'] < thr_neg]
    print(f"  pctile {q:.2f}: OFI>{thr:>10.2f}  n={len(pos):,}  UP-rate={(pos['outcome']=='Up').mean():.4f}")
    print(f"                  OFI<{thr_neg:>10.2f}  n={len(neg):,}  UP-rate={(neg['outcome']=='Up').mean():.4f}")

# Test pct-based threshold
print("\n=== OFI % (normalized) gates ===")
for ofi_pct_thr in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
    pos = late_with_ofi[late_with_ofi['ofi_pct'] > ofi_pct_thr]
    neg = late_with_ofi[late_with_ofi['ofi_pct'] < -ofi_pct_thr]
    print(f"  ofi_pct>{ofi_pct_thr:.2f}: n={len(pos):,}  UP-rate={(pos['outcome']=='Up').mean():.4f}")
    print(f"  ofi_pct<{-ofi_pct_thr:.2f}: n={len(neg):,}  UP-rate={(neg['outcome']=='Up').mean():.4f}")

# Direction-gated: when direction matches OFI sign, what's WR?
print("\n=== Sleeve: only fire if direction matches OFI sign ===")
for ofi_pct_thr in [0.20, 0.30, 0.40, 0.50]:
    aligned = late_with_ofi[
        ((late_with_ofi['direction']=='UP') & (late_with_ofi['ofi_pct'] > ofi_pct_thr)) |
        ((late_with_ofi['direction']=='DOWN') & (late_with_ofi['ofi_pct'] < -ofi_pct_thr))
    ]
    if len(aligned) < 20: continue
    print(f"  ofi_pct |>| {ofi_pct_thr}: n_aligned={len(aligned):,}  WR={aligned['won'].mean():.4f}  $/tr=${aligned['pnl_legacy_usd'].mean():+.4f}")

ofi_df.to_csv(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_v7_research/topic4_btc15m_ofi.csv", index=False)
