"""Pick top 5 distinct V6 candidates + Kelly sizing + timing analysis + cumulative PnL plots.

Kelly sizing uses Option B (empirical WR per # extra gates passing).
Base stack = top 3 atoms; the 2 extra are "bonus" atoms used for conviction.
Bucket by # bonus atoms passing → empirical p per bucket → Kelly-0.25 → stake.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v6")
PLOTS = OUT / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v6.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[18]
val_end = dates_sorted[24]
train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()


def apply_stack(df, atoms):
    if len(atoms) == 0: return df
    mask = np.ones(len(df), dtype=bool)
    for a in atoms:
        mask &= (df[a].values == 1)
    return df[mask].sort_values('fire_us').reset_index(drop=True)


def metrics(sub):
    if len(sub) == 0:
        return dict(n=0, wr=0, dpt=0, dd=0, ls=0, sum_=0, sharpe=0)
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls = 0; cur=0
    for v in pnl:
        if v < 0: cur += 1; ls = max(ls, cur)
        else: cur = 0
    daily = sub.groupby('date')['pnl_legacy_usd'].sum() if 'date' in sub.columns else None
    sharpe = (daily.mean()/daily.std()*np.sqrt(252)) if daily is not None and len(daily) > 1 and daily.std() > 0 else 0
    return dict(n=len(sub), wr=float(sub.won.mean()), dpt=float(pnl.mean()),
                dd=dd, ls=ls, sum_=float(pnl.sum()), sharpe=sharpe)


def kelly_stake(p_win, vwap, kelly_frac=0.25, bankroll=1000.0, stake_min=5.0, stake_max=25.0):
    """Kelly-fractional stake given win prob, entry vwap. Bankroll = notional sizing universe."""
    if vwap <= 0 or vwap >= 1:
        return stake_min
    b = (1 - vwap) * 0.98 / vwap  # profit-per-dollar-at-risk on win (legacy 2% fee)
    if b <= 0: return stake_min
    f_full = (p_win * b - (1 - p_win)) / b
    if f_full <= 0: return 0  # don't bet
    stake = kelly_frac * f_full * bankroll
    return float(max(stake_min, min(stake_max, stake)))


# Load bootstrap results
boot = pd.read_csv(OUT / "_bootstrap_results.csv")
boot_pass = boot[
    (boot['n_l'] >= 30) & (boot['wr_l'] >= 0.65) &
    (boot['dpt_l'] >= 4.0) & (boot['dd_l'] <= 500) &
    (boot['ls_l'] <= 14) & (boot['bootstrap_p_l'] <= 0.05)
].sort_values('score_l', ascending=False).reset_index(drop=True)


def jaccard(a, b):
    sa, sb = set(a.split('|')), set(b.split('|'))
    return len(sa & sb) / len(sa | sb)


picks = []
for _, r in boot_pass.iterrows():
    if len(picks) == 0:
        picks.append(r); continue
    sim_max = max(jaccard(r['stack'], pr['stack']) for pr in picks)
    if sim_max < 0.65:
        picks.append(r)
    if len(picks) >= 5: break
if len(picks) < 5:
    print(f"Only {len(picks)} distinct stacks; padding from top by score")
    seen = set(p['stack'] for p in picks)
    for _, r in boot_pass.iterrows():
        if r['stack'] in seen: continue
        picks.append(r); seen.add(r['stack'])
        if len(picks) >= 5: break


print(f"\nTop {len(picks)} distinct V6 sleeves:")
for i, r in enumerate(picks, 1):
    print(f"  S{i}: {r['stack']}  | dir={r['dir']}  | n_l={r['n_l']} wr_l={r['wr_l']:.3f} dpt_l={r['dpt_l']:.2f} dd_l={r['dd_l']:.0f} ls_l={r['ls_l']} p={r['bootstrap_p_l']:.3f}")


# Bonus atom pool for conviction scoring (Option B)
BONUS_ATOMS = [
    'g_offset_le_60', 'g_offset_60_only', 'g_offset_30_only',
    'g_mp_wt_skew_with', 'g_mp_skew_change_with',
    'g_hod_european_morning', 'g_hod_us_morning_v6',
    'g_compression_tight', 'g_compression_extra_tight',
    'g_rf_full_align', 'g_rf_fresh', 'g_rf_strong',
    'g_bet_imb_strong', 'g_bet_imb_dominant',
    'g_cvd_with', 'mgf_g_markov_with', 'mgf_g_mp_no_extreme',
    'mgf_g_imb5_strong_with', 'g_within_dev',
    'mgf_g_hawkes_imbalance_with',
]
BONUS_ATOMS = [a for a in BONUS_ATOMS if a in p.columns]
print(f"\nBonus atom pool for Kelly conviction: {len(BONUS_ATOMS)}")

top5_rows = []
all_kelly_summary = []
for i, r in enumerate(picks, 1):
    atoms = r['stack'].split('|')
    sub_tr = apply_stack(train, atoms)
    sub_v  = apply_stack(val, atoms)
    sub_l  = apply_stack(lock, atoms)
    m_tr, m_v, m_l = metrics(sub_tr), metrics(sub_v), metrics(sub_l)

    sleeve_id = f"SOL5_V6_S{i}"
    print(f"\n{sleeve_id}: {r['stack']}")

    # Option B: bonus-atom conviction score on TRAIN, then apply to LOCKBOX
    # Compute # bonus atoms passing per fire
    bonus_in_stack = [b for b in BONUS_ATOMS if b not in atoms]  # don't double-count
    if len(bonus_in_stack) == 0:
        # Fall back to single bucket
        p_emp_buckets = {0: m_l['wr']}
    else:
        sub_tr_b = sub_tr.copy()
        sub_tr_b['n_bonus_pass'] = sub_tr_b[bonus_in_stack].sum(axis=1)
        # Bin into 4 buckets
        try:
            sub_tr_b['conv_bucket'] = pd.qcut(sub_tr_b['n_bonus_pass'], q=4, duplicates='drop', labels=False)
        except Exception:
            sub_tr_b['conv_bucket'] = pd.cut(sub_tr_b['n_bonus_pass'], bins=4, labels=False)
        # Empirical WR per bucket on train
        p_emp_buckets = sub_tr_b.groupby('conv_bucket')['won'].mean().to_dict()
        # Cap to [0.5, 0.95] to avoid extreme overconfidence
        p_emp_buckets = {k: max(0.5, min(0.95, v)) for k, v in p_emp_buckets.items()}
        print(f"  conviction p by bucket: {p_emp_buckets}")
        # Apply to lockbox
        sub_l['n_bonus_pass'] = sub_l[bonus_in_stack].sum(axis=1)
        # Use train quantile edges
        edges = sub_tr_b['n_bonus_pass'].quantile([0, 0.25, 0.5, 0.75, 1.0]).values
        # Ensure unique
        edges = np.unique(edges)
        sub_l['conv_bucket'] = pd.cut(sub_l['n_bonus_pass'], bins=edges,
                                       labels=False, include_lowest=True)

    # Kelly stake per fire
    stakes_kelly = []
    stakes_linear = []
    p_used = []
    for _, row in sub_l.iterrows():
        if isinstance(p_emp_buckets, dict) and 'conv_bucket' in row.index:
            cb = row.get('conv_bucket')
            if pd.isna(cb): cb = 0
            p_win = p_emp_buckets.get(int(cb), m_l['wr'])
        else:
            p_win = m_l['wr']
        p_used.append(p_win)
        s_kelly = kelly_stake(p_win, row['entry_vwap'], kelly_frac=0.25, bankroll=200.0)
        # Linear (simpler fallback): scale linearly by p_win in [0.5,0.95] → stake in [5,25]
        s_linear = 5 + (25 - 5) * max(0, (p_win - 0.5) / 0.45)
        s_linear = max(5, min(25, s_linear))
        stakes_kelly.append(s_kelly)
        stakes_linear.append(s_linear)

    sub_l = sub_l.assign(
        stake_kelly=stakes_kelly, stake_linear=stakes_linear, p_win_used=p_used,
        pnl_kelly_usd=(np.array(stakes_kelly)/25.0) * sub_l['pnl_legacy_usd'].values,
        pnl_linear_usd=(np.array(stakes_linear)/25.0) * sub_l['pnl_legacy_usd'].values,
    )

    sum_const = float(sub_l['pnl_legacy_usd'].sum())
    sum_kelly = float(sub_l['pnl_kelly_usd'].sum())
    sum_linear = float(sub_l['pnl_linear_usd'].sum())
    mean_stake_k = float(sub_l['stake_kelly'].mean())
    mean_stake_l = float(sub_l['stake_linear'].mean())

    print(f"  const $25     sum=${sum_const:.2f}  (n={m_l['n']}, $/tr=${m_l['dpt']:.2f})")
    print(f"  Kelly-0.25    sum=${sum_kelly:.2f}  (mean stake=${mean_stake_k:.2f}, range=[${sub_l['stake_kelly'].min():.2f}, ${sub_l['stake_kelly'].max():.2f}])")
    print(f"  linear conv   sum=${sum_linear:.2f}  (mean stake=${mean_stake_l:.2f}, range=[${sub_l['stake_linear'].min():.2f}, ${sub_l['stake_linear'].max():.2f}])")
    print(f"  offset dist:  {sub_l.fire_offset_s.value_counts().sort_index().to_dict()}")

    top5_rows.append({
        'sleeve_id': sleeve_id, 'gate_stack': r['stack'],
        'dir_constraint': r['dir'], 'source': r['source'],
        'conviction_method': 'B (empirical WR per # bonus atoms passing)' if len(bonus_in_stack) > 0 else 'fixed',
        'n_train': m_tr['n'], 'n_val': m_v['n'], 'n_lockbox': m_l['n'],
        'wr_train': m_tr['wr'], 'wr_val': m_v['wr'], 'wr_lockbox': m_l['wr'],
        'dpt_train': m_tr['dpt'], 'dpt_val': m_v['dpt'],
        'dpt_25_lockbox': m_l['dpt'], 'sum_25_28d_const': sum_const,
        'sum_25_28d_kelly': sum_kelly, 'sum_25_28d_linear': sum_linear,
        'max_dd_25': m_l['dd'], 'loss_streak': m_l['ls'], 'sharpe': m_l['sharpe'],
        'bootstrap_p_lockbox': r['bootstrap_p_l'],
        'kelly_stake_mean': mean_stake_k,
        'linear_stake_mean': mean_stake_l,
        'offset_dist': str(sub_l.fire_offset_s.value_counts().sort_index().to_dict()),
    })

    # Kelly stake table per sleeve — bucket by conv_bucket then summarize
    if 'conv_bucket' in sub_l.columns:
        bucket_tbl = sub_l.groupby('conv_bucket', observed=True).agg(
            n=('won','size'), wr=('won','mean'),
            mean_stake_kelly=('stake_kelly','mean'),
            mean_stake_linear=('stake_linear','mean'),
            mean_p_win_used=('p_win_used','mean'),
            sum_const25=('pnl_legacy_usd','sum'),
            sum_kelly=('pnl_kelly_usd','sum'),
            sum_linear=('pnl_linear_usd','sum'),
        ).reset_index()
        bucket_tbl.to_csv(OUT / f"kelly_stake_table_{sleeve_id}.csv", index=False)

    # Cumulative PnL plot
    sub_l_sorted = sub_l.sort_values('fire_us').reset_index(drop=True)
    sub_l_sorted['cum_const'] = sub_l_sorted['pnl_legacy_usd'].cumsum()
    sub_l_sorted['cum_kelly'] = sub_l_sorted['pnl_kelly_usd'].cumsum()
    sub_l_sorted['cum_linear'] = sub_l_sorted['pnl_linear_usd'].cumsum()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(range(len(sub_l_sorted)), sub_l_sorted['cum_const'], label=f'Const $25 (sum=${sum_const:.0f})', color='steelblue', linewidth=2)
    ax.plot(range(len(sub_l_sorted)), sub_l_sorted['cum_kelly'], label=f'Kelly 0.25 (sum=${sum_kelly:.0f}, mean ${mean_stake_k:.1f})', color='darkorange', linewidth=2)
    ax.plot(range(len(sub_l_sorted)), sub_l_sorted['cum_linear'], label=f'Linear conv (sum=${sum_linear:.0f}, mean ${mean_stake_l:.1f})', color='forestgreen', linewidth=1.5, linestyle='--')
    ax.axhline(0, color='gray', linewidth=0.5, linestyle='--')
    ax.set_xlabel(f'fire # (chronological, n={len(sub_l_sorted)})')
    ax.set_ylabel('Cumulative PnL ($)')
    ax.set_title(f'{sleeve_id}  | WR={m_l["wr"]:.3f}  DD=${m_l["dd"]:.0f}  LS={m_l["ls"]}\n{r["stack"]}', fontsize=9)
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS / f"cumulative_pnl_kelly_vs_const_{sleeve_id}.png", dpi=100)
    plt.close(fig)
    all_kelly_summary.append({'sleeve_id': sleeve_id,
                              'sum_const': sum_const, 'sum_kelly': sum_kelly, 'sum_linear': sum_linear,
                              'uplift_kelly_pct': (sum_kelly-sum_const)/abs(sum_const)*100 if sum_const else 0,
                              'uplift_linear_pct': (sum_linear-sum_const)/abs(sum_const)*100 if sum_const else 0,
                              'mean_stake_kelly': mean_stake_k, 'mean_stake_linear': mean_stake_l})


top5_df = pd.DataFrame(top5_rows)
top5_df.to_csv(OUT / "top_5_candidates_v6.csv", index=False)
print(f"\nWrote top_5_candidates_v6.csv ({len(top5_df)} rows)")

print(f"\n=== Kelly summary ===")
print(pd.DataFrame(all_kelly_summary).to_string(index=False))


# === Timing analysis on top sleeve ===
print("\n=== Timing analysis on top sleeve (S1) ===")
top_atoms = picks[0]['stack'].split('|')
all_sub = apply_stack(p, top_atoms)
all_sub['date'] = pd.to_datetime(all_sub['fire_us'], unit='us').dt.date
for ofs_band, lo, hi in [('pre-window/early (30-60)', 30, 60), ('mid (90-150)', 90, 150), ('late (180-270)', 180, 270)]:
    s = all_sub[(all_sub.fire_offset_s >= lo) & (all_sub.fire_offset_s <= hi)]
    if len(s) > 0:
        sl = s[s['date'] >= val_end]
        m = metrics(sl)
        print(f"  {ofs_band}: lockbox n={m['n']} wr={m['wr']:.3f} dpt=${m['dpt']:.2f} sum=${m['sum_']:.2f}")

print(f"\nElapsed: {time.time()-t0:.1f}s")
