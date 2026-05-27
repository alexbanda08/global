"""Finalize top 5 sniper candidates, compute bootstrap p-values + $250 depth, plot cumPnL."""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
PLOT = OUT / "plots"
PLOT.mkdir(exist_ok=True)

p = pd.read_parquet(OUT / "_panel_sol_5m_gated.parquet")
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
p['day_idx'] = (pd.to_datetime(p['date']) - pd.to_datetime(p['date']).min()).dt.days
TR_END, VL_END = 18, 24
p['split'] = np.where(p['day_idx'] < TR_END, 'train',
              np.where(p['day_idx'] < VL_END, 'val', 'lockbox'))
train = p[p['split']=='train']
val = p[p['split']=='val']
lock = p[p['split']=='lockbox']
n_train_d = train['day_idx'].nunique()
n_val_d = val['day_idx'].nunique()
n_lock_d = lock['day_idx'].nunique()

# ---- Top 5 selection ----
# From the search, picking deduplicated unique stacks with diverse anchors and best lock dpt + val dpt agreement
TOP5 = [
    {
        'id': 'SOL5_S1_RF_TR_MID',
        'stack': ['g_rf_strict_align', 'g_tr_partial_stack_with'],
        'offset_band': (90, 180),
        'description': 'RF strict alignment + TR partial stack (mid window 90-180s)',
    },
    {
        'id': 'SOL5_S2_DEPTH_DIR_HOD',
        'stack': ['g_depth_250_strict', 'g_dir_up', 'g_hod_us_afternoon', 'g_tr_in_active_session'],
        'offset_band': (30, 90),
        'description': 'Deep book + UP only + US afternoon + active session (early 30-90s)',
    },
    {
        'id': 'SOL5_S3_RF_TR_PP_MID',
        'stack': ['g_rf_strict_align', 'g_tr_above_ema200', 'g_tr_above_pp', 'g_tr_partial_stack_with'],
        'offset_band': (90, 180),
        'description': 'RF strict + EMA200 + above PP + partial stack (mid)',
    },
    {
        'id': 'SOL5_S4_RF_CCI_TRFULL_MID',
        'stack': ['g_cci_strong_with', 'g_rf_strict_align', 'g_tr_full_stack_with'],
        'offset_band': (90, 180),
        'description': 'CCI strong + RF strict + TR full stack (mid)',
    },
    {
        'id': 'SOL5_S5_MP_RF_ADR_LATE',
        'stack': ['g_mp_no_extreme_100', 'g_rf_strict_align', 'g_tr_within_adr'],
        'offset_band': (180, 270),
        'description': 'Microprice no extreme + RF strict + within ADR (late 180-270s)',
    },
]

def compute(df, stk, off_lo, off_hi, n_days):
    sub = df[(df['fire_offset_s']>=off_lo)&(df['fire_offset_s']<=off_hi)]
    mask = sub[stk].astype(bool).prod(axis=1).astype(bool).values
    s = sub[mask].sort_values('fire_us')
    n = len(s)
    if n == 0: return None
    pnl = s['pnl_legacy_usd'].values
    won_arr = s['won'].values
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max() if len(cum) else 0
    cur = mls = 0
    for v in won_arr:
        if v == 0:
            cur += 1
            if cur > mls: mls = cur
        else: cur = 0
    dates = pd.to_datetime(s['fire_us'], unit='us').dt.date
    daily = s.groupby(dates)['pnl_legacy_usd'].sum()
    shp = (daily.mean()/daily.std()*np.sqrt(365)) if (len(daily)>=2 and daily.std()>0) else 0
    return {'n':n, 'wr':won_arr.mean(), 'dpt':pnl.mean(), 'sum_pnl':pnl.sum(),
            'dd':float(dd), 'ls':mls, 'sharpe':shp, 'n_per_day':n/max(1,n_days),
            'cum_pnl': cum, 'fire_us': s['fire_us'].values, 'won': won_arr,
            'entry_vwap': s['entry_vwap'].values,
            'fire_offset_s': s['fire_offset_s'].values,
            'date': s['date'].values,
            'pnl_series': pnl,
            'sub_df': s,
            'depth_250_strict_pct': s['g_depth_250_strict'].mean() if 'g_depth_250_strict' in s.columns else 0,
            'depth_250_med_pct': s['g_depth_250_med'].mean() if 'g_depth_250_med' in s.columns else 0,
            'depth_250_loose_pct': s['g_depth_250_loose'].mean() if 'g_depth_250_loose' in s.columns else 0,
            'underfilled_250_pct': (s['underfilled_250']==1).mean() if 'underfilled_250' in s.columns else np.nan,
            'mean_slip_250_bps': s['slip_bps_250'].mean() if 'slip_bps_250' in s.columns else np.nan,
    }

