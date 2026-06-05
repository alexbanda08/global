"""
External causal gates sweep — 2026-05-30
Tests 4 external feature families strictly asof fire_us.
Vectorized implementation for speed.
"""

import sys, warnings, os
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

sys.path.insert(0, 'data/v4/canonical')

ROOT = 'C:/Users/alexandre bandarra/Desktop/global'
os.chdir(ROOT)

# ─────────────────────────────────────────────────────────────────────
# 0. Load fires
# ─────────────────────────────────────────────────────────────────────
fires = pd.read_parquet('strategy_lab/_opt_2026_05_30/_results/fires_resolved_all.parquet')
fires = fires.sort_values('fire_us').reset_index(drop=True)
sleeve_n = fires.groupby('sleeve').size()
eligible = sleeve_n[sleeve_n >= 60].index.tolist()
fires_el = fires[fires['sleeve'].isin(eligible)].copy().reset_index(drop=True)
print(f"Fires: {len(fires_el)} eligible across {len(eligible)} sleeves")
print(f"Fire range: {pd.to_datetime(fires_el['fire_us'].min(), unit='us')} to {pd.to_datetime(fires_el['fire_us'].max(), unit='us')}")

# ─────────────────────────────────────────────────────────────────────
# 1. Binance 1s klines — vectorized asof lookup
# ─────────────────────────────────────────────────────────────────────
print("\nLoading klines_1s...")
kl = pd.read_parquet('data/v4/canonical/klines_1s.parquet',
                     columns=['symbol_id','source','time_period_end_us','price_close'])
# Prefer binance-spot-ws over binance-vision for each timestamp
kl = kl.sort_values(['symbol_id','time_period_end_us','source'])
kl = kl.drop_duplicates(subset=['symbol_id','time_period_end_us'], keep='last')
kl = kl.sort_values(['symbol_id','time_period_end_us']).reset_index(drop=True)
print(f"  klines_1s: {len(kl)} rows")

ASSET_SYMS = {'BTC':'BINANCE_SPOT_BTC_USDT','ETH':'BINANCE_SPOT_ETH_USDT','SOL':'BINANCE_SPOT_SOL_USDT'}

def build_momo_features(fires_df, kl_df):
    """Compute log-return momentum features for all fires at once."""
    out = pd.DataFrame(index=fires_df.index)
    HORIZONS_US = {'30': 30_000_000, '60': 60_000_000, '120': 120_000_000, '300': 300_000_000}

    for asset, sym in ASSET_SYMS.items():
        sub = kl_df[kl_df['symbol_id'] == sym].copy()
        sub = sub.sort_values('time_period_end_us').reset_index(drop=True)
        ts_arr = sub['time_period_end_us'].values
        px_arr = sub['price_close'].values

        fire_mask = fires_df['asset'] == asset
        if not fire_mask.any():
            continue
        fire_idx = fires_df.index[fire_mask]
        fire_us_arr = fires_df.loc[fire_mask, 'fire_us'].values

        # Price at fire_us (causal: bar end <= fire_us)
        idx_now = np.searchsorted(ts_arr, fire_us_arr, side='right') - 1
        px_now = np.where(idx_now >= 0, px_arr[np.clip(idx_now, 0, len(px_arr)-1)], np.nan)
        # Also mask where idx_now < 0
        px_now = np.where(idx_now < 0, np.nan, px_now)

        for hz_name, hz_us in HORIZONS_US.items():
            target_us = fire_us_arr - hz_us
            idx_lag = np.searchsorted(ts_arr, target_us, side='right') - 1
            px_lag = np.where(idx_lag >= 0, px_arr[np.clip(idx_lag, 0, len(px_arr)-1)], np.nan)
            px_lag = np.where(idx_lag < 0, np.nan, px_lag)

            log_ret = np.where(
                (px_lag > 0) & ~np.isnan(px_lag) & ~np.isnan(px_now),
                np.log(px_now / px_lag),
                np.nan
            )
            col = f'ret_{hz_name}'
            if col not in out.columns:
                out[col] = np.nan
            out.loc[fire_idx, col] = log_ret

    # "momentum agrees with direction" = ret * sign(direction) > 0
    direction_sign = np.where(fires_df['direction'] == 'UP', 1.0, -1.0)
    for hz_name in HORIZONS_US:
        col = f'ret_{hz_name}'
        if col not in out.columns:
            out[col] = np.nan
        out[f'ma_{hz_name}'] = out[col] * direction_sign > 0
        # set NaN where ret is NaN
        out.loc[out[col].isna(), f'ma_{hz_name}'] = np.nan

    print(f"  Momo coverage: {(~out['ma_30'].isna()).sum()}/{len(fires_df)}")
    return out

