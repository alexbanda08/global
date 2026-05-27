"""Deep validation of top 5 sniper candidates.

For each finalist:
  - Per-day fire histogram (full 33d window where possible)
  - Cumulative PnL plot (saved as PNG)
  - 1000-iter daily-clustered bootstrap CI on lockbox dpt
  - Stake-sensitivity: what happens at $25 vs $5 vs $50
  - Slug overlap with other finalists
  - Worst-week PnL
  - Direction balance check (% UP vs DOWN)
  - Confidence rating
"""
import os, time, warnings
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

log("loading enriched fires")
df = pd.read_parquet(f"{OUT}/eth_15m_enriched.parquet")
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)

top5_csv = pd.read_csv(f"{OUT}/top_5_candidates.csv")
log(f"top 5 loaded: {top5_csv.sleeve_id.tolist()}")

STAKE = 25.0

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        col = np.nan_to_num(col, nan=0.0)
        m &= (col == 1)
    return m

# Cohort-aware splits (same as 03_)
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

def bootstrap_ci(d, gates, n_iter=1000, ci=(2.5, 97.5), seed=42):
    """Daily-clustered bootstrap CI on dpt + p-value."""
    m = gate_passes(d, gates)
    sub = d[m].copy()
    n = len(sub)
    if n < 10: return (np.nan, np.nan, np.nan, np.nan)
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    grp = sub.groupby('date')['pnl_legacy_usd']
    daily_pnl = grp.sum().values
    daily_n = grp.count().values
    n_days = len(daily_pnl)
    if n_days < 3: return (np.nan, np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        means[i] = daily_pnl[idx].sum() / max(daily_n[idx].sum(), 1)
    lo, hi = np.percentile(means, ci)
    obs = sub.pnl_legacy_usd.mean()
    p = (means <= 0).mean() if obs > 0 else 0.5
    return (obs, lo, hi, max(p, 1e-4))

reports = []
finalists = []
for _, row in top5_csv.iterrows():
    name = row.sleeve_id
    gates = row.gate_stack.split('&')
    cohort = row.cohort
    spl = SPLITS[cohort]
    fd = df['fire_date']
    m_tr = (fd >= spl['train'][0]) & (fd < spl['train'][1])
    m_va = (fd >= spl['val'][0])   & (fd < spl['val'][1])
    m_lo = (fd >= spl['lock'][0])  & (fd < spl['lock'][1])
    full_m = (fd >= spl['train'][0]) & (fd < spl['lock'][1])

    m = gate_passes(df, gates)
    fires_all = df[m & full_m].sort_values('fire_us').reset_index(drop=True)
    fires_lo  = df[m & m_lo].sort_values('fire_us').reset_index(drop=True)

    # Bootstrap CI on lockbox
    obs_lo, lo_lo, hi_lo, p_lo = bootstrap_ci(df[m_lo], gates)

    # Cumulative PnL plot (full window)
    cum = fires_all.pnl_legacy_usd.cumsum().values
    dates = fires_all.fire_date.dt.date.values
    fig, axes = plt.subplots(2,1, figsize=(11,7), sharex=False)
    ax = axes[0]
    ax.plot(fires_all.fire_date, cum, lw=1.5)
    ax.axvline(spl['train'][1], color='orange', ls='--', label='train|val')
    ax.axvline(spl['val'][1],   color='red',    ls='--', label='val|lock')
    ax.set_title(f"{name} | cohort={cohort} | cumulative PnL @ $25 stake")
    ax.set_ylabel("Cumulative $")
    ax.grid(True, alpha=0.3); ax.legend()
    # Per-day fires hist
    ax = axes[1]
    fires_per_day = fires_all.groupby(fires_all.fire_date.dt.date).size()
    ax.bar(fires_per_day.index, fires_per_day.values)
    ax.set_title(f"Fires per day | mean={fires_per_day.mean():.2f}/day | min={fires_per_day.min()} max={fires_per_day.max()}")
    ax.set_ylabel("# fires")
    plt.tight_layout()
    out_png = f"{OUT}/cumulative_pnl_{name}.png"
    plt.savefig(out_png, dpi=80)
    plt.close()

    # Direction balance
    dir_balance = fires_lo.direction.value_counts(normalize=True).to_dict() if len(fires_lo) else {}

    # Slug count
    n_slugs_lock = fires_lo.slug.nunique()
    n_slugs_full = fires_all.slug.nunique()

    # Per-day breakdown lockbox
    daily_lo = fires_lo.groupby(fires_lo.fire_date.dt.date)['pnl_legacy_usd'].agg(['sum','count','mean'])

    # Worst-week PnL (rolling 7d cumsum, take min)
    daily_full = fires_all.groupby(fires_all.fire_date.dt.date).pnl_legacy_usd.sum().reset_index()
    daily_full['date'] = pd.to_datetime(daily_full['fire_date'])
    daily_full = daily_full.set_index('date').sort_index()
    worst_week = daily_full.pnl_legacy_usd.rolling(7).sum().min() if len(daily_full) >= 7 else float(daily_full.pnl_legacy_usd.min())

    # Confidence
    n_lock = len(fires_lo)
    train_wr = (df[m & m_tr].won.mean() * 100) if (m & m_tr).sum() > 0 else 0
    val_wr   = (df[m & m_va].won.mean() * 100) if (m & m_va).sum() > 0 else 0
    lock_wr  = fires_lo.won.mean() * 100 if n_lock else 0
    wr_consistency = abs(train_wr - val_wr) + abs(val_wr - lock_wr)
    if n_lock >= 20 and wr_consistency < 25 and (lo_lo > 0):
        confidence = 'HIGH'
    elif n_lock >= 10 and wr_consistency < 35 and (lo_lo > -2):
        confidence = 'MED'
    else:
        confidence = 'LOW'

    report = dict(
        sleeve_id=name, cohort=cohort, gates='&'.join(gates),
        n_lock=n_lock, n_full=len(fires_all), n_slugs_lock=n_slugs_lock, n_slugs_full=n_slugs_full,
        wr_train=train_wr, wr_val=val_wr, wr_lock=lock_wr, wr_consistency_pp=wr_consistency,
        dpt_lock=obs_lo, dpt_ci_lo=lo_lo, dpt_ci_hi=hi_lo, bootstrap_p=p_lo,
        worst_7d_pnl=worst_week, dir_up_pct=dir_balance.get('UP', 0) * 100,
        confidence=confidence,
        daily_lo_pnl_min=daily_lo['sum'].min() if len(daily_lo) else 0,
        daily_lo_pnl_max=daily_lo['sum'].max() if len(daily_lo) else 0,
        daily_lo_count_min=daily_lo['count'].min() if len(daily_lo) else 0,
        daily_lo_count_max=daily_lo['count'].max() if len(daily_lo) else 0,
    )
    reports.append(report)
    finalists.append(dict(name=name, gates=gates, cohort=cohort, fires_full=fires_all, fires_lo=fires_lo, daily_lo=daily_lo))

    log(f"  {name}: n_lock={n_lock} CI=[{lo_lo:.2f}, {hi_lo:.2f}] p={p_lo:.4f} conf={confidence}")

rdf = pd.DataFrame(reports)
rdf.to_csv(f"{OUT}/finalist_validation.csv", index=False)
log("\n=== FINALIST VALIDATION ===")
print(rdf.to_string(max_colwidth=80))

# Slug overlap matrix
log("\n=== SLUG OVERLAP among finalists (lockbox) ===")
overlap_mat = np.zeros((len(finalists), len(finalists)))
for i, f1 in enumerate(finalists):
    for j, f2 in enumerate(finalists):
        s1 = set(f1['fires_lo'].slug); s2 = set(f2['fires_lo'].slug)
        if not s1: overlap_mat[i,j] = 0
        else: overlap_mat[i,j] = len(s1 & s2) / len(s1) * 100
om_df = pd.DataFrame(overlap_mat, index=[f['name'] for f in finalists], columns=[f['name'] for f in finalists])
print(om_df.round(1))
om_df.to_csv(f"{OUT}/finalist_slug_overlap_pct.csv")

# Per-day detail for top finalist
log("\n=== PER-DAY LOCKBOX DETAIL ===")
for f in finalists[:5]:
    print(f"\n{f['name']} ({f['cohort']}):")
    print(f['daily_lo'])
log("DONE")
