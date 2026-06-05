"""
F2 OOS — test the §5 Phase-1 CROSS-EXCHANGE BASIS hypothesis on FRESH fires.

F2_FINAL_VERDICT: the F2 trigger formula has NO edge on the broad universe; alpha is in F2's
slug SELECTION (mechanism unknown). §5 Phase-1 hypothesis: "F2 fires only when binance-perp /
cross-exchange basis is dislocated." We now have cex_futures_ticker (mark/index/funding/OI across
bybit/okx/gate/bitget, BTC perp) for May 30 22:11 -> Jun 4 21:06.

Test: run the F2 trigger on the new window (runner_v2 -> f2_v3_oos_basiswin.csv), join cross-exchange
basis at each fire_ts_us, and ask: does a basis-dislocation gate turn the trigger's broad-universe
loss into an edge? If yes -> basis IS (part of) the missing slug-selector. If no -> rejected.
Judge the best basis-gated subset with DSR (effective_trials = #gates tried).
"""
import sys, itertools, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, r"data\v4\canonical")
from load import load_cex_futures_ticker
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics

FIRES = r"strategy_lab\f2_replica\_results\f2_v3_oos_basiswin.csv"
EXCH = ["bybit", "okx", "gate", "bitget"]
np.random.seed(0)

f = pd.read_csv(FIRES)
print("fires loaded:", len(f), "cols:", list(f.columns)[:20])
f = f.sort_values("fire_ts_us").reset_index(drop=True)
# pnl/won sanity
print(f"raw fires: n={len(f)} WR={f.won.mean():.3f} $/tr={f.pnl_usd.mean():+.4f} (stake=$1)")

# ---- build cross-exchange basis panel at each fire ----
tick = {}
for ex in EXCH:
    sym = f"{ex.upper()}_PERP_BTC_USDT"
    t = load_cex_futures_ticker(exchange=ex, symbol_id=sym)
    if t is None or not len(t): print(f"  {ex}: EMPTY"); continue
    t = t[["time_exchange_us", "mark_price", "index_price", "funding_rate", "open_interest"]].dropna(subset=["mark_price"])
    t = t.sort_values("time_exchange_us").reset_index(drop=True)
    tick[ex] = t
    print(f"  {ex}: {len(t)} rows  ts[{t.time_exchange_us.min()}..{t.time_exchange_us.max()}]")

fkey = f[["fire_ts_us"]].copy()
for ex, t in tick.items():
    m = pd.merge_asof(fkey.sort_values("fire_ts_us"), t, left_on="fire_ts_us", right_on="time_exchange_us",
                      direction="backward", tolerance=10_000_000)  # within 10s
    f[f"mark_{ex}"] = m["mark_price"].values
    f[f"idx_{ex}"] = m["index_price"].values
    f[f"fund_{ex}"] = m["funding_rate"].values
    f[f"oi_{ex}"] = m["open_interest"].values

marks = f[[f"mark_{e}" for e in tick]].values
idxs = f[[f"idx_{e}" for e in tick]].values
funds = f[[f"fund_{e}" for e in tick]].values
with np.errstate(all="ignore"):
    f["xbasis_bp"] = (np.nanstd(marks, axis=1) / np.nanmean(marks, axis=1)) * 1e4      # cross-exch mark dispersion
    f["markidx_bp"] = (np.nanmean(marks - idxs, axis=1) / np.nanmean(idxs, axis=1)) * 1e4  # mark-index (perp premium)
    f["fund_abs"] = np.nanmean(np.abs(funds), axis=1) * 1e4                             # |funding| bps
cov = f.xbasis_bp.notna().mean()
print(f"basis coverage: {cov:.3f} of fires have cross-exchange basis")
f = f[f.xbasis_bp.notna()].copy()
print(f"fires with basis: n={len(f)}  WR={f.won.mean():.3f} $/tr={f.pnl_usd.mean():+.4f}")

# ---- Config B trigger gate (the 86% WR config) applied OOS ----
def report(d, name):
    if len(d) < 5: print(f"{name:42s} n={len(d):4d}  (too few)"); return None
    t = d.pnl_usd.mean() / d.pnl_usd.std() * np.sqrt(len(d)) if d.pnl_usd.std() > 0 else float("nan")
    print(f"{name:42s} n={len(d):4d}  WR={d.won.mean():.3f}  $/tr={d.pnl_usd.mean():+.4f}  t={t:.2f}")
    return d.pnl_usd.values

print("\n=== trigger gates OOS (no basis) ===")
report(f, "all fires(with basis)")
cb = f[(f.n_trades_5s >= 100) & (f.flow_imbalance_5s.abs() >= 0.3) & (f.sum_asks >= 1.01) & (f.offset_s >= 120)]
report(cb, "Config B (n>=100,flow>=.3,sa>=1.01,off>=120)")

# ---- basis-dislocation gates (the hypothesis) ----
print("\n=== basis-dislocation gates on Config-B fires ===")
base = cb if len(cb) >= 20 else f
results = []
gates = []
for col in ["xbasis_bp", "markidx_bp", "fund_abs"]:
    qs = base[col].quantile([0.5, 0.7, 0.8]).values
    for q, qn in zip(qs, ["p50", "p70", "p80"]):
        hi = base[base[col] >= q]; lo = base[base[col] < q]
        rh = report(hi, f"{col}>= {qn}({q:.2f})  [dislocated]")
        report(lo, f"{col}<  {qn}({q:.2f})  [calm]")
        if rh is not None:
            gates.append((f"{col}>={qn}", rh))
print("\n=== DSR on best basis-gated subset (effective_trials = #gates tried) ===")
ntr = max(len(gates), 1)
best = None
for name, arr in gates:
    sh = arr.mean() / arr.std() if arr.std() > 0 else 0
    if best is None or sh > best[1]: best = (name, sh, arr)
if best:
    name, sh, arr = best
    d = deflated_sharpe_ratio_from_statistics(observed_sharpe=sh, n_samples=len(arr), n_trials=ntr,
                                              variance_trials=0.04, frequency="daily", periods_per_year=365)
    print(f"best gate: {name}  per-fire Sharpe={sh:.3f} n={len(arr)} trials={ntr}")
    print(f"DSR prob={d.probability:.3f} sig={d.is_significant}")
print("\nREAD: if no basis gate makes Config-B fires clearly profitable (t>2, DSR sig), the basis")
print("      hypothesis is REJECTED — F2's slug-selector is not cross-exchange basis dislocation.")
