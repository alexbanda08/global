"""
Physics overlay analysis using CORRECT fire times from fires_resolved_all.parquet.
all_sleeve_fires.parquet stores fire_us=slot_end_us (lookahead) - UNUSABLE.
fires_resolved_all.parquet has fire_offset_s = actual fire offset from slot_start.
"""
import sys
import numpy as np
import pandas as pd

ROOT = r'C:\Users\alexandre bandarra\Desktop\global'
sys.path.insert(0, ROOT + r'\data\v4\canonical')
sys.path.insert(0, ROOT)

from load import load_resolutions, load_chainlink_asof
from strategy_lab.physics.physics_signal import physics_at

# ── 1. Load fires with correct fire timing ─────────────────────────────────────
df = pd.read_parquet(ROOT + r'\strategy_lab\_opt_2026_05_30\_results\fires_resolved_all.parquet')
print(f"fires_resolved_all: {len(df)} rows")

# Target sleeves (short names in fires_resolved_all)
TARGET_MAP = {
    'eth_5m_l_ema50_hurst_grandparent_v8':  ('ETH', '5m'),
    'eth_5m_bb_mp_hurst_band_v6':            ('ETH', '5m'),
    'eth_5m_cloud_ribbon_mp_hurst_v6':       ('ETH', '5m'),
    'btc_15m_ema50_ema800_off600_down':       ('BTC', '15m'),
}

fires = df[df['sleeve'].isin(TARGET_MAP.keys())].copy()
print(f"Target sleeves: {len(fires)} fires")
print(fires.groupby('sleeve')[['won','pnl_usd','fire_offset_s']].agg(
    {'won':['mean','count'], 'pnl_usd':'sum', 'fire_offset_s':'first'}
))

# ── 2. Load resolutions ────────────────────────────────────────────────────────
res = load_resolutions(assets=['BTC', 'ETH'], timeframes=['5m', '15m'])
res_map = res.set_index('slug')[['strike_price', 'slot_end_us', 'slot_start_us']].to_dict('index')
print(f"\nLoaded {len(res_map)} resolution slugs")

# ── 3. Load chainlink streams ─────────────────────────────────────────────────
print("Loading BTC chainlink...")
btc_ts, btc_px = load_chainlink_asof('BTC')
btc_ts = np.array(btc_ts, dtype=np.int64)
btc_px = np.array(btc_px, dtype=np.float64)
print(f"  BTC: {len(btc_ts):,} rows")

print("Loading ETH chainlink...")
eth_ts, eth_px = load_chainlink_asof('ETH')
eth_ts = np.array(eth_ts, dtype=np.int64)
eth_px = np.array(eth_px, dtype=np.float64)
print(f"  ETH: {len(eth_ts):,} rows")

CHAINLINK = {'BTC': (btc_ts, btc_px), 'ETH': (eth_ts, eth_px)}

# ── 4. Compute physics features with CORRECT fire timing ─────────────────────
records = []
skipped = 0

for _, row in fires.iterrows():
    slug = row['slug']
    asset = row['asset']
    fire_offset_s = float(row['fire_offset_s'])  # e.g. 60 for ETH 5m, 600 for BTC 15m

    if slug not in res_map:
        skipped += 1
        continue

    rm = res_map[slug]
    strike = rm['strike_price']
    slot_end_us = int(rm['slot_end_us'])
    slot_start_us = int(rm['slot_start_us'])

    # CORRECT fire time: slot_start + fire_offset
    fire_us = int(slot_start_us + fire_offset_s * 1_000_000)

    ts_us, px = CHAINLINK[asset]

    feat = physics_at(ts_us, px, strike, fire_us, slot_end_us, speed_win_s=60)
    if feat is None:
        skipped += 1
        continue

    feat_prev = physics_at(ts_us, px, strike, fire_us - 30_000_000, slot_end_us, speed_win_s=60)
    d_speed = feat['speed'] - feat_prev['speed'] if feat_prev is not None else np.nan

    # Verify: time_to_end should be > 0
    time_to_end_s = (slot_end_us - fire_us) / 1e6

    records.append({
        'sleeve': row['sleeve'],
        'asset': asset,
        'tf': row['tf'],
        'slug': slug,
        'fire_us': fire_us,
        'fire_offset_s': fire_offset_s,
        'time_to_end_s': time_to_end_s,
        'direction': row['direction'],
        'won': bool(row['won']),
        'pnl': float(row['pnl_usd']),
        'entry_vwap': float(row['entry_vwap']) if pd.notna(row.get('entry_vwap')) else float('nan'),
        'dist': feat['dist'],
        'dist_abs': feat['dist_abs'],
        'side': feat['side'],
        'bet': feat['bet'],
        'speed': feat['speed'],
        'speed_away': feat['speed_away'],
        'd_speed': d_speed,
        'have_m': feat['have_m'],
        'margin': feat['margin'],
        'cross': feat['cross'],
        'strike': strike,
        'dist_pct': feat['dist_abs'] / strike * 100,
    })

