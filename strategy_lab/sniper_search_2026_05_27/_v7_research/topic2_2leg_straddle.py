"""Topic 2: 2-leg straddle sleeve analysis on BTC 5m.

For each slug:
  - leg1: BUY UP at offset 30
  - leg2: BUY DOWN at offset 180
- Combined PnL = pnl_up_30 + pnl_dn_180 at slot_end
- Compare vs single-leg (UP only, DOWN only)
- Test: in what fraction of slugs does sleeve net positive?
- Test volatility (sigma of PnL distribution)
- Test high-vol vs low-vol regime split using regime_panel_5m_v2_fixed.realized_vol_60m
"""
import pandas as pd
import numpy as np
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

fp = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet"
df = pd.read_parquet(fp, columns=['asset', 'slug', 'slot_start_us', 'slot_end_us',
                                   'fire_offset_s', 'fire_us', 'direction', 'outcome',
                                   'won', 'entry_vwap', 'pnl_legacy_usd'])
print(f"BTC 5m fires: {len(df):,}")

OFFSET_UP = 30   # leg1
OFFSET_DN = 180  # leg2

up_leg = df[(df['fire_offset_s']==OFFSET_UP) & (df['direction']=='UP')][['slug','slot_start_us','slot_end_us','entry_vwap','pnl_legacy_usd','outcome','won']].copy()
dn_leg = df[(df['fire_offset_s']==OFFSET_DN) & (df['direction']=='DOWN')][['slug','entry_vwap','pnl_legacy_usd','won']].copy()

up_leg.columns = ['slug','slot_start_us','slot_end_us','vwap_up','pnl_up','outcome','won_up']
dn_leg.columns = ['slug','vwap_dn','pnl_dn','won_dn']

both = up_leg.merge(dn_leg, on='slug', how='inner')
print(f"Slugs with BOTH legs: {len(both):,}")
print(f"  vwap_up describe: {both['vwap_up'].describe()}")
print(f"  vwap_dn describe: {both['vwap_dn'].describe()}")

# Combined PnL: cost = vwap_up + vwap_dn for $25 + $25 = $50 stake (1 share each)
# But entry is $25 notional each. pnl_legacy_usd already accounts for $25 stake.
both['pnl_combined'] = both['pnl_up'] + both['pnl_dn']
# Note: sleeve uses $50 capital (twice the single-leg)
both['vwap_sum'] = both['vwap_up'] + both['vwap_dn']

print(f"\n=== 2-LEG STRADDLE ($50 capital, $25 each leg) — BTC 5m offset(30,180) ===")
print(f"n = {len(both):,}")
print(f"PnL combined: mean ${both['pnl_combined'].mean():+.4f}  median ${both['pnl_combined'].median():+.4f}  std ${both['pnl_combined'].std():.4f}")
print(f"PnL win rate (combined>0): {(both['pnl_combined']>0).mean()*100:.2f}%")
print(f"PnL > $1 rate: {(both['pnl_combined']>1).mean()*100:.2f}%")
print(f"vwap_sum mean: {both['vwap_sum'].mean():.4f}  (perfect-arb hint: < 1.00 means free money)")
print(f"vwap_sum < 1.00 count: {(both['vwap_sum']<1.00).sum():,}")
print(f"vwap_sum < 0.95 count: {(both['vwap_sum']<0.95).sum():,}")
print(f"vwap_sum < 0.90 count: {(both['vwap_sum']<0.90).sum():,}")

# Compare single-leg pnls
single_up = up_leg['pnl_up']
single_dn = dn_leg['pnl_dn']
print(f"\n=== SINGLE LEG comparison ===")
print(f"UP at offset 30 only:   mean ${single_up.mean():+.4f}  std ${single_up.std():.4f}  WR(pnl>0) {(single_up>0).mean()*100:.2f}%  n={len(single_up):,}")
print(f"DN at offset 180 only:  mean ${single_dn.mean():+.4f}  std ${single_dn.std():.4f}  WR(pnl>0) {(single_dn>0).mean()*100:.2f}%  n={len(single_dn):,}")

# Bucket by realized_vol_60m from regime_panel_5m_v2_fixed
print("\n[Splitting by realized_vol_60m regime]")
reg5 = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet",
                        columns=['asset', 'ts_us', 'realized_vol_60m', 'regime_label'])
