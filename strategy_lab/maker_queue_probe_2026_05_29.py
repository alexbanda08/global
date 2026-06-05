"""
maker_queue_probe_2026_05_29.py
-------------------------------
PROBE: Does a resting maker BID on the clbasis-favored side yield a
positive edge in BTC-5m Polymarket markets?

Vectorized approach — no per-slug Python loop.

METHOD
------
For each slug in dirscan_btc_5m (offset=120, cl_basis non-null):
  1. Favored side = cl_basis_bps > 0 → Up else Down.
  2. Virtual maker BID at best_bid (fav_bid0 from dirscan).
  3. FILL MODEL: total SELL volume in (slug, fav_side) at price <= bid0
     AFTER fire_us. If total_sell_usd > 0 → filled (optimistic: queue_ahead=0,
     "front of queue"). Cap fill at ORDER_SIZE_USD. This is the BULL CASE for maker.
     Also: CONSERVATIVE case = only fill if sell volume > 2× bid0 (proxy for
     queue-ahead = 50% of fill level already committed), modeled separately.
  4. PnL: fee=0 (maker, feeRate=0 on crypto up-down per CLAUDE.md), $0.01 tx.
  5. Compare vs taker: fill at ask0, fee=2%-on-profit-only (legacy production).
  6. Adverse selection: is maker fill_wr < taker_wr?

Gate notation (Cyclops convention):
  G1: WR > 50%
  G3: mean_pnl > 0
  G4: one-sided t-test p < 0.05, lower 95% CI > 0

OUTPUT
------
strategy_lab/reports/MAKER_QUEUE_LATENCY_PROBE_2026_05_29.md
"""

from __future__ import annotations
import sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
ORDER_SIZE_USD   = 25.0
TX_COST          = 0.01    # per fill
CONSERVATIVE_Q   = 2.0     # conservative queue proxy: need 2x bid fill before us
OFFSET_S         = 120     # production ws_s anchor

print("=" * 70)
print("MAKER QUEUE / LATENCY EDGE PROBE — BTC 5m  (vectorized)")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. LOAD SIGNALS
# ---------------------------------------------------------------------------
print("\n[1] Loading dirscan signals (offset=120)...")
from load import load_resolutions
dirscan = pd.read_parquet(ROOT / "data/v4/canonical/_results/dirscan_btc_5m.parquet")
sig = dirscan[(dirscan["offset_s"] == OFFSET_S) & dirscan["cl_basis_bps"].notna()].copy()

sig["fav_side"]  = sig["cl_basis_bps"].apply(lambda x: "Up" if x > 0 else "Down")
sig["fav_ask0"]  = sig.apply(lambda r: r["u_ask0"] if r["fav_side"]=="Up" else r["d_ask0"], axis=1)
sig["fav_bid0"]  = sig.apply(lambda r: r["u_bid0"] if r["fav_side"]=="Up" else r["d_bid0"], axis=1)

# Attach chainlink resolution
res = load_resolutions(assets=["BTC"], timeframes=["5m"])
res_map = res.set_index("slug")["outcome"].to_dict()
sig["outcome_cl"] = sig["slug"].map(res_map)
sig = sig[sig["outcome_cl"].notna()].copy()
sig["won"] = sig["outcome_cl"] == sig["fav_side"]

print(f"  Signals: {len(sig)}, Up={( sig['fav_side']=='Up').sum()}, Down={(sig['fav_side']=='Down').sum()}")
print(f"  Base WR: {sig['won'].mean()*100:.1f}%")
print(f"  Spread  mean={( sig['fav_ask0']-sig['fav_bid0']).mean():.4f}  p50={(sig['fav_ask0']-sig['fav_bid0']).median():.4f}")

# ---------------------------------------------------------------------------
# 2. LOAD TRADES (5m slugs only)
# ---------------------------------------------------------------------------
print("\n[2] Loading trade tape (5m slugs)...")
target_slugs = set(sig["slug"].unique())
trades = pd.read_parquet(
    ROOT / "data/v4/canonical/trades_polymarket/btc.parquet",
    engine="pyarrow",
    columns=["timestamp_us","slug","outcome","price","size","side"]
)
trades_5m = trades[trades["slug"].isin(target_slugs)].copy()
del trades
print(f"  5m trades: {len(trades_5m):,}  sell: {(trades_5m['side']=='sell').sum():,}")

# Only keep SELLs (these are the flow that would fill a resting BID)
sells = trades_5m[trades_5m["side"] == "sell"].copy()
sells["usd"] = sells["price"] * sells["size"]
del trades_5m