result = pd.DataFrame(records)
print(f"\nComputed {len(result)} fires, skipped {skipped}")
print(f"\nFire timing sanity check (time_to_end_s should be > 0):")
print(result.groupby('sleeve')['time_to_end_s'].describe()[['min','mean','max']])

# ── 5. Direction alignment ────────────────────────────────────────────────────
result['bet_upper'] = result['bet'].str.upper()
result['aligned'] = result['bet_upper'] == result['direction']
print("\n=== Direction alignment (physics continuation vs sleeve direction) ===")
for s in TARGET_MAP.keys():
    sub = result[result['sleeve'] == s]
    al = sub[sub['aligned']]
    mal = sub[~sub['aligned']]
    pct_aligned = len(al) / len(sub) if len(sub) else 0
    print(f"\n  {s} ({sub['asset'].iloc[0]}, tf={sub['tf'].iloc[0]}):")
    print(f"    total={len(sub)}  aligned={len(al)} ({pct_aligned:.0%})  misaligned={len(mal)} ({1-pct_aligned:.0%})")
    if len(al): print(f"    ALIGNED: WR={al['won'].mean():.1%} pnl=${al['pnl'].sum():.2f} ({al['pnl'].mean():.3f}/fire)")
    if len(mal): print(f"    MISALIGNED: WR={mal['won'].mean():.1%} pnl=${mal['pnl'].sum():.2f} ({mal['pnl'].mean():.3f}/fire)")

# ── 6. Gate analysis ──────────────────────────────────────────────────────────
print("\n\n" + "="*80)
print("GATE ANALYSIS WITH CORRECT FIRE TIMING")
print("="*80)

GATES = {
    # dist_abs: absolute distance in native $
    'dist_abs>=40 (BTC-scale)':     lambda r: r['dist_abs'] >= 40,
    # dist_pct: normalized by price level (~0.05% ~ $1 for ETH, $40 for BTC)
    'dist_pct>=0.05%':              lambda r: r['dist_pct'] >= 0.05,
    # d_speed: momentum acceleration
    'd_speed>=0 (accelerating)':    lambda r: r['d_speed'] >= 0,
    # speed_away < 0: price moving toward strike = mean-reversion signal
    'speed_away<0 (toward strike)': lambda r: r['speed_away'] < 0,
    # physics bet aligned with sleeve
    'physics_aligned':              lambda r: r['aligned'],
    # Combined
    'd_speed>=0 AND dist_pct>=0.05': lambda r: (r['d_speed'] >= 0) & (r['dist_pct'] >= 0.05),
}

summary_rows = []

