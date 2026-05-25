"""Chainlink-RTDS vs Binance-1m Markov regime filter comparison.

For each fire in `_results/backtest_prod_strats/fills.csv`:
  1. Build per-asset Chainlink Markov labels (4 variants per asset).
  2. Look up regime at fire_us; compute pass = (signal=UP & regime=BULL) | (signal=DOWN & regime=BEAR).
  3. Tabulate per (strategy, cell, variant) vs the binance-pass columns already in the fills CSV.
  4. Test combined gate (binance AND chainlink pass).
  5. Write summary tables to `_results/CHAINLINK_VS_BINANCE_MARKOV.md` and per-fire CSV
     `_results/_chainlink_markov_fills.csv`.

Run:
    python strategy_lab/markov_filter/chainlink_markov_compare.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from data.v4.canonical.load import load_chainlink_rtds  # noqa: E402
from strategy_lab.markov_filter.markov_regime_micro import (  # noqa: E402
    label_regimes_vol_adaptive, label_regimes_fixed,
    regime_at_us, BEAR, SIDEWAYS, BULL,
)

OUT_MD  = ROOT / "strategy_lab" / "markov_filter" / "_results" / "CHAINLINK_VS_BINANCE_MARKOV.md"
OUT_CSV = ROOT / "strategy_lab" / "markov_filter" / "_results" / "_chainlink_markov_fills.csv"
FILLS   = ROOT / "strategy_lab" / "markov_filter" / "_results" / "backtest_prod_strats" / "fills.csv"


# ----------------------------------------------------------------------- #
# Streamed markdown writer — append-only so partial results survive crash
# ----------------------------------------------------------------------- #
def append_md(text: str):
    with OUT_MD.open("a", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")
    # Console may be cp1252 on Windows — strip non-ascii for stdout only.
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)


# ----------------------------------------------------------------------- #
# Step 1: build chainlink 1m closes + 4 Markov variants per asset
# ----------------------------------------------------------------------- #
def resample_chainlink_to_1m(asset: str) -> tuple[np.ndarray, np.ndarray]:
    """Returns (end_us, last_price_per_minute) for chainlink 1Hz feed.
    end_us = minute_start_us + 60*1e6 to mimic binance convention.
    """
    df = load_chainlink_rtds(asset)
    if df.empty:
        return np.array([], dtype="int64"), np.array([], dtype="float64")
    # Resample to 1m last-price; aligned to floor minute.
    df = df.sort_values("timestamp_us")
    minute_start_us = (df.timestamp_us.values.astype("int64") // 60_000_000) * 60_000_000
    # Take LAST price per minute (closest to "close" of that minute).
    grouped = pd.DataFrame({
        "ms": minute_start_us,
        "p":  df.price_value.values.astype("float64"),
    }).groupby("ms")["p"].last()
    minute_start_arr = grouped.index.to_numpy().astype("int64")
    close_arr        = grouped.values.astype("float64")
    end_us = minute_start_arr + 60_000_000
    return end_us, close_arr


VARIANT_DEFS = [
    # (label, window_bars, mode, threshold)
    ("w20_1m_voladaptive", 20, "vol_adaptive", None),
    ("w20_1m_fixed_0p003", 20, "fixed",        0.003),
    ("w40_1m_voladaptive", 40, "vol_adaptive", None),
    ("w20_1m_fixed_0p001", 20, "fixed",        0.001),
]


def build_chainlink_labels_for_asset(asset: str) -> dict:
    """Returns dict[variant_label] -> (end_us, closes, labels)."""
    end_us, closes = resample_chainlink_to_1m(asset)
    out = {}
    for label, window, mode, thresh in VARIANT_DEFS:
        if mode == "vol_adaptive":
            labels = label_regimes_vol_adaptive(closes, window_bars=window,
                                                bars_per_day=1440, calib_lookback_days=14)
        elif mode == "fixed":
            labels = label_regimes_fixed(closes, window_bars=window, threshold=thresh)
        else:
            raise ValueError(mode)
        out[label] = (end_us, closes, labels)
    return out


# ----------------------------------------------------------------------- #
# Step 2: apply chainlink Markov as gate on existing fills
# ----------------------------------------------------------------------- #
def per_fire_chainlink_regimes(fills: pd.DataFrame,
                               labels_by_asset: dict[str, dict]) -> pd.DataFrame:
    """Adds columns `cl_regime_<variant>` and `cl_pass_<variant>` per row.
    Uses regime_at_us causal asof lookup."""
    out = fills.copy()
    for variant_label, _, _, _ in VARIANT_DEFS:
        regimes  = np.full(len(out), -2, dtype=np.int8)
        passes   = np.zeros(len(out), dtype=bool)
        for asset, grp_idx in out.groupby("asset").groups.items():
            end_us, _, labels = labels_by_asset[asset][variant_label]
            sub = out.loc[grp_idx]
            fire_us_arr = sub.fire_us.values.astype("int64")
            sig_arr     = sub.signal.values
            asset_regimes = np.empty(len(sub), dtype=np.int8)
            for i, t in enumerate(fire_us_arr):
                asset_regimes[i] = regime_at_us(end_us, labels, int(t))
            regimes[grp_idx] = asset_regimes
            up_mask = (sig_arr == "UP") & (asset_regimes == BULL)
            dn_mask = (sig_arr == "DOWN") & (asset_regimes == BEAR)
            passes[grp_idx] = up_mask | dn_mask
        out[f"cl_regime_{variant_label}"] = regimes
        out[f"cl_pass_{variant_label}"]   = passes
    return out


# ----------------------------------------------------------------------- #
# Step 3-5: summary tables
# ----------------------------------------------------------------------- #
def cell_summary(grp: pd.DataFrame) -> dict:
    n = len(grp)
    if n == 0:
        return dict(n=0, wr=float("nan"), per_tr=float("nan"), sum=0.0)
    return dict(
        n=int(n),
        wr=float(grp.won.mean() * 100.0),
        per_tr=float(grp.pnl.mean()),
        sum=float(grp.pnl.sum()),
    )


def summarize_variant(fills: pd.DataFrame, gate_col: str) -> pd.DataFrame:
    """Per (strategy, cell), compute baseline and gated metrics for `gate_col`."""
    rows = []
    for (strategy, cell), g in fills.groupby(["strategy", "cell"]):
        base   = cell_summary(g)
        gated  = cell_summary(g[g[gate_col]])
        rows.append({
            "strategy": strategy,
            "cell": cell,
            "n_base":     base["n"],
            "wr_base":    base["wr"],
            "per_tr_base":base["per_tr"],
            "sum_base":   base["sum"],
            "n_gated":    gated["n"],
            "wr_gated":   gated["wr"],
            "per_tr_gated":gated["per_tr"],
            "sum_gated":  gated["sum"],
            "delta_sum":  gated["sum"] - base["sum"],
        })
    return pd.DataFrame(rows)


def to_md_table(df: pd.DataFrame, fmt: dict[str, str] | None = None,
                max_rows: int | None = None) -> str:
    if max_rows is not None:
        df = df.head(max_rows)
    df = df.copy()
    fmt = fmt or {}
    for c, f in fmt.items():
        if c in df.columns:
            df[c] = df[c].apply(lambda v: f.format(v) if pd.notna(v) else "—")
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep  = "|" + "|".join(["---"] * len(cols)) + "|"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |"
                     for row in df.itertuples(index=False, name=None))
    return "\n".join([head, sep, body])


# ----------------------------------------------------------------------- #
# Main
# ----------------------------------------------------------------------- #
def main():
    fills = pd.read_csv(FILLS)
    print(f"loaded {len(fills):,} fills, assets={sorted(fills.asset.unique())}", flush=True)

    # ------------------------------------------------------------ Step 1
    append_md("\n---\n\n## Step 1 — Chainlink 1m close series + Markov labels\n")
    labels_by_asset = {}
    rows_meta = []
    for asset in ("BTC", "ETH", "SOL"):
        print(f"[step1] building chainlink labels for {asset}", flush=True)
        labels_by_asset[asset] = build_chainlink_labels_for_asset(asset)
        end_us, closes, _ = labels_by_asset[asset]["w20_1m_voladaptive"]
        n_bars = len(closes)
        coverage_start = pd.to_datetime(int(end_us[0]) - 60_000_000, unit="us") if n_bars else None
        coverage_end   = pd.to_datetime(int(end_us[-1]) - 60_000_000, unit="us") if n_bars else None
        for variant_label, _, _, _ in VARIANT_DEFS:
            _, _, labs = labels_by_asset[asset][variant_label]
            labelled = labs[labs >= 0]
            n_lab = int(len(labelled))
            if n_lab == 0:
                share_bear = share_side = share_bull = float("nan")
            else:
                share_bear = float((labelled == BEAR).mean() * 100.0)
                share_side = float((labelled == SIDEWAYS).mean() * 100.0)
                share_bull = float((labelled == BULL).mean() * 100.0)
            rows_meta.append({
                "asset": asset,
                "variant": variant_label,
                "n_bars": int(n_bars),
                "n_labelled": n_lab,
                "share_bear_pct": share_bear,
                "share_side_pct": share_side,
                "share_bull_pct": share_bull,
                "coverage_start": coverage_start,
                "coverage_end":   coverage_end,
            })
    df_meta = pd.DataFrame(rows_meta)
    append_md(to_md_table(df_meta, fmt={
        "share_bear_pct": "{:.1f}",
        "share_side_pct": "{:.1f}",
        "share_bull_pct": "{:.1f}",
    }))

    # ------------------------------------------------------------ Step 2
    append_md("\n---\n\n## Step 2 — Apply chainlink Markov as gate on existing fills\n")
    print("[step2] computing per-fire chainlink regimes + pass flags", flush=True)
    fills_x = per_fire_chainlink_regimes(fills, labels_by_asset)

    # Quick global summary per variant
    overall_rows = []
    for label, _, _, _ in VARIANT_DEFS:
        col = f"cl_pass_{label}"
        sub = fills_x[fills_x[col]]
        overall_rows.append({
            "variant":  f"chainlink {label}",
            "n_pass":   int(len(sub)),
            "share_of_total_pct": float(len(sub) / len(fills_x) * 100.0),
            "wr_pct":   float(sub.won.mean() * 100.0) if len(sub) else float("nan"),
            "per_tr":   float(sub.pnl.mean()) if len(sub) else float("nan"),
            "sum":      float(sub.pnl.sum()),
        })
    # add binance equivalents for reference
    for binance_col in ("markov_pass_w20_1m_voladaptive",
                        "markov_pass_w20_1m_fixed",
                        "markov_pass_w20_5m_voladaptive",
                        "markov_pass_w20_5m_fixed"):
        sub = fills_x[fills_x[binance_col]]
        overall_rows.append({
            "variant":  f"binance {binance_col.replace('markov_pass_', '')}",
            "n_pass":   int(len(sub)),
            "share_of_total_pct": float(len(sub) / len(fills_x) * 100.0),
            "wr_pct":   float(sub.won.mean() * 100.0) if len(sub) else float("nan"),
            "per_tr":   float(sub.pnl.mean()) if len(sub) else float("nan"),
            "sum":      float(sub.pnl.sum()),
        })
    # baseline (no gate)
    overall_rows.append({
        "variant":  "BASELINE (no gate)",
        "n_pass":   int(len(fills_x)),
        "share_of_total_pct": 100.0,
        "wr_pct":   float(fills_x.won.mean() * 100.0),
        "per_tr":   float(fills_x.pnl.mean()),
        "sum":      float(fills_x.pnl.sum()),
    })
    df_overall = pd.DataFrame(overall_rows)
    append_md("\n### Overall gate stats across ALL fills (n=11,681)\n")
    append_md(to_md_table(df_overall, fmt={
        "share_of_total_pct": "{:.1f}",
        "wr_pct":   "{:.1f}",
        "per_tr":   "{:+.4f}",
        "sum":      "{:+.2f}",
    }))

    # ------------------------------------------------------------ Step 3
    append_md("\n---\n\n## Step 3 — Side-by-side chainlink vs binance Markov per (strategy, cell)\n")
    print("[step3] building per-cell side-by-side tables", flush=True)

    # Best chainlink variant per (strategy, cell) by sum
    best_rows = []
    for (strategy, cell), g in fills_x.groupby(["strategy", "cell"]):
        base = cell_summary(g)
        row = {"strategy": strategy, "cell": cell,
               "n_base": base["n"], "wr_base": base["wr"],
               "per_tr_base": base["per_tr"], "sum_base": base["sum"]}
        # Chainlink — pick best by sum
        best_cl_sum, best_cl_meta = float("-inf"), None
        for label, _, _, _ in VARIANT_DEFS:
            s = cell_summary(g[g[f"cl_pass_{label}"]])
            if s["n"] >= 5 and s["sum"] > best_cl_sum:
                best_cl_sum, best_cl_meta = s["sum"], (label, s)
        if best_cl_meta:
            lbl, s = best_cl_meta
            row.update({
                "best_cl_variant": lbl,
                "cl_n":  s["n"], "cl_wr": s["wr"],
                "cl_per_tr": s["per_tr"], "cl_sum": s["sum"],
            })
        else:
            row.update({"best_cl_variant": "—", "cl_n": 0,
                        "cl_wr": float("nan"), "cl_per_tr": float("nan"),
                        "cl_sum": 0.0})
        # Binance — pick best by sum
        best_bn_sum, best_bn_meta = float("-inf"), None
        for binance_col in ("markov_pass_w20_1m_voladaptive",
                            "markov_pass_w20_1m_fixed",
                            "markov_pass_w20_5m_voladaptive",
                            "markov_pass_w20_5m_fixed"):
            s = cell_summary(g[g[binance_col]])
            if s["n"] >= 5 and s["sum"] > best_bn_sum:
                best_bn_sum, best_bn_meta = s["sum"], (binance_col, s)
        if best_bn_meta:
            lbl, s = best_bn_meta
            row.update({
                "best_bn_variant": lbl.replace("markov_pass_", ""),
                "bn_n":  s["n"], "bn_wr": s["wr"],
                "bn_per_tr": s["per_tr"], "bn_sum": s["sum"],
            })
        else:
            row.update({"best_bn_variant": "—", "bn_n": 0,
                        "bn_wr": float("nan"), "bn_per_tr": float("nan"),
                        "bn_sum": 0.0})
        row["cl_minus_bn_sum"] = row["cl_sum"] - row["bn_sum"]
        best_rows.append(row)
    df_best = pd.DataFrame(best_rows).sort_values("cl_minus_bn_sum", ascending=False)
    append_md("\n### Best variant per cell, chainlink vs binance (sorted by chainlink−binance sum)\n")
    append_md(to_md_table(df_best, fmt={
        "wr_base": "{:.1f}", "per_tr_base": "{:+.4f}", "sum_base": "{:+.2f}",
        "cl_wr": "{:.1f}", "cl_per_tr": "{:+.4f}", "cl_sum": "{:+.2f}",
        "bn_wr": "{:.1f}", "bn_per_tr": "{:+.4f}", "bn_sum": "{:+.2f}",
        "cl_minus_bn_sum": "{:+.2f}",
    }))

    # ------------------------------------------------------------ Step 4: combined gate
    append_md("\n---\n\n## Step 4 — Combined gate (binance AND chainlink both pass)\n")
    print("[step4] building combined-gate tables", flush=True)

    combo_pairs = [
        ("markov_pass_w20_1m_voladaptive", "cl_pass_w20_1m_voladaptive"),
        ("markov_pass_w20_1m_fixed",        "cl_pass_w20_1m_fixed_0p003"),
        ("markov_pass_w20_5m_voladaptive",  "cl_pass_w40_1m_voladaptive"),
        ("markov_pass_w20_1m_voladaptive",  "cl_pass_w40_1m_voladaptive"),
    ]
    combo_rows = []
    for bn_col, cl_col in combo_pairs:
        gate = fills_x[bn_col] & fills_x[cl_col]
        sub = fills_x[gate]
        combo_rows.append({
            "binance_col": bn_col.replace("markov_pass_", ""),
            "chainlink_col": cl_col.replace("cl_pass_", ""),
            "n_pass": int(len(sub)),
            "share_pct": float(len(sub) / len(fills_x) * 100.0),
            "wr_pct":  float(sub.won.mean() * 100.0) if len(sub) else float("nan"),
            "per_tr":  float(sub.pnl.mean()) if len(sub) else float("nan"),
            "sum":     float(sub.pnl.sum()),
        })
    df_combo = pd.DataFrame(combo_rows)
    append_md("\n### Combined-gate overall (binance AND chainlink both pass)\n")
    append_md(to_md_table(df_combo, fmt={
        "share_pct": "{:.1f}", "wr_pct": "{:.1f}",
        "per_tr": "{:+.4f}", "sum": "{:+.2f}",
    }))

    # Per cell — best combined pair
    combo_cell_rows = []
    for (strategy, cell), g in fills_x.groupby(["strategy", "cell"]):
        base = cell_summary(g)
        best_sum, best_pair = float("-inf"), None
        best_s = None
        for bn_col, cl_col in combo_pairs:
            gate = g[bn_col] & g[cl_col]
            s = cell_summary(g[gate])
            if s["n"] >= 5 and s["sum"] > best_sum:
                best_sum = s["sum"]
                best_pair = (bn_col, cl_col)
                best_s = s
        if best_s is None:
            continue
        bn_col, cl_col = best_pair
        combo_cell_rows.append({
            "strategy": strategy, "cell": cell,
            "n_base":  base["n"], "wr_base": base["wr"],
            "sum_base":base["sum"],
            "bn_variant": bn_col.replace("markov_pass_", ""),
            "cl_variant": cl_col.replace("cl_pass_", ""),
            "n_combo":   best_s["n"], "wr_combo":  best_s["wr"],
            "per_tr_combo":best_s["per_tr"], "sum_combo": best_s["sum"],
            "delta_combo": best_s["sum"] - base["sum"],
        })
    df_combo_cell = pd.DataFrame(combo_cell_rows).sort_values("sum_combo", ascending=False)
    append_md("\n### Best combined-gate pair per cell (n>=5, ranked by sum)\n")
    append_md(to_md_table(df_combo_cell, fmt={
        "wr_base":  "{:.1f}", "sum_base": "{:+.2f}",
        "wr_combo": "{:.1f}", "per_tr_combo": "{:+.4f}",
        "sum_combo":"{:+.2f}", "delta_combo": "{:+.2f}",
    }))

    # ------------------------------------------------------------ Step 5: top 10 chainlink-only
    append_md("\n---\n\n## Step 5 — Top 10 (strategy, cell, chainlink_variant) by sum$ (n>=30)\n")
    print("[step5] top 10 chainlink combos", flush=True)
    top_rows = []
    for (strategy, cell), g in fills_x.groupby(["strategy", "cell"]):
        for label, _, _, _ in VARIANT_DEFS:
            s = cell_summary(g[g[f"cl_pass_{label}"]])
            if s["n"] >= 30:
                top_rows.append({
                    "strategy": strategy, "cell": cell, "variant": label,
                    "n": s["n"], "wr": s["wr"],
                    "per_tr": s["per_tr"], "sum": s["sum"],
                })
    df_top = pd.DataFrame(top_rows).sort_values("sum", ascending=False).head(10)
    append_md(to_md_table(df_top, fmt={
        "wr": "{:.1f}", "per_tr": "{:+.4f}", "sum": "{:+.2f}",
    }))

    # ------------------------------------------------------------ Per-cell sum comparison (full)
    append_md("\n### Per-cell sum comparison — best chainlink variant vs best binance variant\n")
    append_md("(All cells, sorted by chainlink−binance sum delta. Negative = binance wins.)\n")
    df_best_full = df_best[["strategy", "cell",
                             "best_cl_variant", "cl_n", "cl_wr", "cl_sum",
                             "best_bn_variant", "bn_n", "bn_wr", "bn_sum",
                             "cl_minus_bn_sum"]]
    append_md(to_md_table(df_best_full, fmt={
        "cl_wr": "{:.1f}", "cl_sum": "{:+.2f}",
        "bn_wr": "{:.1f}", "bn_sum": "{:+.2f}",
        "cl_minus_bn_sum": "{:+.2f}",
    }))

    # ------------------------------------------------------------ Verdict
    append_md("\n---\n\n## Step 5 — Recommendation\n")

    # Compute global $ totals
    base_sum = float(fills_x.pnl.sum())
    cl_best_total = float(df_best["cl_sum"].sum())
    bn_best_total = float(df_best["bn_sum"].sum())
    combo_total   = float(df_combo_cell["sum_combo"].sum()) if not df_combo_cell.empty else float("nan")

    cl_wins  = int((df_best["cl_minus_bn_sum"] > 0).sum())
    bn_wins  = int((df_best["cl_minus_bn_sum"] < 0).sum())
    ties     = int((df_best["cl_minus_bn_sum"] == 0).sum())

    summary_lines = [
        f"- **Baseline (no gate)** sum = ${base_sum:+.2f} across {len(fills_x):,} fires.",
        f"- **Sum (best chainlink variant per cell)** = ${cl_best_total:+.2f}.",
        f"- **Sum (best binance variant per cell)** = ${bn_best_total:+.2f}.",
        f"- **Sum (best combined per cell)** = ${combo_total:+.2f}.",
        f"- Cell-level wins: chainlink={cl_wins}, binance={bn_wins}, ties={ties}.",
    ]
    append_md("\n".join(summary_lines))

    # Write fills CSV
    print("[step6] writing _chainlink_markov_fills.csv", flush=True)
    keep_cols = [c for c in fills_x.columns
                 if c in ("asset", "tf", "cell", "strategy", "slug", "ws_s",
                          "signal", "won", "fire_us", "pnl")
                 or c.startswith("cl_regime_") or c.startswith("cl_pass_")
                 or c.startswith("markov_pass_")]
    fills_x[keep_cols].to_csv(OUT_CSV, index=False)
    append_md(f"\nPer-fire output: `{OUT_CSV.relative_to(ROOT).as_posix()}` ({len(fills_x):,} rows).")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
