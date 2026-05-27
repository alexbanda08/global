"""
Round 6: Slug-Overlap Audit + Deploy Manifest
=============================================
Step 1: Build the sleeve-fire matrix.

For each Tier-1 sleeve, identify the (slug, fire_us, direction) triples it fires on
and the per-fire pnl_usd (LegacyConfig).

Output: data/v4/canonical/_results/_overlap_audit_2026_05_26/fired_by_sleeve.parquet
"""
import os, sys
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
OUT = f"{RES}/_overlap_audit_2026_05_26"
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------------------
# LOAD: base panels (OOS-validated full window 32d, all gates pre-computed)
# ------------------------------------------------------------------------
print("Loading base panels (Tier-1 5m/15m fires with gate columns)...")
panels = {}
for asset in ['BTC', 'ETH', 'SOL']:
    for tf in ['5m', '15m']:
        p = f"{RES}/_full_window_2026_05_26/oos_fires_{asset}_{tf}.parquet"
        if os.path.exists(p):
            df = pd.read_parquet(p)
            df['key'] = df['asset'].astype(str) + '|' + df['tf'].astype(str)
            panels[(asset, tf)] = df
            print(f"  {asset} {tf}: {df.shape[0]:,} rows")

base = pd.concat(list(panels.values()), ignore_index=True)
print(f"BASE TOTAL: {len(base):,} fires across BTC/ETH/SOL × 5m/15m")
# In oos panels each fire row has BOTH directions; gate stacks filter them
# direction column already has UP / DOWN; pnl_legacy_usd is signed for that bet

# Numeric coercion
for g in [c for c in base.columns if c.startswith('g_')]:
    base[g] = pd.to_numeric(base[g], errors='coerce').fillna(0).astype(int)

# Ensure direction-side gates exist (some gates are direction-aware already)
# Filtering helper
def apply_gates(df, gate_list, direction=None):
    """Filter df rows matching the gate stack. direction can be 'BOTH'/'UP'/'DOWN'/None"""
    mask = pd.Series(True, index=df.index)
    for g in gate_list:
        if g in df.columns:
            mask &= (df[g] == 1)
        else:
            return pd.DataFrame(columns=df.columns)  # gate missing → empty
    sub = df[mask].copy()
    if direction in ('UP', 'DOWN'):
        sub = sub[sub['direction'] == direction]
    elif direction == 'BOTH' or direction is None:
        pass  # all directions allowed
    return sub

# ------------------------------------------------------------------------
# Tier-1 sleeve registry (from ROUND5_SYNTHESIS §8 + sleeve_full_window_validation)
# ------------------------------------------------------------------------
# Each: id, asset, tf, offset_range (lo, hi inclusive seconds), gate_stack list,
#       direction_pick (BOTH/UP/DOWN), base label.
SLEEVES = []

