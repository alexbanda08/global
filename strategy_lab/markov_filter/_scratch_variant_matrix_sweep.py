"""Expanded Markov variant matrix sweep.

For each (strategy, cell, markov_variant) compute n / WR / avg$ / sum$ on
the existing backtest fills (using f7_mode='off' fires, i.e. independent
of F7).

Variants:
- window_bars: 10, 15, 20, 30, 40, 60
- bar_minutes: 1, 5
- mode 'vol_adaptive' with quantile cuts: (.25,.75), (.33,.66), (.40,.60), (.45,.55)
- mode 'fixed' with per-asset thresholds: tight / default / loose / very_tight

Markov pass = (signal=UP & regime=BULL) OR (signal=DOWN & regime=BEAR).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, "strategy_lab/markov_filter")
import numpy as np
import pandas as pd
from pathlib import Path

from markov_regime_micro import (
    build_transition_matrix, label_regimes_fixed,
    asof_label_idx, regime_at_us,
    BEAR, SIDEWAYS, BULL,
)

# --------------------------------------------------------------------------- #
# Generalized vol-adaptive labeller with quantile cuts
# --------------------------------------------------------------------------- #
def label_regimes_vol_adaptive_q(
    closes: np.ndarray,
    window_bars: int,
    q_lo: float,
    q_hi: float,
    bars_per_day: int = 1440,
    calib_lookback_days: int = 14,
) -> np.ndarray:
    n = len(closes)
    out = np.full(n, -1, dtype=np.int8)
    if n < window_bars + 2:
        return out
    log_close = np.log(closes)
    rr = np.empty(n, dtype=np.float64)
    rr[:window_bars] = np.nan
    rr[window_bars:] = log_close[window_bars:] - log_close[:-window_bars]
    calib_len = calib_lookback_days * bars_per_day
    warmup = window_bars + calib_len
    if n < warmup + 1:
        return out
    for t in range(warmup, n):
        history = rr[t - calib_len:t]
        history = history[~np.isnan(history)]
        if len(history) < 100:
            continue
        qlo, qhi = np.quantile(history, [q_lo, q_hi])
        r = rr[t]
        if not np.isfinite(r):
            continue
        if r < qlo:
            out[t] = BEAR
        elif r > qhi:
            out[t] = BULL
        else:
            out[t] = SIDEWAYS
    return out


# --------------------------------------------------------------------------- #
# Load fresh klines once per (asset, bar_minutes)
# --------------------------------------------------------------------------- #
KLINES_CSV = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
ASSET_SYM = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}

print("[1] Loading fresh klines...")
k_all = pd.read_csv(KLINES_CSV)

def load_closes(asset: str, bar_minutes: int):
    sym = ASSET_SYM[asset]
    df = k_all[k_all["symbol_id"] == sym].copy()
    df = df.drop_duplicates("time_period_start_us").sort_values("time_period_start_us")
    df["ts_s"] = (df["time_period_start_us"] // 1_000_000).astype("int64")
    if bar_minutes != 1:
        ts_s = df["ts_s"].values
        keep_mask = (ts_s % (bar_minutes * 60)) == 0
        df = df[keep_mask].reset_index(drop=True)
    period_s = bar_minutes * 60
    end_us = (df["time_period_start_us"].values.astype("int64")
              + period_s * 1_000_000)
    closes = df["price_close"].values.astype("float64")
    return end_us, closes

CLOSES = {}
for asset in ("BTC", "ETH", "SOL"):
    for bm in (1, 5):
        CLOSES[(asset, bm)] = load_closes(asset, bm)
        end_us, closes = CLOSES[(asset, bm)]
        print(f"   [{asset} {bm}m] {len(closes):,} bars")

# --------------------------------------------------------------------------- #
# Build all label series
# --------------------------------------------------------------------------- #
WINDOWS = [10, 15, 20, 30, 40, 60]
BAR_MINS = [1, 5]
QUANTILES = [(0.25, 0.75), (0.33, 0.66), (0.40, 0.60), (0.45, 0.55)]
# Fixed thresholds per asset
FIXED_PROFILES = {
    "tight":      {"BTC": 0.002, "ETH": 0.003, "SOL": 0.005},
    "default":    {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    "loose":      {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
    "very_tight": {"BTC": 0.001, "ETH": 0.002, "SOL": 0.003},
}

print("\n[2] Building Markov label series ...")
LABELS: dict[tuple, np.ndarray] = {}  # (asset, bm, mode, key, w) -> labels

for asset in ("BTC", "ETH", "SOL"):
    for bm in BAR_MINS:
        end_us, closes = CLOSES[(asset, bm)]
        bars_per_day = (24 * 60) // bm
        for w in WINDOWS:
            for (q_lo, q_hi) in QUANTILES:
                key = f"q{int(q_lo*100):02d}_{int(q_hi*100):02d}"
                labels = label_regimes_vol_adaptive_q(
                    closes, window_bars=w, q_lo=q_lo, q_hi=q_hi,
                    bars_per_day=bars_per_day, calib_lookback_days=14,
                )
                LABELS[(asset, bm, "vol_adaptive", key, w)] = labels
            for prof_name, prof in FIXED_PROFILES.items():
                thr = prof[asset]
                labels = label_regimes_fixed(closes, window_bars=w, threshold=thr)
                LABELS[(asset, bm, "fixed", prof_name, w)] = labels
        print(f"   [{asset} {bm}m] built {len(WINDOWS)*(len(QUANTILES)+len(FIXED_PROFILES))} variants")

# --------------------------------------------------------------------------- #
# Score each variant on fills
# --------------------------------------------------------------------------- #
print("\n[3] Loading fills.csv (f7_mode='off') ...")
fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
fills = fills[fills["f7_mode"] == "off"].copy()
print(f"   {len(fills):,} fills")

# Map cell -> asset
fills["asset_u"] = fills["asset"].str.upper()
fills["sig_u"]   = fills["signal"].str.upper()
fills["is_up"]   = (fills["sig_u"] == "UP")

rows = []

print("\n[4] Sweeping variants ...")
n_variants = 0
for (asset_v, bm, mode, key, w), labels in LABELS.items():
    end_us, _closes = CLOSES[(asset_v, bm)]
    # For each fill of this asset, compute regime at fire_us
    sub = fills[fills["asset_u"] == asset_v]
    if sub.empty:
        continue
    fire_us_arr = sub["fire_us"].values.astype("int64")
    # Vectorized asof via searchsorted
    idx = np.searchsorted(end_us, fire_us_arr, side="right") - 1
    valid = (idx >= 0) & (idx < len(labels))
    regimes = np.where(valid, labels[np.clip(idx, 0, len(labels)-1)], -1)
    is_up = sub["is_up"].values
    # pass = (UP & BULL) | (DOWN & BEAR)
    passes = ((is_up & (regimes == BULL)) | ((~is_up) & (regimes == BEAR)))
    sub2 = sub.assign(_pass=passes)
    kept = sub2[sub2["_pass"]]
    # group by (strategy, cell)
    for (strat, cell), g in kept.groupby(["strategy", "cell"]):
        n = len(g)
        if n == 0:
            continue
        wr = float(g["won"].mean()) * 100.0
        avg = float(g["pnl"].mean())
        s   = float(g["pnl"].sum())
        rows.append({
            "strategy": strat,
            "cell": cell,
            "window_bars": w,
            "bar_minutes": bm,
            "mode": mode,
            "threshold_or_quantile": key,
            "n": n,
            "wr": round(wr, 2),
            "avg_pnl": round(avg, 4),
            "sum_pnl": round(s, 2),
        })
    n_variants += 1

print(f"   scored {n_variants} (asset, variant) pairs -> {len(rows)} table rows")

out = pd.DataFrame(rows)
out_path = Path("strategy_lab/markov_filter/_results/MARKOV_VARIANT_MATRIX.csv")
out_path.parent.mkdir(parents=True, exist_ok=True)
out.to_csv(out_path, index=False)
print(f"\n[5] Wrote {out_path}  ({len(out):,} rows)")

# --------------------------------------------------------------------------- #
# Markdown summary
# --------------------------------------------------------------------------- #
print("\n[6] Building markdown summary ...")
md_path = Path("strategy_lab/markov_filter/_results/MARKOV_VARIANT_MATRIX.md")

def fmt_variant(r):
    if r["mode"] == "vol_adaptive":
        return f"w{r['window_bars']}_{r['bar_minutes']}m_{r['threshold_or_quantile']}"
    return f"w{r['window_bars']}_{r['bar_minutes']}m_fix_{r['threshold_or_quantile']}"

out["variant"] = out.apply(fmt_variant, axis=1)
out_n30 = out[out["n"] >= 30].copy()

top_sum = out_n30.sort_values("sum_pnl", ascending=False).head(10)
top_wr  = out_n30.sort_values("wr", ascending=False).head(10)

# Best variant per (strategy, cell): by sum_pnl, n>=30
best_per_cell = (
    out_n30.sort_values("sum_pnl", ascending=False)
            .groupby(["strategy", "cell"], as_index=False).first()
            .sort_values("sum_pnl", ascending=False)
)

lines = []
lines.append("# Markov Variant Matrix Sweep")
lines.append("")
lines.append("Generated by `_scratch_variant_matrix_sweep.py`.")
lines.append("")
lines.append(f"- Source fills: `strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv` "
             f"({len(fills):,} fires after `f7_mode='off'` filter)")
lines.append(f"- Klines: `strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv` "
             f"(fresh through 2026-05-21 19:31 UTC)")
lines.append("- Markov pass rule: `(signal=UP & regime=BULL) OR (signal=DOWN & regime=BEAR)`")
lines.append("- Variants: 6 windows x 2 bar TFs x 8 thresholds = 96 per asset (4 vol-adaptive quantiles + 4 fixed profiles)")
lines.append(f"- Total table rows: {len(out):,} (with n>=30: {len(out_n30):,})")
lines.append("")

lines.append("## Top 10 (strategy, cell, variant) by sum$ (n>=30)")
lines.append("")
lines.append("| # | strategy | cell | variant | n | WR% | avg$ | sum$ |")
lines.append("|--:|---|---|---|--:|--:|--:|--:|")
for i, r in enumerate(top_sum.itertuples(), 1):
    lines.append(f"| {i} | {r.strategy} | {r.cell} | {r.variant} "
                 f"| {r.n} | {r.wr:.2f} | {r.avg_pnl:.4f} | {r.sum_pnl:.2f} |")
lines.append("")

lines.append("## Top 10 (strategy, cell, variant) by WR% (n>=30)")
lines.append("")
lines.append("| # | strategy | cell | variant | n | WR% | avg$ | sum$ |")
lines.append("|--:|---|---|---|--:|--:|--:|--:|")
for i, r in enumerate(top_wr.itertuples(), 1):
    lines.append(f"| {i} | {r.strategy} | {r.cell} | {r.variant} "
                 f"| {r.n} | {r.wr:.2f} | {r.avg_pnl:.4f} | {r.sum_pnl:.2f} |")
lines.append("")

lines.append("## Best variant per (strategy, cell) by sum$ (n>=30)")
lines.append("")
lines.append("| strategy | cell | best variant | n | WR% | avg$ | sum$ |")
lines.append("|---|---|---|--:|--:|--:|--:|")
for r in best_per_cell.itertuples():
    lines.append(f"| {r.strategy} | {r.cell} | {r.variant} "
                 f"| {r.n} | {r.wr:.2f} | {r.avg_pnl:.4f} | {r.sum_pnl:.2f} |")
lines.append("")

# Conclusion: compare to existing top-3
baseline = {
    "btc_15m_v1_w20_1m_voladaptive": 368,
    "btc_15m_v2_w20_1m_voladaptive": 235,
    "eth_15m_v2_w20_1m_voladaptive": 189,
}
lines.append("## Conclusion vs existing top-3")
lines.append("")
lines.append("Existing top-3 from earlier sweep (sum$):")
lines.append("- `btc_15m + momo_v1 + MARKOV:w20_5m_voladaptive` = +$368")
lines.append("- `btc_15m + momo_v2 + MARKOV:w20_1m_voladaptive` = +$235")
lines.append("- `eth_15m + momo_v2 + MARKOV:w20_1m_voladaptive` = +$189")
lines.append("")
# Best for those 3 cells, any variant
challengers = []
for (strat, cell, baseline_sum) in [
    ("momo_v1", "btc_15m", 368),
    ("momo_v2", "btc_15m", 235),
    ("momo_v2", "eth_15m", 189),
]:
    sub = out_n30[(out_n30["strategy"]==strat) & (out_n30["cell"]==cell)]
    if sub.empty:
        challengers.append((strat, cell, baseline_sum, None, None, None, None))
        continue
    best = sub.sort_values("sum_pnl", ascending=False).iloc[0]
    challengers.append((strat, cell, baseline_sum,
                        best["variant"], int(best["n"]),
                        float(best["wr"]), float(best["sum_pnl"])))

lines.append("| baseline | baseline sum$ | best new variant | n | WR% | new sum$ | delta |")
lines.append("|---|--:|---|--:|--:|--:|--:|")
beats_any = False
for (s, c, b, v, n, wr, sm) in challengers:
    if v is None:
        lines.append(f"| {s} {c} | {b} | (no n>=30 variant) | - | - | - | - |")
    else:
        delta = sm - b
        if delta > 0: beats_any = True
        lines.append(f"| {s} {c} | {b} | {v} | {n} | {wr:.2f} | {sm:.2f} | {delta:+.2f} |")
lines.append("")

# Also report the absolute best variant across all 18 cells
abs_best = out_n30.sort_values("sum_pnl", ascending=False).iloc[0]
lines.append(f"**Absolute best variant in sweep (n>=30)**: "
             f"`{abs_best['strategy']} + {abs_best['cell']} + {abs_best['variant']}` "
             f"= +${abs_best['sum_pnl']:.2f} (n={int(abs_best['n'])}, WR={abs_best['wr']:.1f}%, "
             f"avg ${abs_best['avg_pnl']:.4f}/trade)")
lines.append("")
if beats_any:
    lines.append("**Verdict: at least one expanded variant BEATS one of the existing top-3 baselines (see delta column).**")
else:
    lines.append("**Verdict: no expanded variant beats any of the existing top-3 baselines.**")

md_path.write_text("\n".join(lines), encoding="utf-8")
print(f"   wrote {md_path}")
print()
print("=" * 70)
print("TOP-10 BY SUM$ (n>=30):")
print(top_sum[["strategy","cell","variant","n","wr","avg_pnl","sum_pnl"]].to_string(index=False))
print()
print("BEST PER CELL (top 8 shown):")
print(best_per_cell[["strategy","cell","variant","n","wr","avg_pnl","sum_pnl"]].head(8).to_string(index=False))
print()
print("CHALLENGER COMPARISON:")
for (s, c, b, v, n, wr, sm) in challengers:
    if v is None:
        print(f"  {s} {c}: baseline +${b}, no n>=30 variant")
    else:
        print(f"  {s} {c}: baseline +${b}  ->  {v}: n={n}, WR={wr:.1f}%, +${sm:.2f}  delta {sm-b:+.2f}")
