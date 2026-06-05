"""
Final physics overlay analysis with direction alignment fix (case mismatch corrected).
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
        'bet': feat['bet'],   # 'Up' or 'Down' (title case)
        'speed': feat['speed'], 'speed_away': feat['speed_away'],
        'd_speed': d_speed, 'have_m': feat['have_m'], 'margin': feat['margin'],
        'cross': feat['cross'], 'strike': strike,
        'dist_pct': feat['dist_abs'] / strike * 100,
    })

result = pd.DataFrame(records)
print(f"Computed {len(result)} fires, skipped {skipped}")

# FIX: normalize case before comparing
result['bet_upper'] = result['bet'].str.upper()
result['aligned'] = result['bet_upper'] == result['direction']

print("\n=== CORRECTED Direction alignment check ===")
for s in TARGET_SLEEVES:
    sub = result[result['sleeve'] == s]
    al = sub[sub['aligned']]
    mal = sub[~sub['aligned']]
    print(f"\n{s}:")
    print(f"  total={len(sub)}  aligned={len(al)} ({len(al)/len(sub):.0%})  misaligned={len(mal)} ({len(mal)/len(sub):.0%})")
    if len(al):
        print(f"  ALIGNED: WR={al['won'].mean():.1%} pnl=${al['pnl'].sum():.2f}")
    if len(mal):
        print(f"  MISALIGNED: WR={mal['won'].mean():.1%} pnl=${mal['pnl'].sum():.2f}")

# ── Full gate analysis ─────────────────────────────────────────────────────────
print("\n\n" + "="*80)
print("GATE ANALYSIS (gates defined relative to physics continuation bet)")
print("="*80)

# For ETH, normalize dist_abs to dist_pct for meaningful thresholds
# ETH ~$2000: dist_abs>=40 = dist_pct>=2% (unreachable at fire time)
# Equivalent to BTC>=40 for ETH is dist_abs>=1.0 (=0.05% ~ same pct tier)

GATES = {
    # Original gates from physics enriched analysis (BTC-scale, $$)
    'dist_abs>=40':         lambda r: r['dist_abs'] >= 40,
    'd_speed>=0':           lambda r: r['d_speed'] >= 0,
    'NOT_WEAK_COMBO':       lambda r: ~((r['dist_abs'] < 30) & (r['speed_away'] < 10)),
    # ETH-normalized: dist_abs at 0.05% of price level (~$1 for ETH ~$2000, ~$40 for BTC ~$80k)
    'dist_pct>=0.05':       lambda r: r['dist_pct'] >= 0.05,
    # speed_away <0 means price moving TOWARD strike (contrarian-confirming for misaligned sleeves)
    'speed_away<0':         lambda r: r['speed_away'] < 0,
    # d_speed < 0: momentum decelerating (good for contrarian bet)
    'd_speed<0':            lambda r: r['d_speed'] < 0,
    # Alignment: only bet when physics also agrees with sleeve
    'physics_aligned':      lambda r: r['aligned'],
    'physics_misaligned':   lambda r: ~r['aligned'],
}

summary_rows = []

for sleeve_name in TARGET_SLEEVES:
    sub = result[result['sleeve'] == sleeve_name]
    if len(sub) == 0:
        print(f"\n{sleeve_name}: NO DATA")
        continue

    n_total = len(sub)
    wr_total = sub['won'].mean()
    pnl_total = sub['pnl'].sum()
    pnl_per_fire = pnl_total / n_total

    print(f"\n{'-'*70}")
    print(f"SLEEVE: {sleeve_name}")
    print(f"  Unfiltered: n={n_total}, WR={wr_total:.1%}, net_PnL=${pnl_total:.2f}, PnL/fire=${pnl_per_fire:.3f}")

    for gate_name, gate_fn in GATES.items():
        mask = gate_fn(sub)
        kept = sub[mask]
        vetoed = sub[~mask]

        n_kept = len(kept)
        if n_kept == 0:
            print(f"  [{gate_name}]  kept=0/{n_total} (0%) -- no fires pass")
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
              f"PnL/fire=${pnl_per_kept:.3f}  "
              f"| vetoed WR={wr_vetoed:.1%} pnl=${pnl_vetoed:.2f}")

        summary_rows.append({
            'sleeve': sleeve_name,
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
print("SUMMARY TABLE (all gates x all sleeves)")
print("="*80)
print(summary.to_string(index=False))

# ── Combined gates ─────────────────────────────────────────────────────────────
print("\n\n" + "="*80)
print("COMBINED GATES (all sleeves pooled)")
print("="*80)

combined_gates = {
    'd_speed>=0 (acceleration)':  lambda r: r['d_speed'] >= 0,
    'd_speed<0 (deceleration)':   lambda r: r['d_speed'] < 0,
    'speed_away<0 (toward)':      lambda r: r['speed_away'] < 0,
    'aligned (continuation)':     lambda r: r['aligned'],
    'misaligned (contrarian)':    lambda r: ~r['aligned'],
    'dist_pct>=0.05':             lambda r: r['dist_pct'] >= 0.05,
    'dist_pct<0.05':              lambda r: r['dist_pct'] < 0.05,
    'd_speed>=0 AND dist_pct>=0.05': lambda r: (r['d_speed'] >= 0) & (r['dist_pct'] >= 0.05),
    'd_speed>=0 AND aligned':        lambda r: (r['d_speed'] >= 0) & r['aligned'],
}

base_pnl = result['pnl'].sum()
base_wr = result['won'].mean()
print(f"All sleeves base: n={len(result)} WR={base_wr:.1%} pnl=${base_pnl:.2f}")
for gname, gfn in combined_gates.items():
    mask = gfn(result)
    kept = result[mask]
    if len(kept) == 0:
        continue
    wr_k = kept['won'].mean()
    pnl_k = kept['pnl'].sum()
    pnl_vetoed = result[~mask]['pnl'].sum()
    print(f"  [{gname}]: n={len(kept)}/{len(result)} ({len(kept)/len(result):.0%}) "
          f"WR={wr_k:.1%} ({wr_k-base_wr:+.1%}) "
          f"PnL=${pnl_k:.2f} ({pnl_k-base_pnl:+.2f})"
          f"  vetoed_pnl=${pnl_vetoed:.2f}")

print("\nDone.")