# --- 5m Tier-1 (R4-validated, hybrid family) ---
SLEEVES += [
    dict(id='S6TA_btc_top1', asset='BTC', tf='5m', off=(60,150),
         gates=['g_cci_with','g_stoch_with','g_rf_with','g_tr_above_ema50','g_ribbon_agrees'],
         direction='BOTH', base='s6_hybrid_v1'),
    dict(id='S6TA_eth_top1', asset='ETH', tf='5m', off=(60,150),
         gates=['g_cci_with','g_bb_pos_with','g_ribbon_agrees'],
         direction='BOTH', base='s6_hybrid_v1'),
    dict(id='poly_updown_btc_5m_s6_hybrid_v1', asset='BTC', tf='5m', off=(60,150),
         gates=['g_cci_with','g_stoch_with','g_rf_with','g_tr_above_ema50','g_ribbon_agrees'],
         direction='BOTH', base='s6_hybrid_v1'),
    dict(id='poly_updown_eth_5m_s6_hybrid_v1', asset='ETH', tf='5m', off=(60,150),
         gates=['g_cci_with','g_bb_pos_with','g_ribbon_agrees'],
         direction='BOTH', base='s6_hybrid_v1'),
    dict(id='poly_updown_sol_5m_s6_hybrid_v1', asset='SOL', tf='5m', off=(60,150),
         gates=['g_mfi_with','g_bb_pos_with','g_ribbon_agrees'],
         direction='BOTH', base='s6_hybrid_v1'),
    dict(id='poly_updown_btc_5m_s15_hybrid_v1', asset='BTC', tf='5m', off=(150,240),
         gates=['g_tr_above_pp','g_ribbon_agrees','g_stoch_with','g_tight_ribbon'],
         direction='BOTH', base='s15_hybrid_v1'),
    dict(id='poly_updown_eth_5m_s15_hybrid_v1', asset='ETH', tf='5m', off=(150,240),
         gates=['g_ribbon_agrees','g_tr_above_ema200','g_stoch_with','g_bb_pos_with','g_cci_with'],
         direction='BOTH', base='s15_hybrid_v1'),
    # S7 (BTC base sleeve - Cyclops) - approximate from BTC S6 panel by selecting tighter stack
    dict(id='S7_btc_5m_base', asset='BTC', tf='5m', off=(120,300),
         gates=['g_cci_with','g_stoch_with','g_rf_with','g_tr_above_ema50','g_tr_above_ema200','g_ribbon_agrees'],
         direction='BOTH', base='s7_cyclops'),
    # R1 lite/top2
    dict(id='R1_btc_5m_s6_top2', asset='BTC', tf='5m', off=(60,150),
         gates=['g_cci_with','g_rf_with','g_ribbon_agrees'],
         direction='BOTH', base='s6_top2'),
    dict(id='R1_btc_5m_s6_lite', asset='BTC', tf='5m', off=(60,150),
         gates=['g_cci_with','g_ribbon_agrees'],
         direction='BOTH', base='s6_lite'),
    dict(id='R1_eth_5m_s6_tight_pos_cloud', asset='ETH', tf='5m', off=(60,150),
         gates=['g_cci_with','g_bb_pos_with','g_ribbon_agrees','g_tr_above_cloud','g_tight_ribbon'],
         direction='BOTH', base='s6_tight'),
    # S2 Fade Momo BTC - distinct (anti-momo) - approximate by using rare opposite stack
    dict(id='S2_btc_fade', asset='BTC', tf='5m', off=(120,300),
         gates=['g_dev_extreme','g_ribbon_agrees'],
         direction='BOTH', base='s2_fade'),
    # R2 BTC 5m S1.5 3bps  - dev/within bands
    dict(id='R2_btc_5m_s1_5_3bps', asset='BTC', tf='5m', off=(60,180),
         gates=['g_within_dev','g_rf_strong','g_ribbon_agrees'],
         direction='BOTH', base='s1_5'),
]

# --- 15m Tier-1 (R4 trend_slope family) ---
SLEEVES += [
    # NOTE: SOL 15m oos panel not present; we'll skip SOL 15m gracefully
    dict(id='R4_SOL_15m_120_240_trendslope', asset='SOL', tf='15m', off=(120,240),
         gates=['g_rf_strong','g_ribbon_slope_with'],
         direction='BOTH', base='15m_trendslope'),
    dict(id='R4_POOL_15m_600_720_ribbon_slope_vwap', asset='BTC', tf='15m', off=(600,720),
         gates=['g_ribbon_agrees','g_rf_strong','g_within_dev'],
         direction='BOTH', base='15m_pool_ribbon_slope'),
    dict(id='R4_POOL_15m_240_360_trendslope_vwap', asset='BTC', tf='15m', off=(240,360),
         gates=['g_rf_strong','g_within_dev'],
         direction='BOTH', base='15m_pool_trendslope'),
    dict(id='R4_POOL_15m_120_240_trendslope', asset='BTC', tf='15m', off=(120,240),
         gates=['g_rf_strong','g_ribbon_slope_with'],
         direction='BOTH', base='15m_pool_120'),
    dict(id='R4_ETH_15m_60_120_trstack_trendslope', asset='ETH', tf='15m', off=(60,120),
         gates=['g_tr_stack_with','g_rf_strong'],
         direction='BOTH', base='15m_eth_trstack'),
]

