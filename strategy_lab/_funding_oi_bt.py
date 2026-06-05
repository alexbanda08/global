import sys
sys.path.insert(0, 'data/v4/canonical')
import pandas as pd
import numpy as np

ticker = pd.read_parquet('data/v4/canonical/cex_futures_ticker.parquet')

def get_futures_features(asset_upper, fire_us_series):
    sym = 'BITGET_PERP_' + asset_upper + '_USDT'
    ft = ticker[ticker['symbol_id']==sym][['time_exchange_us','funding_rate','open_interest']].copy()
    ft = ft.sort_values('time_exchange_us').reset_index(drop=True)
    ft = ft.dropna(subset=['funding_rate','open_interest'])

    fire_arr = np.asarray(fire_us_series)
    idxs = np.searchsorted(ft['time_exchange_us'].values, fire_arr, side='right') - 1
    valid = idxs >= 0

    results = pd.DataFrame(index=range(len(fire_arr)))
    results['fr'] = np.where(valid, ft['funding_rate'].values[np.maximum(idxs, 0)], np.nan)
    results['oi'] = np.where(valid, ft['open_interest'].values[np.maximum(idxs, 0)], np.nan)

    lookback_us = 300_000_000  # 5 min
    idxs_5m = np.searchsorted(ft['time_exchange_us'].values, fire_arr - lookback_us, side='right') - 1
    valid_5m = idxs_5m >= 0
    oi_5m_ago = np.where(valid_5m, ft['open_interest'].values[np.maximum(idxs_5m, 0)], np.nan)
    results['oi_5m_ago'] = oi_5m_ago
    results['oi_5m_chg_pct'] = (results['oi'] - results['oi_5m_ago']) / results['oi_5m_ago'] * 100
    return results


def realistic_pnl(side, vwap, won, notional=25.0):
    shares = notional / vwap
    fee = shares * 0.07 * vwap * (1 - vwap)
    tx = 0.01
    if won:
        return shares - notional - fee - tx
    else:
        return -notional - fee - tx