# ---------------------------------------------------------------------------
# 3. JOIN signals → sells
# ---------------------------------------------------------------------------
print("\n[3] Building per-slug sell aggregates post fire_us...")

# For each (slug, fav_side), we want:
#   a) total sell USD at price <= bid0, timestamp_us > fire_us
# We'll do this efficiently with a merge + filter

# Prep sig lookup
sig_idx = sig[["slug","fav_side","fire_us","fav_bid0","fav_ask0","won","cl_basis_bps","outcome_cl"]].copy()
sig_idx = sig_idx.rename(columns={"fav_side":"outcome","fav_bid0":"bid0","fav_ask0":"ask0"})

# Merge sells with signal reference on (slug, outcome=fav_side)
merged = sells.merge(
    sig_idx[["slug","outcome","fire_us","bid0"]],
    on=["slug","outcome"],
    how="inner"
)

# Filter: only sells AFTER fire_us and at price <= bid0
merged_filt = merged[(merged["timestamp_us"] > merged["fire_us"]) & (merged["price"] <= merged["bid0"])].copy()

# Sum USD by (slug, outcome)
sell_agg = merged_filt.groupby(["slug","outcome"])["usd"].sum().reset_index()
sell_agg.columns = ["slug","outcome","total_sell_usd"]

# Also get the EARLIEST fill time (for timing analysis)
first_fill = merged_filt.groupby(["slug","outcome"])["timestamp_us"].min().reset_index()
first_fill.columns = ["slug","outcome","first_fill_us"]

sell_agg = sell_agg.merge(first_fill, on=["slug","outcome"], how="left")

print(f"  Slugs with any sell at bid: {sell_agg['slug'].nunique()}")

# ---------------------------------------------------------------------------
# 4. COMPUTE PnL
# ---------------------------------------------------------------------------
print("\n[4] Computing maker + taker PnL...")

df = sig_idx.rename(columns={"outcome":"fav_side","bid0":"maker_bid","ask0":"taker_ask"}).merge(
    sell_agg.rename(columns={"outcome":"fav_side"}),
    on=["slug","fav_side"], how="left"
)
df["total_sell_usd"] = df["total_sell_usd"].fillna(0.0)

# OPTIMISTIC fill model (front of queue): fill = min(total_sell_usd, ORDER_SIZE)
df["fill_usd_opt"]    = df["total_sell_usd"].clip(upper=ORDER_SIZE_USD)
df["filled_opt"]      = df["fill_usd_opt"] > 0
df["fill_shares_opt"] = df["fill_usd_opt"] / df["maker_bid"].clip(lower=0.001)

# CONSERVATIVE fill model: only fill if total_sell > CONSERVATIVE_Q * bid0 * ORDER_SIZE
# (proxy: need CONSERVATIVE_Q × our order size of sell volume before any reaches us)
q_threshold = CONSERVATIVE_Q * ORDER_SIZE_USD
df["fill_usd_cons"]    = (df["total_sell_usd"] - q_threshold).clip(lower=0).clip(upper=ORDER_SIZE_USD)
df["filled_cons"]      = df["fill_usd_cons"] > 0
df["fill_shares_cons"] = df["fill_usd_cons"] / df["maker_bid"].clip(lower=0.001)

# MAKER PnL (no fee on crypto up-down, $0.01 tx)
for suffix, fs_col, filled_col in [
    ("opt",  "fill_shares_opt",  "filled_opt"),
    ("cons", "fill_shares_cons", "filled_cons"),
]:
    won_col = "won"
    pnl_col = f"maker_pnl_{suffix}"
    df[pnl_col] = np.where(
        ~df[filled_col], 0.0,
        np.where(
            df[won_col],
            df[fs_col] * (1.0 - df["maker_bid"]) - TX_COST,
            -df[fs_col] * df["maker_bid"] - TX_COST
        )
    )

# TAKER PnL (same direction, legacy 2%-on-profit-only fee)
taker_shares = ORDER_SIZE_USD / df["taker_ask"].clip(lower=0.001)
df["taker_pnl"] = np.where(
    df["won"],
    taker_shares * (1.0 - df["taker_ask"]) * 0.98,
    -taker_shares * df["taker_ask"]
)
df["price_improvement"] = df["taker_ask"] - df["maker_bid"]   # positive = maker cheaper

# ---------------------------------------------------------------------------
# 5. RESULTS
# ---------------------------------------------------------------------------
from scipy import stats as scipy_stats

