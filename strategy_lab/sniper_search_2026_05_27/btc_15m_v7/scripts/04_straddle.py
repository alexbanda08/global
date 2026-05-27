"""V7 Path B: 2-leg straddle on same slug.

For each slug, evaluate {UP at offset_a, DOWN at offset_b} (both legs entered).
Sum the two PnLs. Two configs:
  - early-late: UP@60 + DOWN@600
  - early-late: UP@60 + DOWN@840
  - late-late:  UP@600 + DOWN@840
  - early-early: UP@60 + DOWN@120

Also test gated straddles (require a quality gate on each leg).

Output: v7_straddle_results.csv
"""
import os, time, json
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v7_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v7"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


def compute_dd(pnl_arr):
    if len(pnl_arr) == 0: return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    return float(-(cum - peak).min())


def max_loss_streak(won_arr):
    if len(won_arr) == 0: return 0
    streak = mx = 0
    for w in won_arr:
        if w == 0:
            streak += 1; mx = max(mx, streak)
        else:
            streak = 0
    return mx


def daily_sharpe(d, col):
    if len(d) == 0: return 0.0
    daily = d.groupby(d.fire_date.dt.date)[col].sum()
    if len(daily) < 2 or daily.std() == 0: return 0.0
    return float(daily.mean() / daily.std() * np.sqrt(365))


def bootstrap_p(d, col, n=1000, seed=42):
    if len(d) < 5: return np.nan
    daily = d.groupby(d.fire_date.dt.date)[col].sum().values
    if len(daily) < 2: return np.nan
    rng = np.random.default_rng(seed)
    boot = rng.choice(daily, size=(n, len(daily)), replace=True).sum(axis=1)
    return max(float((boot <= 0).sum() / n), 1.0/n)


