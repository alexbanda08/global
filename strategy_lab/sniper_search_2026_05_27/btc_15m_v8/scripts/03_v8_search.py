"""V8 BTC 15m gate combinatorial search.

Uses the V8 panel (251 cols) with new gates:
- TOD (asia/european/us_afternoon/us_evening) — Path K
- 1h grandparent regime (trend_with, ranging, slope_with) — Path L
- 2-asset confluence (xa_unanimity, btc_eth, btc_sol, majority) — Path J
- Liquidity shock (with/against/calm) — Path P

Splits (full window, 32.66d):
- train: first 60% (≈19.6d)  Apr 24 → May 13.6
- val:   next 20% (≈6.5d)    May 13.6 → May 20.1
- lock:  last 20% (≈6.5d)    May 20.1 → May 26.6

Search strategy:
1. Per offset × direction, build a list of "high-promise" base gates (V7 winners + new V8)
2. Sweep 2-leg, 3-leg, 4-leg combos
3. Filter by train+val+lock all $/tr > $4, lock WR ≥ 55%
4. Score by min(proj_32d, proj_full) (honest projection)
5. Add TOD-stratified analysis to find TOD-specialized sleeves
"""
import os, sys, time, itertools, json
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading V8 panel")
df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
log(f"  rows: {len(df)}, cols: {len(df.columns)}")
log(f"  date range: {df.fire_date.min()} -> {df.fire_date.max()}")

# ============================== Splits (60/20/20 of FULL window) ==============================
total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
total_days = total_secs / 86400
log(f"  total span: {total_days:.2f}d")
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)

df['split'] = np.where(df.fire_date < t_train_end, 'train',
              np.where(df.fire_date < t_val_end, 'val', 'lockbox'))
log(f"  train: {(df.split=='train').sum()} fires, days={(t_train_end-t_min).total_seconds()/86400:.2f}")
log(f"  val:   {(df.split=='val').sum()} fires,   days={(t_val_end-t_train_end).total_seconds()/86400:.2f}")
log(f"  lock:  {(df.split=='lockbox').sum()} fires,  days={(df.fire_date.max()-t_val_end).total_seconds()/86400:.2f}")

train_days = (t_train_end-t_min).total_seconds()/86400
val_days = (t_val_end-t_train_end).total_seconds()/86400
lock_days = (df.fire_date.max()-t_val_end).total_seconds()/86400

# pnl col
PNL = 'pnl_legacy_usd'   # legacy 2%-on-profit fee (matches production)

# ============================== Bootstrap p-value helper ==============================
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
    return (boots >= obs).mean()

def metrics(sub, label):
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, total_pnl=np.nan, max_dd=np.nan, loss_streak=np.nan, sharpe=np.nan)
    wr = sub.won.mean()
    pnl_per_unit = sub[PNL].values
    # at $25 stake (legacy pnl col is at $1)
    pnl_25 = pnl_per_unit * 25.0
    dpt_25 = pnl_25.mean()
    total = pnl_25.sum()
    # running PnL
    cum = pnl_25.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = dd.min()
    # loss streak
    losses = (pnl_25 < 0).astype(int)
    streak = 0; max_streak = 0
    for l in losses:
        if l == 1:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    sharpe = (dpt_25 / pnl_25.std()) * np.sqrt(252) if pnl_25.std() > 0 else 0.0
    return dict(n=n, wr=wr, dpt=dpt_25, total_pnl=total, max_dd=max_dd, loss_streak=max_streak, sharpe=sharpe)

# ============================== Sweep candidate gates ==============================
# Pick top-promise gates: V7 winners + V8 new
V8_NEW_GATES = [
    'g_tod_asia_morning','g_tod_european_morning','g_tod_us_afternoon','g_tod_us_evening',
    'g_grandparent_1h_trend_with','g_grandparent_1h_ranging','g_grandparent_1h_slope_with','g_grandparent_1h_slope_strong_with',
    'g_xa_unanimity_5m_with','g_xa_unanimity_15m_with','g_btc_eth_confluence_5m_with',
    'g_btc_sol_confluence_5m_with','g_xa_majority_5m_with','g_btc_eth_divergence',
    'g_liq_shock_with','g_liq_shock_against','g_liq_calm',
]

