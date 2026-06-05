"""
Physics overlay analysis on existing winning sleeves.
Tests whether physics gates (dist_abs>=40, d_speed>=0, NOT WEAK_COMBO) improve
our known profitable sleeves.

Target sleeves:
- poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8
- poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6
- poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6
- poly_sniper_v5_btc_15m_ema50_ema800_off600_down
"""
import sys
import numpy as np
import pandas as pd

ROOT = r'C:\Users\alexandre bandarra\Desktop\global'
sys.path.insert(0, ROOT + r'\data\v4\canonical')
sys.path.insert(0, ROOT)

from load import load_resolutions, load_chainlink_asof
from strategy_lab.physics.physics_signal import physics_at

# ── 1. Load fires ──────────────────────────────────────────────────────────────
RESULTS_DIR = ROOT + r'\strategy_lab\_opt_2026_05_30\_results'
df = pd.read_parquet(RESULTS_DIR + r'\all_sleeve_fires.parquet')

TARGET_SLEEVES = [
    'poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8',
    'poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6',
    'poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6',
    'poly_sniper_v5_btc_15m_ema50_ema800_off600_down',
]

fires = df[df['sleeve'].isin(TARGET_SLEEVES)].copy()
print(f"Loaded {len(fires)} fires for {len(TARGET_SLEEVES)} target sleeves")

# ── 2. Load resolutions (slug -> strike, slot_end_us) ─────────────────────────
res = load_resolutions(assets=['BTC', 'ETH'], timeframes=['5m', '15m'])
# Build slug -> (strike_price, slot_end_us, slot_start_us) map
res_map = res.set_index('slug')[['strike_price', 'slot_end_us', 'slot_start_us']].to_dict('index')
print(f"Loaded {len(res_map)} resolution slugs")

# ── 3. Load chainlink streams per asset ────────────────────────────────────────
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

# ── 4. Compute physics features for each fire ─────────────────────────────────
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
    slot_start_us = int(rm['slot_start_us'])

    ts_us, px = CHAINLINK[asset]

    # Physics at fire_us (60s speed window)
    feat = physics_at(ts_us, px, strike, fire_us, slot_end_us, speed_win_s=60)
    if feat is None:
        skipped += 1
        continue

    # d_speed: speed now minus speed 30s ago (= change in 60s-speed over last 30s)
    # As used in the physics enriched parquet: speed at fire_us minus speed at fire_us-30s
    feat_prev = physics_at(ts_us, px, strike, fire_us - 30_000_000, slot_end_us, speed_win_s=60)
    d_speed = feat['speed'] - feat_prev['speed'] if feat_prev is not None else np.nan

    records.append({
        'sleeve': row['sleeve'],
        'asset': asset,
        'tf': row['tf'],
        'slug': slug,
        'fire_us': fire_us,
        'direction': row['direction'],
        'won': bool(row['won']),
        'pnl': float(row['pnl']),
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
    })

result = pd.DataFrame(records)
print(f"\nComputed physics for {len(result)} fires, skipped {skipped}")
print(result.groupby('sleeve')[['won', 'pnl']].agg({'won': ['mean', 'count'], 'pnl': 'sum'}))

# ── 5. Gate analysis ──────────────────────────────────────────────────────────
GATES = {
    'dist_abs>=40':     lambda r: r['dist_abs'] >= 40,
    'd_speed>=0':       lambda r: r['d_speed'] >= 0,
    'NOT_WEAK_COMBO':   lambda r: ~((r['dist_abs'] < 30) & (r['speed_away'] < 10)),
    'COMBINED_ANY':     lambda r: (r['dist_abs'] >= 40) | (r['d_speed'] >= 0) | ~((r['dist_abs'] < 30) & (r['speed_away'] < 10)),
    'COMBINED_dist40_OR_dspeed': lambda r: (r['dist_abs'] >= 40) | (r['d_speed'] >= 0),
}