def gate_test(pnl_series, wr, label):
    n = len(pnl_series)
    mean_pnl = pnl_series.mean()
    g1 = wr > 0.50
    g3 = mean_pnl > 0
    if n >= 10:
        t_stat, p2 = scipy_stats.ttest_1samp(pnl_series, 0)
        p1 = p2 / 2 if t_stat > 0 else 1 - p2 / 2
        g4 = p1 < 0.05
        ci95_lower = mean_pnl - 1.645 * pnl_series.std() / np.sqrt(n)
    else:
        p1 = float("nan"); t_stat = float("nan"); g4 = False; ci95_lower = float("nan")
    return {
        "label": label, "n": n, "wr_pct": round(wr*100,1),
        "mean_pnl": round(mean_pnl, 4),
        "G1": "PASS" if g1 else "FAIL",
        "G3": "PASS" if g3 else "FAIL",
        "G4": "PASS" if g4 else "FAIL",
        "p_one": round(p1, 4) if not np.isnan(p1) else "N/A",
        "t_stat": round(t_stat, 3) if not np.isnan(t_stat) else "N/A",
        "ci95_lower": round(ci95_lower, 4) if not np.isnan(ci95_lower) else "N/A",
    }

print("\n" + "=" * 70)
print("RESULTS TABLE")
print("=" * 70)

n_total   = len(df)
base_wr   = df["won"].mean()

# TAKER BASELINE
taker_g = gate_test(df["taker_pnl"], base_wr, "TAKER (all signals)")
print(f"\nTAKER BASELINE (n={n_total}, 2%-on-profit fee, always fills at ask0):")
for k,v in taker_g.items(): print(f"  {k}: {v}")

# MAKER OPTIMISTIC
filled_opt = df[df["filled_opt"]]
n_opt = len(filled_opt)
wr_opt = filled_opt["won"].mean() if n_opt > 0 else 0
print(f"\nMAKER OPTIMISTIC (front of queue, n_filled={n_opt}/{n_total}, fill_rate={n_opt/n_total*100:.1f}%):")
if n_opt > 0:
    g = gate_test(filled_opt["maker_pnl_opt"], wr_opt, "MAKER OPT")
    for k,v in g.items(): print(f"  {k}: {v}")
    print(f"  adverse_select_pp: {(wr_opt - base_wr)*100:+.1f}pp")
    print(f"  price_improvement mean: {df['price_improvement'].mean():.4f}")
    print(f"  per-signal PnL (incl unfilled=0): {df['maker_pnl_opt'].mean():.4f}")

# MAKER CONSERVATIVE
filled_cons = df[df["filled_cons"]]
n_cons = len(filled_cons)
wr_cons = filled_cons["won"].mean() if n_cons > 0 else 0
print(f"\nMAKER CONSERVATIVE (back of queue, q_threshold=${q_threshold:.0f}, n_filled={n_cons}/{n_total}, fill_rate={n_cons/n_total*100:.1f}%):")
if n_cons > 0:
    g = gate_test(filled_cons["maker_pnl_cons"], wr_cons, "MAKER CONS")
    for k,v in g.items(): print(f"  {k}: {v}")
    print(f"  adverse_select_pp: {(wr_cons - base_wr)*100:+.1f}pp")
    print(f"  per-signal PnL (incl unfilled=0): {df['maker_pnl_cons'].mean():.4f}")

# SELL FLOW STATS
print(f"\n{'='*60}")
print("SELL FLOW CHARACTERISTICS")
print(f"{'='*60}")
print(f"  Slugs with ANY sell at bid: {(df['total_sell_usd']>0).sum()} / {n_total}")
print(f"  total_sell_usd p50: ${df['total_sell_usd'].median():.2f}")
print(f"  total_sell_usd p75: ${df['total_sell_usd'].quantile(0.75):.2f}")
print(f"  total_sell_usd mean: ${df['total_sell_usd'].mean():.2f}")
print(f"  0-sell slugs: {(df['total_sell_usd']==0).sum()}")

# Adverse selection: do sells cluster in slugs that LOSE?
print(f"\n{'='*60}")
print("ADVERSE SELECTION: sell flow vs outcome")
print(f"{'='*60}")
won_sell  = df[df["won"]]["total_sell_usd"].mean()
lost_sell = df[~df["won"]]["total_sell_usd"].mean()
print(f"  Mean sell_usd at bid in WON slugs:  ${won_sell:.2f}")
print(f"  Mean sell_usd at bid in LOST slugs: ${lost_sell:.2f}")
print(f"  Ratio lost/won: {lost_sell/won_sell:.2f}x  (>1 = adverse)")