V7_STRONG_GATES = [
    'g_tr_above_ema200','g_tr_above_ema800','g_tr_above_pp','g_tr_above_cloud','g_tr_in_active_session',
    'g_tr_stack_with','g_tr_stack_full_with',
    'g_mp_skew_strong_with','g_mp_skew_with','g_mp_no_extreme','g_mp_no_extreme_150',
    'g_rf_with','g_rf_strong','g_rf_fresh',
    'g_ribbon_agrees','g_ribbon_slope_with','g_tight_ribbon',
    'g_trend_slope_with','g_trend_slope_strong_with',
    'g_regime_trending_with','g_regime_ranging','g_regime_trending_either',
    'g_adx_trending','g_adx_strong','g_di_agrees',
    'g_imb5_with','g_imb5_strong_with',
    'g_hurst_trending_with','g_hurst_strong_trending',
    'g_ret_2m_with','g_ret_2m_strong_with',
    'g_bb_pos_with','g_stoch_with','g_mfi_with','g_cci_with',
    'g_within_dev','g_dev_extreme',
    'g_vol_high','g_vol_expanding','g_vol_contracting',
]

ALL_GATES = list(dict.fromkeys(V7_STRONG_GATES + V8_NEW_GATES))   # dedup, keep order

# Filter to gates with min coverage 200 fires
ok_gates = []
for g in ALL_GATES:
    if g not in df.columns: continue
    s = (df[g]==1).sum()
    if 200 <= s <= len(df)*0.9:
        ok_gates.append(g)

log(f"candidate gates after coverage filter (200..90%): {len(ok_gates)}")

# Per offset × direction
OFFSETS = sorted(df.fire_offset_s.unique())
DIRS = ['UP','DOWN']

# Strategy:
# Round 1 — single-leg gates (find best baselines per off/dir)
# Round 2 — 2-leg combos
# Round 3 — 3-leg combos (using top 12 from R2)
# Round 4 — 4-leg combos (using top 8 from R3)

def eval_combo(sub_df, gates, label):
    """sub_df is already filtered to (offset, direction). gates is tuple of gate names."""
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates:
        m &= (sub_df[g].values == 1)
    sub = sub_df[m]
    if len(sub) < 10:
        return None
    tr = sub[sub.split=='train']
    vl = sub[sub.split=='val']
    lk = sub[sub.split=='lockbox']
    mt = metrics(tr, 'train')
    mv = metrics(vl, 'val')
    ml = metrics(lk, 'lock')
    mf = metrics(sub, 'full')
    # honest projection
    proj_32d = ml['dpt']*ml['n']/lock_days*32.66 if (ml['n']>0 and lock_days>0) else 0
    proj_full = mf['dpt']*mf['n']/total_days*32.66 if mf['n']>0 else 0
    proj_honest = min(proj_32d, proj_full)
    return {
        'gates': '+'.join(gates),
        'n_train':mt['n'],'wr_train':mt['wr'],'dpt_train':mt['dpt'],
        'n_val':mv['n'],'wr_val':mv['wr'],'dpt_val':mv['dpt'],
        'n_lock':ml['n'],'wr_lock':ml['wr'],'dpt_lock':ml['dpt'],
        'n_full':mf['n'],'wr_full':mf['wr'],'dpt_full':mf['dpt'],
        'max_dd_lock':ml['max_dd'],'loss_streak_lock':ml['loss_streak'],
        'sharpe_lock':ml['sharpe'],
        'proj_32d':proj_32d,'proj_full':proj_full,'proj_honest':proj_honest,
    }

# Run search
all_results = []
log("Round 1: single-leg + offset+direction baselines")
for off in OFFSETS:
    for direction in DIRS:
        sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
        if len(sub_df) < 100: continue
        # Baseline (no gates)
        r = eval_combo(sub_df, (), 'baseline')
        if r:
            r['off'] = off; r['dir'] = direction
            r['n_gates'] = 0
            all_results.append(r)
        # Single
        for g in ok_gates:
            r = eval_combo(sub_df, (g,), 'single')
            if r:
                r['off'] = off; r['dir'] = direction; r['n_gates'] = 1
                all_results.append(r)