# --- R5 Standalone: Microprice "universal" panel + Hawkes families ---
# These need their own panel joins
# We'll handle them in step 02 (load microprice_panel + hawkes_panel and apply gates)
# Tag here:
SLEEVES += [
    dict(id='R5_microprice_univ_5m_rf_ribbon', asset='UNIV', tf='5m', off=(60,300),
         gates=['__mp_no_extreme__','g_rf_with','g_ribbon_agrees'],
         direction='BOTH', base='microprice'),
    dict(id='R5_hawkes_btc_5m_off120', asset='BTC', tf='5m', off=(90,150),
         gates=['__hawkes_imb_with__'],
         direction='HAWKES', base='hawkes'),
    dict(id='R5_hawkes_eth_5m_off120', asset='ETH', tf='5m', off=(90,150),
         gates=['__hawkes_imb_with__'],
         direction='HAWKES', base='hawkes'),
    dict(id='R5_hawkes_sol_5m_off120', asset='SOL', tf='5m', off=(90,150),
         gates=['__hawkes_imb_with__'],
         direction='HAWKES', base='hawkes'),
]

# --- R5 Overlays as standalone sleeves (with overlay applied to base) ---
SLEEVES += [
    # microprice no-extreme on top of ETH S6
    dict(id='R5_eth_s6_v1_plus_mp_no_extreme', asset='ETH', tf='5m', off=(60,150),
         gates=['g_cci_with','g_bb_pos_with','g_ribbon_agrees','__mp_no_extreme__'],
         direction='BOTH', base='s6_hybrid_v1+mp'),
    # mp_change_with on ETH S6
    dict(id='R5_eth_s6_v1_plus_mp_change_with', asset='ETH', tf='5m', off=(60,150),
         gates=['g_cci_with','g_bb_pos_with','g_ribbon_agrees','__mp_change_with__'],
         direction='BOTH', base='s6_hybrid_v1+mp_change'),
    # LM high stat on BTC S6
    dict(id='R5_btc_s6_v1_plus_lm_high_stat', asset='BTC', tf='5m', off=(60,150),
         gates=['g_cci_with','g_stoch_with','g_rf_with','g_tr_above_ema50','g_ribbon_agrees','__lm_high_stat__'],
         direction='BOTH', base='s6_hybrid_v1+lm'),
    # microprice no-extreme on BTC S15
    dict(id='R5_btc_s15_v1_plus_mp_no_extreme', asset='BTC', tf='5m', off=(150,240),
         gates=['g_tr_above_pp','g_ribbon_agrees','g_stoch_with','g_tight_ribbon','__mp_no_extreme__'],
         direction='BOTH', base='s15_hybrid_v1+mp'),
]

print(f"\n{len(SLEEVES)} Tier-1 sleeves registered.")

# ------------------------------------------------------------------------
# Load R5 overlay data (microprice + hawkes + lm)
# ------------------------------------------------------------------------
print("\nLoading R5 overlay panels...")
mp = pd.read_parquet(f"{RES}/microprice_panel.parquet")[['asset','slug','tf','fire_us','fire_offset_s','mp_skew','mp_weighted_skew','mp_up_dev_change_500ms']].copy()
# g_mp_no_extreme: |mp_skew| < 50 bps
mp['g_mp_no_extreme'] = (mp['mp_skew'].abs() < 50).astype(int)
# g_mp_change_with: positive direction means MP change matches bet direction
mp['mp_change_sign'] = np.sign(mp['mp_up_dev_change_500ms']).fillna(0).astype(int)