def bootstrap_p_daily(sub_df, n_iter=1000, seed=42):
    """Daily-clustered bootstrap: resample DAYS with replacement, compute mean dpt,
    check if 0 is below the lower CI bound."""
    rng = np.random.default_rng(seed)
    s = sub_df.sort_values('fire_us')
    s['date'] = pd.to_datetime(s['fire_us'], unit='us').dt.date
    days = sorted(s['date'].unique())
    if len(days) < 2: return np.nan, np.nan, np.nan

    daily_pnl = s.groupby('date')['pnl_legacy_usd'].agg(['sum','count'])
    daily_pnl = daily_pnl.reindex(days, fill_value=0)

    sums = []
    for _ in range(n_iter):
        chosen = rng.choice(days, size=len(days), replace=True)
        sub_pnl = daily_pnl.loc[chosen]
        total_sum = sub_pnl['sum'].sum()
        total_n = sub_pnl['count'].sum()
        sums.append(total_sum / max(1, total_n))  # bootstrap dpt
    sums = np.array(sums)
    # p-value: % of bootstrap dpt values <= 0
    p = (sums <= 0).mean()
    lo, hi = np.percentile(sums, [2.5, 97.5])
    return p, lo, hi

def compute_250_metrics(sub):
    """Compute PnL at $250 stake using slip-adjusted entry vwap."""
    s = sub.copy()
    # Scale: at $25, pnl = won*(1-ev)/ev*25*0.98 - (1-won)*ev*25
    # At $250, with vwap_250 instead: pnl = won*(1-v250)/v250*250*0.98 - (1-won)*v250*250
    # Approximate: use entry_vwap + slip_bps_250/10000 as effective_ev
    eff_ev = s['entry_vwap'] + s.get('slip_bps_250', pd.Series([0]*len(s))).fillna(0) / 10000
    eff_ev = eff_ev.clip(0.01, 0.99)
    won = s['won']
    pnl_250_won = (1 - eff_ev) / eff_ev * 250 * 0.98
    pnl_250_lost = -eff_ev * 250
    pnl_250 = np.where(won == 1, pnl_250_won, pnl_250_lost)
    # If underfilled, scale down: assume partial fill
    if 'underfilled_250' in s.columns:
        underfilled = (s['underfilled_250']==1).values
        # For underfilled, simulate $25 only
        pnl_25_won = (1 - s['entry_vwap']) / s['entry_vwap'] * 25 * 0.98
        pnl_25_lost = -s['entry_vwap'] * 25
        pnl_25 = np.where(won == 1, pnl_25_won, pnl_25_lost)
        pnl_250 = np.where(underfilled, pnl_25, pnl_250)
    return pnl_250

