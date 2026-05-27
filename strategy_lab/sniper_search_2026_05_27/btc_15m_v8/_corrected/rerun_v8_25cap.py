"""ALTERNATIVE rerun assuming user's preferred convention:
$25 = FIXED MAX PAYOUT (buy 25 shares max, regardless of vwap).
Per-fire PnL is capped at [-$25, +$24.50].

This is the "cap at \$25 stake" interpretation from the user prompt.
"""
import os, sys, time
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8/_corrected"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading V8 panel")
df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
df = df[(df.asset == 'BTC') & (df.tf == '15m')].copy()
log(f"  BTC 15m rows: {len(df)}")

# Splits (same as corrected)
total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
total_days = total_secs / 86400
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)
df['split'] = np.where(df.fire_date < t_train_end, 'train',
              np.where(df.fire_date < t_val_end, 'val', 'lockbox'))
train_days = (t_train_end - t_min).total_seconds() / 86400
val_days = (t_val_end - t_train_end).total_seconds() / 86400
lock_days = (df.fire_date.max() - t_val_end).total_seconds() / 86400

# CONVENTION: $25 = max payout.
# 25 shares × (1 if won else 0) − 25 × vwap × shares_bought
# legacy fee: 2% on win profit only.
# net_won = 25 × (1 − vwap) × 0.98
# net_lost = −25 × vwap
def compute_25_capped(sub):
    vwap = sub['entry_vwap'].values
    won = sub['won'].values
    # 25-share fixed allocation
    pnl = np.where(won == 1,
                   25.0 * (1.0 - vwap) * 0.98,
                   -25.0 * vwap)
    return pnl

# ============================== Metric helpers ==============================
def metrics_25cap(sub):
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, total_pnl=0.0, max_dd=np.nan,
                    loss_streak=np.nan, sharpe=np.nan)
    pnl = compute_25_capped(sub)
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
                loss_streak=max_streak, sharpe=sharpe, pnl_arr=pnl)

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

SLEEVES = [
    dict(rank=1, off=600, dir='DOWN', gates=['g_btc_sol_confluence_5m_with', 'g_liq_shock_against']),
    dict(rank=2, off=600, dir='DOWN', gates=['g_xa_unanimity_5m_with', 'g_liq_shock_against']),
    dict(rank=3, off=600, dir='DOWN', gates=['g_btc_eth_confluence_5m_with', 'g_di_agrees', 'g_liq_shock_against']),
    dict(rank=4, off=720, dir='UP',   gates=['g_btc_eth_divergence', 'g_stoch_with', 'g_vol_contracting']),
    dict(rank=5, off=720, dir='UP',   gates=['g_grandparent_1h_slope_strong_with', 'g_stoch_with', 'g_vol_high']),
]

rows = []
for sl in SLEEVES:
    rank = sl['rank']; off = sl['off']; direction = sl['dir']; gates = sl['gates']
    log(f"\n=== rank={rank} off={off} dir={direction} gates={'+'.join(gates)} ===")
    sub_df = df[(df.fire_offset_s == off) & (df.direction == direction)].copy()
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates:
        m &= (sub_df[g].values == 1)
    sub = sub_df[m].copy()
    tr = sub[sub.split == 'train']
    vl = sub[sub.split == 'val']
    lk = sub[sub.split == 'lockbox']
    mt = metrics_25cap(tr); mv = metrics_25cap(vl); ml = metrics_25cap(lk); mf = metrics_25cap(sub)
    bp_full = bootstrap_p(mf['pnl_arr'])
    bp_lock = bootstrap_p(ml['pnl_arr']) if ml['n'] > 0 else 1.0
    proj_32d = (ml['dpt'] * ml['n'] / lock_days * 32.66) if (lock_days > 0 and ml['n'] > 0) else 0
    proj_full = (mf['dpt'] * mf['n'] / total_days * 32.66) if mf['n'] > 0 else 0
    proj_honest = min(proj_32d, proj_full)

    log(f"  TRAIN  n={mt['n']:3} WR={mt['wr']:.3f} $/tr=${mt['dpt']:+.3f} sum=${mt['total_pnl']:+.2f}")
    log(f"  VAL    n={mv['n']:3} WR={mv['wr']:.3f} $/tr=${mv['dpt']:+.3f} sum=${mv['total_pnl']:+.2f}")
    log(f"  LOCK   n={ml['n']:3} WR={ml['wr']:.3f} $/tr=${ml['dpt']:+.3f} sum=${ml['total_pnl']:+.2f}  DD=${ml['max_dd']:.2f}")
    log(f"  FULL   n={mf['n']:3} WR={mf['wr']:.3f} $/tr=${mf['dpt']:+.3f} sum=${mf['total_pnl']:+.2f}  DD=${mf['max_dd']:.2f}  LS={mf['loss_streak']}")
    log(f"  bootstrap_p_full={bp_full:.4f}  bootstrap_p_lock={bp_lock:.4f}")
    log(f"  proj_32d=${proj_32d:+.2f}  proj_full=${proj_full:+.2f}  proj_honest=${proj_honest:+.2f}")
    log(f"  per-fire range: min=${mf['pnl_arr'].min():+.2f}  max=${mf['pnl_arr'].max():+.2f}")
    rows.append(dict(
        rank=rank, off=off, dir=direction, gates='+'.join(gates),
        n_train=mt['n'], wr_train=mt['wr'], dpt_train=mt['dpt'],
        n_val=mv['n'], wr_val=mv['wr'], dpt_val=mv['dpt'],
        n_lock=ml['n'], wr_lock=ml['wr'], dpt_lock=ml['dpt'],
        n_full=mf['n'], wr_full=mf['wr'], dpt_full=mf['dpt'],
        sum_full=mf['total_pnl'], dd_full=mf['max_dd'],
        loss_streak_full=mf['loss_streak'], sharpe_full=mf['sharpe'],
        bootstrap_p_full=bp_full, bootstrap_p_lock=bp_lock,
        proj_32d_lock=proj_32d, proj_full=proj_full, proj_honest=proj_honest,
        max_pnl_full=float(mf['pnl_arr'].max()), min_pnl_full=float(mf['pnl_arr'].min()),
    ))

out_csv = f"{OUTDIR}/top_5_candidates_v8_CORRECTED_25CAP.csv"
pd.DataFrame(rows).to_csv(out_csv, index=False)
log(f"\nsaved {out_csv}")
log("DONE")