momo = build_momo_features(fires_el, kl)
fires_el = pd.concat([fires_el, momo], axis=1)

# ─────────────────────────────────────────────────────────────────────
# 2. Chainlink basis
# ─────────────────────────────────────────────────────────────────────
print("\nLoading chainlink RTDS...")
from load import load_chainlink_rtds

def build_basis_features(fires_df):
    out = pd.DataFrame(index=fires_df.index)
    out['basis_bps'] = np.nan
    out['basis_agrees'] = np.nan
    out['basis_large'] = np.nan

    for asset, sym in ASSET_SYMS.items():
        # Binance price at fire_us
        sub_kl = kl[kl['symbol_id'] == sym].sort_values('time_period_end_us').reset_index(drop=True)
        kl_ts = sub_kl['time_period_end_us'].values
        kl_px = sub_kl['price_close'].values

        # CL price at fire_us
        cl = load_chainlink_rtds(asset)
        cl = cl.sort_values('timestamp_us').reset_index(drop=True)
        cl_ts = cl['timestamp_us'].values
        cl_px = cl['price_value'].values

        fire_mask = fires_df['asset'] == asset
        if not fire_mask.any():
            continue
        fire_idx = fires_df.index[fire_mask]
        fire_us_arr = fires_df.loc[fire_mask, 'fire_us'].values

        # Causal asof lookup
        idx_kl = np.searchsorted(kl_ts, fire_us_arr, side='right') - 1
        px_bn = np.where(idx_kl >= 0, kl_px[np.clip(idx_kl, 0, len(kl_px)-1)], np.nan)
        px_bn = np.where(idx_kl < 0, np.nan, px_bn)

        idx_cl = np.searchsorted(cl_ts, fire_us_arr, side='right') - 1
        px_cl = np.where(idx_cl >= 0, cl_px[np.clip(idx_cl, 0, len(cl_px)-1)], np.nan)
        px_cl = np.where(idx_cl < 0, np.nan, px_cl)

        basis = np.where(
            ~np.isnan(px_bn) & ~np.isnan(px_cl) & (px_cl > 0),
            (px_bn - px_cl) / px_cl * 1e4,
            np.nan
        )
        out.loc[fire_idx, 'basis_bps'] = basis

        direction_sign = np.where(fires_df.loc[fire_mask, 'direction'] == 'UP', 1.0, -1.0)
        out.loc[fire_idx, 'basis_agrees'] = np.where(~np.isnan(basis), (basis * direction_sign) > 0, np.nan)
        out.loc[fire_idx, 'basis_large'] = np.where(~np.isnan(basis), np.abs(basis) > 3.0, np.nan)

    print(f"  Basis coverage: {(~out['basis_bps'].isna()).sum()}/{len(fires_df)}")
    return out

basis = build_basis_features(fires_el)
fires_el = pd.concat([fires_el, basis], axis=1)

# ─────────────────────────────────────────────────────────────────────
# 3. HL liquidation cascade — vectorized
# ─────────────────────────────────────────────────────────────────────
print("\nLoading HL liquidations...")
from load import load_hyperliquid_liquidations
hl = load_hyperliquid_liquidations()
hl = hl[hl['coin'].isin(['BTC','ETH','SOL'])].copy()
hl['is_long_liq'] = hl['dir'].str.contains('Long', case=False, na=False)
hl['is_short_liq'] = hl['dir'].str.contains('Short', case=False, na=False)
hl['notional'] = hl['price'] * hl['size']
hl['signed_notional'] = np.where(hl['is_long_liq'], -hl['notional'],
                         np.where(hl['is_short_liq'],  hl['notional'], 0.0))
