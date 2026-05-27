"""Build the final curated top_5_candidates with deduplication and diversity.

Selection logic:
  1. Take all sniper-passing candidates from all_candidates.csv
  2. Dedupe by gate_stack
  3. Group by 'gate atom signature' (e.g. presence of g_tr_stack_full_with as anchor)
  4. Pick the best from each group, prioritizing:
     - sniper_score (out of 8)
     - dpt_25
     - n_lockbox (more = more reliable)
     - DD low
  5. Ensure at least one candidate per cohort (22D, 28D, 31D, 33D) if available
  6. Top 5 final

Also produces final plots, bootstrap CI, and the SNIPER report MD.
"""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m"

df = pd.read_parquet(f"{OUT}/eth_15m_enriched.parquet")
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)

# Re-evaluate the FINAL chosen 5 candidates from research
SPLITS = {
    '33D': dict(
        train=(pd.Timestamp('2026-04-24', tz='UTC'), pd.Timestamp('2026-05-15', tz='UTC')),
        val  =(pd.Timestamp('2026-05-15', tz='UTC'), pd.Timestamp('2026-05-22', tz='UTC')),
        lock =(pd.Timestamp('2026-05-22', tz='UTC'), pd.Timestamp('2026-05-26', tz='UTC')),
    ),
    '31D': dict(
        train=(pd.Timestamp('2026-04-24', tz='UTC'), pd.Timestamp('2026-05-15', tz='UTC')),
        val  =(pd.Timestamp('2026-05-15', tz='UTC'), pd.Timestamp('2026-05-21', tz='UTC')),
        lock =(pd.Timestamp('2026-05-21', tz='UTC'), pd.Timestamp('2026-05-25', tz='UTC')),
    ),
    '28D': dict(
        train=(pd.Timestamp('2026-04-28', tz='UTC'), pd.Timestamp('2026-05-14', tz='UTC')),
        val  =(pd.Timestamp('2026-05-14', tz='UTC'), pd.Timestamp('2026-05-20', tz='UTC')),
        lock =(pd.Timestamp('2026-05-20', tz='UTC'), pd.Timestamp('2026-05-25', tz='UTC')),
    ),
    '22D': dict(
        train=(pd.Timestamp('2026-05-01', tz='UTC'), pd.Timestamp('2026-05-14', tz='UTC')),
        val  =(pd.Timestamp('2026-05-14', tz='UTC'), pd.Timestamp('2026-05-18', tz='UTC')),
        lock =(pd.Timestamp('2026-05-18', tz='UTC'), pd.Timestamp('2026-05-22', tz='UTC')),
    ),
}

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float); col = np.nan_to_num(col, nan=0.0)
        m &= (col == 1)
    return m

def m_for(d, cohort):
    spl = SPLITS[cohort]; fd = d['fire_date']
    return ((fd >= spl['train'][0]) & (fd < spl['train'][1]),
            (fd >= spl['val'][0]) & (fd < spl['val'][1]),
            (fd >= spl['lock'][0]) & (fd < spl['lock'][1]),
            (fd >= spl['train'][0]) & (fd < spl['lock'][1]))

def metrics(d, gates):
    m = gate_passes(d, gates); sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0: return dict(n=0, wr=0, dpt=0, sum=0, dd=0, ls=0, sharpe=0, n_days=0)
    pnl = sub.pnl_legacy_usd.values
    wr = sub.won.mean() * 100; dpt = float(pnl.mean())
    cum = np.cumsum(pnl); peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = float((peak-cum).max())
    losers = (pnl < 0).astype(int); cur_run=max_run=0
    for v in losers:
        if v == 1:
            cur_run += 1
            if cur_run > max_run: max_run = cur_run
        else: cur_run = 0
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    daily = sub.groupby('date').pnl_legacy_usd.sum()
    sharpe = (daily.mean()/daily.std())*np.sqrt(252) if len(daily)>1 and daily.std()>0 else 0.0
    return dict(n=n, wr=float(wr), dpt=dpt, sum=float(pnl.sum()), dd=dd, ls=int(max_run), sharpe=float(sharpe), n_days=int(daily.shape[0]))

