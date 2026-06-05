"""
Detailed investigation: direction alignment, dist_pct thresholds, d_speed breakdown.
"""
import sys
import numpy as np
import pandas as pd

ROOT = r'C:\Users\alexandre bandarra\Desktop\global'
sys.path.insert(0, ROOT + r'\data\v4\canonical')
sys.path.insert(0, ROOT)

from load import load_resolutions, load_chainlink_asof
from strategy_lab.physics.physics_signal import physics_at

df = pd.read_parquet(ROOT + r'\strategy_lab\_opt_2026_05_30\_results\all_sleeve_fires.parquet')
TARGET_SLEEVES = [
    'poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8',
    'poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6',
    'poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6',
    'poly_sniper_v5_btc_15m_ema50_ema800_off600_down',
]
fires = df[df['sleeve'].isin(TARGET_SLEEVES)].copy()
res = load_resolutions(assets=['BTC', 'ETH'], timeframes=['5m', '15m'])
res_map = res.set_index('slug')[['strike_price', 'slot_end_us', 'slot_start_us']].to_dict('index')

btc_ts, btc_px = load_chainlink_asof('BTC')
btc_ts = np.array(btc_ts, dtype=np.int64)
btc_px = np.array(btc_px, dtype=np.float64)
eth_ts, eth_px = load_chainlink_asof('ETH')
eth_ts = np.array(eth_ts, dtype=np.int64)
eth_px = np.array(eth_px, dtype=np.float64)
CHAINLINK = {'BTC': (btc_ts, btc_px), 'ETH': (eth_ts, eth_px)}

records = []
skipped = 0
for _, row in fires.iterrows():
    slug = row['slug']
    fire_us = int(row['fire_us'])
    asset = row['asset']
    if slug not in res_map:
        skipped += 1
        continue
    rm = res_map[slug]
    strike = rm['strike_price']
    slot_end_us = int(rm['slot_end_us'])
    ts_us, px = CHAINLINK[asset]
    feat = physics_at(ts_us, px, strike, fire_us, slot_end_us, speed_win_s=60)
    if feat is None:
        skipped += 1
        continue
    feat_prev = physics_at(ts_us, px, strike, fire_us - 30_000_000, slot_end_us, speed_win_s=60)
    d_speed = feat['speed'] - feat_prev['speed'] if feat_prev else np.nan
    records.append({
        'sleeve': row['sleeve'], 'asset': asset, 'tf': row['tf'],
        'slug': slug, 'fire_us': fire_us,
        'direction': row['direction'], 'won': bool(row['won']), 'pnl': float(row['pnl']),
        'dist': feat['dist'], 'dist_abs': feat['dist_abs'], 'side': feat['side'],
        'bet': feat['bet'], 'speed': feat['speed'], 'speed_away': feat['speed_away'],
        'd_speed': d_speed, 'have_m': feat['have_m'], 'margin': feat['margin'],
        'cross': feat['cross'], 'strike': strike,
        'dist_pct': feat['dist_abs'] / strike * 100,
    })

result = pd.DataFrame(records)
print(f"Computed {len(result)} fires, skipped {skipped}")

# ── Direction alignment ────────────────────────────────────────────────────────
print("\n=== Direction alignment check ===")
result['aligned'] = result['bet'] == result['direction']
for s in TARGET_SLEEVES:
    sub = result[result['sleeve'] == s]
    al = sub[sub['aligned']]
    mal = sub[~sub['aligned']]
    print(f"{s}:")
    print(f"  aligned={len(al)}  misaligned={len(mal)}")
    if len(al):
        print(f"  aligned WR={al['won'].mean():.1%} pnl=${al['pnl'].sum():.2f}")
    if len(mal):
        print(f"  misaligned WR={mal['won'].mean():.1%} pnl=${mal['pnl'].sum():.2f}")