hl = hl.sort_values('time_exchange_us').reset_index(drop=True)
hl_max_us = hl['time_exchange_us'].max()
print(f"  HL liq max: {pd.to_datetime(hl_max_us, unit='us')}")
fire_min_us = fires_el['fire_us'].min()
print(f"  Fires start: {pd.to_datetime(fire_min_us, unit='us')}")
print(f"  HL rows after fire_start: {(hl['time_exchange_us'] >= fire_min_us).sum()}")

def build_hl_features(fires_df, hl_df, lookback_us, col_prefix):
    """Net signed notional in [fire_us - lookback_us, fire_us). Vectorized per asset."""
    col_net = f'{col_prefix}_net'
    col_agrees = f'{col_prefix}_agrees'
    out = pd.DataFrame(index=fires_df.index)
    out[col_net] = np.nan
    out[col_agrees] = np.nan

    for asset in ['BTC','ETH','SOL']:
        fire_mask = fires_df['asset'] == asset
        if not fire_mask.any():
            continue
        hl_sub = hl_df[hl_df['coin'] == asset].copy()
        if len(hl_sub) == 0:
            continue

        fire_idx = fires_df.index[fire_mask]
        fire_us_arr = fires_df.loc[fire_mask, 'fire_us'].values
        direction_arr = fires_df.loc[fire_mask, 'direction'].values

        hl_ts = hl_sub['time_exchange_us'].values
        hl_sn = hl_sub['signed_notional'].values

        # For each fire, sum hl_sn where hl_ts in [fire_us - lookback_us, fire_us)
        # Use searchsorted for window bounds
        lo_arr = fire_us_arr - lookback_us
        # searchsorted for right boundary (exclusive: fire_us)
        r_idx = np.searchsorted(hl_ts, fire_us_arr, side='left')
        l_idx = np.searchsorted(hl_ts, lo_arr, side='left')

        net_vals = np.array([hl_sn[l:r].sum() if r > l else np.nan
                             for l, r in zip(l_idx, r_idx)], dtype=float)
        # If window had no events, mark nan
        has_events = r_idx > l_idx
        net_vals = np.where(has_events, net_vals, np.nan)

        out.loc[fire_idx, col_net] = net_vals

        dir_sign = np.where(direction_arr == 'UP', 1.0, -1.0)
        out.loc[fire_idx, col_agrees] = np.where(~np.isnan(net_vals), (net_vals * dir_sign) > 0, np.nan)

    coverage = (~out[col_net].isna()).sum()
    print(f"  HL {col_prefix} coverage: {coverage}/{len(fires_df)}")
    return out

hl60  = build_hl_features(fires_el, hl, 60_000_000,  'hlc60')
hl300 = build_hl_features(fires_el, hl, 300_000_000, 'hlc300')
fires_el = pd.concat([fires_el, hl60, hl300], axis=1)

# ─────────────────────────────────────────────────────────────────────
# 4. Polymarket CVD — vectorized
# ─────────────────────────────────────────────────────────────────────
print("\nLoading polymarket trades...")
from load import load_trades

