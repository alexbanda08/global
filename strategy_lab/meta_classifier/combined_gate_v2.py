"""combined_gate_v2 — test V3 ∪ Phase 7 ∪ Phase 9 (Polymarket TFI).

Three signals confirmed independently:
  V3 baseline : prob_stack at 0.65 → 63.6% hit / +25.3% ROI / 330 bets
  Phase 7     : |imb_slope_2m| ≥ p95 (CONTRARIAN) → 65.4% hit / 136 bets
  Phase 9     : |poly_tfi_2m|  ≥ p90  (PROCYCLIC) → 77.7% hit / 355 bets
                (sign of TFI = predicted direction)

Question: with three orthogonal signals, what does the union look like?

Outputs:
  strategy_lab/results/meta_classifier/combined_v3_p7_p9.csv
  strategy_lab/reports/COMBINED_V3_P7_P9.md
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
MIN_CSV  = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
V3_CSV   = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"
PHASE7   = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_clob_momentum_v1.parquet"
PHASE9   = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_trade_flow_v1.parquet"
OUT_DIR  = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT_CSV  = OUT_DIR / "combined_v3_p7_p9.csv"
REPORT   = ROOT / "strategy_lab" / "reports" / "COMBINED_V3_P7_P9.md"


def trade_pnl(direction: int, outcome: int, fee: float = 0.01) -> float:
    win = (direction == outcome)
    return (1.00 - 0.50 - fee) if win else (0.00 - 0.50 - fee)


def gate_stats(df: pd.DataFrame, mask: pd.Series, dir_col: str, label: str) -> dict:
    sub = df.loc[mask & df[dir_col].notna() & df["outcome_up"].notna()].copy()
    if len(sub) == 0:
        return {"label": label, "n": 0, "hit": float("nan"), "roi": float("nan"), "pnl": 0.0}
    correct = (sub[dir_col].astype(int).values == sub["outcome_up"].astype(int).values)
    pnls = np.where(correct, 0.49, -0.51)
    return {"label": label, "n": len(sub), "hit": correct.mean(),
            "roi": pnls.mean()/0.50, "pnl": float(pnls.sum())}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1] universe…")
    universe = pd.read_csv(MIN_CSV).dropna(subset=["window_start_unix", "outcome_up"])
    universe["outcome_up"] = universe["outcome_up"].astype(int)

    print("[2] V3 features…")
    v3 = pd.read_csv(V3_CSV)[["slug", "prob_stack"]].drop_duplicates("slug")

    print("[3] Phase 7…")
    p7 = pd.read_parquet(PHASE7)[["slug", "imb_t", "imb_slope_2m"]]

    print("[4] Phase 9…")
    p9 = pd.read_parquet(PHASE9)[["slug", "poly_tfi_2m", "poly_trade_count_2m"]]

    df = universe.merge(v3, on="slug", how="left") \
                 .merge(p7, on="slug", how="left") \
                 .merge(p9, on="slug", how="left")
    print(f"    rows={len(df)}  v3={df['prob_stack'].notna().sum()}  "
          f"p7={df['imb_slope_2m'].notna().sum()}  p9={df['poly_tfi_2m'].notna().sum()}")

    # -------- Gate definitions --------
    V3_THR = 0.65
    P7_PCTILE = 0.95
    P9_PCTILE = 0.90  # top 10% — gives ~355 markets, ~77% hit

    df["v3_conf"]      = (df["prob_stack"] - 0.5).abs() + 0.5
    df["v3_fired"]     = df["v3_conf"] > V3_THR
    df["v3_direction"] = (df["prob_stack"] > 0.5).astype("Int8")

    p7_thr = df["imb_slope_2m"].abs().quantile(P7_PCTILE)
    df["p7_fired"]     = df["imb_slope_2m"].abs() >= p7_thr
    df["p7_direction"] = (df["imb_slope_2m"] < 0).astype("Int8")  # CONTRARIAN

    p9_thr = df.loc[df["poly_trade_count_2m"] >= 1, "poly_tfi_2m"].abs().quantile(P9_PCTILE)
    df["p9_fired"]     = (df["poly_tfi_2m"].abs() >= p9_thr) & (df["poly_trade_count_2m"] >= 1)
    df["p9_direction"] = (df["poly_tfi_2m"] > 0).astype("Int8")  # PROCYCLIC

    # -------- Individual gate stats --------
    g_v3 = gate_stats(df, df["v3_fired"], "v3_direction", "V3 alone")
    g_p7 = gate_stats(df, df["p7_fired"], "p7_direction", "P7 alone")
    g_p9 = gate_stats(df, df["p9_fired"], "p9_direction", "P9 alone")

    # -------- Pairwise overlap --------
    def overlap(a, b, name_a, name_b):
        only_a = (df[a] & ~df[b] & df["outcome_up"].notna()).sum()
        only_b = (~df[a] & df[b] & df["outcome_up"].notna()).sum()
        both   = (df[a] & df[b] & df["outcome_up"].notna()).sum()
        jacc   = both / (only_a + only_b + both) if (only_a+only_b+both) else 0
        return f"{name_a}∩{name_b}: only_{name_a}={only_a}  only_{name_b}={only_b}  both={both}  Jaccard={jacc:.3f}"

    overlap_lines = [
        overlap("v3_fired", "p7_fired", "V3", "P7"),
        overlap("v3_fired", "p9_fired", "V3", "P9"),
        overlap("p7_fired", "p9_fired", "P7", "P9"),
    ]

    # -------- UNION strategies --------
    # union_3 = ANY signal fires; resolve direction by priority V3 > P9 > P7
    df["union_fired"] = df["v3_fired"] | df["p7_fired"] | df["p9_fired"]
    df["union_direction"] = pd.NA
    # Priority: V3 first (highest n, validated), then P9 (highest hit rate), then P7
    for src_dir in ["v3_direction", "p9_direction", "p7_direction"]:
        src_fire = src_dir.replace("_direction", "_fired")
        m = df["union_fired"] & df[src_fire] & df["union_direction"].isna()
        df.loc[m, "union_direction"] = df.loc[m, src_dir]

    g_union = gate_stats(df, df["union_fired"], "union_direction", "UNION (V3∪P7∪P9)")

    # union_v3_p9 = only V3 and P9 (drop P7 since contrarian and small)
    df["union_v3p9_fired"] = df["v3_fired"] | df["p9_fired"]
    df["union_v3p9_direction"] = pd.NA
    for src_dir in ["v3_direction", "p9_direction"]:
        src_fire = src_dir.replace("_direction", "_fired")
        m = df["union_v3p9_fired"] & df[src_fire] & df["union_v3p9_direction"].isna()
        df.loc[m, "union_v3p9_direction"] = df.loc[m, src_dir]

    g_union2 = gate_stats(df, df["union_v3p9_fired"], "union_v3p9_direction", "UNION (V3∪P9)")

    # Existing baseline V3∪P7
    df["union_v3p7_fired"] = df["v3_fired"] | df["p7_fired"]
    df["union_v3p7_direction"] = pd.NA
    for src_dir in ["v3_direction", "p7_direction"]:
        src_fire = src_dir.replace("_direction", "_fired")
        m = df["union_v3p7_fired"] & df[src_fire] & df["union_v3p7_direction"].isna()
        df.loc[m, "union_v3p7_direction"] = df.loc[m, src_dir]
    g_union0 = gate_stats(df, df["union_v3p7_fired"], "union_v3p7_direction", "UNION (V3∪P7) [baseline]")

    # -------- Build report --------
    lines = ["# Combined Gate v2 — V3 ∪ Phase 7 ∪ Phase 9\n",
             "_Generated: 2026-05-05_\n",
             "## Gate definitions\n",
             f"- **V3** : prob_stack confidence ≥ {V3_THR}  (procyclic)",
             f"- **P7** : |imb_slope_2m| ≥ p{P7_PCTILE*100:.0f}, threshold={p7_thr:.4g}  (CONTRARIAN)",
             f"- **P9** : |poly_tfi_2m|  ≥ p{P9_PCTILE*100:.0f}, threshold={p9_thr:.4g}  (procyclic, ≥1 trade)",
             "\n## Individual gate performance\n",
             "| Gate | n_bets | hit | ROI | pnl_total |",
             "|---|---|---|---|---|"]
    for g in [g_v3, g_p7, g_p9]:
        lines.append(f"| {g['label']} | {g['n']} | {g['hit']:.1%} | {g['roi']:+.1%} | ${g['pnl']:+.2f} |")

    lines.append("\n## Pairwise overlap (Jaccard)\n")
    for o in overlap_lines:
        lines.append(f"- {o}")

    lines.append("\n## UNION strategies\n")
    lines.append("| Strategy | n_bets | hit | ROI | pnl_total |")
    lines.append("|---|---|---|---|---|")
    for g in [g_union0, g_union2, g_union]:
        lines.append(f"| {g['label']} | {g['n']} | {g['hit']:.1%} | {g['roi']:+.1%} | ${g['pnl']:+.2f} |")

    report_str = "\n".join(lines)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report_str, encoding="utf-8")
    print("\n" + report_str)
    print(f"\n[report] wrote {REPORT}")

    # Persist signal table
    cols = ["slug", "timeframe", "window_start_unix", "outcome_up",
            "prob_stack", "v3_fired", "v3_direction",
            "imb_slope_2m", "p7_fired", "p7_direction",
            "poly_tfi_2m", "p9_fired", "p9_direction",
            "union_fired", "union_direction"]
    df[cols].to_csv(OUT_CSV, index=False)
    print(f"[csv] wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
