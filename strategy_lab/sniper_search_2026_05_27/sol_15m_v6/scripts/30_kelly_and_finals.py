"""V6 SOL 15m: Kelly sizing per top sleeve + composable conviction bucket + final report.

Top candidates from _v6_full_bootstrap.csv:
- C1: g_hod_european_morning + g_off_60_240 + g_rf_with + g_tr_stack_with
- C2: g_hod_european_morning + g_off_60 + g_tr_stack_with + g_tr_within_adr  (early fire, small n)
- C3: g_hod_european_morning + g_rf_with + g_tight_ribbon + g_tr_stack_with (larger n)
- C4: g_bb_pos_with + g_hod_european_morning + g_rf_with + g_tr_stack_with
- C5: g_tr_stack_with + g_tr_within_adr + g_vol_high (no HoD; smaller n but clean)

Kelly framework (V6 brief §1):
- b = (1 - vwap) * 0.98 / vwap
- f_full = (p * b - (1-p)) / b
- f_kelly_25 = max(0, 0.25 * f_full)
- stake_kelly = clip(f_kelly_25 * STAKE_MAX, STAKE_MIN, STAKE_MAX)

Use Option B conviction (empirical WR per bucket).
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_15m_v6")
PLOTS = OUT / "plots"
PLOTS.mkdir(exist_ok=True)
t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

STAKE_MIN = 5.0
STAKE_MAX = 25.0


def kelly_stake(vwap, p):
    """V6 brief §1 EXACT: stake_kelly = clip(f_kelly_25 * STAKE_MAX, STAKE_MIN, STAKE_MAX).

    If Kelly fraction is 0 or negative (no edge) → SKIP (stake=0, don't fire).
    If Kelly positive but tiny → clip UP to STAKE_MIN.
    Otherwise → scale to bounds.
    """
    if vwap <= 0 or vwap >= 1: return 0.0
    b = (1.0 - vwap) * 0.98 / vwap
    f_full = (p * b - (1 - p)) / b
    if f_full <= 0:
        return 0.0  # no edge → skip fire
    f_kelly_25 = 0.25 * f_full
    stake = np.clip(f_kelly_25 * STAKE_MAX, STAKE_MIN, STAKE_MAX)
    return float(stake)


def pnl_at_stake(vwap, won, stake):
    """Legacy 2%-on-profit fee model. Returns dollar PnL at given stake."""
    if stake <= 0: return 0.0
    if vwap <= 0 or vwap >= 1: return 0.0
    shares = stake / vwap
    if won:
        return (1.0 - vwap) * shares * 0.98
    return -stake


def eval_kelly_sleeve(df, atoms, kelly_p_lookup):
    """Apply Kelly per-fire. Returns dict of metrics."""
    mask = np.ones(len(df), dtype=bool)
    for a in atoms:
        col = df[a].values
        if col.dtype == float:
            col = np.where(np.isnan(col), 0, col)
        mask &= (col == 1)
    sub = df[mask].copy().sort_values('fire_us').reset_index(drop=True)
    if len(sub) == 0:
        return None
    # Estimate p per fire using kelly_p_lookup (here: rolling expanding WR; or just use overall WR)
    # Option B: empirical WR per #-gates-passing. We have a single fixed set of atoms
    # so there's no conviction bucketing within the stack itself. Use overall WR as p.
    # Alternative: use overall WR over preceding window (expanding).
    overall_wr = float(sub['won'].mean())
    log_pnl_const, log_pnl_kelly = [], []
    stakes = []
    for _, r in sub.iterrows():
        vwap = float(r['entry_vwap'])
        won = bool(r['won'])
        # Constant $25
        pnl_const = pnl_at_stake(vwap, won, 25.0)
        # Kelly stake
        stake_k = kelly_stake(vwap, overall_wr)
        pnl_k = pnl_at_stake(vwap, won, stake_k)
        log_pnl_const.append(pnl_const)
        log_pnl_kelly.append(pnl_k)
        stakes.append(stake_k)
    arr_const = np.array(log_pnl_const)
    arr_kelly = np.array(log_pnl_kelly)
    stakes = np.array(stakes)
    return {
        'sub': sub, 'pnl_const': arr_const, 'pnl_kelly': arr_kelly,
        'stakes': stakes, 'overall_wr': overall_wr,
    }


def metrics(pnl_arr):
    if len(pnl_arr) == 0:
        return dict(n=0, sum=0, mean=0, dd=0, ls=0)
    cumsum = np.cumsum(pnl_arr)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0
    cur = 0
    for v in pnl_arr:
        if v < 0:
            cur += 1
            ls_max = max(ls_max, cur)
        else:
            cur = 0
    return dict(n=len(pnl_arr), sum=float(pnl_arr.sum()), mean=float(pnl_arr.mean()),
                dd=dd, ls=ls_max)


# Load universe
p = pd.read_parquet(OUT / "sol_15m_v6_universe.parquet")
p = p[p['entry_vwap'] < 0.998].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[22]
val_end = dates_sorted[29]
lock_start = val_end

log(f"Universe: {len(p):,} fires")

# Top candidates
TOPS = [
    {'id':'C1_EARLYWIN_HOD_EU_OFF60_240', 'stack':['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']},
    {'id':'C2_OFF60_RFA_HOD', 'stack':['g_hod_european_morning','g_off_60','g_tr_stack_with','g_tr_within_adr']},
    {'id':'C3_HOD_TIGHTRIB', 'stack':['g_hod_european_morning','g_rf_with','g_tight_ribbon','g_tr_stack_with']},
    {'id':'C4_HOD_BBPOS', 'stack':['g_bb_pos_with','g_hod_european_morning','g_rf_with','g_tr_stack_with']},
    {'id':'C5_VOL_ADR_TS', 'stack':['g_tr_stack_with','g_tr_within_adr','g_vol_high']},
]

reports = []
for c in TOPS:
    log(f"=== {c['id']} ===")
    # Train-window estimate of WR for Kelly p
    train_df = p[p['date'] < train_end]
    train_res = eval_kelly_sleeve(train_df, c['stack'], None)
    if train_res is None:
        log(f"  no fires in train window; skip")
        continue
    p_train = train_res['overall_wr']
    log(f"  train WR (used as Kelly p): {p_train:.3f}")

    # Validate on val, lock, full
    val_df = p[(p['date'] >= train_end) & (p['date'] < val_end)]
    lock_df = p[p['date'] >= lock_start]

    # We use p_train for Kelly stake at EVERY fire (no per-fire prediction)
    def eval_kelly_with_p(df, atoms, p_kelly):
        mask = np.ones(len(df), dtype=bool)
        for a in atoms:
            col = df[a].values
            if col.dtype == float:
                col = np.where(np.isnan(col), 0, col)
            mask &= (col == 1)
        sub = df[mask].copy().sort_values('fire_us').reset_index(drop=True)
        if len(sub) == 0:
            return None
        pnl_c, pnl_k, stakes = [], [], []
        for _, r in sub.iterrows():
            vwap = float(r['entry_vwap'])
            won = bool(r['won'])
            pnl_c.append(pnl_at_stake(vwap, won, 25.0))
            stake_k = kelly_stake(vwap, p_kelly)
            pnl_k.append(pnl_at_stake(vwap, won, stake_k))
            stakes.append(stake_k)
        return {'sub': sub,
                'pnl_const': np.array(pnl_c), 'pnl_kelly': np.array(pnl_k),
                'stakes': np.array(stakes)}

    tr = eval_kelly_with_p(train_df, c['stack'], p_train)
    vl = eval_kelly_with_p(val_df, c['stack'], p_train)
    lk = eval_kelly_with_p(lock_df, c['stack'], p_train)
    fu = eval_kelly_with_p(p, c['stack'], p_train)

    # Metrics
    m_tr_c = metrics(tr['pnl_const']) if tr else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_tr_k = metrics(tr['pnl_kelly']) if tr else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_vl_c = metrics(vl['pnl_const']) if vl else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_vl_k = metrics(vl['pnl_kelly']) if vl else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_lk_c = metrics(lk['pnl_const']) if lk else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_lk_k = metrics(lk['pnl_kelly']) if lk else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_fu_c = metrics(fu['pnl_const']) if fu else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    m_fu_k = metrics(fu['pnl_kelly']) if fu else dict(n=0,sum=0,mean=0,dd=0,ls=0)
    wr_tr = float(tr['sub']['won'].mean()) if tr is not None else 0
    wr_vl = float(vl['sub']['won'].mean()) if vl is not None else 0
    wr_lk = float(lk['sub']['won'].mean()) if lk is not None else 0
    wr_fu = float(fu['sub']['won'].mean()) if fu is not None else 0

    log(f"  TRAIN     n={m_tr_c['n']:4d} WR={wr_tr:.3f} const dpt=${m_tr_c['mean']:.2f} sum=${m_tr_c['sum']:.0f} | kelly dpt=${m_tr_k['mean']:.2f} sum=${m_tr_k['sum']:.0f}")
    log(f"  VAL       n={m_vl_c['n']:4d} WR={wr_vl:.3f} const dpt=${m_vl_c['mean']:.2f} sum=${m_vl_c['sum']:.0f} | kelly dpt=${m_vl_k['mean']:.2f} sum=${m_vl_k['sum']:.0f}")
    log(f"  LOCKBOX   n={m_lk_c['n']:4d} WR={wr_lk:.3f} const dpt=${m_lk_c['mean']:.2f} sum=${m_lk_c['sum']:.0f} | kelly dpt=${m_lk_k['mean']:.2f} sum=${m_lk_k['sum']:.0f}")
    log(f"  FULL      n={m_fu_c['n']:4d} WR={wr_fu:.3f} const dpt=${m_fu_c['mean']:.2f} sum=${m_fu_c['sum']:.0f} | kelly dpt=${m_fu_k['mean']:.2f} sum=${m_fu_k['sum']:.0f}")
    log(f"  avg stake (kelly): ${fu['stakes'].mean():.2f}, max: ${fu['stakes'].max():.2f}")

    reports.append({
        'sleeve_id': c['id'], 'gate_stack': '|'.join(c['stack']),
        'p_kelly': p_train, 'avg_stake_kelly': float(fu['stakes'].mean()),
        'n_train': m_tr_c['n'], 'n_val': m_vl_c['n'], 'n_lock': m_lk_c['n'], 'n_full': m_fu_c['n'],
        'wr_train': wr_tr, 'wr_val': wr_vl, 'wr_lock': wr_lk, 'wr_full': wr_fu,
        'dpt_lock_const': m_lk_c['mean'], 'dpt_lock_kelly': m_lk_k['mean'],
        'dpt_full_const': m_fu_c['mean'], 'dpt_full_kelly': m_fu_k['mean'],
        'sum_lock_const': m_lk_c['sum'], 'sum_lock_kelly': m_lk_k['sum'],
        'sum_full_const': m_fu_c['sum'], 'sum_full_kelly': m_fu_k['sum'],
        'dd_lock_const': m_lk_c['dd'], 'dd_lock_kelly': m_lk_k['dd'],
        'dd_full_const': m_fu_c['dd'], 'dd_full_kelly': m_fu_k['dd'],
        'ls_lock_const': m_lk_c['ls'], 'ls_full_const': m_fu_c['ls'],
    })

    # Kelly stake table — for V6 brief §8 output
    # Bucket by entry_vwap quartiles
    if fu is not None and len(fu['sub']) > 0:
        sub = fu['sub'].copy()
        sub['stake_kelly'] = fu['stakes']
        sub['pnl_const'] = fu['pnl_const']
        sub['pnl_kelly'] = fu['pnl_kelly']
        # bucket
        qs = sub['entry_vwap'].quantile([0.25, 0.5, 0.75]).values
        def vb(v):
            if v <= qs[0]: return 'Q1_low_vwap'
            if v <= qs[1]: return 'Q2'
            if v <= qs[2]: return 'Q3'
            return 'Q4_high_vwap'
        sub['vwap_bucket'] = sub['entry_vwap'].apply(vb)
        bucket_table = sub.groupby('vwap_bucket').agg(
            n=('won','size'),
            wr=('won','mean'),
            mean_vwap=('entry_vwap','mean'),
            mean_stake_kelly=('stake_kelly','mean'),
            sum_const=('pnl_const','sum'),
            sum_kelly=('pnl_kelly','sum'),
            mean_const=('pnl_const','mean'),
            mean_kelly=('pnl_kelly','mean'),
        ).reset_index()
        bucket_table.to_csv(OUT / f"kelly_stake_table_{c['id']}.csv", index=False)
        log(f"  kelly stake table per vwap bucket → kelly_stake_table_{c['id']}.csv")
        print(bucket_table.to_string(index=False))

    # Cumulative PnL plot
    if fu is not None and len(fu['sub']) > 0:
        fig, ax = plt.subplots(figsize=(10, 5))
        x = pd.to_datetime(fu['sub']['fire_us'], unit='us')
        ax.plot(x, np.cumsum(fu['pnl_const']), label='const $25', alpha=0.85)
        ax.plot(x, np.cumsum(fu['pnl_kelly']), label='Kelly-25 (avg ${:.1f})'.format(fu['stakes'].mean()), alpha=0.85)
        ax.set_title(f"SOL 15m V6: {c['id']} cumulative PnL")
        ax.set_xlabel('date')
        ax.set_ylabel('cum PnL USD')
        ax.legend()
        ax.grid(alpha=0.3)
        # Mark lockbox boundary
        lock_ts = pd.Timestamp(lock_start)
        ax.axvline(lock_ts, color='red', linestyle='--', alpha=0.5, label='lock')
        fig.tight_layout()
        out_path = OUT / f"cumulative_pnl_kelly_vs_const_{c['id']}.png"
        fig.savefig(out_path, dpi=110)
        plt.close(fig)
        log(f"  plot → {out_path.name}")

# Save final report CSV
df_reports = pd.DataFrame(reports)
df_reports.to_csv(OUT / "top_5_candidates_v6.csv", index=False)
log(f"WROTE top_5_candidates_v6.csv ({len(df_reports)} rows)")
print(df_reports.to_string(index=False))

log(f"Elapsed: {time.time()-t0:.1f}s")