hk = pd.read_parquet(f"{RES}/hawkes_panel.parquet")
# Sort for asof
hk = hk.sort_values(['asset','ts_us']).reset_index(drop=True)

lm = pd.read_parquet(f"{RES}/lm_at_fires_5m.parquet")[['asset','slug','fire_us','fire_offset_s','lm_L_stat_at_fire']].copy()
lm['g_lm_high_stat'] = (lm['lm_L_stat_at_fire'] > 5.97).fillna(False).astype(int)

print(f"  microprice: {len(mp):,}, hawkes: {len(hk):,}, lm: {len(lm):,}")

# ------------------------------------------------------------------------
# Iterate sleeves: build fires_by_sleeve
# ------------------------------------------------------------------------
print("\nApplying gate stacks per sleeve...")
records = []
for slv in SLEEVES:
    sid = slv['id']
    asset, tf, off, gates, direction_pick, base_name = slv['asset'], slv['tf'], slv['off'], slv['gates'], slv['direction'], slv['base']

    # Resolve asset 'UNIV' = all
    if asset == 'UNIV':
        if tf == '5m':
            df = pd.concat([panels.get((a,'5m'), pd.DataFrame()) for a in ['BTC','ETH','SOL']], ignore_index=True)
        else:
            df = pd.concat([panels.get((a,'15m'), pd.DataFrame()) for a in ['BTC','ETH']], ignore_index=True)
    else:
        df = panels.get((asset, tf), pd.DataFrame())
    if df.empty:
        print(f"  [SKIP] {sid}: no panel for {asset} {tf}")
        continue

    # offset filter
    df = df[(df['fire_offset_s'] >= off[0]) & (df['fire_offset_s'] <= off[1])].copy()

    # Apply R5 overlay gates (need joins)
    overlay_gates = [g for g in gates if g.startswith('__')]
    core_gates    = [g for g in gates if not g.startswith('__')]

    # Core gate filter
    mask = pd.Series(True, index=df.index)
    for g in core_gates:
        if g not in df.columns:
            mask &= False
            print(f"  [WARN] {sid}: gate {g} missing - sleeve empty")
        else:
            mask &= (df[g] == 1)
    df = df[mask].copy()
    if df.empty:
        print(f"  [EMPTY post core gates] {sid}")
        continue

    # Overlay joins
    for og in overlay_gates:
        if og == '__mp_no_extreme__':
            df = df.merge(mp[['slug','fire_us','g_mp_no_extreme']], on=['slug','fire_us'], how='left')
            df = df[df['g_mp_no_extreme'] == 1]
        elif og == '__mp_change_with__':
            df = df.merge(mp[['slug','fire_us','mp_change_sign']], on=['slug','fire_us'], how='left')
            # bet direction agrees: UP/+1 or DOWN/-1
            dir_num = df['direction'].map({'UP': 1, 'DOWN': -1}).fillna(0).astype(int)
            df = df[df['mp_change_sign'] == dir_num]
        elif og == '__lm_high_stat__':
            df = df.merge(lm[['slug','fire_us','g_lm_high_stat']], on=['slug','fire_us'], how='left')
            df = df[df['g_lm_high_stat'] == 1]
        elif og == '__hawkes_imb_with__':
            # use asof join: get hawkes lambda at fire_us
            asset_lc = df['asset'].iloc[0] if len(df) else None
            hk_a = hk[hk['asset'] == asset_lc].sort_values('ts_us')
            if len(hk_a) == 0:
                print(f"  [WARN] {sid}: no hawkes data")
                df = df.iloc[0:0]
                continue
            df_s = df.sort_values('fire_us')
            df = pd.merge_asof(
                df_s, hk_a[['ts_us','lambda_imbalance']],
                left_on='fire_us', right_on='ts_us', direction='backward', tolerance=10_000_000  # 10s
            )
            df = df.dropna(subset=['lambda_imbalance'])
            df = df[df['lambda_imbalance'].abs() > 0.3]
            # Direction follows sign of lambda_imbalance
            hawkes_dir = np.where(df['lambda_imbalance'] > 0, 'UP', 'DOWN')
            # In oos_fires each slug × offset has BOTH directions; pick the one Hawkes says
            df = df[df['direction'] == hawkes_dir]
        else:
            print(f"  [WARN] Unknown overlay: {og}")

    if df.empty:
        print(f"  [EMPTY post overlays] {sid}")
        continue

    # Direction filter
    if direction_pick == 'UP':
        df = df[df['direction'] == 'UP']
    elif direction_pick == 'DOWN':
        df = df[df['direction'] == 'DOWN']
    elif direction_pick == 'HAWKES':
        pass  # already filtered above
    # BOTH: oos_fires rows have UP and DOWN separately - we keep both as separate fires

    df = df.copy()
    df['sleeve_id'] = sid
    df['base'] = base_name
    df['asset_norm'] = df['asset']
    df['tf_norm'] = df['tf']
    df['offset_lo'] = off[0]
    df['offset_hi'] = off[1]
    df['gate_stack_str'] = '&'.join(gates)

    # Standardize cols
    keep = ['sleeve_id','base','asset_norm','tf_norm','offset_lo','offset_hi','gate_stack_str',
            'slug','fire_us','fire_offset_s','direction','outcome','won','pnl_legacy_usd']
    for k in keep:
        if k not in df.columns:
            df[k] = np.nan
    df_out = df[keep].copy()
    n = len(df_out)
    wr = df_out['won'].mean() * 100 if n else 0
    pnl_sum = df_out['pnl_legacy_usd'].sum()
    pnl_per_tr = df_out['pnl_legacy_usd'].mean() if n else 0
    print(f"  {sid:50s}  n={n:6d}  WR={wr:5.1f}%  $/tr={pnl_per_tr:6.2f}  sum=${pnl_sum:9.0f}")
    records.append(df_out)