log(f"Round 1 done, {len(all_results)} entries")

log("Round 2: 2-leg combos")
# Use top-30 single-leg per (off,dir) as seeds — to keep search manageable
for off in OFFSETS:
    for direction in DIRS:
        sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
        if len(sub_df) < 100: continue
        # All 2-leg combos from ok_gates (size limit)
        for g1, g2 in itertools.combinations(ok_gates, 2):
            # quick pre-filter: skip if either gate is rare in this off+dir slice
            if (sub_df[g1]==1).sum() < 30 or (sub_df[g2]==1).sum() < 30: continue
            r = eval_combo(sub_df, (g1, g2), '2leg')
            if r and r['n_full'] >= 30:
                r['off'] = off; r['dir'] = direction; r['n_gates'] = 2
                all_results.append(r)

log(f"Round 2 done, {len(all_results)} total entries")

# Save round 2 intermediate
df_r2 = pd.DataFrame(all_results)
df_r2.to_csv(f"{OUTDIR}/v8_combinatorial_r2.csv", index=False)
log(f"saved r2: {len(df_r2)}")

# Top N from R2 per off+dir for R3 seeding
log("Round 3: 3-leg combos (top-seeds from R2)")
# Build R3 search via top-12 R2 sleeves per (off,dir) ranked by proj_honest
df_r2['v8_pass'] = (df_r2.dpt_train > 0) & (df_r2.dpt_val > 0) & (df_r2.dpt_lock > 0) & (df_r2.wr_lock >= 0.55) & (df_r2.n_lock >= 5)
top_seeds = (df_r2[df_r2.n_gates==2]
             .sort_values('proj_honest', ascending=False)
             .groupby(['off','dir']).head(8))
log(f"  R3 seeds: {len(top_seeds)}")

# Build the union of gates that appear in top-8 seeds per (off,dir), then 3-leg combos within
r3_results = []
for (off, direction), grp in top_seeds.groupby(['off','dir']):
    sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
    seed_gates = set()
    for gs in grp.gates:
        for g in gs.split('+'):
            seed_gates.add(g)
    seed_gates = sorted(seed_gates)
    if len(seed_gates) < 3: continue
    for trip in itertools.combinations(seed_gates, 3):
        r = eval_combo(sub_df, trip, '3leg')
        if r and r['n_full'] >= 20:
            r['off'] = off; r['dir'] = direction; r['n_gates'] = 3
            r3_results.append(r)

all_results.extend(r3_results)
log(f"Round 3 done: +{len(r3_results)} 3-leg combos")

# Round 4: 4-leg, top-6 R3 seeds per (off,dir)
log("Round 4: 4-leg combos")
df_r3 = pd.DataFrame(r3_results)
if len(df_r3) > 0:
    df_r3['v8_pass'] = (df_r3.dpt_train>0)&(df_r3.dpt_val>0)&(df_r3.dpt_lock>0)&(df_r3.wr_lock>=0.55)&(df_r3.n_lock>=5)
    top_r3 = (df_r3.sort_values('proj_honest', ascending=False)
                  .groupby(['off','dir']).head(6))
    r4_results = []
    for (off, direction), grp in top_r3.groupby(['off','dir']):
        sub_df = df[(df.fire_offset_s==off) & (df.direction==direction)].copy()
        seed_gates = set()
        for gs in grp.gates:
            for g in gs.split('+'):
                seed_gates.add(g)
        seed_gates = sorted(seed_gates)
        if len(seed_gates) < 4: continue
        for quad in itertools.combinations(seed_gates, 4):
            r = eval_combo(sub_df, quad, '4leg')
            if r and r['n_full'] >= 15:
                r['off'] = off; r['dir'] = direction; r['n_gates'] = 4
                r4_results.append(r)
    all_results.extend(r4_results)
    log(f"Round 4 done: +{len(r4_results)} 4-leg combos")

# ============================== Final filter & ranking ==============================
res = pd.DataFrame(all_results)
log(f"TOTAL combos evaluated: {len(res)}")

