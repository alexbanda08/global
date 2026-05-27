"""V6 SOL 15m: final report with Top 5 + Kelly schedule + plots + bootstrap stats.

After vwap-aware refinement, top sleeves are:
- C1a: HOD_EU + off_60_240 + rf_with + tr_stack + vwap LT 80 → PASS STRICT V6 LOCKBOX
- C1b: HOD_EU + off_60_240 + rf_with + tr_stack + vwap 30_70 → near pass (dpt_l=$3.82)
- C1c: HOD_EU + off_60_240 + rf_with + tr_stack + vwap LT 55 → small n high dpt
- C2a: HOD_EU + off_60 + tr_stack + tr_within_adr + vwap 30_70 → small lock but strong full
- C3a: HOD_EU + rf_with + tight_ribbon + tr_stack + vwap LT 80
- C6a: rf_with + tr_stack + ribbon_slope_with + vwap LT 55 → highest full-window score
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

p = pd.read_parquet(OUT / "sol_15m_v6_universe.parquet")
p = p[p['entry_vwap'] < 0.998].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[22]
val_end = dates_sorted[29]
lock_start = val_end


def kelly_stake(vwap, p_win):
    if vwap <= 0 or vwap >= 1: return 0.0
    b = (1.0 - vwap) * 0.98 / vwap
    f_full = (p_win * b - (1 - p_win)) / b
    if f_full <= 0: return 0.0
    f_kelly_25 = 0.25 * f_full
    return float(np.clip(f_kelly_25 * STAKE_MAX, STAKE_MIN, STAKE_MAX))


def pnl_at_stake(vwap, won, stake):
    if stake <= 0: return 0.0
    if vwap <= 0 or vwap >= 1: return 0.0
    shares = stake / vwap
    return (1.0 - vwap) * shares * 0.98 if won else -stake


def bootstrap_p(pnl_arr, dates_arr, n_iter=2000, seed=42):
    if len(pnl_arr) < 5: return np.nan
    rng = np.random.default_rng(seed)
    dates = np.array(dates_arr)
    unique_dates = np.unique(dates)
    if len(unique_dates) < 3: return np.nan
    sims = []
    for _ in range(n_iter):
        sample = rng.choice(unique_dates, size=len(unique_dates), replace=True)
        b_pnl = []
        for d in sample:
            b_pnl.extend(pnl_arr[dates == d])
        if len(b_pnl) == 0: continue
        sims.append(np.mean(b_pnl))
    sims = np.array(sims)
    return float((sims <= 0).mean())


def apply_sleeve(df, atoms, vfn):
    mask = np.ones(len(df), dtype=bool)
    for a in atoms:
        col = df[a].values
        if col.dtype == float:
            col = np.where(np.isnan(col), 0, col)
        mask &= (col == 1)
    sub = df[mask].copy()
    sub = sub[vfn(sub)].copy()
    return sub.sort_values('fire_us').reset_index(drop=True)


def metrics_from_pnl(pnl):
    if len(pnl) == 0:
        return dict(n=0,sum=0,mean=0,dd=0,ls=0)
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls = 0; cur = 0
    for v in pnl:
        if v < 0:
            cur += 1; ls = max(ls, cur)
        else:
            cur = 0
    return dict(n=len(pnl), sum=float(pnl.sum()), mean=float(pnl.mean()), dd=dd, ls=ls)


SLEEVES = [
    {'id':'C1a_HOD_EU_OFF60-240_VWAP_lt80',
     'stack':['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with'],
     'vfn':lambda s: s['entry_vwap'] < 0.80,
     'vfn_name':'entry_vwap < 0.80',
     'anchor':'offset_60_240s (early to mid 15m window)'},
    {'id':'C1b_HOD_EU_OFF60-240_VWAP_30_70',
     'stack':['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with'],
     'vfn':lambda s: (s['entry_vwap'] >= 0.30) & (s['entry_vwap'] < 0.70),
     'vfn_name':'entry_vwap in [0.30, 0.70)',
     'anchor':'offset_60_240s (early to mid 15m window)'},
    {'id':'C2_HOD_EU_OFF60_TR_ADR_VWAP_30_70',
     'stack':['g_hod_european_morning','g_off_60','g_tr_stack_with','g_tr_within_adr'],
     'vfn':lambda s: (s['entry_vwap'] >= 0.30) & (s['entry_vwap'] < 0.70),
     'vfn_name':'entry_vwap in [0.30, 0.70)',
     'anchor':'offset_60 EARLY FIRE (matches production)'},
    {'id':'C3_HOD_EU_TIGHTRIB_VWAP_lt80',
     'stack':['g_hod_european_morning','g_rf_with','g_tight_ribbon','g_tr_stack_with'],
     'vfn':lambda s: s['entry_vwap'] < 0.80,
     'vfn_name':'entry_vwap < 0.80',
     'anchor':'all offsets (g_off filter not applied; primarily 60-840s window)'},
    {'id':'C6_TR_RF_RIBSLP_VWAP_lt55',
     'stack':['g_tr_stack_with','g_rf_with','g_ribbon_slope_with'],
     'vfn':lambda s: s['entry_vwap'] < 0.55,
     'vfn_name':'entry_vwap < 0.55',
     'anchor':'all offsets (broad-window, ribbon-aligned underdog fires)'},
]


reports = []
for sl in SLEEVES:
    log(f"=== {sl['id']} ===")
    train_df = p[p['date'] < train_end]
    val_df   = p[(p['date'] >= train_end) & (p['date'] < val_end)]
    lock_df  = p[p['date'] >= lock_start]

    tr = apply_sleeve(train_df, sl['stack'], sl['vfn'])
    vl = apply_sleeve(val_df,   sl['stack'], sl['vfn'])
    lk = apply_sleeve(lock_df,  sl['stack'], sl['vfn'])
    fu = apply_sleeve(p,         sl['stack'], sl['vfn'])

    p_train = float(tr['won'].mean()) if len(tr) > 0 else 0.5
    log(f"  train WR (used as Kelly p): {p_train:.3f}")

    # Constant $25
    pnl_tr_c = tr['pnl_legacy_usd'].values
    pnl_vl_c = vl['pnl_legacy_usd'].values
    pnl_lk_c = lk['pnl_legacy_usd'].values
    pnl_fu_c = fu['pnl_legacy_usd'].values

    # Kelly stake per fire
    def kelly_arr(df):
        if len(df) == 0:
            return np.array([]), np.array([])
        stakes = df['entry_vwap'].apply(lambda v: kelly_stake(v, p_train)).values
        pnl = np.array([pnl_at_stake(v, w, s) for v,w,s in zip(df['entry_vwap'].values, df['won'].values, stakes)])
        return pnl, stakes

    pnl_tr_k, stakes_tr = kelly_arr(tr)
    pnl_vl_k, stakes_vl = kelly_arr(vl)
    pnl_lk_k, stakes_lk = kelly_arr(lk)
    pnl_fu_k, stakes_fu = kelly_arr(fu)

    m_tr_c = metrics_from_pnl(pnl_tr_c); m_tr_k = metrics_from_pnl(pnl_tr_k)
    m_vl_c = metrics_from_pnl(pnl_vl_c); m_vl_k = metrics_from_pnl(pnl_vl_k)
    m_lk_c = metrics_from_pnl(pnl_lk_c); m_lk_k = metrics_from_pnl(pnl_lk_k)
    m_fu_c = metrics_from_pnl(pnl_fu_c); m_fu_k = metrics_from_pnl(pnl_fu_k)

    # WR per window
    wr_tr = float(tr['won'].mean()) if len(tr) > 0 else 0
    wr_vl = float(vl['won'].mean()) if len(vl) > 0 else 0
    wr_lk = float(lk['won'].mean()) if len(lk) > 0 else 0
    wr_fu = float(fu['won'].mean()) if len(fu) > 0 else 0

    # Bootstrap
    bp_lk_c = bootstrap_p(pnl_lk_c, lk['date'].values) if len(lk) >= 5 else np.nan
    bp_lk_k = bootstrap_p(pnl_lk_k, lk['date'].values) if len(lk) >= 5 else np.nan
    bp_fu_c = bootstrap_p(pnl_fu_c, fu['date'].values) if len(fu) >= 30 else np.nan
    bp_fu_k = bootstrap_p(pnl_fu_k, fu['date'].values) if len(fu) >= 30 else np.nan

    # Sharpe daily approx
    if len(fu) > 0 and pnl_fu_c.std() > 0:
        sharpe_fu = float(pnl_fu_c.mean() / pnl_fu_c.std() * np.sqrt(len(fu) / 33))
    else:
        sharpe_fu = 0
    if len(lk) > 0 and pnl_lk_c.std() > 0:
        sharpe_lk = float(pnl_lk_c.mean() / pnl_lk_c.std() * np.sqrt(len(lk) / 4))
    else:
        sharpe_lk = 0

    log(f"  TRAIN  n={m_tr_c['n']:4d} WR={wr_tr:.3f} const$25 dpt=${m_tr_c['mean']:.2f} sum=${m_tr_c['sum']:.0f} | kelly dpt=${m_tr_k['mean']:.2f} sum=${m_tr_k['sum']:.0f}")
    log(f"  VAL    n={m_vl_c['n']:4d} WR={wr_vl:.3f} const$25 dpt=${m_vl_c['mean']:.2f} sum=${m_vl_c['sum']:.0f} | kelly dpt=${m_vl_k['mean']:.2f} sum=${m_vl_k['sum']:.0f}")
    log(f"  LOCK   n={m_lk_c['n']:4d} WR={wr_lk:.3f} const$25 dpt=${m_lk_c['mean']:.2f} sum=${m_lk_c['sum']:.0f}  bp={bp_lk_c:.3f} | kelly dpt=${m_lk_k['mean']:.2f} sum=${m_lk_k['sum']:.0f} bp_k={bp_lk_k:.3f}")
    log(f"  FULL   n={m_fu_c['n']:4d} WR={wr_fu:.3f} const$25 dpt=${m_fu_c['mean']:.2f} sum=${m_fu_c['sum']:.0f}  bp={bp_fu_c:.3f} | kelly dpt=${m_fu_k['mean']:.2f} sum=${m_fu_k['sum']:.0f}")
    log(f"  Avg Kelly stake: ${stakes_fu.mean() if len(stakes_fu) else 0:.2f}")
    log(f"  Sharpe full (daily-scaled): {sharpe_fu:.2f}")

    reports.append({
        'sleeve_id': sl['id'],
        'anchor': sl['anchor'],
        'gate_stack': '|'.join(sl['stack']),
        'vwap_filter': sl['vfn_name'],
        'conviction_method': 'Option A — fixed Kelly p from train WR',
        'p_kelly': p_train,
        'avg_stake_kelly': float(stakes_fu.mean()) if len(stakes_fu) else 0,
        'n_train': m_tr_c['n'], 'n_val': m_vl_c['n'], 'n_lockbox': m_lk_c['n'], 'n_full': m_fu_c['n'],
        'wr_train': wr_tr, 'wr_val': wr_vl, 'wr_lockbox': wr_lk, 'wr_full': wr_fu,
        'dpt_25_train': m_tr_c['mean'], 'dpt_25_val': m_vl_c['mean'],
        'dpt_25_lockbox': m_lk_c['mean'], 'dpt_25_full': m_fu_c['mean'],
        'sum_25_lockbox_const': m_lk_c['sum'], 'sum_25_full_const': m_fu_c['sum'],
        'sum_kelly_lockbox': m_lk_k['sum'], 'sum_kelly_full': m_fu_k['sum'],
        'dd_25_lockbox': m_lk_c['dd'], 'dd_25_full': m_fu_c['dd'],
        'loss_streak_lockbox': m_lk_c['ls'], 'loss_streak_full': m_fu_c['ls'],
        'sharpe_lockbox': sharpe_lk, 'sharpe_full': sharpe_fu,
        'bootstrap_p_lockbox_const25': bp_lk_c, 'bootstrap_p_full_const25': bp_fu_c,
        # V6 pass check
        'V6_pass_lock': (m_lk_c['n']>=20 and wr_lk>=0.65 and m_lk_c['mean']>=4 and m_lk_c['dd']<=500 and m_lk_c['ls']<=14 and bp_lk_c<=0.05),
    })

    # Kelly stake table by vwap bucket
    if len(fu) > 0:
        df_k = fu[['entry_vwap','won','date']].copy()
        df_k['stake_kelly'] = stakes_fu
        df_k['pnl_const'] = pnl_fu_c
        df_k['pnl_kelly'] = pnl_fu_k
        # Bucket by vwap
        bins = [0, 0.3, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0]
        labels = ['<.30','.30-.45','.45-.55','.55-.65','.65-.75','.75-.85','>=.85']
        df_k['vwap_band'] = pd.cut(df_k['entry_vwap'], bins=bins, labels=labels)
        tbl = df_k.groupby('vwap_band', observed=True).agg(
            n=('won','size'),
            wr=('won','mean'),
            mean_vwap=('entry_vwap','mean'),
            stake_kelly=('stake_kelly','mean'),
            const_sum=('pnl_const','sum'),
            const_mean=('pnl_const','mean'),
            kelly_sum=('pnl_kelly','sum'),
            kelly_mean=('pnl_kelly','mean'),
        ).reset_index()
        tbl.to_csv(OUT / f"kelly_stake_table_{sl['id']}.csv", index=False)
        log(f"  kelly stake table → kelly_stake_table_{sl['id']}.csv")

    # Plot
    if len(fu) > 0:
        fig, ax = plt.subplots(figsize=(11, 5))
        x = pd.to_datetime(fu['fire_us'], unit='us')
        ax.plot(x, np.cumsum(pnl_fu_c), label=f'const $25 (sum=${pnl_fu_c.sum():.0f})', linewidth=1.5)
        ax.plot(x, np.cumsum(pnl_fu_k), label=f'Kelly-25 avg${stakes_fu.mean():.1f} (sum=${pnl_fu_k.sum():.0f})', alpha=0.9, linewidth=1.5)
        ax.axvline(pd.Timestamp(train_end), color='gray', linestyle='--', alpha=0.4, label='train→val')
        ax.axvline(pd.Timestamp(val_end), color='red', linestyle='--', alpha=0.5, label='lockbox start')
        ax.axhline(0, color='black', linewidth=0.5, alpha=0.5)
        ax.set_title(f"SOL 15m V6: {sl['id']}\n{sl['vfn_name']}, n_full={len(fu)}, WR_full={wr_fu:.1%}, $/tr_full=${pnl_fu_c.mean():.2f}")
        ax.set_xlabel('date'); ax.set_ylabel('cumulative PnL USD')
        ax.legend(loc='upper left'); ax.grid(alpha=0.3)
        fig.tight_layout()
        out_path = OUT / f"cumulative_pnl_kelly_vs_const_{sl['id']}.png"
        fig.savefig(out_path, dpi=110)
        plt.close(fig)
        log(f"  plot → {out_path.name}")


df_reports = pd.DataFrame(reports)
df_reports.to_csv(OUT / "top_5_candidates_v6.csv", index=False)
log(f"\nWROTE top_5_candidates_v6.csv ({len(df_reports)} rows)")
print(df_reports[['sleeve_id','n_full','wr_full','dpt_25_full','n_lockbox','wr_lockbox','dpt_25_lockbox','dd_25_full','loss_streak_full','bootstrap_p_full_const25','bootstrap_p_lockbox_const25','V6_pass_lock']].to_string(index=False))

# === FAIL CASE: per-direction asym test ===
log("\n=== Per-direction asym check (UP vs DOWN) on TOP sleeve C1 ===")
def per_dir_eval(sleeve, direction):
    train_df = p[(p['date'] < train_end) & (p['direction']==direction)]
    full_df = p[p['direction']==direction]
    tr = apply_sleeve(train_df, sleeve['stack'], sleeve['vfn'])
    fu = apply_sleeve(full_df, sleeve['stack'], sleeve['vfn'])
    if len(fu) == 0:
        return f"{direction}: zero fires"
    return f"{direction}: train n={len(tr)} WR={tr['won'].mean():.3f} dpt=${tr['pnl_legacy_usd'].mean():.2f} | full n={len(fu)} WR={fu['won'].mean():.3f} dpt=${fu['pnl_legacy_usd'].mean():.2f}"

sl1 = SLEEVES[0]  # C1a
print(per_dir_eval(sl1, 'UP'))
print(per_dir_eval(sl1, 'DOWN'))

log(f"Elapsed: {time.time()-t0:.1f}s")
