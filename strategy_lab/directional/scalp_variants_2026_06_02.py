"""Sweep exit-scalp VARIANTS on the enriched parquet (no L25 reload) to find which deserve a shadow sleeve.
Deployable bar: worst-fee (0.07 both legs) bootstrap 95% CI of $/tr EXCLUDES 0 (robust), or at least
realistic-fee (0.015/leg) significant (t>=2 + CI>0). Baseline deployed = δ≥5, vwap<0.55, exit+60s."""
import sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
E = pd.read_parquet(ROOT / "strategy_lab" / "directional" / "_results" / "scalp_rigor_full_2026_06_02.parquet")
FEE = 0.07
rng = np.random.default_rng(20260602)


def hold(ev, sh, won): return (1 - ev) * sh * (1 - FEE * ev) if won else -ev * sh


def scalp_series(df, exit_col, fl):
    out = np.empty(len(df))
    ev = df.entry_vwap.values; sh = df.shares.values; ex = df[exit_col].values; wn = df.won.values
    for i in range(len(df)):
        if not np.isfinite(ex[i]):
            out[i] = hold(ev[i], sh[i], wn[i])
        else:
            rt = (ex[i] - ev[i]) * sh[i]
            if fl > 0:
                rt -= (fl * ev[i] * (1 - ev[i]) + fl * ex[i] * (1 - ex[i])) * sh[i]
            out[i] = rt
    return out


def st(x):
    x = np.asarray(x, float); n = len(x)
    if n < 3: return (np.nan, np.nan, n)
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n); return (m, m / se if se else np.nan, n)


def ci(x, B=6000):
    x = np.asarray(x, float); n = len(x)
    if n < 5: return (np.nan, np.nan)
    return tuple(np.percentile(x[rng.integers(0, n, (B, n))].mean(axis=1), [2.5, 97.5]))


def row(df, label, exit_col):
    if len(df) < 10:
        print(f"  {label:<34} n={len(df):>4}  (too few)"); return
    m0, t0, n = st(scalp_series(df, exit_col, 0.0))
    s15 = scalp_series(df, exit_col, 0.015); m1, t1, _ = st(s15)
    s7 = scalp_series(df, exit_col, FEE); m7, t7, _ = st(s7)
    lo, hi = ci(s7)
    rob = "✅ROBUST" if lo > 0 else ("~real" if t1 >= 2 else "")
    print(f"  {label:<34} n={n:>4}  fee0 ${m0:+.2f}(t{t0:>4.1f}) | fee.015 ${m1:+.2f}(t{t1:>4.1f}) | "
          f"fee.07 ${m7:+.2f}(t{t7:>4.1f}) CI[{lo:+.2f},{hi:+.2f}] {rob}")


B = E[E.asset.isin(["BTC", "ETH"])].copy()
print(f"universe (rigor_full): {len(B)} BTC+ETH fires, delta range {B.delta_bps.min():.0f}-{B.delta_bps.max():.0f}")
print("baseline deployed = δ≥5 + vwap<0.55 + exit+60\n")

print("=== 1. EXIT TIMING (δ≥5, vwap<0.55) ===")
g = B[(B.delta_bps >= 5) & (B.entry_vwap < 0.55)]
for col, lab in [("exit_h45", "exit+45s"), ("exit_h60", "exit+60s [DEPLOYED]"), ("exit_h90", "exit+90s")]:
    row(g, lab, col)

print("\n=== 2. ENTRY BAND (δ≥5, exit+60) ===")
for lab, mask in [("no band (=control)", B.entry_vwap.notna()), ("vwap<0.55 [DEPLOYED]", B.entry_vwap < 0.55),
                  ("vwap<0.50", B.entry_vwap < 0.50), ("vwap<0.45", B.entry_vwap < 0.45),
                  ("0.40<=vwap<0.55", (B.entry_vwap >= 0.40) & (B.entry_vwap < 0.55)),
                  ("0.45<=vwap<0.55", (B.entry_vwap >= 0.45) & (B.entry_vwap < 0.55))]:
    row(B[(B.delta_bps >= 5) & mask], lab, "exit_h60")

print("\n=== 3. DELTA THRESHOLD (vwap<0.55, exit+60) ===")
for d in [3, 5, 8, 10]:
    row(B[(B.delta_bps >= d) & (B.entry_vwap < 0.55)], f"delta>={d}", "exit_h60")

print("\n=== 4. PER TIMEFRAME (δ≥5, vwap<0.55, exit+60) ===")
for tf in ["5m", "15m"]:
    row(B[(B.delta_bps >= 5) & (B.entry_vwap < 0.55) & (B.tf == tf)], f"tf={tf}", "exit_h60")

print("\n=== 5. PER ASSET (δ≥5, vwap<0.55, exit+60) ===")
for a in ["BTC", "ETH"]:
    row(B[(B.delta_bps >= 5) & (B.entry_vwap < 0.55) & (B.asset == a)], f"asset={a}", "exit_h60")

print("\n=== 6. CANDIDATE NEW VARIANTS (vs deployed δ≥5/vwap<0.55/+60) ===")
row(B[(B.delta_bps >= 3) & (B.entry_vwap < 0.55)], "δ≥3 vwap<0.55 +60 (more vol)", "exit_h60")
row(B[(B.delta_bps >= 5) & (B.entry_vwap < 0.50)], "δ≥5 vwap<0.50 +60 (tighter)", "exit_h60")
row(B[(B.delta_bps >= 5) & (B.entry_vwap < 0.55)], "δ≥5 vwap<0.55 +45 (faster exit)", "exit_h45")
row(B[(B.delta_bps >= 3) & (B.entry_vwap < 0.50)], "δ≥3 vwap<0.50 +45 (vol+tight+fast)", "exit_h45")