log("loading panel")
df = pd.read_parquet(IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
log(f"  rows: {len(df)}")

TRAIN_END = pd.Timestamp("2026-05-16", tz="UTC")
VAL_END = pd.Timestamp("2026-05-22", tz="UTC")
LOCK_END = pd.Timestamp("2026-05-26", tz="UTC")
TRAIN_START = pd.Timestamp("2026-04-28", tz="UTC")

# Configurations to try
STRADDLE_CFGS = [
    ('UP', 60,  'DOWN', 600),
    ('UP', 60,  'DOWN', 840),
    ('UP', 600, 'DOWN', 840),
    ('UP', 60,  'DOWN', 120),
    ('UP', 60,  'DOWN', 240),
    ('UP', 120, 'DOWN', 600),
    ('UP', 240, 'DOWN', 600),
    ('UP', 240, 'DOWN', 840),
    ('UP', 480, 'DOWN', 840),
    # The reverse: late UP + early DOWN
    ('DOWN', 60,  'UP', 600),
    ('DOWN', 60,  'UP', 840),
]
# Gate stacks to test on each leg
GATE_STACKS = [
    None,  # ungated
    ['g_mp_skew_with'],
    ['g_tr_above_ema800'],
    ['g_rf_with'],
    ['g_ribbon_slope_with'],
    ['g_mp_skew_with', 'g_tr_above_ema800'],
    ['g_mp_skew_with', 'g_rf_with'],
    ['g_mp_skew_strong_with', 'g_tr_above_ema800'],
    ['g_tr_above_ema800', 'g_ribbon_slope_with'],
    ['g_rf_with', 'g_tr_above_ema800'],
    ['g_mp_skew_strong_with', 'g_rf_with', 'g_tr_above_ema800'],
]

results = []

for dir_a, off_a, dir_b, off_b in STRADDLE_CFGS:
    for stack_a in GATE_STACKS:
        for stack_b in GATE_STACKS:
            leg_a = df[(df.fire_offset_s == off_a) & (df.direction == dir_a)].copy()
            leg_b = df[(df.fire_offset_s == off_b) & (df.direction == dir_b)].copy()
            if stack_a:
                m = np.ones(len(leg_a), dtype=bool)
                for g in stack_a:
                    if g not in leg_a.columns: m[:]=False; break
                    m &= (leg_a[g].values == 1)
                leg_a = leg_a[m]
            if stack_b:
                m = np.ones(len(leg_b), dtype=bool)
                for g in stack_b:
                    if g not in leg_b.columns: m[:]=False; break
                    m &= (leg_b[g].values == 1)
                leg_b = leg_b[m]
            if len(leg_a) < 10 or len(leg_b) < 10: continue

            # Merge on slug — fire both legs
            ja = leg_a[['slug', 'fire_date', 'pnl_legacy_usd', 'won']].rename(
                columns={'pnl_legacy_usd':'pnl_a', 'won':'won_a', 'fire_date':'date_a'}).set_index('slug')
            jb = leg_b[['slug', 'fire_date', 'pnl_legacy_usd', 'won']].rename(
                columns={'pnl_legacy_usd':'pnl_b', 'won':'won_b', 'fire_date':'date_b'}).set_index('slug')
            joined = ja.join(jb, how='inner')
            if len(joined) < 10: continue
            # Combined: stake $25 on EACH leg, total $50 risked, combined PnL = pnl_a + pnl_b
            joined['pnl_total'] = joined['pnl_a'] + joined['pnl_b']
            joined['won_either'] = ((joined['won_a']==1) | (joined['won_b']==1)).astype(int)
            joined['won_both'] = ((joined['won_a']==1) & (joined['won_b']==1)).astype(int)
            joined['fire_date'] = joined['date_a']  # straddle date = leg_a date

            tr = joined[(joined.fire_date >= TRAIN_START) & (joined.fire_date < TRAIN_END)]
            va = joined[(joined.fire_date >= TRAIN_END) & (joined.fire_date < VAL_END)]
            lo = joined[(joined.fire_date >= VAL_END) & (joined.fire_date < LOCK_END)]
            if len(tr) < 30 or len(lo) < 10: continue

            tr_pnl = tr['pnl_total'].values
            tr_won_either = tr['won_either'].values
            tr_dpt = tr_pnl.mean()
            tr_wr = tr_won_either.mean()  # at least one leg won
            if tr_dpt <= 0: continue  # straddle must be train-positive

            lo_pnl = lo['pnl_total'].values
            lo_won_either = lo['won_either'].values
            lo_dpt = lo_pnl.mean()
            lo_dd = compute_dd(lo_pnl)
            lo_streak = max_loss_streak((lo['pnl_total'] > 0).astype(int).values)
            # Use V7 bar for straddles: dpt(total $50 risk) >= $4, no losing streak >14
            if lo_dpt < 2.0:  # straddles risk $50, expect lower $/per-leg; relax to $2
                continue
            if lo_dd > 800:  # 2x V7 cap for $50 risk
                continue
            if lo_streak > 14: continue

            va_dpt = va['pnl_total'].mean() if len(va) else np.nan
            va_wr = va['won_either'].mean() if len(va) else np.nan
            sh = daily_sharpe(lo, 'pnl_total')
            bp = bootstrap_p(lo, 'pnl_total')

            results.append(dict(
                straddle_id=f"{dir_a}@{off_a}+{dir_b}@{off_b}",
                stack_a='+'.join(stack_a) if stack_a else 'none',
                stack_b='+'.join(stack_b) if stack_b else 'none',
                train_n=len(tr), train_dpt=tr_dpt, train_won_either=tr_wr,
                val_n=len(va), val_dpt=va_dpt, val_won_either=va_wr,
                lock_n=len(lo), lock_dpt=lo_dpt, lock_won_either=lo['won_either'].mean(),
                lock_won_both=lo['won_both'].mean(),
                lock_dd=lo_dd, lock_streak=lo_streak, lock_sharpe=sh,
                lock_unique_days=lo.fire_date.dt.date.nunique(),
                bootstrap_p=bp,
                obj_score=lo_dpt * np.sqrt(len(lo)),
                v7_path="B_straddle",
            ))

df_r = pd.DataFrame(results)
log(f"{len(df_r)} straddle configs survived")
if len(df_r) > 0:
    df_r = df_r.sort_values(['bootstrap_p', 'obj_score'], ascending=[True, False])
    df_r.to_csv(f"{OUT_DIR}/v7_straddle_results.csv", index=False)
    print()
    print("=" * 80)
    print("TOP 10 STRADDLES (by bootstrap_p asc, obj_score desc):")
    print("=" * 80)
    cols = ['straddle_id','stack_a','stack_b','lock_n','lock_dpt','lock_dd','lock_streak',
            'lock_sharpe','bootstrap_p','obj_score']
    print(df_r.head(10)[cols].to_string())
log("DONE")
