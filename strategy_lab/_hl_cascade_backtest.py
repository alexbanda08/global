import pandas as pd
import numpy as np
import sys
sys.path.insert(0, 'C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical')
from load import load_hyperliquid_liquidations_full
import warnings
warnings.filterwarnings('ignore')

print("Loading HL liquidations...")
liqs = load_hyperliquid_liquidations_full()
liqs['notional'] = liqs['price'] * liqs['size']

down_dirs = {'Close Long', 'Liquidated Cross Long', 'Liquidated Isolated Long'}
up_dirs = {'Close Short', 'Liquidated Cross Short', 'Liquidated Isolated Short'}


def compute_liq_cascade_vectorized(asset, tf, primary_offset):
    coin = asset.upper()
    fpath = f'C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/dirscan_{asset}_{tf}.parquet'

    df = pd.read_parquet(fpath)
    df = df[df['offset_s'] == primary_offset].copy()
    df = df.sort_values('fire_us').reset_index(drop=True)

    liq_coin = liqs[liqs['coin'] == coin].copy()
    hl_max_us = liq_coin['time_exchange_us'].max()
    hl_min_us = liq_coin['time_exchange_us'].min()

    df = df[(df['fire_us'] <= hl_max_us) & (df['fire_us'] >= hl_min_us + 60_000_000)]

    liq_down = liq_coin[liq_coin['dir'].isin(down_dirs)][['time_exchange_us', 'notional']].sort_values('time_exchange_us').reset_index(drop=True)
    liq_up = liq_coin[liq_coin['dir'].isin(up_dirs)][['time_exchange_us', 'notional']].sort_values('time_exchange_us').reset_index(drop=True)

    fire_arr = df['fire_us'].values
    start_arr = fire_arr - 60_000_000

    down_ts = liq_down['time_exchange_us'].values
    down_notional_arr = liq_down['notional'].values
    down_cumsum = np.concatenate([[0], np.cumsum(down_notional_arr)])
    lo_d = np.searchsorted(down_ts, start_arr, side='left')
    hi_d = np.searchsorted(down_ts, fire_arr, side='left')
    down_window = down_cumsum[hi_d] - down_cumsum[lo_d]

    up_ts = liq_up['time_exchange_us'].values
    up_notional_arr = liq_up['notional'].values
    up_cumsum = np.concatenate([[0], np.cumsum(up_notional_arr)])
    lo_u = np.searchsorted(up_ts, start_arr, side='left')
    hi_u = np.searchsorted(up_ts, fire_arr, side='left')
    up_window = up_cumsum[hi_u] - up_cumsum[lo_u]

    df['down_notional'] = down_window
    df['up_notional'] = up_window
    df['total_notional'] = df['down_notional'] + df['up_notional']
    df['net_notional'] = df['up_notional'] - df['down_notional']
    df['asset_name'] = asset

    return df


def realistic_pnl_row(row, side, asset):
    usd = 25.0
    if side == 'Up':
        vwap = row['u_vwap']
        won = (row['outcome_truth'] == 'Up')
        ok = row['u_ok']
        ask0 = row['u_ask0']
        bid0 = row['u_bid0']
    else:
        vwap = row['d_vwap']
        won = (row['outcome_truth'] == 'Down')
        ok = row['d_ok']
        ask0 = row['d_ask0']
        bid0 = row['d_bid0']

    if not ok or pd.isna(vwap) or vwap <= 0:
        return np.nan

    # Spread filter
    spread = ask0 - bid0
    max_spread = 0.025 if asset == 'sol' else 0.02
    if spread > max_spread:
        return np.nan

    shares = usd / vwap
    fee = shares * 0.07 * vwap * (1 - vwap)

    if won:
        pnl = shares - usd - fee - 0.01
    else:
        pnl = -usd - fee - 0.01

    return pnl