reg5 = reg5[reg5['asset']=='BTC'].copy()
reg5 = reg5.sort_values('ts_us')
# asof: for each slot_start_us in both, get regime val at most-recent ts_us <= slot_start_us
both = both.sort_values('slot_start_us')
both_with_reg = pd.merge_asof(both, reg5[['ts_us','realized_vol_60m','regime_label']],
                              left_on='slot_start_us', right_on='ts_us', direction='backward')
print(f"  after asof join: {len(both_with_reg):,} ({both_with_reg['realized_vol_60m'].notna().sum()} with vol)")

bwr = both_with_reg.dropna(subset=['realized_vol_60m'])
med = bwr['realized_vol_60m'].median()
hi = bwr[bwr['realized_vol_60m'] > med]
lo = bwr[bwr['realized_vol_60m'] <= med]
print(f"  median realized_vol_60m = {med:.6f}")
print(f"  HI vol (>med): n={len(hi):,}  pnl_combined mean ${hi['pnl_combined'].mean():+.4f}  std ${hi['pnl_combined'].std():.4f}  WR(>0) {(hi['pnl_combined']>0).mean()*100:.2f}%")
print(f"  LO vol (<med): n={len(lo):,}  pnl_combined mean ${lo['pnl_combined'].mean():+.4f}  std ${lo['pnl_combined'].std():.4f}  WR(>0) {(lo['pnl_combined']>0).mean()*100:.2f}%")

# Top quartile vs bottom quartile
q1 = bwr['realized_vol_60m'].quantile(0.25)
q3 = bwr['realized_vol_60m'].quantile(0.75)
top = bwr[bwr['realized_vol_60m'] > q3]
bot = bwr[bwr['realized_vol_60m'] < q1]
print(f"\n  Top 25% vol: n={len(top):,}  pnl_combined mean ${top['pnl_combined'].mean():+.4f}  std ${top['pnl_combined'].std():.4f}  WR(>0) {(top['pnl_combined']>0).mean()*100:.2f}%")
print(f"  Bot 25% vol: n={len(bot):,}  pnl_combined mean ${bot['pnl_combined'].mean():+.4f}  std ${bot['pnl_combined'].std():.4f}  WR(>0) {(bot['pnl_combined']>0).mean()*100:.2f}%")

# Same offsets, but flip: DOWN-at-30 / UP-at-180?
print("\n=== Alt: DOWN at 30 + UP at 180 ===")
dn30 = df[(df['fire_offset_s']==30) & (df['direction']=='DOWN')][['slug','pnl_legacy_usd','entry_vwap']]
up180 = df[(df['fire_offset_s']==180) & (df['direction']=='UP')][['slug','pnl_legacy_usd','entry_vwap']]
dn30.columns = ['slug','pnl_dn30','vwap_dn30']
up180.columns = ['slug','pnl_up180','vwap_up180']
alt = dn30.merge(up180, on='slug', how='inner')
alt['pnl_combined'] = alt['pnl_dn30'] + alt['pnl_up180']
print(f"n={len(alt):,}  pnl_combined mean ${alt['pnl_combined'].mean():+.4f}  std ${alt['pnl_combined'].std():.4f}  WR(>0) {(alt['pnl_combined']>0).mean()*100:.2f}%")

# offset 30 + 30 (both legs at same time — pure straddle)
print("\n=== Pure straddle: UP at 30 + DOWN at 30 ===")
up30 = df[(df['fire_offset_s']==30) & (df['direction']=='UP')][['slug','pnl_legacy_usd','entry_vwap']]
dn30b = df[(df['fire_offset_s']==30) & (df['direction']=='DOWN')][['slug','pnl_legacy_usd','entry_vwap']]
up30.columns = ['slug','pnl_up30','vwap_up30']
dn30b.columns = ['slug','pnl_dn30','vwap_dn30']
pure = up30.merge(dn30b, on='slug', how='inner')
pure['pnl_combined'] = pure['pnl_up30'] + pure['pnl_dn30']
pure['vwap_sum'] = pure['vwap_up30'] + pure['vwap_dn30']
print(f"n={len(pure):,}  pnl_combined mean ${pure['pnl_combined'].mean():+.4f}  std ${pure['pnl_combined'].std():.4f}  WR(>0) {(pure['pnl_combined']>0).mean()*100:.2f}%")
print(f"vwap_sum mean: {pure['vwap_sum'].mean():.4f}  (arb if <1.00)")
print(f"vwap_sum <0.99: {(pure['vwap_sum']<0.99).sum():,}")
print(f"vwap_sum <0.95: {(pure['vwap_sum']<0.95).sum():,}")
