"""Detailed stats table for the scalp variants (δ≥3 recommended + δ≥5 deployed), all columns."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
E = pd.read_parquet(ROOT / "strategy_lab" / "directional" / "_results" / "scalp_rigor_full_2026_06_02.parquet")
FEE = 0.07; STAKE = 25.0; rng = np.random.default_rng(20260602)


def hold(ev, sh, won): return (1 - ev) * sh * (1 - FEE * ev) if won else -ev * sh
def pnl_row(ev, ex, sh, won, fl):
    if not np.isfinite(ex): return hold(ev, sh, won)
    rt = (ex - ev) * sh
    if fl > 0: rt -= (fl * ev * (1 - ev) + fl * ex * (1 - ex)) * sh
    return rt
def series(df, fl, col="exit_h60"):
    return np.array([pnl_row(r.entry_vwap, r[col], r.shares, r.won, fl) for _, r in df.iterrows()])
def ci(x, B=6000):
    x = np.asarray(x, float); n = len(x)
    return tuple(np.percentile(x[rng.integers(0, n, (B, n))].mean(axis=1), [2.5, 97.5])) if n >= 5 else (np.nan, np.nan)
def t_(x):
    x = np.asarray(x, float); n = len(x); se = x.std(ddof=1) / np.sqrt(n) if n > 1 else 0
    return x.mean() / se if se else np.nan

period = (pd.Timestamp(int(E.slot_start.min()), unit="s", tz="UTC"), pd.Timestamp(int(E.slot_start.max()), unit="s", tz="UTC"))
print(f"PERIOD TESTED: {period[0]:%Y-%m-%d} -> {period[1]:%Y-%m-%d}  (~{(int(E.slot_start.max())-int(E.slot_start.min()))/86400:.0f} days)")
print(f"STAKE / FIRE: ${STAKE:.0f} notional (L25 book-walk on entry; shares = $25/entry_vwap)")
print(f"EXIT: sell on book at fire+60s (or TP@0.65 / stop fill-0.10). WR = % of round-trips POSITIVE (mark-to-market, NOT resolution).")
print(f"FEE: fee0 = 0% (current Polymarket behavior, evidence: $0 sell fills) | fee.015 realistic | fee.07 pessimistic worst-case\n")

hdr = f"{'variant (vwap<0.55, exit+60)':<32}{'n':>5}{'WR%':>6}{'entryVW':>8}{'stake':>7}{'$/tr f0':>9}{'$/tr f.015':>11}{'$/tr f.07':>10}{'t(.015)':>8}{'95%CI f.07':>16}"
print(hdr); print("-" * len(hdr))

def line(df, label):
    if len(df) < 5:
        print(f"{label:<32}{len(df):>5}  (too few)"); return
    p0 = series(df, 0.0); p15 = series(df, 0.015); p7 = series(df, FEE)
    wr = 100 * (p15 > 0).mean()
    lo, hi = ci(p7)
    print(f"{label:<32}{len(df):>5}{wr:>6.1f}{df.entry_vwap.mean():>8.3f}{'$'+str(int(STAKE)):>7}"
          f"{p0.mean():>+9.2f}{p15.mean():>+11.2f}{p7.mean():>+10.2f}{t_(p15):>8.2f}{f'[{lo:+.2f},{hi:+.2f}]':>16}")

g3 = E[(E.delta_bps >= 3) & (E.entry_vwap < 0.55)]
g5 = E[(E.delta_bps >= 5) & (E.entry_vwap < 0.55)]
print(">> δ≥3 vwap<0.55  (RECOMMENDED new variant)")
line(g3, "  δ≥3 ALL (BTC+ETH)")
line(g3[g3.asset == "BTC"], "  δ≥3 BTC")
line(g3[g3.asset == "ETH"], "  δ≥3 ETH")
line(g3[g3.tf == "5m"], "  δ≥3 5m")
line(g3[g3.tf == "15m"], "  δ≥3 15m")
print(">> δ≥5 vwap<0.55  (DEPLOYED, for comparison)")
line(g5, "  δ≥5 ALL (BTC+ETH) [deployed]")
line(g5[g5.asset == "BTC"], "  δ≥5 BTC")
line(g5[g5.asset == "ETH"], "  δ≥5 ETH")
print(">> per-segment (δ≥3 vwap<0.55) — OOS robustness")
for seg in ["bwd_oos", "fit_IS", "fit_OOS", "fwd_oos"]:
    line(g3[g3.segment == seg], f"  {seg}")