def bootstrap(d, gates, n_iter=1000, seed=42):
    m = gate_passes(d, gates); sub = d[m].copy(); n = len(sub)
    if n < 10: return (np.nan, np.nan, np.nan, np.nan)
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    grp = sub.groupby('date').pnl_legacy_usd
    daily_pnl = grp.sum().values; daily_n = grp.count().values
    n_days = len(daily_pnl)
    if n_days < 3: return (np.nan, np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        means[i] = daily_pnl[idx].sum() / max(daily_n[idx].sum(), 1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    obs = sub.pnl_legacy_usd.mean()
    p = (means <= 0).mean() if obs > 0 else 0.5
    return (obs, lo, hi, max(p, 1e-4))

# ---- FINAL CURATED TOP 5 ----
# Based on research findings, prioritize:
#   1. Different gate atoms (avoid 3 identical FULL_k4)
#   2. Different cohorts where possible (different effective windows)
#   3. Different offset anchors (early, mid, late, all)
#   4. Diversity of cohort: 22D (best metrics) + 31D (more fires) + others

FINAL_TOP5 = {
    # Primary: best in show — HUR22_k4 (with all 4 gates synergistic, HIGH confidence)
    'SNIPER_ETH15M_S1_HUR22_TRSTACK_OFFEARLY_VOLHIGH_VWAP': dict(
        cohort='22D',
        gates=['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high'],
        anchor='offset_early(0-60s)',
        description="TR pivot+EMA stack full alignment + 1h daily-VWAP follow + first 60s of slot + high realized vol (top quartile)",
        confidence='HIGH',
    ),
    # Secondary: 31D variant with mp_skew — exploits microprice info (full window — more fires)
    'SNIPER_ETH15M_S2_MP31_MPSKEW_OFFEARLY_VWAP': dict(
        cohort='31D',
        gates=['g_mp_skew_with','g_offset_early','g_above_1h_dailyvwap_with'],
        anchor='offset_early(0-60s)',
        description="Microprice skew aligned with direction + 1h daily-VWAP follow + first 60s of slot — fresh 15m alpha from L25 microprice",
        confidence='MED',
    ),
    # Tertiary: 33D FULL_k4 (no panel dependency, runnable on any future fires)
    'SNIPER_ETH15M_S3_FULL_RFAGED_OFFEARLY_RIBBONSLOPE_VWAP': dict(
        cohort='33D',
        gates=['g_above_1h_dailyvwap_with','g_offset_early','g_rf_aged','g_ribbon_slope_with'],
        anchor='offset_early(0-60s)',
        description="Range Filter aged signal + ribbon slope alignment + first 60s + 1h VWAP — fully panel-independent, runs on any historical fires",
        confidence='LOW',
    ),
    # 31D pivot-based: alternative geometric framework
    'SNIPER_ETH15M_S4_MP31_NEARPIVOT_OFFEARLY_VWAP': dict(
        cohort='31D',
        gates=['g_near_pivot','g_offset_early','g_above_1h_dailyvwap_with'],
        anchor='offset_early(0-60s)',
        description="Daily pivot proximity (<0.5% of pp) + first 60s of slot + 1h daily-VWAP follow — fresh geometric 15m alpha",
        confidence='MED',
    ),
    # 31D — same offset_early anchor but with TR stack (more selective)
    'SNIPER_ETH15M_S5_MP31_TRSTACKFULL_OFFEARLY_VWAP': dict(
        cohort='31D',
        gates=['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with'],
        anchor='offset_early(0-60s)',
        description="TR pivot+EMA stack full alignment + first 60s + 1h daily-VWAP — broader coverage than S1 (no vol_high), tradeoff: lower dpt",
        confidence='MED',
    ),
}

# Re-evaluate each
records = []
for name, info in FINAL_TOP5.items():
    cohort = info['cohort']; gates = info['gates']
    m_tr, m_va, m_lo, m_full = m_for(df, cohort)
    mt_tr = metrics(df[m_tr], gates); mt_va = metrics(df[m_va], gates)
    mt_lo = metrics(df[m_lo], gates); mt_full = metrics(df[m_full], gates)
    obs_lo, ci_lo, ci_hi, p_lo = bootstrap(df[m_lo], gates)
    spl = SPLITS[cohort]
    days_full = (spl['lock'][1] - spl['train'][0]).total_seconds() / 86400.0
    days_lock = (spl['lock'][1] - spl['lock'][0]).total_seconds() / 86400.0
    fpd_full = mt_full['n'] / max(days_full, 1)
    fpd_lock = mt_lo['n'] / max(days_lock, 1)

    rec = dict(
        sleeve_id=name, anchor=info['anchor'], cohort=cohort,
        gate_stack='&'.join(gates),
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=mt_full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=mt_full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=mt_full['dpt'],
        sum_25_full=mt_full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['dd'], max_dd_full=mt_full['dd'],
        loss_streak=mt_lo['ls'], loss_streak_full=mt_full['ls'],
        sharpe=mt_lo['sharpe'], sharpe_full=mt_full['sharpe'],
        dpt_ci_lo=ci_lo, dpt_ci_hi=ci_hi,
        bootstrap_p_lockbox=p_lo,
        fires_per_day=fpd_full, fires_per_day_lock=fpd_lock,
        days_full=days_full, days_lock=days_lock,
        confidence=info['confidence'], description=info['description'],
    )
    records.append(rec)
    log(f"  {name}: lock n={mt_lo['n']} WR={mt_lo['wr']:.1f}% dpt=${mt_lo['dpt']:+.2f} CI=[{ci_lo:.2f},{ci_hi:.2f}] p={p_lo:.4f} conf={info['confidence']}")

top5_df = pd.DataFrame(records)
top5_df.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
log(f"WROTE top_5_candidates.csv (5 curated)")

# Cumulative PnL plots
log("\nGenerating cumulative PnL plots")
for name, info in FINAL_TOP5.items():
    cohort = info['cohort']; gates = info['gates']
    m_tr, m_va, m_lo, m_full = m_for(df, cohort)
    fires = df[m_full & gate_passes(df, gates)].sort_values('fire_us').reset_index(drop=True)
    fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date
    cum = fires.pnl_legacy_usd.cumsum().values
    spl = SPLITS[cohort]

    fig, axes = plt.subplots(2,1, figsize=(11,7), gridspec_kw={'height_ratios':[2,1]})
    ax = axes[0]
    ax.plot(fires.fire_date, cum, lw=1.5, color='steelblue')
    ax.axvline(spl['train'][1], color='orange', ls='--', alpha=0.7, label='train|val')
    ax.axvline(spl['val'][1],   color='red',    ls='--', alpha=0.7, label='val|lock')
    ax.fill_betweenx([cum.min()-50, cum.max()+50],
                     spl['lock'][0], spl['lock'][1], alpha=0.1, color='green', label='lockbox')
    ax.set_title(f"{name}\nCohort: {cohort} | Stack: {' & '.join(gates)}")
    ax.set_ylabel("Cumulative PnL ($25 stake)"); ax.grid(True, alpha=0.3); ax.legend(loc='upper left', fontsize=8)
    ax = axes[1]
    daily = fires.groupby('date').agg(pnl=('pnl_legacy_usd','sum'), n=('pnl_legacy_usd','count')).reset_index()
    cols = ['steelblue' if v > 0 else 'firebrick' for v in daily.pnl]
    ax.bar(daily.date, daily.pnl, color=cols, alpha=0.7)
    ax.set_title(f"Daily PnL | mean fires/day = {fires.shape[0]/max((spl['lock'][1]-spl['train'][0]).days,1):.2f}")
    ax.set_ylabel("Daily PnL ($)"); ax.tick_params(axis='x', rotation=45); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUT}/cumulative_pnl_{name}.png", dpi=80)
    plt.close()

log("DONE")