for sleeve_name in TARGET_MAP.keys():
    sub = result[result['sleeve'] == sleeve_name]
    if len(sub) == 0:
        print(f"\n{sleeve_name}: NO DATA")
        continue

    n_total = len(sub)
    wr_total = sub['won'].mean()
    pnl_total = sub['pnl'].sum()
    pnl_per_fire = pnl_total / n_total
    asset = sub['asset'].iloc[0]
    tf = sub['tf'].iloc[0]

    print(f"\n{'-'*70}")
    print(f"SLEEVE: {sleeve_name} [{asset} {tf}]")
    print(f"  Unfiltered: n={n_total}, WR={wr_total:.1%}, net_PnL=${pnl_total:.2f}, PnL/fire=${pnl_per_fire:.3f}")

    for gate_name, gate_fn in GATES.items():
        mask = gate_fn(sub)
        kept = sub[mask]
        vetoed = sub[~mask]
        n_kept = len(kept)

        if n_kept == 0:
            print(f"  [{gate_name}]  0/{n_total} fires pass (gate always blocks)")
            continue

        frac_kept = n_kept / n_total
        wr_kept = kept['won'].mean()
        pnl_kept = kept['pnl'].sum()
        pnl_per_kept = pnl_kept / n_kept
        n_vetoed = len(vetoed)
        wr_vetoed = vetoed['won'].mean() if n_vetoed > 0 else float('nan')
        pnl_vetoed = vetoed['pnl'].sum() if n_vetoed > 0 else 0.0
        delta_pnl = pnl_kept - pnl_total
        delta_wr = wr_kept - wr_total

        print(f"  [{gate_name}]  kept={n_kept}/{n_total} ({frac_kept:.0%})  "
              f"WR={wr_kept:.1%} ({delta_wr:+.1%})  "
              f"net_PnL=${pnl_kept:.2f} ({delta_pnl:+.2f})  "
              f"PnL/fire=${pnl_per_kept:.3f}"
              f"  | vetoed n={n_vetoed} WR={wr_vetoed:.1%} PnL=${pnl_vetoed:.2f}")

        summary_rows.append({
            'sleeve': sleeve_name,
            'asset': asset,
            'tf': tf,
            'gate': gate_name,
            'n_total': n_total,
            'n_kept': n_kept,
            'frac_kept': round(frac_kept, 3),
            'wr_base': round(wr_total, 4),
            'wr_kept': round(wr_kept, 4),
            'delta_wr': round(delta_wr, 4),
            'pnl_base': round(pnl_total, 2),
            'pnl_kept': round(pnl_kept, 2),
            'delta_pnl': round(delta_pnl, 2),
            'pnl_per_fire_base': round(pnl_per_fire, 4),
            'pnl_per_fire_kept': round(pnl_per_kept, 4),
        })

summary = pd.DataFrame(summary_rows)
print("\n\n" + "="*80)
print("SUMMARY TABLE")
print("="*80)
print(summary.to_string(index=False))

# ── 7. Overall verdict ────────────────────────────────────────────────────────
print("\n\n" + "="*80)
print("OVERALL COMBINED VIEW (all target sleeves pooled)")
print("="*80)
base_pnl = result['pnl'].sum()
base_wr = result['won'].mean()
n_total = len(result)
print(f"All {len(TARGET_MAP)} sleeves: n={n_total} WR={base_wr:.1%} pnl=${base_pnl:.2f}")

combined = {
    'd_speed>=0':               lambda r: r['d_speed'] >= 0,
    'dist_pct>=0.05%':          lambda r: r['dist_pct'] >= 0.05,
    'speed_away<0':             lambda r: r['speed_away'] < 0,
    'physics_aligned':          lambda r: r['aligned'],
    'd_speed>=0 AND dist>=0.05%': lambda r: (r['d_speed'] >= 0) & (r['dist_pct'] >= 0.05),
}
for gname, gfn in combined.items():
    mask = gfn(result)
    kept = result[mask]
    if not len(kept): continue
    wr_k = kept['won'].mean()
    pnl_k = kept['pnl'].sum()
    print(f"  [{gname}]: kept={len(kept)}/{n_total} ({len(kept)/n_total:.0%}) "
          f"WR={wr_k:.1%} ({wr_k-base_wr:+.1%}) PnL=${pnl_k:.2f} ({pnl_k-base_pnl:+.2f})")

# ── 8. dist_pct sweep for ETH ────────────────────────────────────────────────
print("\n\n" + "="*80)
print("ETH DIST_PCT SWEEP (per sleeve)")
print("="*80)
eth_res = result[result['asset']=='ETH']
for s in [k for k,v in TARGET_MAP.items() if v[0]=='ETH']:
    sub = eth_res[eth_res['sleeve']==s]
    if not len(sub): continue
    base = sub['pnl'].sum()
    base_wr = sub['won'].mean()
    print(f"\n{s}: base n={len(sub)} WR={base_wr:.1%} pnl=${base:.2f}")
    print(f"  dist_abs range: {sub['dist_abs'].min():.2f} - {sub['dist_abs'].max():.2f} (median {sub['dist_abs'].median():.2f})")
    for thr in [0.5, 1.0, 2.0, 3.0, 5.0, 8.0]:
        k = sub[sub['dist_abs'] >= thr]
        if not len(k): continue
        print(f"  dist>={thr}$ ({thr/sub['strike'].median()*100:.3f}%): n={len(k)} ({len(k)/len(sub):.0%}) WR={k['won'].mean():.1%} pnl=${k['pnl'].sum():.2f} ({k['pnl'].sum()-base:+.2f})")

print("\nDone.")