def run_backtest(df_with_features, asset, tf, label):
    df = df_with_features.copy()

    # Only non-zero cascade rows
    df_cascade = df[df['total_notional'] > 0].copy()

    if len(df_cascade) < 10:
        print(f"  Too few non-zero cascade rows ({len(df_cascade)}), skip")
        return None

    # Top-decile threshold among rows with ANY liq activity
    cascade_thresh = df_cascade['total_notional'].quantile(0.90)

    # Large cascade = top decile
    df_large = df_cascade[df_cascade['total_notional'] >= cascade_thresh].copy()

    print(f"{label}: {len(df_large)} cascade rows (top 10% of non-zero, thresh=${cascade_thresh:,.0f})")

    if len(df_large) < 25:
        print(f"  Too few rows after cascade filter, skip")
        return None

    # Signal: direction of net liq pressure
    df_large['signal'] = np.where(df_large['net_notional'] > 0, 'Up', 'Down')

    df_large['entry_vwap'] = np.where(
        df_large['signal'] == 'Up', df_large['u_vwap'], df_large['d_vwap'])
    df_large['entry_ok'] = np.where(
        df_large['signal'] == 'Up', df_large['u_ok'], df_large['d_ok'])

    df_large['implied_side'] = df_large.apply(
        lambda r: r['u_vwap'] / (r['u_vwap'] + r['d_vwap'])
        if r['signal'] == 'Up'
        else r['d_vwap'] / (r['u_vwap'] + r['d_vwap']), axis=1)

    # Try favored range first [0.55, 0.92]
    df_gated = df_large[
        (df_large['entry_vwap'] >= 0.55) &
        (df_large['entry_vwap'] <= 0.92) &
        (df_large['entry_ok'] == True)
    ].copy()

    gate_label = 'favored'
    if len(df_gated) < 25:
        # Try underdog range [0.12, 0.55]
        df_gated = df_large[
            (df_large['entry_vwap'] >= 0.12) &
            (df_large['entry_vwap'] <= 0.55) &
            (df_large['entry_ok'] == True)
        ].copy()
        gate_label = 'underdog'

    print(f"  After vwap gate [{gate_label}]: {len(df_gated)} rows")

    if len(df_gated) < 25:
        print(f"  Not enough rows, skip")
        return None

    # Compute PnL
    df_gated['pnl'] = df_gated.apply(
        lambda r: realistic_pnl_row(r, r['signal'], asset), axis=1)
    df_gated = df_gated.dropna(subset=['pnl'])

    print(f"  After spread filter: {len(df_gated)} rows")

    if len(df_gated) < 25:
        return None

    n = len(df_gated)
    df_gated['won'] = df_gated.apply(
        lambda r: r['outcome_truth'] == r['signal'], axis=1)
    wr = df_gated['won'].mean()
    mean_pnl = df_gated['pnl'].mean()
    implied_wr = df_gated['implied_side'].mean()
    wr_minus_implied = wr - implied_wr

    # Block bootstrap by UTC day
    df_gated['date'] = pd.to_datetime(df_gated['fire_us'], unit='us').dt.date
    days = df_gated['date'].unique()

    np.random.seed(42)
    n_boot = 4000
    boot_means = []
    for _ in range(n_boot):
        sampled_days = np.random.choice(days, size=len(days), replace=True)
        boot_rows = pd.concat([df_gated[df_gated['date'] == d] for d in sampled_days])
        boot_means.append(boot_rows['pnl'].mean())
    ci_lo = np.percentile(boot_means, 2.5)

    g1_pass = mean_pnl > 0
    g2_pass = wr_minus_implied > 0
    g3_pass = ci_lo > 0

    verdict = "PASS" if (g1_pass and g2_pass and g3_pass) else \
              ("WEAK" if (g1_pass and g2_pass) else "FAIL")

    print(f"  n={n}, WR={wr:.3f}, implied={implied_wr:.3f}, WR-implied={wr_minus_implied:+.3f}")
    print(f"  mean_pnl={mean_pnl:+.4f}, CI_lo={ci_lo:+.4f}")
    print(f"  G1={g1_pass}, G2={g2_pass}, G3={g3_pass} => {verdict}")

    return {
        'cell': label,
        'n': n,
        'wr': wr,
        'implied_wr': implied_wr,
        'wr_minus_implied': wr_minus_implied,
        'mean_pnl': mean_pnl,
        'ci_lo': ci_lo,
        'verdict': verdict,
        'cascade_thresh': cascade_thresh,
    }


markets = [
    ('btc', '5m', 60),
    ('btc', '15m', 180),
    ('eth', '5m', 60),
    ('eth', '15m', 180),
    ('sol', '5m', 60),
    ('sol', '15m', 180),
]

all_results = []
for asset, tf, offset in markets:
    label = f"{asset}_{tf}"
    print(f"\n=== {label} ===")
    try:
        df = compute_liq_cascade_vectorized(asset, tf, offset)
        r = run_backtest(df, asset, tf, label)
        if r is not None:
            all_results.append(r)
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

print("\n\n=== SUMMARY ===")
for r in all_results:
    print(f"{r['cell']:12s}: n={r['n']:4d}, WR={r['wr']:.3f}, implied={r['implied_wr']:.3f}, "
          f"WR-impl={r['wr_minus_implied']:+.3f}, pnl={r['mean_pnl']:+.4f}, CI_lo={r['ci_lo']:+.4f} => {r['verdict']}")

# Find best cell
if all_results:
    best = sorted(all_results, key=lambda x: x['ci_lo'], reverse=True)[0]
    print(f"\nBEST CELL: {best['cell']} (CI_lo={best['ci_lo']:+.4f})")

    # Write result CSV
    import csv, os
    out_path = 'C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/wf_strathunt_hl_liq_cascade.csv'
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['cell', 'n', 'wr', 'wr_minus_implied', 'mean_pnl', 'ci_lo', 'verdict'])
        writer.writeheader()
        for r in all_results:
            writer.writerow({k: r[k] for k in ['cell', 'n', 'wr', 'wr_minus_implied', 'mean_pnl', 'ci_lo', 'verdict']})
    print(f"Results written to {out_path}")
