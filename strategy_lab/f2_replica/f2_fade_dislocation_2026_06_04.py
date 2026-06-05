"""
F2 follow-up: is cross-exchange basis DISLOCATION a tradeable CONTRARIAN edge?

Observation: when xbasis is wide, the F2 trigger's picked side wins only ~7-14% -> FADING it wins ~86-93%.
But the trigger buys the CHEAP underdog (mean entry ~$0.31); fading buys the FAVORITE (~$0.69), which
wins often but pays little. WR != edge (priced-in trap killed 65 candidates this session). The real test:
  does fade WR exceed the price-IMPLIED WR (1 - opp_entry)?  If fade_WR >> implied -> mispricing = edge.
  If fade_WR ~= implied -> efficient, no edge.
We compute the ACTUAL opposite-side PnL (real up_ask/dn_ask + 0.07 winner-only fee), bucket by basis,
on the FULL fire universe (n=4353, more power than Config-B's n=15), with bootstrap CI + DSR + sign-flip.
"""
import sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, r"data\v4\canonical")
from load import load_cex_futures_ticker
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics
np.random.seed(0)

f = pd.read_csv(r"strategy_lab\f2_replica\_results\f2_v3_oos_basiswin.csv").sort_values("fire_ts_us").reset_index(drop=True)
# --- sanity on outcome columns ---
won_chk = (f.winner.astype(str) == f.direction.astype(str)).astype(int)
print("won == (winner==direction)?", round((won_chk == f.won.astype(int)).mean(), 4))
print("direction vals", list(pd.unique(f.direction))[:5], "| winner vals", list(pd.unique(f.winner))[:5])
print(f"entry_px mean={f.entry_px.mean():.3f}  up_ask+dn_ask mean={ (f.up_ask+f.dn_ask).mean():.3f}")

# --- opposite-side (FADE) trade: buy the side trigger did NOT pick, real ask, $1 stake, 0.07 winner-only ---
opp_up = f.direction.astype(str).str.lower().str.startswith("d")  # trigger picked Down -> fade buys Up
opp_entry = np.where(opp_up, f.up_ask, f.dn_ask).astype(float)
opp_won = (1 - f.won.astype(int)).values                          # binary up/down: fade wins iff trigger lost
opp_entry = np.clip(opp_entry, 1e-3, 0.999)
shares = 1.0 / opp_entry
fade_pnl = np.where(opp_won == 1, shares * (1 - opp_entry) * (1 - 0.07 * opp_entry), -shares * opp_entry)
f["fade_pnl"] = fade_pnl
f["opp_entry"] = opp_entry
f["implied_wr"] = opp_entry                                      # favorite token price = market-implied P(fade wins)
valid_ask = (f.up_ask > 0) & (f.dn_ask > 0) & (f.up_ask < 1) & (f.dn_ask < 1)
f = f[valid_ask].copy()
print(f"fires w/ valid two-sided ask: {len(f)}")

# --- basis join ---
EXCH = ["bybit", "okx", "gate", "bitget"]
fk = f[["fire_ts_us"]].copy()
marks = []
for ex in EXCH:
    t = load_cex_futures_ticker(exchange=ex, symbol_id=f"{ex.upper()}_PERP_BTC_USDT")
    if t is None or not len(t): continue
    t = t[["time_exchange_us", "mark_price"]].dropna().sort_values("time_exchange_us")
    m = pd.merge_asof(fk.sort_values("fire_ts_us"), t, left_on="fire_ts_us", right_on="time_exchange_us",
                      direction="backward", tolerance=10_000_000)
    f[f"mark_{ex}"] = m["mark_price"].values
    marks.append(f"mark_{ex}")
M = f[marks].values
with np.errstate(all="ignore"):
    f["xbasis_bp"] = (np.nanstd(M, axis=1) / np.nanmean(M, axis=1)) * 1e4
f = f[f.xbasis_bp.notna()].copy()
print(f"fires with basis: {len(f)}\n")

def boot_ci(v, nb=5000):
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))

def line(d, name):
    if len(d) < 5: print(f"{name:34s} n={len(d):4d} (few)"); return None
    fw, iw = d.fade_pnl.values, d.implied_wr.values
    wr = (1 - d.won).mean(); imp = iw.mean()
    t = fw.mean() / fw.std() * np.sqrt(len(fw)) if fw.std() > 0 else np.nan
    ci = boot_ci(fw)
    edge = wr - imp
    print(f"{name:34s} n={len(d):4d} fadeWR={wr:.3f} implWR={imp:.3f} edge={edge:+.3f} "
          f"fade$/tr={fw.mean():+.4f} t={t:+.2f} CI=[{ci[0]:+.3f},{ci[1]:+.3f}]")
    return fw

print("=== FADE PnL by cross-exchange basis dislocation (full universe) ===")
print("(edge = fadeWR - implied_WR ; >0 with CI>0 = real mispricing, not priced-in)")
all_fw = line(f, "ALL fires")
gates = []
for q in [0.5, 0.6, 0.7, 0.8, 0.9]:
    thr = f.xbasis_bp.quantile(q)
    fw = line(f[f.xbasis_bp >= thr], f"xbasis>=p{int(q*100)}({thr:.2f})")
    if fw is not None: gates.append((f"p{int(q*100)}", fw))
print("-- calm control --")
line(f[f.xbasis_bp < f.xbasis_bp.quantile(0.5)], "xbasis< p50 (calm)")

# Config B subset for reference
cb = f[(f.n_trades_5s >= 100) & (f.flow_imbalance_5s.abs() >= 0.3) & (f.sum_asks >= 1.01) & (f.offset_s >= 120)]
print("\n=== Config-B subset ===")
line(cb, "Config B all")
for q in [0.7, 0.8]:
    thr = cb.xbasis_bp.quantile(q)
    line(cb[cb.xbasis_bp >= thr], f"  CB xbasis>=p{int(q*100)}")

# DSR on best dislocation gate (effective_trials = #gates tried)
print("\n=== DSR on best fade gate ===")
best = max(gates, key=lambda g: (g[1].mean() / g[1].std() if g[1].std() > 0 else -9)) if gates else None
if best:
    name, fw = best
    sh = fw.mean() / fw.std()
    d = deflated_sharpe_ratio_from_statistics(observed_sharpe=sh, n_samples=len(fw), n_trials=len(gates),
                                              variance_trials=0.04, frequency="daily", periods_per_year=365)
    print(f"best={name} per-fire Sharpe={sh:.3f} n={len(fw)} $/tr={fw.mean():+.4f} DSR_prob={d.probability:.3f} sig={d.is_significant}")
# --- DEDUP: 1 fire per slug (kill the 5-fires/slug clustering that inflates n & t) ---
print("\n=== SLUG-DEDUPED (first fire per slug) — removes autocorrelation inflation ===")
fd = f.sort_values("fire_ts_us").drop_duplicates("slug", keep="first")
line(fd, "ALL fires (dedup)")
for q in [0.5, 0.7, 0.8]:
    thr = fd.xbasis_bp.quantile(q)
    line(fd[fd.xbasis_bp >= thr], f"dedup xbasis>=p{int(q*100)}")
line(fd[fd.xbasis_bp < fd.xbasis_bp.quantile(0.5)], "dedup xbasis< p50 (calm)")

print("\nREAD: edge = fadeWR - implied_WR(=favorite price). Real edge needs edge>0 with CI>0 on the")
print("      DEDUPED set AND DSR sig AND dislocated>calm. Else it's favorite-longshot tilt / noise.")
