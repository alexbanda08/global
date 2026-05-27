"""V8 BTC 15m CLEAN search — uses ONLY gates with healthy coverage through May 26.

Excludes 30 stale gates (hurst, ret_2m, f7_rsi, imb*, hawkes, queue, sms, lm, rv) that have 0 fires on May 23-26.

Rounds 1-4 same combinatorial sweep, but constrained to:
- gates with late_ratio >= 0.5
- v8 strict pass: train+val+lock all $/tr > 0
"""
import os, sys, time, itertools
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading V8 panel + healthy gate list")
df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)

# Load coverage audit
audit = pd.read_csv(f"{OUTDIR}/v8_gate_coverage_audit.csv")
healthy = set(audit[audit.late_ratio > 0.5].gate.tolist())
log(f"healthy gates: {len(healthy)}")

# Splits
total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
total_days = total_secs / 86400
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)
df['split'] = np.where(df.fire_date < t_train_end, 'train',
              np.where(df.fire_date < t_val_end, 'val', 'lockbox'))
train_days = (t_train_end-t_min).total_seconds()/86400
val_days = (t_val_end-t_train_end).total_seconds()/86400
lock_days = (df.fire_date.max()-t_val_end).total_seconds()/86400

PNL = 'pnl_legacy_usd'

def metrics(sub):
    n = len(sub)
    if n == 0: return dict(n=0, wr=np.nan, dpt=np.nan, total=np.nan, dd=np.nan, ls=np.nan)
    pnl25 = sub[PNL].values * 25.0
    cum = pnl25.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    losses = (pnl25 < 0).astype(int)
    s = 0; ls = 0
    for L in losses:
        if L == 1: s += 1; ls = max(ls, s)
        else: s = 0
    return dict(n=n, wr=sub.won.mean(), dpt=pnl25.mean(), total=pnl25.sum(), dd=dd, ls=ls)

def eval_combo(sub_df, gates):
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates:
        m &= (sub_df[g].values == 1)
    sub = sub_df[m]
    if len(sub) < 10:
        return None
    tr = sub[sub.split=='train']
    vl = sub[sub.split=='val']
    lk = sub[sub.split=='lockbox']
    mt = metrics(tr); mv = metrics(vl); ml = metrics(lk); mf = metrics(sub)
    proj_32d = (ml['total'] / lock_days) * 32.66 if lock_days else 0
    proj_full = (mf['total'] / total_days) * 32.66
    proj_honest = min(proj_32d, proj_full)
    return dict(
        gates='+'.join(gates),
        n_train=mt['n'], wr_train=mt['wr'], dpt_train=mt['dpt'],
        n_val=mv['n'], wr_val=mv['wr'], dpt_val=mv['dpt'],
        n_lock=ml['n'], wr_lock=ml['wr'], dpt_lock=ml['dpt'],
        n_full=mf['n'], wr_full=mf['wr'], dpt_full=mf['dpt'],
        dd_lock=ml['dd'], ls_lock=ml['ls'],
        dd_full=mf['dd'], ls_full=mf['ls'],
        proj_32d=proj_32d, proj_full=proj_full, proj_honest=proj_honest,
    )

# Healthy gate set (combine V8 new + V7 strong, intersect with healthy)
V8_NEW = ['g_tod_asia_morning','g_tod_european_morning','g_tod_us_afternoon','g_tod_us_evening',
    'g_grandparent_1h_trend_with','g_grandparent_1h_ranging','g_grandparent_1h_slope_with','g_grandparent_1h_slope_strong_with',
    'g_xa_unanimity_5m_with','g_xa_unanimity_15m_with','g_btc_eth_confluence_5m_with',
    'g_btc_sol_confluence_5m_with','g_xa_majority_5m_with','g_btc_eth_divergence',
    'g_liq_shock_with','g_liq_shock_against','g_liq_calm',
    'g_btc_eth_confluence_15m_with']
V7_BASE = ['g_tr_above_ema200','g_tr_above_ema800','g_tr_above_pp','g_tr_above_cloud','g_tr_in_active_session',
    'g_tr_stack_with','g_tr_stack_full_with',
    'g_mp_skew_strong_with','g_mp_skew_with','g_mp_no_extreme','g_mp_no_extreme_150',
    'g_rf_with','g_rf_strong','g_rf_fresh',
    'g_ribbon_agrees','g_ribbon_slope_with','g_tight_ribbon',
    'g_trend_slope_with','g_trend_slope_strong_with',
    'g_regime_ranging',
    'g_adx_trending','g_adx_strong','g_di_agrees',
    'g_bb_pos_with','g_stoch_with','g_mfi_with','g_cci_with',
    'g_within_dev','g_dev_extreme',
    'g_vol_high','g_vol_expanding','g_vol_contracting',]
ALL_CANDIDATE = list(dict.fromkeys(V7_BASE + V8_NEW))
ok_gates = [g for g in ALL_CANDIDATE if g in df.columns and g in healthy and 200 <= (df[g]==1).sum() <= len(df)*0.9]
log(f"final candidate gates after healthy filter: {len(ok_gates)}")
log(f"  V8 new (healthy): {[g for g in V8_NEW if g in ok_gates]}")
log(f"  V7 base (healthy): {[g for g in V7_BASE if g in ok_gates][:20]}...")

OFFSETS = sorted(df.fire_offset_s.unique())
DIRS = ['UP','DOWN']

all_results = []
log("Round 1: baseline + single-leg")
for off in OFFSETS:
    for direction in DIRS:
        sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
        if len(sub_df) < 100: continue
        r = eval_combo(sub_df, ())
        if r:
            r['off']=off; r['dir']=direction; r['n_gates']=0
            all_results.append(r)
        for g in ok_gates:
            r = eval_combo(sub_df, (g,))
            if r:
                r['off']=off; r['dir']=direction; r['n_gates']=1
                all_results.append(r)