# V8 target: train+val+lock all dpt > 0, lock WR >= 55%, dpt_lock >= $4, n_lock >= 5, max_dd_lock >= -500
res['v8_pass'] = (
    (res.dpt_train > 0) &
    (res.dpt_val   > 0) &
    (res.dpt_lock  > 0) &
    (res.wr_lock   >= 0.55) &
    (res.dpt_lock  >= 4) &
    (res.n_lock    >= 5) &
    (res.max_dd_lock >= -500) &
    (res.loss_streak_lock <= 14) &
    (res.n_full >= 30)
)

survivors = res[res.v8_pass].copy()
log(f"V8-passing survivors: {len(survivors)}")

# Also relaxed bucket: lock dpt>=$8 + lock WR>=55% (slightly relaxed train/val)
res['v8_relax'] = (
    (res.dpt_train + res.dpt_val > 0) &
    (res.dpt_lock  >= 8) &
    (res.wr_lock   >= 0.55) &
    (res.n_lock    >= 5) &
    (res.max_dd_lock >= -500) &
    (res.n_full >= 25)
)
relaxed = res[res.v8_relax & ~res.v8_pass].copy()
log(f"V8 relaxed: {len(relaxed)}")

# Compute bootstrap p on lockbox for top 30 sleeves
top_for_bs = pd.concat([survivors.sort_values('proj_honest', ascending=False).head(20),
                        relaxed.sort_values('proj_honest', ascending=False).head(15)]).drop_duplicates()
log(f"Computing bootstrap p for {len(top_for_bs)} top sleeves...")
def get_lock_pnls(row):
    sub_df = df[(df.fire_offset_s==row['off']) & (df.direction==row['dir']) & (df.split=='lockbox')]
    m = np.ones(len(sub_df), dtype=bool)
    for g in row['gates'].split('+'):
        if g and g in sub_df.columns:
            m &= (sub_df[g].values == 1)
    sub = sub_df[m]
    return sub[PNL].values * 25.0   # at $25 stake

p_vals = []
for _, row in top_for_bs.iterrows():
    pnls = get_lock_pnls(row)
    p = bootstrap_p(pnls)
    p_vals.append(p)
top_for_bs['bootstrap_p_lock'] = p_vals
top_for_bs.sort_values('proj_honest', ascending=False).to_csv(f"{OUTDIR}/v8_top_candidates_with_bootstrap.csv", index=False)

# Save full results
res.to_csv(f"{OUTDIR}/v8_combinatorial_all.csv", index=False)
log(f"saved all: {OUTDIR}/v8_combinatorial_all.csv ({len(res)} rows)")

# Top 5 final
TOP_FINAL = top_for_bs.sort_values('proj_honest', ascending=False).head(10)
TOP_FINAL.to_csv(f"{OUTDIR}/top_5_candidates_v8.csv", index=False)

# Print top-10
print()
print("="*120)
print("TOP 10 V8 BTC 15m SLEEVES (by proj_honest)")
print("="*120)
for _, r in TOP_FINAL.iterrows():
    print(f"  off={r['off']:3} dir={r['dir']:4} n_gates={r['n_gates']}  "
          f"n_full={r['n_full']:4} n_lock={r['n_lock']:3}  "
          f"WR_lock={r['wr_lock']:.3f}  $/tr_lock=${r['dpt_lock']:+.2f}  "
          f"$/tr_full=${r['dpt_full']:+.2f}  "
          f"proj_32d=${r['proj_32d']:+.0f} proj_full=${r['proj_full']:+.0f} proj_honest=${r['proj_honest']:+.0f}  "
          f"DD=${r['max_dd_lock']:+.0f}  loss_streak={r['loss_streak_lock']}  "
          f"p_lock={r.get('bootstrap_p_lock','N/A')}")
    print(f"        gates: {r['gates']}")
    print(f"        train: n={r['n_train']:3} WR={r['wr_train']:.3f} $/tr={r['dpt_train']:+.2f}    "
          f"val: n={r['n_val']:3} WR={r['wr_val']:.3f} $/tr={r['dpt_val']:+.2f}")
    print()

log("DONE")
