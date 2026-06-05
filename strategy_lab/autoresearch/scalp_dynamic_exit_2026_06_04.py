"""
EXECUTION upgrade: dynamic take-profit exit vs fixed +45/+60s on the confirmed exit-scalp.

Session thesis: the edge is EXECUTION. D-1 closed the entry side (delta_bps sufficient, no ML filter).
Here we test the EXIT side. The physics cache has the full bid path + take-profit hit times:
  tp_hit_{60,65,70,75}_dt = seconds until bid first reached that level; bid_{30..180} = bid at +Ns.
Policy(TP, cap): sell at TP if bid hits it by `cap` seconds, else sell at bid_{cap}. Book-sell fee
(0.015 round-trip, matching the confirmed scalp pnl_at). Compare to fixed-45 (deployed) and fixed-60.
Rigor: per-fire bootstrap CI + slug/time CPCV(8,2) OOF on the chosen policy + DSR (n_trials=#policies).
bid_pathmax = oracle ceiling (best possible sell) to size the opportunity.
"""
import sys, itertools, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, r"data\v4\canonical")
from ml4t.diagnostic.splitters.combinatorial import CombinatorialCV
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics
np.random.seed(0)

c = pd.read_parquet(r"strategy_lab\directional\_results\scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[c.asset.isin(["BTC", "ETH"])].copy()
c = c[c.filled == 1].sort_values("fire_us").reset_index(drop=True)

def book_pnl(sell, ev, sh):
    return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))

def hold_pnl(won, ev, sh):
    return np.where(won, sh * (1 - ev) * (1 - 0.07 * ev), -sh * ev)

def policy_pnl(d, kind, tp=None, cap=120):
    ev = d.entry_vwap.values; sh = d.shares.values; won = d.won.values.astype(bool)
    capcol = f"bid_{cap}"
    bcap = pd.to_numeric(d[capcol], errors="coerce").values if capcol in d else np.full(len(d), np.nan)
    b45 = pd.to_numeric(d["bid_45"], errors="coerce").values
    fallback = np.where(np.isfinite(bcap), bcap, np.where(np.isfinite(b45), b45, np.nan))
    if kind == "fixed":
        sell = pd.to_numeric(d[f"bid_{tp}"], errors="coerce").values  # tp here = seconds
        out = np.where(np.isfinite(sell), book_pnl(sell, ev, sh), hold_pnl(won, ev, sh))
        return out
    if kind == "oracle":
        sell = pd.to_numeric(d["bid_pathmax"], errors="coerce").values
        return np.where(np.isfinite(sell), book_pnl(sell, ev, sh), hold_pnl(won, ev, sh))
    # take-profit: sell at TP if hit by cap, else fallback bid_cap
    hitdt = pd.to_numeric(d[f"tp_hit_{tp}_dt"], errors="coerce").values
    hit = np.isfinite(hitdt) & (hitdt <= cap)
    tp_price = tp / 100.0
    sell_tp = book_pnl(tp_price, ev, sh)
    sell_fb = np.where(np.isfinite(fallback), book_pnl(fallback, ev, sh), hold_pnl(won, ev, sh))
    return np.where(hit, sell_tp, sell_fb)

def boot(v, nb=5000):
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))

def summ(v, name):
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    print(f"  {name:26s} n={len(v):4d} $/tr={v.mean():+.4f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]")
    return v.mean()

POLICIES = [
    ("fixed_45", "fixed", 45, None), ("fixed_60", "fixed", 60, None),
    ("TP60_cap90", "tp", 60, 90), ("TP65_cap120", "tp", 65, 120),
    ("TP70_cap150", "tp", 70, 150), ("TP65_cap90", "tp", 65, 90),
    ("TP70_cap120", "tp", 70, 120), ("TP75_cap180", "tp", 75, 180),
]

for cell_name, mask in [("CELL d>=5 & vwap<0.55", (c.delta_bps >= 5) & (c.entry_vwap < 0.55)),
                        ("BROAD vwap<0.55", c.entry_vwap < 0.55)]:
    d = c[mask].reset_index(drop=True)
    print(f"\n========== {cell_name}  n={len(d)} ==========")
    pnls = {}
    for name, kind, tp, cap in POLICIES:
        pnls[name] = policy_pnl(d, kind, tp, cap)
        summ(pnls[name], name)
    orc = policy_pnl(d, "oracle"); summ(orc, "ORACLE pathmax (ceiling)")
    base = pnls["fixed_45"]
    # best TP policy by mean
    tp_names = [n for n, *_ in POLICIES if n.startswith("TP")]
    best = max(tp_names, key=lambda n: pnls[n].mean())
    lift = pnls[best].mean() - base.mean()
    print(f"  >> best TP = {best}  lift vs fixed_45 = {lift:+.4f}/tr")
    # paired bootstrap: P(best TP > fixed_45)
    diff = pnls[best] - base
    dlo, dhi = boot(diff)
    print(f"  >> paired diff (best - fixed_45): mean={diff.mean():+.4f} CI=[{dlo:+.3f},{dhi:+.3f}]"
          f"  {'SIG' if dlo>0 else 'ns'}")
    # CPCV OOF of best TP threshold selection (avoid picking TP in-sample)
    if len(d) >= 80:
        cv = CombinatorialCV(n_groups=8, n_test_groups=2, embargo_pct=0.01)
        oof = np.full(len(d), np.nan); cnt = np.zeros(len(d))
        for tr, te in cv.split(d.values):
            # choose best TP policy on train, apply to test
            bt = max(tp_names, key=lambda n: pnls[n][tr].mean())
            v = pnls[bt][te]
            oof[te] = np.where(np.isnan(oof[te]), 0, oof[te]) + v; cnt[te] += 1
        oofm = oof / np.maximum(cnt, 1)
        valid = cnt > 0
        summ(oofm[valid], "CPCV-OOF best-TP")
        # DSR on OOF gated (n_trials = #TP policies)
        v = oofm[valid]; sh = v.mean() / v.std() if v.std() > 0 else 0
        dsr = deflated_sharpe_ratio_from_statistics(observed_sharpe=sh, n_samples=valid.sum(),
                                                    n_trials=len(tp_names), variance_trials=0.04,
                                                    frequency="daily", periods_per_year=365)
        print(f"  >> CPCV-OOF DSR prob={dsr.probability:.3f} sig={dsr.is_significant}")
print("\nREAD: deploy a TP exit only if best-TP beats fixed_45 with paired CI>0 AND CPCV-OOF stays positive.")
print("      ORACLE shows the max headroom; if fixed_45 ~= best TP, the fixed exit is already near-optimal.")
