"""Rigor pass on the exit-scalp: bootstrap CI + permutation + mean/variance decomposition.
Uses the saved per-fire exit vwaps (no L25 reload). n=430 (BTC+ETH delta>=5)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
P = ROOT / "strategy_lab" / "directional" / "_results" / "scalp_exit_validation_2026_06_02.parquet"
FEE = 0.07
rng = np.random.default_rng(20260602)  # fixed seed (Math.random unavailable convention; deterministic)


def fee_share(v): return FEE * v * (1.0 - v)


def hold_pnl(ev, sh, won):
    return (1 - ev) * sh * (1 - FEE * ev) if won else -ev * sh


def scalp_pnl(ev, ex, sh, won, feeleg):
    if not np.isfinite(ex):  # never reached target/time -> fall back to hold
        return hold_pnl(ev, sh, won)
    rt = (ex - ev) * sh
    if feeleg > 0:
        rt -= (feeleg * ev * (1 - ev) + feeleg * ex * (1 - ex)) * sh / FEE * FEE  # feeleg curve both legs
        rt = (ex - ev) * sh - (feeleg * ev * (1 - ev) + feeleg * ex * (1 - ex)) * sh
    return rt


def stats(x):
    x = np.asarray(x, float); n = len(x)
    m = x.mean(); sd = x.std(ddof=1); se = sd / np.sqrt(n)
    return dict(n=n, mean=m, sd=sd, t=m / se if se else np.nan, sharpe=m / sd if sd else np.nan)


def boot_ci(x, B=10000):
    x = np.asarray(x, float); n = len(x)
    idx = rng.integers(0, n, size=(B, n))
    means = x[idx].mean(axis=1)
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


def perm_p(x, B=10000):
    """null: PnL has zero mean (sign-flip permutation) -> p that observed mean is from null."""
    x = np.asarray(x, float); n = len(x); obs = x.mean()
    signs = rng.choice([-1.0, 1.0], size=(B, n))
    null = (x * signs).mean(axis=1)
    return float((np.abs(null) >= abs(obs)).mean())


D = pd.read_parquet(P)
print(f"loaded n={len(D)} (BTC+ETH delta>=5)")

# build per-trade PnL series for HOLD and TIME+90s, fee scenarios
def series(col, feeleg):
    return np.array([scalp_pnl(r.entry_vwap, r[col], r.shares, r.won, feeleg) for _, r in D.iterrows()])

hold = np.array([hold_pnl(r.entry_vwap, r.shares, r.won) for _, r in D.iterrows()])
print("\n=== MEAN vs VARIANCE decomposition (is it EV edge or variance reduction?) ===")
print(f"{'config':<22}{'n':>5}{'mean$':>9}{'sd':>8}{'t':>7}{'sharpe/tr':>10}")
for name, x in [("HOLD", hold), ("TIME+90s fee0", series('time90', 0.0)),
                ("TIME+90s fee0.015", series('time90', 0.015)), ("TIME+90s fee0.07", series('time90', FEE)),
                ("TP@0.65 fee0", series('tp065', 0.0)), ("TP@0.65 fee0.015", series('tp065', 0.015))]:
    s = stats(x)
    print(f"{name:<22}{s['n']:>5}{s['mean']:>9.3f}{s['sd']:>8.2f}{s['t']:>7.2f}{s['sharpe']:>10.3f}")

print("\n=== BOOTSTRAP 95% CI (10k) + PERMUTATION p (sign-flip null) ===")
for name, col, fl in [("HOLD", None, 0.0), ("TIME+90s fee0", 'time90', 0.0),
                      ("TIME+90s fee0.015", 'time90', 0.015), ("TIME+90s fee0.07", 'time90', FEE)]:
    x = hold if col is None else series(col, fl)
    lo, hi = boot_ci(x); p = perm_p(x)
    flag = "✓>0" if lo > 0 else ("~0" if hi > 0 else "<0")
    print(f"  {name:<20} mean={x.mean():+.3f}  95%CI=[{lo:+.3f},{hi:+.3f}] {flag}  perm_p={p:.4f}")

print("\n=== GATE: entry_vwap<0.55 (the part computable from saved data) ===")
for lab, mask in [("vwap<0.55", D.entry_vwap < 0.55), ("vwap>=0.55", D.entry_vwap >= 0.55)]:
    sub = D[mask]
    if len(sub) < 10: continue
    x0 = np.array([scalp_pnl(r.entry_vwap, r.time90, r.shares, r.won, 0.0) for _, r in sub.iterrows()])
    x7 = np.array([scalp_pnl(r.entry_vwap, r.time90, r.shares, r.won, FEE) for _, r in sub.iterrows()])
    s0 = stats(x0); s7 = stats(x7); lo, hi = boot_ci(x7)
    print(f"  {lab:<11} n={s0['n']:>4}  TIME+90s fee0 ${s0['mean']:+.3f} t={s0['t']:.2f} | "
          f"fee0.07 ${s7['mean']:+.3f} t={s7['t']:.2f} 95%CI=[{lo:+.2f},{hi:+.2f}]")

print("\nNOTE: permutation here is a sign-flip null (tests mean!=0). A DIRECTION-shuffle permutation needs the "
      "opposite-token exit path (not in saved data) — flagged as remaining rigor. CUSUM gate also needs recompute.")