# ── dist_pct stats ─────────────────────────────────────────────────────────────
print("\n=== dist_pct (% of price) stats by asset ===")
for asset in ['ETH', 'BTC']:
    sub = result[result['asset'] == asset]
    print(f"{asset}: dist_pct min={sub['dist_pct'].min():.3f}%  max={sub['dist_pct'].max():.3f}%  "
          f"median={sub['dist_pct'].median():.3f}%  p90={sub['dist_pct'].quantile(0.9):.3f}%")

# ── ETH: normalized dist thresholds ───────────────────────────────────────────
print("\n=== ETH: dist_abs thresholds ===")
eth_r = result[result['asset'] == 'ETH']
print(f"ETH dist_abs range: {eth_r['dist_abs'].min():.2f} - {eth_r['dist_abs'].max():.2f} "
      f"(median {eth_r['dist_abs'].median():.2f})")
base_pnl_eth = eth_r['pnl'].sum()
for thr in [1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0]:
    kept = eth_r[eth_r['dist_abs'] >= thr]
    if len(kept) == 0:
        continue
    wr = kept['won'].mean()
    p = kept['pnl'].sum()
    print(f"  dist_abs>={thr}: n={len(kept)}/{len(eth_r)} ({len(kept)/len(eth_r):.0%}) "
          f"WR={wr:.1%} pnl=${p:.2f} ({p-base_pnl_eth:+.2f})")

# ── ETH: dist_pct thresholds ──────────────────────────────────────────────────
print("\n=== ETH: dist_pct thresholds (% of strike price) ===")
for thr_pct in [0.05, 0.10, 0.15, 0.25, 0.50, 1.0]:
    kept = eth_r[eth_r['dist_pct'] >= thr_pct]
    if len(kept) == 0:
        continue
    wr = kept['won'].mean()
    p = kept['pnl'].sum()
    print(f"  dist_pct>={thr_pct:.2f}%: n={len(kept)}/{len(eth_r)} ({len(kept)/len(eth_r):.0%}) "
          f"WR={wr:.1%} pnl=${p:.2f} ({p-base_pnl_eth:+.2f})")

# ── BTC 15m: dist_abs thresholds ──────────────────────────────────────────────
print("\n=== BTC 15m: dist_abs thresholds ===")
btc_r = result[result['asset'] == 'BTC']
base_pnl_btc = btc_r['pnl'].sum()
print(f"BTC dist_abs range: {btc_r['dist_abs'].min():.2f} - {btc_r['dist_abs'].max():.2f} "
      f"(median {btc_r['dist_abs'].median():.2f})")
for thr in [20, 40, 60, 80, 100, 150, 200]:
    kept = btc_r[btc_r['dist_abs'] >= thr]
    if len(kept) == 0:
        continue
    wr = kept['won'].mean()
    p = kept['pnl'].sum()
    print(f"  dist_abs>={thr}: n={len(kept)}/{len(btc_r)} ({len(kept)/len(btc_r):.0%}) "
          f"WR={wr:.1%} pnl=${p:.2f} ({p-base_pnl_btc:+.2f})")

# ── d_speed gate ──────────────────────────────────────────────────────────────
print("\n=== d_speed gate per sleeve ===")
for s in TARGET_SLEEVES:
    sub = result[result['sleeve'] == s]
    kept = sub[sub['d_speed'] >= 0]
    vetoed = sub[sub['d_speed'] < 0]
    wr_k = kept['won'].mean() if len(kept) else float('nan')
    wr_v = vetoed['won'].mean() if len(vetoed) else float('nan')
    print(f"{s}:")
    print(f"  d_speed>=0: kept={len(kept)} ({len(kept)/len(sub):.0%}) WR={wr_k:.1%} pnl=${kept['pnl'].sum():.2f}")
    print(f"  d_speed<0:  vetoed={len(vetoed)} ({len(vetoed)/len(sub):.0%}) WR={wr_v:.1%} pnl=${vetoed['pnl'].sum():.2f}")

