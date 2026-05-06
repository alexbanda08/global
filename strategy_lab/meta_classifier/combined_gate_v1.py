"""
combined_gate_v1 — test the combination of V3 prob_stack and Phase 7 CLOB momentum.

Two signals confirmed independently:
  V3 baseline: prob_stack at threshold 0.65 → 63.6% hit / +25.3% ROI / 330 bets
  Phase 7    : |imb_slope_2m| ≥ p95 → 65.4% hit / 136 bets (CONTRARIAN — predict opposite of slope sign)

Question: do they overlap or are they orthogonal? If orthogonal, the UNION is the play.

Outputs:
  strategy_lab/results/meta_classifier/combined_v3_phase7.csv  per-market signal table
  strategy_lab/reports/COMBINED_V3_PHASE7.md                    findings report
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
MIN_CSV  = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
V3_CSV   = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"
PHASE7   = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_clob_momentum_v1.parquet"
OUT_DIR  = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT_CSV  = OUT_DIR / "combined_v3_phase7.csv"


def trade_pnl(direction: int, outcome: int, fee: float = 0.01) -> float:
    """Bet at 0.50 mid, win if direction == outcome. Returns per-bet PnL on 0.50 stake."""
    win = (direction == outcome)
    return (1.00 - 0.50 - fee) if win else (0.00 - 0.50 - fee)  # +0.49 or -0.51


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Universe with outcomes
    print("[1] loading universe…")
    universe = pd.read_csv(MIN_CSV)
    universe = universe.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    universe["outcome_up"] = universe["outcome_up"].astype(int)
    print(f"    {len(universe)} BTC markets")

    # 2. V3 features — keep slug + prob_stack
    print("[2] loading V3 features…")
    v3 = pd.read_csv(V3_CSV)[["slug", "prob_stack"]].drop_duplicates("slug")
    print(f"    {len(v3)} V3 rows")

    # 3. Phase 7 momentum features
    print("[3] loading Phase 7 momentum…")
    p7 = pd.read_parquet(PHASE7)
    print(f"    {len(p7)} Phase 7 rows, cols: {list(p7.columns)}")

    # 4. Join all
    df = universe.merge(v3, on="slug", how="left")
    df = df.merge(p7[["slug", "imb_t", "imb_slope_2m"]], on="slug", how="left")
    print(f"[4] joined: {len(df)} rows")
    print(f"    has V3 prob_stack: {df['prob_stack'].notna().sum()}")
    print(f"    has Phase 7 slope_2m: {df['imb_slope_2m'].notna().sum()}")
    has_both = df["prob_stack"].notna() & df["imb_slope_2m"].notna()
    print(f"    has both: {has_both.sum()}")

    # 5. Define gates
    V3_THR = 0.65   # confidence threshold (prob_stack > 0.65 OR < 0.35)
    P7_PCTILE = 0.95  # top 5% |slope_2m|

    # V3 gate: confident either direction
    df["v3_conf"]      = (df["prob_stack"] - 0.5).abs() + 0.5  # max(p, 1-p)
    df["v3_fired"]     = df["v3_conf"] > V3_THR
    df["v3_direction"] = (df["prob_stack"] > 0.5).astype("Int8")  # 1 = Up, 0 = Down

    # Phase 7 gate: top 5% extreme |slope_2m|, CONTRARIAN direction
    has_p7 = df["imb_slope_2m"].notna()
    if has_p7.sum() > 0:
        slope_p95 = df.loc[has_p7, "imb_slope_2m"].abs().quantile(P7_PCTILE)
        df["p7_fired"]     = df["imb_slope_2m"].abs() >= slope_p95
        # Contrarian: positive slope (book getting bid-heavy on Up) → predict Down (0)
        # Negative slope (book leaving Up) → predict Up (1)
        df["p7_direction"] = (df["imb_slope_2m"] < 0).astype("Int8")
    else:
        df["p7_fired"]     = False
        df["p7_direction"] = pd.NA

    # Fill False/NA for missing
    df["v3_fired"] = df["v3_fired"].fillna(False).astype(bool)
    df["p7_fired"] = df["p7_fired"].fillna(False).astype(bool)

    # 6. Compute per-bet PnL for each gate
    df["v3_correct"] = pd.NA
    df["p7_correct"] = pd.NA
    df["v3_pnl"]     = np.nan
    df["p7_pnl"]     = np.nan

    v3_mask = df["v3_fired"] & df["v3_direction"].notna() & df["outcome_up"].notna()
    df.loc[v3_mask, "v3_correct"] = (df.loc[v3_mask, "v3_direction"].astype(int)
                                      == df.loc[v3_mask, "outcome_up"]).astype(int)
    df.loc[v3_mask, "v3_pnl"] = df.loc[v3_mask].apply(
        lambda r: trade_pnl(int(r["v3_direction"]), int(r["outcome_up"])), axis=1
    )

    p7_mask = df["p7_fired"] & df["p7_direction"].notna() & df["outcome_up"].notna()
    df.loc[p7_mask, "p7_correct"] = (df.loc[p7_mask, "p7_direction"].astype(int)
                                      == df.loc[p7_mask, "outcome_up"]).astype(int)
    df.loc[p7_mask, "p7_pnl"] = df.loc[p7_mask].apply(
        lambda r: trade_pnl(int(r["p7_direction"]), int(r["outcome_up"])), axis=1
    )

    # 7. Build report blocks
    print("\n=== INDIVIDUAL GATES ===")
    n_v3 = v3_mask.sum()
    if n_v3 > 0:
        v3_hit = df.loc[v3_mask, "v3_correct"].mean()
        v3_pnl_total = df.loc[v3_mask, "v3_pnl"].sum()
        v3_roi = df.loc[v3_mask, "v3_pnl"].mean() / 0.50
        print(f"V3 alone:        n={n_v3} hit={v3_hit:.1%} ROI={v3_roi:+.2%} pnl_total=${v3_pnl_total:+.2f}")

    n_p7 = p7_mask.sum()
    if n_p7 > 0:
        p7_hit = df.loc[p7_mask, "p7_correct"].mean()
        p7_pnl_total = df.loc[p7_mask, "p7_pnl"].sum()
        p7_roi = df.loc[p7_mask, "p7_pnl"].mean() / 0.50
        print(f"Phase 7 alone:   n={n_p7} hit={p7_hit:.1%} ROI={p7_roi:+.2%} pnl_total=${p7_pnl_total:+.2f}")

    # 8. Overlap analysis
    print("\n=== OVERLAP ANALYSIS ===")
    only_v3   = df["v3_fired"] & ~df["p7_fired"] & df["outcome_up"].notna()
    only_p7   = ~df["v3_fired"] & df["p7_fired"] & df["outcome_up"].notna()
    both_fire = df["v3_fired"] & df["p7_fired"] & df["outcome_up"].notna()
    print(f"only V3 fires: {only_v3.sum()}")
    print(f"only P7 fires: {only_p7.sum()}")
    print(f"BOTH fire:     {both_fire.sum()}")

    # 9. When both fire — do they agree on direction?
    if both_fire.sum() > 0:
        agree = both_fire & (df["v3_direction"] == df["p7_direction"])
        disagree = both_fire & (df["v3_direction"] != df["p7_direction"])
        print(f"  agree on direction: {agree.sum()}")
        print(f"  disagree: {disagree.sum()}")
        if agree.sum() > 0:
            agree_hit = (df.loc[agree, "v3_direction"].astype(int) == df.loc[agree, "outcome_up"]).mean()
            agree_pnl = df.loc[agree].apply(lambda r: trade_pnl(int(r["v3_direction"]), int(r["outcome_up"])), axis=1).sum()
            print(f"  AGREE  hit={agree_hit:.1%}  pnl=${agree_pnl:+.2f}")
        if disagree.sum() > 0:
            v3_disagree_hit = (df.loc[disagree, "v3_direction"].astype(int) == df.loc[disagree, "outcome_up"]).mean()
            p7_disagree_hit = (df.loc[disagree, "p7_direction"].astype(int) == df.loc[disagree, "outcome_up"]).mean()
            print(f"  DISAGREE: V3 says X hit={v3_disagree_hit:.1%}, P7 says Y hit={p7_disagree_hit:.1%}")

    # 10. UNION strategy: bet whenever EITHER gate fires; if both, defer to V3 (higher base hit rate)
    union_mask = (df["v3_fired"] | df["p7_fired"]) & df["outcome_up"].notna()
    df["union_direction"] = pd.NA
    # Where V3 fires, use V3 direction
    v3_choose = df["v3_fired"] & df["outcome_up"].notna()
    df.loc[v3_choose, "union_direction"] = df.loc[v3_choose, "v3_direction"]
    # Where only P7 fires, use P7 direction
    p7_choose = ~df["v3_fired"] & df["p7_fired"] & df["outcome_up"].notna()
    df.loc[p7_choose, "union_direction"] = df.loc[p7_choose, "p7_direction"]

    if union_mask.sum() > 0:
        union_correct = (df.loc[union_mask, "union_direction"].astype(int)
                          == df.loc[union_mask, "outcome_up"]).astype(int)
        union_pnl = df.loc[union_mask].apply(
            lambda r: trade_pnl(int(r["union_direction"]), int(r["outcome_up"])), axis=1
        )
        print(f"\n=== UNION (V3 OR Phase 7), V3 wins ties ===")
        print(f"n_bets={union_mask.sum()}  hit={union_correct.mean():.1%}  "
              f"ROI={union_pnl.mean()/0.50:+.2%}  pnl_total=${union_pnl.sum():+.2f}")

    # 11. INTERSECTION (only bet when BOTH agree) — high-conviction strategy
    if both_fire.sum() > 0:
        agree = both_fire & (df["v3_direction"] == df["p7_direction"])
        if agree.sum() > 0:
            inter_correct = (df.loc[agree, "v3_direction"].astype(int)
                              == df.loc[agree, "outcome_up"]).astype(int)
            inter_pnl = df.loc[agree].apply(
                lambda r: trade_pnl(int(r["v3_direction"]), int(r["outcome_up"])), axis=1
            )
            print(f"\n=== INTERSECTION (BOTH fire AND agree) ===")
            print(f"n_bets={agree.sum()}  hit={inter_correct.mean():.1%}  "
                  f"ROI={inter_pnl.mean()/0.50:+.2%}  pnl_total=${inter_pnl.sum():+.2f}")

    # Persist per-market signal table
    cols = ["slug", "timeframe", "window_start_unix", "outcome_up",
            "prob_stack", "v3_conf", "v3_fired", "v3_direction", "v3_correct", "v3_pnl",
            "imb_t", "imb_slope_2m", "p7_fired", "p7_direction", "p7_correct", "p7_pnl",
            "union_direction"]
    df[cols].to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