log("Round 2: 2-leg combos")
for off in OFFSETS:
    for direction in DIRS:
        sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
        if len(sub_df) < 100: continue
        for g1, g2 in itertools.combinations(ok_gates, 2):
            if (sub_df[g1]==1).sum() < 30 or (sub_df[g2]==1).sum() < 30: continue
            r = eval_combo(sub_df, (g1, g2))
            if r and r['n_full'] >= 30:
                r['off']=off; r['dir']=direction; r['n_gates']=2
                all_results.append(r)

log(f"After R2: {len(all_results)}")

# Round 3: 3-leg from top R2 seeds per (off,dir)
df_r2 = pd.DataFrame([x for x in all_results if x['n_gates']==2])
top_seeds = (df_r2.sort_values('proj_honest', ascending=False)
                .groupby(['off','dir']).head(10))

r3_results = []
for (off, direction), grp in top_seeds.groupby(['off','dir']):
    sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
    seed_gates = sorted({g for gs in grp.gates for g in gs.split('+')})
    if len(seed_gates) < 3: continue
    for trip in itertools.combinations(seed_gates, 3):
        r = eval_combo(sub_df, trip)
        if r and r['n_full'] >= 25:
            r['off']=off; r['dir']=direction; r['n_gates']=3
            r3_results.append(r)
all_results.extend(r3_results)
log(f"After R3: {len(all_results)}")

# Round 4: 4-leg from top R3 seeds
df_r3 = pd.DataFrame(r3_results) if r3_results else pd.DataFrame()
if len(df_r3) > 0:
    top_r3 = (df_r3.sort_values('proj_honest', ascending=False)
                  .groupby(['off','dir']).head(8))
    r4_results = []
    for (off, direction), grp in top_r3.groupby(['off','dir']):
        sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
        seed_gates = sorted({g for gs in grp.gates for g in gs.split('+')})
        if len(seed_gates) < 4: continue
        for quad in itertools.combinations(seed_gates, 4):
            r = eval_combo(sub_df, quad)
            if r and r['n_full'] >= 20:
                r['off']=off; r['dir']=direction; r['n_gates']=4
                r4_results.append(r)
    all_results.extend(r4_results)
    log(f"After R4: {len(all_results)}")

# Filter
res = pd.DataFrame(all_results)
log(f"TOTAL CLEAN combos: {len(res)}")

# Strict v8 pass: train+val+lock all > 0, WR_lock >= 55%, $/tr_lock >= $4
res['v8_strict'] = (
    (res.dpt_train > 0) & (res.dpt_val > 0) & (res.dpt_lock > 0) &
    (res.wr_lock >= 0.55) & (res.dpt_lock >= 4) &
    (res.n_lock >= 5) & (res.n_full >= 30) &
    (res.dd_lock >= -500) & (res.ls_lock <= 14)
)

# Honest projection >= $1000 (1k+ per 32.7d)
strict = res[res.v8_strict].sort_values('proj_honest', ascending=False)
log(f"STRICT clean survivors: {len(strict)}")

# Top 20
print()
print("="*130)
print("V8 BTC 15m CLEAN (healthy-gates-only) — TOP 20 STRICT SURVIVORS")
print("="*130)
for _, r in strict.head(20).iterrows():
    print(f"  off={r['off']:3} dir={r['dir']:4} n_gates={r['n_gates']}  "
          f"n_full={r['n_full']:4} n_lock={r['n_lock']:3}  "
          f"WR(t/v/l)=({r['wr_train']:.2f}/{r['wr_val']:.2f}/{r['wr_lock']:.2f})  "
          f"$/tr(t/v/l)=(${r['dpt_train']:+.1f}/${r['dpt_val']:+.1f}/${r['dpt_lock']:+.1f})  "
          f"proj_honest=${r['proj_honest']:+.0f}  DD_lock=${r['dd_lock']:+.0f}")
    print(f"        gates: {r['gates']}")

strict.to_csv(f"{OUTDIR}/v8_strict_survivors_CLEAN.csv", index=False)
res.to_csv(f"{OUTDIR}/v8_combinatorial_all_CLEAN.csv", index=False)
log(f"saved CLEAN survivors: {len(strict)}")

# Relaxed (lock $/tr >= 8 even if train/val flat)
res['v8_relax'] = (
    (res.dpt_train + res.dpt_val >= 0) &
    (res.dpt_lock >= 8) & (res.wr_lock >= 0.55) &
    (res.n_lock >= 5) & (res.n_full >= 30) &
    (res.dd_lock >= -500)
)
relax = res[res.v8_relax & ~res.v8_strict].sort_values('proj_honest', ascending=False)
log(f"Relaxed (lock-only profitable, train+val avg >= 0): {len(relax)}")
if len(relax):
    print()
    print("--- TOP 10 RELAXED (lock-only profitable) ---")
    for _, r in relax.head(10).iterrows():
        print(f"  off={r['off']:3} dir={r['dir']:4} n_g={r['n_gates']}  "
              f"n_full={r['n_full']:4} n_lock={r['n_lock']:3}  "
              f"WR(t/v/l)=({r['wr_train']:.2f}/{r['wr_val']:.2f}/{r['wr_lock']:.2f})  "
              f"$/tr(t/v/l)=(${r['dpt_train']:+.1f}/${r['dpt_val']:+.1f}/${r['dpt_lock']:+.1f})  "
              f"proj=${r['proj_honest']:+.0f}")
        print(f"        gates: {r['gates']}")

log("DONE")