# --- Fill timing ---
if "first_fill_us" in df.columns:
    df_tf = df[df["filled_opt"] & df["first_fill_us"].notna()].copy()
    if len(df_tf) > 0:
        df_tf["fill_lag_s"] = (df_tf["first_fill_us"] - df_tf["fire_us"]) / 1e6
        print(f"\n  FILL TIMING (opt fills):")
        print(f"    lag_s p50: {df_tf['fill_lag_s'].median():.1f}s")
        print(f"    lag_s p75: {df_tf['fill_lag_s'].quantile(0.75):.1f}s")
        print(f"    lag_s mean: {df_tf['fill_lag_s'].mean():.1f}s")

# --- Spread capture ---
print(f"\n{'='*60}")
print("SPREAD CAPTURE (exit immediately at ask0, no inventory risk)")
print(f"{'='*60}")
df["spread_pnl_opt"] = np.where(
    df["filled_opt"],
    df["fill_shares_opt"] * (df["taker_ask"] - df["maker_bid"]) - TX_COST,
    0.0
)
sp_filled = df[df["filled_opt"]]
if len(sp_filled) > 0:
    print(f"  Gross spread per fill: ${(sp_filled['fill_shares_opt'] * sp_filled['price_improvement']).mean():.4f}")
    print(f"  Net spread PnL/fill (after $0.01 tx): ${sp_filled['spread_pnl_opt'].mean():.4f}")
    print(f"  Note: EXIT at ask0 costs taker fees → spread_pnl = spread_gross - tx (fee≈0 on buy side, but taker fee on exit varies)")
    print(f"  Also: exit via sell order needs a buyer at ask0, which is itself a maker order (unlimited time).")

# --- CL basis magnitude vs fill rate ---
print(f"\n{'='*60}")
print("SIGNAL STRENGTH: cl_basis_bps buckets")
print(f"{'='*60}")
df["basis_q"] = pd.qcut(df["cl_basis_bps"].abs(), q=4, duplicates="drop", labels=False)
for q, grp in df.groupby("basis_q"):
    n_q = len(grp)
    wr_q = grp["won"].mean()
    fr_q = grp["filled_opt"].mean()
    pnl_q = grp[grp["filled_opt"]]["maker_pnl_opt"].mean() if grp["filled_opt"].sum() > 0 else float("nan")
    print(f"  Q{q} (n={n_q}, basis_bps_p50={grp['cl_basis_bps'].abs().median():.1f}): "
          f"WR={wr_q*100:.1f}%  fill_rate={fr_q*100:.1f}%  maker_pnl/fill=${pnl_q:.4f}")

# ---------------------------------------------------------------------------
# 6. SAVE
# ---------------------------------------------------------------------------
out_dir = ROOT / "strategy_lab" / "maker_arb_audit"
out_dir.mkdir(parents=True, exist_ok=True)
df.to_csv(out_dir / "maker_queue_probe_results_2026_05_29.csv", index=False)

# Summary stats for report
summary = {
    "n_total":              n_total,
    "base_wr_pct":          round(base_wr*100, 1),
    "taker_mean_pnl":       round(df["taker_pnl"].mean(), 4),
    "fill_rate_opt_pct":    round(n_opt/n_total*100, 1) if n_total > 0 else 0,
    "maker_wr_opt_pct":     round(wr_opt*100, 1) if n_opt > 0 else 0,
    "adverse_sel_opt_pp":   round((wr_opt - base_wr)*100, 1) if n_opt > 0 else 0,
    "maker_pnl_per_fill_opt": round(filled_opt["maker_pnl_opt"].mean(), 4) if n_opt > 0 else 0,
    "maker_pnl_per_signal": round(df["maker_pnl_opt"].mean(), 4),
    "fill_rate_cons_pct":   round(n_cons/n_total*100, 1),
    "maker_wr_cons_pct":    round(wr_cons*100, 1) if n_cons > 0 else 0,
    "adverse_sel_cons_pp":  round((wr_cons - base_wr)*100, 1) if n_cons > 0 else 0,
    "maker_pnl_per_fill_cons": round(filled_cons["maker_pnl_cons"].mean(), 4) if n_cons > 0 else 0,
    "sell_usd_at_bid_p50":  round(df["total_sell_usd"].median(), 2),
    "adv_sel_ratio_lost_won": round(lost_sell/won_sell, 3) if won_sell > 0 else 0,
    "price_improvement_mean": round(df["price_improvement"].mean(), 4),
}

print("\n" + "="*70)
print("SUMMARY (for report)")
print("="*70)
for k, v in summary.items():
    print(f"  {k}: {v}")

print("\nDone.")
