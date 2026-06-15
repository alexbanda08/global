"""
LOW-VOL GATE on the open exit-scalp  —  2026-06-10  (CORRECTED-HARNESS RERUN of THREAD C)
The regime POC found low realized-vol cells richer (+$1.28 vs hi-vol +$0.67) but only ever train/test'd the
HI-vol gate (which FAILED). This cleanly tests the LOW-vol gate as the DEPLOYABLE direction, with two independent
splits (a gate is real only if it lifts $/tr above baseline on BOTH sides of BOTH splits, CI>0):
  SPLIT-1 time: first-half fires (train) vs second-half (test).
  SPLIT-2 coin: BTC+ETH (train) vs SOL (test).
Vol = std of 1s binance log-returns, trailing 300s, causal (recomputed per fire). Reuses the CORRECTED gated OOS
fires (scalp_oos_bbo_fires_fixed_2026_06_10*.parquet, BBO Mar30-Apr21, 6 coins). Light: klines only, no BBO reload.
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global"); CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"
fires = pd.concat([pd.read_parquet(f) for f in glob.glob(str(RES / "scalp_oos_bbo_fires_fixed_2026_06_10*.parquet"))], ignore_index=True)
fires = fires.drop_duplicates(["coin", "fire_us"]).reset_index(drop=True)
print(f"gated OOS fires: {len(fires)}  coins={fires.coin.value_counts().to_dict()}")

def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def add_vol(g):
    coin = g.name; te, pe = klines(coin); lp = np.log(pe); out = []
    for fu in g.fire_us.values:
        i = np.searchsorted(te, int(fu), "right") - 1
        out.append(np.std(np.diff(lp[i - 300:i + 1])) * 1e4 if i >= 301 else np.nan)
    return pd.Series(out, index=g.index)
fires["rv300"] = fires.groupby("coin", group_keys=False).apply(add_vol)
F = fires.dropna(subset=["rv300"]).copy()
print(f"with vol: {len(F)}")

def boot(v, nb=5000):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def stat(v):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return f"n={len(v):4d}(few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"

print(f"\nBASELINE (all gated): {stat(F.pnl60.values)}")
print("\n===== SPLIT-1 TIME (low-vol gate must beat baseline on BOTH halves) =====")
med = F.fire_us.median(); tr = F[F.fire_us <= med]; te = F[F.fire_us > med]
vthr = tr.rv300.median()  # 'low vol' = below TRAIN median (no test leakage)
print(f"  low-vol thr (train median rv300) = {vthr:.2f} bps")
print(f"  TRAIN base {stat(tr.pnl60.values)}  | TRAIN lowVol {stat(tr[tr.rv300 <= vthr].pnl60.values)} | TRAIN hiVol {stat(tr[tr.rv300 > vthr].pnl60.values)}")
print(f"  TEST  base {stat(te.pnl60.values)}  | TEST  lowVol {stat(te[te.rv300 <= vthr].pnl60.values)} | TEST  hiVol {stat(te[te.rv300 > vthr].pnl60.values)}")
print("\n===== SPLIT-2 COIN (train BTC+ETH, test SOL) =====")
tr2 = F[F.coin.isin(["BTC", "ETH"])]; te2 = F[F.coin == "SOL"]
vthr2 = tr2.rv300.median()
print(f"  low-vol thr (BTC+ETH median rv300) = {vthr2:.2f} bps")
print(f"  TRAIN(BTC+ETH) base {stat(tr2.pnl60.values)} | lowVol {stat(tr2[tr2.rv300 <= vthr2].pnl60.values)} | hiVol {stat(tr2[tr2.rv300 > vthr2].pnl60.values)}")
print(f"  TEST(SOL)      base {stat(te2.pnl60.values)} | lowVol {stat(te2[te2.rv300 <= vthr2].pnl60.values)} | hiVol {stat(te2[te2.rv300 > vthr2].pnl60.values)}")
print("\n===== terciles (pooled, for shape) =====")
q = F.rv300.quantile([1/3, 2/3]).values
for lab, sel in [("LOW", F.rv300 <= q[0]), ("MID", (F.rv300 > q[0]) & (F.rv300 <= q[1])), ("HIGH", F.rv300 > q[1])]:
    print(f"  {lab:4s} {stat(F[sel].pnl60.values)}")
print("\nREAD: low-vol is a DEPLOYABLE gate only if lowVol>baseline AND lowVol CI>0 on BOTH test sides.")
print("If lowVol only wins in-sample/one split -> monitor, not a gate (same fate as every other regime lever).")