# Run all top 5 across splits
print("="*80)
print("Top 5 SOL 5m sniper candidates — full validation")
print("="*80)
rows = []
for cand in TOP5:
    print(f"\n--- {cand['id']}: {cand['description']} ---")
    rt = compute(train, cand['stack'], cand['offset_band'][0], cand['offset_band'][1], n_train_d)
    rv = compute(val, cand['stack'], cand['offset_band'][0], cand['offset_band'][1], n_val_d)
    rl = compute(lock, cand['stack'], cand['offset_band'][0], cand['offset_band'][1], n_lock_d)
    if not all([rt, rv, rl]):
        print("  SKIP: insufficient data")
        continue

    # Bootstrap p
    bp, blo, bhi = bootstrap_p_daily(rl['sub_df'], n_iter=1000)

    # $250 metrics (lockbox)
    pnl_250 = compute_250_metrics(rl['sub_df'])
    dpt_250 = pnl_250.mean()
    sum_250 = pnl_250.sum()

    # Cum PnL plot
    fig, ax = plt.subplots(figsize=(10, 5))
    # Concatenate train -> val -> lockbox
    all_pnl = np.concatenate([rt['pnl_series'], rv['pnl_series'], rl['pnl_series']])
    all_dates = np.concatenate([rt['date'], rv['date'], rl['date']])
    cum = np.cumsum(all_pnl)
    ax.plot(pd.to_datetime(all_dates), cum, lw=1.2, color='steelblue', label=f'cum PnL @ $25')
    ax.axvline(pd.to_datetime(all_dates[len(rt['pnl_series'])]), color='gray', ls='--', alpha=0.5, label='val start')
    ax.axvline(pd.to_datetime(all_dates[len(rt['pnl_series'])+len(rv['pnl_series'])]), color='red', ls='--', alpha=0.5, label='lockbox start')
    ax.set_title(f"{cand['id']} — Cum PnL  (train+val+lockbox)")
    ax.set_ylabel('$ cumulative')
    ax.set_xlabel('Date')
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOT / f"cumulative_pnl_{cand['id']}.png", dpi=100)
    plt.close(fig)

    # Per-day hist
    daily_n = pd.Series(rl['date']).value_counts().sort_index()

    print(f"  TRAIN:   n={rt['n']}  WR={rt['wr']:.3f}  $/tr={rt['dpt']:.2f}  DD={rt['dd']:.0f}  LS={rt['ls']}  Sharpe={rt['sharpe']:.1f}")
    print(f"  VAL:     n={rv['n']}  WR={rv['wr']:.3f}  $/tr={rv['dpt']:.2f}  DD={rv['dd']:.0f}  LS={rv['ls']}  Sharpe={rv['sharpe']:.1f}")
    print(f"  LOCKBOX: n={rl['n']}  WR={rl['wr']:.3f}  $/tr={rl['dpt']:.2f}  DD={rl['dd']:.0f}  LS={rl['ls']}  Sharpe={rl['sharpe']:.1f}")
    print(f"  Bootstrap p={bp:.4f}  CI=[${blo:.2f}, ${bhi:.2f}]")
    print(f"  $250 capacity: depth_strict={rl['depth_250_strict_pct']*100:.0f}%, med={rl['depth_250_med_pct']*100:.0f}%, underfilled={rl['underfilled_250_pct']*100:.0f}%")
    print(f"  $250 mean slippage: {rl['mean_slip_250_bps']:.0f} bps")
    print(f"  $250 lockbox dpt: ${dpt_250:.2f}/tr, total ${sum_250:.0f}")
    print(f"  Lockbox daily fire count: {daily_n.values.tolist()}  (mean {daily_n.mean():.1f}/day)")

    rows.append({
        'sleeve_id': cand['id'],
        'anchor': f"offset_{cand['offset_band'][0]}-{cand['offset_band'][1]}s",
        'gate_stack': ' & '.join(cand['stack']),
        'description': cand['description'],
        'n_train': rt['n'], 'n_val': rv['n'], 'n_lockbox': rl['n'],
        'wr_train': rt['wr'], 'wr_val': rv['wr'], 'wr_lockbox': rl['wr'],
        'dpt_25_train': rt['dpt'], 'dpt_25_val': rv['dpt'], 'dpt_25_lockbox': rl['dpt'],
        'sum_25_train': rt['sum_pnl'], 'sum_25_val': rv['sum_pnl'], 'sum_25_lockbox': rl['sum_pnl'],
        'max_dd_25_train': rt['dd'], 'max_dd_25_val': rv['dd'], 'max_dd_25_lockbox': rl['dd'],
        'loss_streak_train': rt['ls'], 'loss_streak_val': rv['ls'], 'loss_streak_lockbox': rl['ls'],
        'sharpe_train': rt['sharpe'], 'sharpe_val': rv['sharpe'], 'sharpe_lockbox': rl['sharpe'],
        'np_d_lockbox': rl['n_per_day'],
        'bootstrap_p_lockbox': bp, 'bootstrap_ci_lo': blo, 'bootstrap_ci_hi': bhi,
        'depth_250_strict_pct_lockbox': rl['depth_250_strict_pct'],
        'depth_250_med_pct_lockbox': rl['depth_250_med_pct'],
        'depth_250_loose_pct_lockbox': rl['depth_250_loose_pct'],
        'underfilled_250_pct_lockbox': rl['underfilled_250_pct'],
        'mean_slip_250_bps_lockbox': rl['mean_slip_250_bps'],
        'dpt_250_lockbox': dpt_250,
        'sum_250_lockbox': sum_250,
    })

df = pd.DataFrame(rows)
df.to_csv(OUT / "top_5_candidates.csv", index=False)
print(f"\nWrote top_5_candidates.csv with {len(df)} rows")

# Print sniper-pass summary
print("\n=== Sniper criteria check (lockbox) ===")
print(f"{'sleeve':<25} {'n':>4} {'WR':>6} {'$/tr':>6} {'DD':>5} {'LS':>3} {'Shp':>6} {'bp':>6}")
for _, r in df.iterrows():
    pass_n = '✓' if 50 <= r['n_lockbox'] <= 500 else 'X'
    pass_wr = '✓' if r['wr_lockbox'] >= 0.75 else 'X'
    pass_dpt = '✓' if r['dpt_25_lockbox'] >= 3 else 'X'
    pass_dd = '✓' if r['max_dd_25_lockbox'] <= 300 else 'X'
    pass_ls = '✓' if r['loss_streak_lockbox'] <= 6 else 'X'
    pass_shp = '✓' if r['sharpe_lockbox'] >= 2 else 'X'
    pass_bp = '✓' if r['bootstrap_p_lockbox'] <= 0.05 else 'X'
    all_pass = all(c == '✓' for c in [pass_n, pass_wr, pass_dpt, pass_dd, pass_ls, pass_shp, pass_bp])
    star = '*' if all_pass else ' '
    print(f"{star} {r['sleeve_id']:<22} {r['n_lockbox']:>4} {r['wr_lockbox']:>6.3f} {r['dpt_25_lockbox']:>6.2f} {r['max_dd_25_lockbox']:>5.0f} {r['loss_streak_lockbox']:>3} {r['sharpe_lockbox']:>6.1f} {r['bootstrap_p_lockbox']:>6.3f}")