# ── speed_away gate ────────────────────────────────────────────────────────────
print("\n=== speed_away>0 gate per sleeve ===")
for s in TARGET_SLEEVES:
    sub = result[result['sleeve'] == s]
    kept = sub[sub['speed_away'] > 0]
    vetoed = sub[sub['speed_away'] <= 0]
    wr_k = kept['won'].mean() if len(kept) else float('nan')
    wr_v = vetoed['won'].mean() if len(vetoed) else float('nan')
    print(f"{s}:")
    print(f"  speed_away>0: kept={len(kept)} ({len(kept)/len(sub):.0%}) WR={wr_k:.1%} pnl=${kept['pnl'].sum():.2f}")
    print(f"  speed_away<=0: vetoed={len(vetoed)} ({len(vetoed)/len(sub):.0%}) WR={wr_v:.1%} pnl=${vetoed['pnl'].sum():.2f}")

# ── ETH: normalized WEAK_COMBO ────────────────────────────────────────────────
print("\n=== ETH: normalized WEAK_COMBO (dist_abs<2 AND speed_away<1) ===")
eth_r2 = result[result['asset'] == 'ETH'].copy()
eth_r2['weak_combo'] = (eth_r2['dist_abs'] < 2) & (eth_r2['speed_away'] < 1)
wc = eth_r2[eth_r2['weak_combo']]
nwc = eth_r2[~eth_r2['weak_combo']]
print(f"All ETH: WC vetoed={len(wc)} ({len(wc)/len(eth_r2):.0%}) WR={wc['won'].mean():.1%} "
      f"| kept={len(nwc)} WR={nwc['won'].mean():.1%} pnl=${nwc['pnl'].sum():.2f} (vs ${eth_r2['pnl'].sum():.2f})")
for s in TARGET_SLEEVES:
    sub = result[(result['sleeve'] == s) & (result['asset'] == 'ETH')].copy()
    if len(sub) == 0:
        continue
    sub['weak_combo'] = (sub['dist_abs'] < 2) & (sub['speed_away'] < 1)
    wc2 = sub[sub['weak_combo']]
    nwc2 = sub[~sub['weak_combo']]
    print(f"  {s}:")
    print(f"    WC vetoed={len(wc2)} ({len(wc2)/len(sub):.0%}) WR={wc2['won'].mean() if len(wc2) else float('nan'):.1%}")
    print(f"    kept={len(nwc2)} WR={nwc2['won'].mean() if len(nwc2) else float('nan'):.1%} pnl=${nwc2['pnl'].sum():.2f} (vs ${sub['pnl'].sum():.2f})")

# ── BTC 15m: COMBINED physics gate ───────────────────────────────────────────
print("\n=== BTC 15m: best combined gate ===")
btc_r = result[result['sleeve'] == 'poly_sniper_v5_btc_15m_ema50_ema800_off600_down']
base = btc_r['pnl'].sum()
# dist_abs>=40 AND d_speed>=0
kept_both = btc_r[(btc_r['dist_abs'] >= 40) & (btc_r['d_speed'] >= 0)]
kept_d40 = btc_r[btc_r['dist_abs'] >= 40]
kept_ds = btc_r[btc_r['d_speed'] >= 0]
print(f"Base: n={len(btc_r)} WR={btc_r['won'].mean():.1%} pnl=${base:.2f}")
print(f"dist_abs>=40: n={len(kept_d40)} ({len(kept_d40)/len(btc_r):.0%}) WR={kept_d40['won'].mean():.1%} pnl=${kept_d40['pnl'].sum():.2f}")
print(f"d_speed>=0: n={len(kept_ds)} ({len(kept_ds)/len(btc_r):.0%}) WR={kept_ds['won'].mean():.1%} pnl=${kept_ds['pnl'].sum():.2f}")
print(f"BOTH: n={len(kept_both)} ({len(kept_both)/len(btc_r):.0%}) WR={kept_both['won'].mean():.1%} pnl=${kept_both['pnl'].sum():.2f}")

print("\nDone.")