print(f"\nConcatenating {len(records)} sleeve frames...")
fired = pd.concat(records, ignore_index=True)
print(f"TOTAL fires across all Tier-1 sleeves: {len(fired):,}")
print(f"UNIQUE (slug, fire_us, direction) combos: {fired[['slug','fire_us','direction']].drop_duplicates().shape[0]:,}")

# Save
out_path = f"{OUT}/fired_by_sleeve.parquet"
fired.to_parquet(out_path, compression='snappy')
print(f"\nSAVED -> {out_path}")

# Summary table
summary = fired.groupby('sleeve_id').agg(
    n=('won','size'),
    wr=('won','mean'),
    sum_pnl=('pnl_legacy_usd','sum'),
    per_tr=('pnl_legacy_usd','mean'),
    asset=('asset_norm','first'),
    tf=('tf_norm','first'),
    offset_lo=('offset_lo','first'),
    offset_hi=('offset_hi','first'),
).reset_index().sort_values('sum_pnl', ascending=False)
# AUDIT-FIX 2026-05-26 (Bug #4): fired_by_sleeve.parquet covers May 21 - May 25
# = 3.96 days, NOT 32 days. Scaling must be 28/3.96 not 28/32.
summary['sum_pnl_28d'] = summary['sum_pnl'] * (28.0 / 3.96)
summary['wr_pct'] = summary['wr'] * 100
summary = summary[['sleeve_id','asset','tf','offset_lo','offset_hi','n','wr_pct','per_tr','sum_pnl','sum_pnl_28d']]
summary.to_csv(f"{OUT}/sleeve_summary.csv", index=False)
print(f"SAVED -> {OUT}/sleeve_summary.csv")
print("\n=== SLEEVE SUMMARY ===")
print(summary.to_string(index=False))
