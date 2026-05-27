"""V8 BTC 15m sleeve rerun with CORRECT $25 normalization.

BUG: The original `03_v8_search.py` did:
    pnl_per_unit = sub[PNL].values        # comment: "legacy pnl col is at $1"
    pnl_25 = pnl_per_unit * 25.0

But `pnl_legacy_usd` is ALREADY at $25 notional (verified: NOTIONAL=25.0 in
`full_window_validation_v2.py`, and hold_pnl uses fill['usd']=$25 → shares=
$25/vwap → won returns shares*$1 - $25; e.g. vwap=0.18 wins ≈ +$111 NET,
which IS the correct $25-notional PnL because you bought 138 shares for $25).

So original V8 numbers are inflated 25× (effectively $625 stake).

FIX: use pnl_legacy_usd directly (no ×25). All else identical.
"""
import os, sys, time
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8/_corrected"
os.makedirs(OUTDIR, exist_ok=True)

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading V8 panel")
df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
df = df[(df.asset == 'BTC') & (df.tf == '15m')].copy()
log(f"  BTC 15m rows: {len(df)}")
log(f"  pnl_legacy_usd range: ${df.pnl_legacy_usd.min():.2f} .. ${df.pnl_legacy_usd.max():.2f} mean=${df.pnl_legacy_usd.mean():+.4f}")

# ============================== Splits (60/20/20 of FULL window) ==============================
total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
total_days = total_secs / 86400
log(f"  total span: {total_days:.2f}d")
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)
df['split'] = np.where(df.fire_date < t_train_end, 'train',
              np.where(df.fire_date < t_val_end, 'val', 'lockbox'))
train_days = (t_train_end - t_min).total_seconds() / 86400
val_days = (t_val_end - t_train_end).total_seconds() / 86400
lock_days = (df.fire_date.max() - t_val_end).total_seconds() / 86400
log(f"  train_days={train_days:.2f} val_days={val_days:.2f} lock_days={lock_days:.2f}")

PNL = 'pnl_legacy_usd'   # ALREADY $25-stake (verified)

# ============================== Metric helpers (CORRECTED) ==============================
def metrics(sub):
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, total_pnl=0.0, max_dd=np.nan,
                    loss_streak=np.nan, sharpe=np.nan)
    pnl = sub[PNL].values   # NO ×25 — already at $25 stake
    wr = float(sub.won.mean())
    dpt = float(pnl.mean())
    total = float(pnl.sum())
    cum = pnl.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if n > 0 else 0.0
    losses = (pnl < 0).astype(int)
    streak = 0; max_streak = 0
    for l in losses:
        if l == 1:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    sharpe = (dpt / pnl.std()) * np.sqrt(252) if pnl.std() > 0 else 0.0
    return dict(n=n, wr=wr, dpt=dpt, total_pnl=total, max_dd=max_dd,
                loss_streak=max_streak, sharpe=sharpe)