def run_cell(asset, tf, signals_df):
    df = signals_df.copy()
    spread_limit = 0.025 if asset == 'sol' else 0.02

    df = df.dropna(subset=['fr', 'oi_5m_chg_pct', 'side'])
    df['vwap_side'] = np.where(df['side']=='Up', df['u_vwap'], df['d_vwap'])
    df['ask0_side'] = np.where(df['side']=='Up', df['u_ask0'], df['d_ask0'])
    df['bid0_side'] = np.where(df['side']=='Up', df['u_bid0'], df['d_bid0'])
    df['ok_side']   = np.where(df['side']=='Up', df['u_ok'],   df['d_ok'])
    df['spread'] = df['ask0_side'] - df['bid0_side']

    df = df[(df['vwap_side'] >= 0.55) & (df['vwap_side'] <= 0.92)]
    df = df[df['spread'] <= spread_limit]
    df = df[df['ok_side'] == True]

    if len(df) < 5:
        return None

    df['won'] = df['outcome_truth'] == df['side']
    df['pnl'] = df.apply(lambda r: realistic_pnl(r['side'], r['vwap_side'], r['won']), axis=1)
    df['u_imp'] = df['u_vwap'] / (df['u_vwap'] + df['d_vwap'])
    df['d_imp'] = 1 - df['u_imp']
    df['implied_side'] = np.where(df['side']=='Up', df['u_imp'], df['d_imp'])

    n = len(df)
    wr = df['won'].mean()
    mean_pnl = df['pnl'].mean()
    implied_wr = df['implied_side'].mean()
    wr_minus_implied = wr - implied_wr

    df['utc_day'] = (df['fire_us'] // 1_000_000 // 86400).astype(int)
    days = df['utc_day'].unique()

    np.random.seed(42)
    n_iter = 4000
    boot_means = []
    for _ in range(n_iter):
        sampled_days = np.random.choice(days, size=len(days), replace=True)
        boot_rows = pd.concat([df[df['utc_day']==d] for d in sampled_days], ignore_index=True)
        boot_means.append(boot_rows['pnl'].mean())
    ci_lo = float(np.percentile(boot_means, 2.5))

    return {
        'asset': asset, 'tf': tf, 'n': n, 'wr': wr,
        'mean_pnl': mean_pnl, 'implied_wr': implied_wr,
        'wr_minus_implied': wr_minus_implied,
        'ci_lo': ci_lo,
        'n_days': len(days)
    }


futures_start_us = 1780179089219000
results = []

for asset in ['btc', 'eth', 'sol']:
    asset_upper = asset.upper()
    for tf in ['5m', '15m']:
        primary_offset = 60 if tf == '5m' else 180
        ds = pd.read_parquet('data/v4/canonical/_results/dirscan_' + asset + '_' + tf + '.parquet')
        ds_p = ds[ds['offset_s'] == primary_offset].copy()
        overlap = ds_p[ds_p['fire_us'] >= futures_start_us].copy().reset_index(drop=True)

        print(asset + '_' + tf + ': overlap_n=' + str(len(overlap)))
        if len(overlap) < 10:
            continue

        feats = get_futures_features(asset_upper, overlap['fire_us'])
        overlap['fr'] = feats['fr'].values
        overlap['oi_5m_chg_pct'] = feats['oi_5m_chg_pct'].values

        fr_vals = overlap['fr'].dropna()
        fr_p75 = fr_vals.quantile(0.75)
        fr_p25 = fr_vals.quantile(0.25)
        oi_chg_std = overlap['oi_5m_chg_pct'].std()

        print('  FR p25=' + str(round(fr_p25,7)) + ' p75=' + str(round(fr_p75,7)) + ' OI_chg_std=' + str(round(oi_chg_std,4)))

        # Strategy A: extreme positive FR -> fade -> BUY DOWN
        sa = overlap[overlap['fr'] > fr_p75].copy()
        sa['side'] = 'Down'
        ra = run_cell(asset, tf, sa)
        if ra:
            ra['strategy'] = 'FR_pos_fade_DOWN'
            results.append(ra)

        # Strategy B: extreme negative FR -> shorts crowded -> BUY UP
        sb = overlap[overlap['fr'] < fr_p25].copy()
        sb['side'] = 'Up'
        rb = run_cell(asset, tf, sb)
        if rb:
            rb['strategy'] = 'FR_neg_fade_UP'
            results.append(rb)

        # Strategy C: OI spike + price up -> momentum UP
        oi_spike = overlap['oi_5m_chg_pct'] > oi_chg_std
        price_up  = overlap['ret_60s_bps'] > 0
        sc = overlap[oi_spike & price_up].copy()
        sc['side'] = 'Up'
        rc = run_cell(asset, tf, sc)
        if rc:
            rc['strategy'] = 'OI_spike_price_up_MOM'
            results.append(rc)

        # Strategy D: OI spike + price down -> momentum DOWN
        price_dn = overlap['ret_60s_bps'] < 0
        sd = overlap[oi_spike & price_dn].copy()
        sd['side'] = 'Down'
        rd = run_cell(asset, tf, sd)
        if rd:
            rd['strategy'] = 'OI_spike_price_dn_MOM'
            results.append(rd)

        # Strategy E: FR high AND OI rising -> crowded longs with fresh buying -> fade DOWN
        fr_high  = overlap['fr'] > fr_p75
        oi_rising = overlap['oi_5m_chg_pct'] > 0
        se = overlap[fr_high & oi_rising].copy()
        se['side'] = 'Down'
        re = run_cell(asset, tf, se)
        if re:
            re['strategy'] = 'FR_hi_OI_rising_DOWN'
            results.append(re)

        # Strategy F: FR low AND OI falling -> short squeeze UP
        fr_low    = overlap['fr'] < fr_p25
        oi_falling = overlap['oi_5m_chg_pct'] < 0
        sf = overlap[fr_low & oi_falling].copy()
        sf['side'] = 'Up'
        rf = run_cell(asset, tf, sf)
        if rf:
            rf['strategy'] = 'FR_lo_OI_fall_UP'
            results.append(rf)

print('\n=== ALL RESULTS (sorted by mean_pnl) ===')
for r in sorted(results, key=lambda x: x['mean_pnl'], reverse=True):
    p1 = r['mean_pnl'] > 0
    p2 = r['wr_minus_implied'] > 0
    p3 = r['ci_lo'] > 0
    ok_n = r['n'] >= 25
    if p1 and p2 and p3 and ok_n:
        verdict = 'PASS'
    elif p1 and p2 and ok_n:
        verdict = 'WEAK'
    else:
        verdict = 'FAIL'
    print(r['asset'] + '_' + r['tf'] + ' ' + r['strategy'] + ': n=' + str(r['n']) +
          ', WR=' + str(round(r['wr'],3)) + ', +impl=' + str(round(r['wr_minus_implied'],3)) +
          ', pnl=' + str(round(r['mean_pnl'],4)) + ', ci_lo=' + str(round(r['ci_lo'],4)) +
          ' [' + verdict + ']')

# Best cell
best = sorted([r for r in results if r['n']>=25], key=lambda x: x['mean_pnl'], reverse=True)
if best:
    b = best[0]
    print('\nBEST: ' + b['asset'] + '_' + b['tf'] + ' ' + b['strategy'])
    print('  n=' + str(b['n']) + ' WR=' + str(round(b['wr'],4)) +
          ' wr_minus_implied=' + str(round(b['wr_minus_implied'],4)) +
          ' mean_pnl=' + str(round(b['mean_pnl'],4)) +
          ' ci_lo=' + str(round(b['ci_lo'],4)))