def build_cvd_features(fires_df, lookback_us, col_prefix):
    """Net taker $ flow on slug+outcome in [fire_us - lookback, fire_us). Vectorized per asset."""
    col_cvd = f'{col_prefix}_cvd'
    col_align = f'{col_prefix}_align'
    col_contra = f'{col_prefix}_contra'
    out = pd.DataFrame(index=fires_df.index)
    out[col_cvd] = np.nan
    out[col_align] = np.nan
    out[col_contra] = np.nan

    for asset in ['BTC','ETH','SOL']:
        fire_mask = fires_df['asset'] == asset
        if not fire_mask.any():
            continue

        tr = load_trades(asset)
        # direction-match: outcome column matches direction (Up/Down)
        # 'outcome' in trades is 'Up' or 'Down', direction in fires is 'UP'/'DOWN'
        tr['dollar_flow'] = tr['price'] * tr['size'] * tr['side'].map({'buy': 1.0, 'sell': -1.0}).fillna(0.0)
        tr = tr.sort_values('timestamp_us').reset_index(drop=True)

        fire_idx = fires_df.index[fire_mask]
        fire_us_arr = fires_df.loc[fire_mask, 'fire_us'].values
        slug_arr = fires_df.loc[fire_mask, 'slug'].values
        dir_arr = fires_df.loc[fire_mask, 'direction'].values  # 'UP'/'DOWN'

        # For each fire, we need: sum of dollar_flow where
        #   slug == fire_slug AND outcome.lower() == direction.lower() AND ts in window
        # Group trades by slug for fast lookup
        tr_by_slug = {}
        for slug_val, grp in tr.groupby('slug'):
            tr_by_slug[slug_val] = grp.reset_index(drop=True)

        cvd_vals = []
        for fu, sl, di in zip(fire_us_arr, slug_arr, dir_arr):
            if sl not in tr_by_slug:
                cvd_vals.append(np.nan)
                continue
            grp = tr_by_slug[sl]
            lo = fu - lookback_us
            ts = grp['timestamp_us'].values
            mask_t = (ts >= lo) & (ts < fu)
            if not mask_t.any():
                cvd_vals.append(np.nan)
                continue
            sub = grp[mask_t]
            # Filter to matching outcome
            di_match = di.capitalize()  # 'UP'->'Up', 'DOWN'->'Down'
            side_sub = sub[sub['outcome'] == di_match]
            if len(side_sub) == 0:
                cvd_vals.append(np.nan)
                continue
            cvd_vals.append(side_sub['dollar_flow'].sum())

        cvd_arr = np.array(cvd_vals, dtype=float)
        out.loc[fire_idx, col_cvd] = cvd_arr
        out.loc[fire_idx, col_align] = np.where(~np.isnan(cvd_arr), cvd_arr > 0, np.nan)
        out.loc[fire_idx, col_contra] = np.where(~np.isnan(cvd_arr), cvd_arr < 0, np.nan)

    coverage = (~out[col_cvd].isna()).sum()
    print(f"  CVD {col_prefix} coverage: {coverage}/{len(fires_df)}")
    return out

cvd30 = build_cvd_features(fires_el, 30_000_000, 'cvd30')
cvd60 = build_cvd_features(fires_el, 60_000_000, 'cvd60')
fires_el = pd.concat([fires_el, cvd30, cvd60], axis=1)

# ─────────────────────────────────────────────────────────────────────
# 5. Feature coverage report
# ─────────────────────────────────────────────────────────────────────
GATE_COLS = [
    'ma_30', 'ma_60', 'ma_120', 'ma_300',
    'basis_agrees', 'basis_large',
    'hlc60_agrees', 'hlc300_agrees',
    'cvd30_align', 'cvd60_align',
    'cvd30_contra', 'cvd60_contra',
]

print("\nFeature coverage:")
for col in GATE_COLS:
    if col in fires_el.columns:
        nn = fires_el[col].notna().sum()
        print(f"  {col}: {nn}/{len(fires_el)} ({nn/len(fires_el)*100:.1f}%)")
    else:
        print(f"  {col}: MISSING")

# ─────────────────────────────────────────────────────────────────────
# 6. Gate sweep per sleeve
# ─────────────────────────────────────────────────────────────────────
print("\nRunning gate sweep...")
results = []