def bootstrap_p(pnls, n_boot=2000, seed=42):
    if len(pnls) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    obs = pnls.mean()
    if obs <= 0:
        return 1.0
    n = len(pnls)
    centered = pnls - obs
    boots = np.array([centered[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return float((boots >= obs).mean())

def bootstrap_ci(pnls, n_boot=2000, seed=42, alpha=0.05):
    if len(pnls) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    n = len(pnls)
    boots = np.array([pnls[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return float(np.quantile(boots, alpha/2)), float(np.quantile(boots, 1-alpha/2))

# ============================== The 5 sleeves ==============================
SLEEVES = [
    dict(rank=1, off=600, dir='DOWN', gates=['g_btc_sol_confluence_5m_with', 'g_liq_shock_against']),
    dict(rank=2, off=600, dir='DOWN', gates=['g_xa_unanimity_5m_with', 'g_liq_shock_against']),
    dict(rank=3, off=600, dir='DOWN', gates=['g_btc_eth_confluence_5m_with', 'g_di_agrees', 'g_liq_shock_against']),
    dict(rank=4, off=720, dir='UP',   gates=['g_btc_eth_divergence', 'g_stoch_with', 'g_vol_contracting']),
    dict(rank=5, off=720, dir='UP',   gates=['g_grandparent_1h_slope_strong_with', 'g_stoch_with', 'g_vol_high']),
]

# ============================== Evaluate ==============================
rows_out = []
per_fire_dump = {}  # rank -> sub df for plots
for sl in SLEEVES:
    rank = sl['rank']; off = sl['off']; direction = sl['dir']; gates = sl['gates']
    log(f"\n=== rank={rank} off={off} dir={direction} gates={'+'.join(gates)} ===")
    sub_df = df[(df.fire_offset_s == off) & (df.direction == direction)].copy()
    log(f"  off+dir slice: n={len(sub_df)}")
    # Apply gates
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates:
        if g not in sub_df.columns:
            log(f"  MISSING GATE {g}")
            m &= False
            break
        m &= (sub_df[g].values == 1)
    sub = sub_df[m].copy()
    log(f"  after gates: n={len(sub)}")
    if len(sub) == 0:
        rows_out.append(dict(rank=rank, off=off, dir=direction, gates='+'.join(gates), error='no fires'))
        continue
    # Splits
    tr = sub[sub.split == 'train']
    vl = sub[sub.split == 'val']
    lk = sub[sub.split == 'lockbox']
    mt = metrics(tr); mv = metrics(vl); ml = metrics(lk); mf = metrics(sub)
    # bootstrap p on full and lock
    bp_full = bootstrap_p(sub[PNL].values)
    bp_lock = bootstrap_p(lk[PNL].values)
    ci_lo_full, ci_hi_full = bootstrap_ci(sub[PNL].values)
    ci_lo_lock, ci_hi_lock = bootstrap_ci(lk[PNL].values)
    # projections — fires-per-day extrapolation to 32d
    proj_32d_lock = (ml['dpt'] * ml['n'] / lock_days * 32.66) if (lock_days > 0 and ml['n'] > 0) else 0
    proj_full = (mf['dpt'] * mf['n'] / total_days * 32.66) if mf['n'] > 0 else 0
    proj_honest = min(proj_32d_lock, proj_full)

    log(f"  TRAIN  n={mt['n']:3} WR={mt['wr']:.3f} $/tr=${mt['dpt']:+.3f} sum=${mt['total_pnl']:+.2f}")
    log(f"  VAL    n={mv['n']:3} WR={mv['wr']:.3f} $/tr=${mv['dpt']:+.3f} sum=${mv['total_pnl']:+.2f}")
    log(f"  LOCK   n={ml['n']:3} WR={ml['wr']:.3f} $/tr=${ml['dpt']:+.3f} sum=${ml['total_pnl']:+.2f}  DD=${ml['max_dd']:.2f}")
    log(f"  FULL   n={mf['n']:3} WR={mf['wr']:.3f} $/tr=${mf['dpt']:+.3f} sum=${mf['total_pnl']:+.2f}  DD=${mf['max_dd']:.2f}  LS={mf['loss_streak']}")
    log(f"  bootstrap_p_full={bp_full:.4f}  bootstrap_p_lock={bp_lock:.4f}")
    log(f"  proj_32d=${proj_32d_lock:+.2f}  proj_full=${proj_full:+.2f}  proj_honest=${proj_honest:+.2f}")
    rows_out.append(dict(
        rank=rank, off=off, dir=direction, gates='+'.join(gates),
        n_train=mt['n'], wr_train=mt['wr'], dpt_train=mt['dpt'],
        n_val=mv['n'], wr_val=mv['wr'], dpt_val=mv['dpt'],
        n_lock=ml['n'], wr_lock=ml['wr'], dpt_lock=ml['dpt'],
        n_full=mf['n'], wr_full=mf['wr'], dpt_full=mf['dpt'],
        sum_full=mf['total_pnl'], dd_full=mf['max_dd'],
        loss_streak_full=mf['loss_streak'], sharpe_full=mf['sharpe'],
        bootstrap_p_full=bp_full, bootstrap_p_lock=bp_lock,
        ci_lo_full=ci_lo_full, ci_hi_full=ci_hi_full,
        ci_lo_lock=ci_lo_lock, ci_hi_lock=ci_hi_lock,
        proj_32d_lock=proj_32d_lock, proj_full=proj_full, proj_honest=proj_honest,
        max_pnl_full=float(sub[PNL].max()), min_pnl_full=float(sub[PNL].min()),
    ))
    per_fire_dump[rank] = sub.copy()

out_csv = f"{OUTDIR}/top_5_candidates_v8_CORRECTED.csv"
pd.DataFrame(rows_out).to_csv(out_csv, index=False)
log(f"\nsaved {out_csv}")

# ============================== Plots ==============================
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

for rank, sub in per_fire_dump.items():
    sub_sorted = sub.sort_values('fire_us').copy()
    cum_pnl = sub_sorted[PNL].cumsum().values
    times = pd.to_datetime(sub_sorted.fire_us, unit='us', utc=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times, cum_pnl, '-', lw=1.4, color='tab:blue')
    ax.axhline(0, color='k', lw=0.5, alpha=0.5)
    # Split boundaries
    ax.axvline(t_train_end, color='orange', lw=0.7, alpha=0.5, label='train end')
    ax.axvline(t_val_end, color='red', lw=0.7, alpha=0.5, label='val end')
    final = cum_pnl[-1]
    title = f"Sleeve #{rank} (CORRECTED $25): {[s['gates'] for s in SLEEVES if s['rank']==rank][0]}"
    ax.set_title(f"{title}\nn={len(sub_sorted)} final=${final:+.2f}", fontsize=9)
    ax.set_ylabel('Cumulative PnL ($, $25 stake)')
    ax.legend(loc='best', fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    plot_path = f"{OUTDIR}/cum_pnl_sleeve_{rank}_CORRECTED.png"
    fig.savefig(plot_path, dpi=110)
    plt.close(fig)
    log(f"  plot saved: {plot_path}")

log("DONE")
