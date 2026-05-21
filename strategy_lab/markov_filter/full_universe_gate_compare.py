"""Head-to-head: F7 vs Markov vs F7+Markov gates on the full canonical universe.

Source: data/v4/canonical/_results/full_universe_live_mimic_2026_05_16/per_trade.csv
  - 516 unique momo fires (q90 |ret_2m| gated)
  - 14 exit-policy variants → we use SELL_5bp as representative
  - Apr 25 → May 15 (live-mimic engine, real fees + latency)
  - Raw data: binance 1m klines (signal source) + Polymarket L25 book v2 sub-1Hz (fills)

Computes per fire:
  - RSI(14) at ws_s on binance 1m closes        → F7 gate
  - Markov regime at fire_us (4 variants)       → Markov gate

Then 4 gate modes × 4 Markov variants = 17 columns of comparison.

Output: CSVs + report-ready tables in _results/full_universe_gate_compare/.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import load_klines  # noqa: E402
sys.path.insert(0, "strategy_lab/markov_filter")
from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, BEAR, SIDEWAYS, BULL,
)

PER_TRADE = "data/v4/canonical/_results/full_universe_live_mimic_2026_05_16/per_trade.csv"
OUT_DIR = Path("strategy_lab/markov_filter/_results/full_universe_gate_compare")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Exit-policy chosen as representative for entry-filter analysis
REP_VARIANT = "SELL_5bp"

MARKOV_VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
}


# --------------------------------------------------------------------------- #
# RSI helper
# --------------------------------------------------------------------------- #
def compute_rsi_at(end_us: np.ndarray, closes: np.ndarray, target_us: int,
                   period: int = 14) -> float:
    """Wilder-RSI at the close of the bar that ended at-or-before target_us.
    Causal. Returns NaN if not enough history."""
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if idx < period:
        return float("nan")
    c = closes[idx - period:idx + 1]
    diffs = np.diff(c)
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    print("[1] Loading per_trade.csv ...")
    df = pd.read_csv(PER_TRADE)
    fires = df[(df["variant"] == REP_VARIANT) & df["fired"]].copy().reset_index(drop=True)
    print(f"    {len(fires)} fires under variant={REP_VARIANT}")

    # BUG FIX: CSV's `ws` column == slug_suffix == slot_start, NOT ws_s.
    # Per CLAUDE.md: ws_s = slot_start - window_s. F7 spec anchors RSI at ws_s.
    fires["slot_start_s"] = fires["ws"].astype("int64")
    fires["window_s"] = fires["tf"].map({"5m": 300, "15m": 900})
    fires["ws_s"] = fires["slot_start_s"] - fires["window_s"]
    fires["ws_us"] = fires["ws_s"] * 1_000_000           # anchor for RSI(14)
    # fire_offset_s is slot_start-relative; fire_us = slot_start + fire_offset_s
    fires["fire_us"] = (fires["slot_start_s"] +
                        fires["fire_offset_s"].astype("int64")) * 1_000_000

    # Outcome → won
    fires["won"] = (
        ((fires["signal"] == "UP")   & (fires["outcome"] == "Up")) |
        ((fires["signal"] == "DOWN") & (fires["outcome"] == "Down"))
    )
    # True HOLD-to-settlement PnL from raw cols (engine's variant pnl is
    # collapsed to a single exit policy — recompute the pure entry-quality PnL).
    fires["pnl"] = np.where(
        fires["won"],
        fires["shares_e"] - fires["usd_e"] - fires["fee_in"],
        -fires["usd_e"] - fires["fee_in"],
    )

    print("\n[2] Loading binance 1m klines for RSI...")
    klines = {}
    for asset in ("BTC", "ETH", "SOL"):
        kdf = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
        end_us = (kdf["time_period_start_us"].values.astype("int64") +
                  60 * 1_000_000)
        closes = kdf["price_close"].values.astype("float64")
        klines[asset] = (end_us, closes)
        print(f"    {asset}: {len(end_us):,} 1m bars")

    print("\n[3] Computing RSI(14) at ws_s per fire...")
    rsis = []
    for _, r in fires.iterrows():
        end_us, closes = klines[r["asset"]]
        rsi = compute_rsi_at(end_us, closes, int(r["ws_us"]), period=14)
        rsis.append(rsi)
    fires["rsi_14"] = rsis
    fires["f7_pass"] = (
        ((fires["signal"] == "UP")   & (fires["rsi_14"] > 50)) |
        ((fires["signal"] == "DOWN") & (fires["rsi_14"] < 50))
    )
    print(f"    RSI finite: {fires['rsi_14'].notna().sum()} / {len(fires)}")
    print(f"    F7 pass: {fires['f7_pass'].sum()} / {len(fires)}  ({fires['f7_pass'].mean()*100:.1f}%)")

    print("\n[4] Building Markov labels per (asset × variant)...")
    cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ("BTC", "ETH", "SOL"):
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"])
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            cache[(vname, asset)] = (end_us, labels)
            print(f"    {asset} {vname}: n_labelled={(labels >= 0).sum():,}")

    print("\n[5] Computing Markov regime at fire_us per (fire × variant)...")
    for vname, _ in MARKOV_VARIANTS:
        regs = []
        for _, r in fires.iterrows():
            end_us, labels = cache[(vname, r["asset"])]
            regs.append(regime_at_us(end_us, labels, int(r["fire_us"])))
        fires[f"regime_{vname}"] = regs
        pass_mask = (
            ((fires["signal"] == "UP")   & (fires[f"regime_{vname}"] == BULL)) |
            ((fires["signal"] == "DOWN") & (fires[f"regime_{vname}"] == BEAR))
        )
        fires[f"markov_pass_{vname}"] = pass_mask
        print(f"    {vname} pass: {pass_mask.sum()} / {len(fires)}  ({pass_mask.mean()*100:.1f}%)")

    fires.to_csv(OUT_DIR / "fires_with_gates.csv", index=False)
    print(f"\n    wrote {OUT_DIR / 'fires_with_gates.csv'}")

    # ------------------------------------------------------------------- #
    # Aggregate per gate variant
    # ------------------------------------------------------------------- #
    def summarize(g: pd.DataFrame, label: str) -> dict:
        n = len(g)
        wins = int(g["won"].sum())
        pnl  = float(g["pnl"].sum())
        return {
            "filter": label, "n": n,
            "wr": round(wins / n * 100, 2) if n else 0.0,
            "pnl": round(pnl, 2),
            "avg": round(pnl / n, 3) if n else 0.0,
            "keep%": round(n / len(fires) * 100, 1) if len(fires) else 0.0,
        }

    print("\n[6] Building comparison tables...")
    blocks = []

    # 1) Overall
    rows = [summarize(fires, "NO_FILTER")]
    rows.append(summarize(fires[fires["f7_pass"]], "F7_only"))
    for vname, _ in MARKOV_VARIANTS:
        rows.append(summarize(fires[fires[f"markov_pass_{vname}"]],
                              f"MARKOV_only:{vname}"))
        rows.append(summarize(fires[fires["f7_pass"] & fires[f"markov_pass_{vname}"]],
                              f"F7+MARKOV:{vname}"))
    overall = pd.DataFrame(rows)
    overall.to_csv(OUT_DIR / "summary_overall.csv", index=False)
    print("\n=== OVERALL ===")
    print(overall.to_string(index=False))
    blocks.append(("OVERALL", overall))

    # 2) Per cell (symbol_tf) + version
    fires["cell"] = (fires["asset"].str.lower() + "_" + fires["tf"] +
                     "_" + fires["version"])
    cells = sorted(fires["cell"].unique())
    print(f"\n=== Per cell (n_cells={len(cells)}) ===")
    cell_rows = []
    for cell in cells:
        sub = fires[fires["cell"] == cell]
        if len(sub) < 5:
            continue
        rows_cell = [summarize(sub, "NO_FILTER")]
        rows_cell.append(summarize(sub[sub["f7_pass"]], "F7_only"))
        for vname, _ in MARKOV_VARIANTS:
            rows_cell.append(summarize(sub[sub[f"markov_pass_{vname}"]],
                                       f"MARKOV_only:{vname}"))
            rows_cell.append(summarize(sub[sub["f7_pass"] & sub[f"markov_pass_{vname}"]],
                                       f"F7+MARKOV:{vname}"))
        for row in rows_cell:
            row["cell"] = cell
            cell_rows.append(row)
    cell_df = pd.DataFrame(cell_rows)[
        ["cell", "filter", "n", "wr", "avg", "pnl", "keep%"]
    ]
    cell_df.to_csv(OUT_DIR / "summary_per_cell.csv", index=False)
    # Compact pivot for readability: filter × cell average pnl
    piv = cell_df.pivot(index="filter", columns="cell", values="avg")
    print(piv.to_string())

    # 3) Distillation — pick winning filter per cell by total PnL
    print("\n=== Winning filter per cell (by sum PnL, min n=10 kept) ===")
    best_rows = []
    for cell in cells:
        sub = cell_df[(cell_df["cell"] == cell) & (cell_df["n"] >= 10)]
        if sub.empty:
            continue
        baseline = sub[sub["filter"] == "NO_FILTER"].iloc[0]
        best = sub.loc[sub["pnl"].idxmax()]
        best_rows.append({
            "cell": cell,
            "n_base": int(baseline["n"]), "wr_base": baseline["wr"],
            "avg_base": baseline["avg"], "pnl_base": baseline["pnl"],
            "best_filter": best["filter"],
            "n_best": int(best["n"]), "wr_best": best["wr"],
            "avg_best": best["avg"], "pnl_best": best["pnl"],
            "keep%_best": best["keep%"],
            "lift_avg": round(best["avg"] - baseline["avg"], 3),
            "lift_total_pnl": round(best["pnl"] - baseline["pnl"], 2),
        })
    best_df = pd.DataFrame(best_rows)
    best_df.to_csv(OUT_DIR / "summary_best_per_cell.csv", index=False)
    print(best_df.to_string(index=False))


if __name__ == "__main__":
    main()