print("\n\n" + "="*80)
print("PHYSICS OVERLAY GATE ANALYSIS")
print("="*80)

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
        frac_kept = n_kept / n_total
        wr_kept = kept['won'].mean() if n_kept > 0 else np.nan
        pnl_kept = kept['pnl'].sum() if n_kept > 0 else 0.0
        pnl_per_kept = pnl_kept / n_kept if n_kept > 0 else np.nan

        n_vetoed = len(vetoed)
        wr_vetoed = vetoed['won'].mean() if n_vetoed > 0 else np.nan
        pnl_vetoed = vetoed['pnl'].sum() if n_vetoed > 0 else 0.0

        delta_pnl = pnl_kept - pnl_total
        delta_wr = wr_kept - wr_total if np.isfinite(wr_kept) else np.nan

        print(f"  [{gate_name}]  kept={n_kept}/{n_total} ({frac_kept:.0%})  "
              f"WR={wr_kept:.1%} ({delta_wr:+.1%} vs base)  "
              f"net_PnL=${pnl_kept:.2f} ({delta_pnl:+.2f})  "
              f"PnL/fire=${pnl_per_kept:.3f}")

        summary_rows.append({
            'sleeve': sleeve_name,
            'gate': gate_name,
            'n_total': n_total,
            'n_kept': n_kept,
            'frac_kept': frac_kept,
            'wr_base': wr_total,
            'wr_kept': wr_kept,
            'delta_wr': delta_wr,
            'pnl_base': pnl_total,
            'pnl_kept': pnl_kept,
            'delta_pnl': delta_pnl,
            'pnl_per_fire_base': pnl_per_fire,
            'pnl_per_fire_kept': pnl_per_kept,
        })

summary = pd.DataFrame(summary_rows)
print("\n\n" + "="*80)
print("SUMMARY TABLE")
print("="*80)
print(summary.to_string(index=False))

# ── 6. Direction alignment check ──────────────────────────────────────────────
print("\n\n" + "="*80)
print("DIRECTION ALIGNMENT: physics bet vs sleeve direction")
print("="*80)
result['aligned'] = result['bet'] == result['direction']
print(result.groupby('sleeve')['aligned'].value_counts().unstack(fill_value=0).to_string())
print()
# Physics bet alignment with outcome:
print("When physics bet ALIGNS with sleeve direction vs when it doesn't:")
for sleeve_name in TARGET_SLEEVES:
    sub = result[result['sleeve'] == sleeve_name]
    if len(sub) == 0:
        continue
    aligned = sub[sub['aligned']]
    misaligned = sub[~sub['aligned']]
    print(f"\n  {sleeve_name}")
    if len(aligned):
        print(f"    aligned   n={len(aligned):3d} WR={aligned['won'].mean():.1%}  pnl=${aligned['pnl'].sum():.2f}")
    if len(misaligned):
        print(f"    misalign  n={len(misaligned):3d} WR={misaligned['won'].mean():.1%}  pnl=${misaligned['pnl'].sum():.2f}")

# ── 7. Best physics filter combinations ───────────────────────────────────────
print("\n\n" + "="*80)
print("DETAILED GATE BREAKDOWN PER GATE (all sleeves combined)")
print("="*80)
for gate_name, gate_fn in GATES.items():
    mask = gate_fn(result)
    kept = result[mask]
    vetoed = result[~mask]
    n_total = len(result)
    n_kept = len(kept)
    wr_base = result['won'].mean()
    wr_kept = kept['won'].mean() if n_kept else np.nan
    pnl_base = result['pnl'].sum()
    pnl_kept = kept['pnl'].sum() if n_kept else 0
    print(f"[{gate_name}]")
    print(f"  All sleeves: kept {n_kept}/{n_total} ({n_kept/n_total:.0%})  "
          f"WR {wr_kept:.1%} vs {wr_base:.1%}  "
          f"PnL ${pnl_kept:.2f} vs ${pnl_base:.2f}  ({pnl_kept-pnl_base:+.2f})")
    print()

print("\nDone.")