for sleeve in eligible:
    sub = fires_el[fires_el['sleeve'] == sleeve].copy()
    n_total = len(sub)
    base_mean = sub['pnl_usd'].mean()

    for gate in GATE_COLS:
        if gate not in sub.columns:
            continue
        valid = sub[sub[gate].notna()].copy()
        coverage = len(valid) / n_total
        if coverage < 0.3:
            # Gate covers <30% of fires — mark as low coverage but still test
            pass

        # Only gate on True values
        gated = valid[valid[gate] == True]
        n_gated = len(gated)
        if n_gated < 15:
            continue

        gated_mean = gated['pnl_usd'].mean()
        lift = gated_mean - base_mean

        # Chronological 50/50 split
        sub_sorted = sub.sort_values('fire_us').reset_index(drop=True)
        mid = len(sub_sorted) // 2
        h1 = sub_sorted.iloc[:mid]
        h2 = sub_sorted.iloc[mid:]

        def half_eval(half_df):
            valid_h = half_df[half_df[gate].notna()]
            if len(valid_h) < 5:
                return None, None, None, None
            base_h = valid_h['pnl_usd'].mean()
            gated_h = valid_h[valid_h[gate] == True]
            if len(gated_h) < 5:
                return None, None, None, None
            gm = gated_h['pnl_usd'].mean()
            return base_h, gm, len(gated_h), gm - base_h

        h1_base, h1_gm, h1_n, h1_lift = half_eval(h1)
        h2_base, h2_gm, h2_n, h2_lift = half_eval(h2)

        if h1_lift is None or h2_lift is None:
            continue

        both_pos = (h1_lift > 0) and (h2_lift > 0)

        results.append({
            'sleeve': sleeve,
            'gate': gate,
            'n_total': n_total,
            'base_mean_pnl': base_mean,
            'coverage': coverage,
            'n_gated': n_gated,
            'pct_gated': n_gated / n_total,
            'gated_mean_pnl': gated_mean,
            'lift': lift,
            'h1_n': h1_n, 'h1_base': h1_base, 'h1_gated_mean': h1_gm, 'h1_lift': h1_lift,
            'h2_n': h2_n, 'h2_base': h2_base, 'h2_gated_mean': h2_gm, 'h2_lift': h2_lift,
            'both_halves_positive': both_pos,
        })

results_df = pd.DataFrame(results)
print(f"Gate evaluations: {len(results_df)}")
if len(results_df) > 0:
    passing = results_df[results_df['both_halves_positive'] == True]
    print(f"Gates passing both-half test: {len(passing)}")

# ─────────────────────────────────────────────────────────────────────
# 7. Save
# ─────────────────────────────────────────────────────────────────────
os.makedirs('strategy_lab/_opt_2026_05_30/_results', exist_ok=True)
results_df.to_csv('strategy_lab/_opt_2026_05_30/_results/external_gates.csv', index=False)
fires_el.to_parquet('strategy_lab/_opt_2026_05_30/_results/fires_with_external_features.parquet', index=False)
print("Saved external_gates.csv and fires_with_external_features.parquet")

# ─────────────────────────────────────────────────────────────────────
# 8. Full summary print for report
# ─────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("SLEEVE SUMMARY")
print("="*70)
for sleeve in eligible:
    sub_r = results_df[results_df['sleeve'] == sleeve] if len(results_df) > 0 else pd.DataFrame()
    n = sleeve_n[sleeve]
    bm = fires_el[fires_el['sleeve'] == sleeve]['pnl_usd'].mean()
    print(f"\n{sleeve} | n={n} | base_mean={bm:.4f}")
    if len(sub_r) == 0:
        print("  No gates evaluated")
        continue
    passing_r = sub_r[sub_r['both_halves_positive'] == True].sort_values('lift', ascending=False)
    if len(passing_r) > 0:
        for _, row in passing_r.iterrows():
            print(f"  ✓ {row['gate']:20s} n_gated={int(row['n_gated']):4d} ({row['pct_gated']*100:4.0f}%) "
                  f"gated_mean={row['gated_mean_pnl']:+.4f} lift={row['lift']:+.4f} "
                  f"h1_lift={row['h1_lift']:+.4f} h2_lift={row['h2_lift']:+.4f}")
    else:
        best = sub_r.sort_values('lift', ascending=False).iloc[0]
        print(f"  ✗ best: {best['gate']:20s} lift={best['lift']:+.4f} "
              f"h1={best['h1_lift']:+.4f} h2={best['h2_lift']:+.4f} (fail: one half negative)")

print("\n" + "="*70)
print("GATE PASS RATES")
if len(results_df) > 0:
    summary = results_df.groupby('gate').agg(
        n_evals=('sleeve','count'),
        n_passing=('both_halves_positive', 'sum'),
        mean_lift=('lift','mean'),
    ).sort_values('n_passing', ascending=False)
    print(summary.to_string())
