"""
v4_phase7_crossref — does Phase 7 CLOB momentum filter improve the v4 sleeve?

Inputs:
  - data/v4/shadow_trades_2026_05_05_live/v3_v4_resolutions.csv (fresh from VPS3)
  - strategy_lab/data/meta_classifier/btc_clob_momentum_v1.parquet (Phase 7 features)
  - data/v4/refresh_2026_05_02/btc_markets_minimal.csv (slug ↔ strike_price mapping)

Approach:
  1. Match v4/v3 trades to polymarket markets via (symbol, tf, strike_price≈, time≈)
  2. Look up Phase 7 imb_t / imb_slope_2m for each matched market
  3. Compute hit rate WHEN Phase 7 confirms vs disagrees
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
TRADES = ROOT / "data" / "v4" / "shadow_trades_2026_05_05_live" / "v3_v4_resolutions.csv"
MIN_CSV = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
P7 = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_clob_momentum_v1.parquet"


def main():
    print("=== v4 × Phase 7 cross-reference ===\n")

    # 1. Load trades
    trades = pd.read_csv(TRADES, parse_dates=["at"])
    # Coerce 't'/'f' to bool, then to int for arithmetic
    trades["won"] = trades["won"].map({"t": 1, "f": 0, True: 1, False: 0})
    trades = trades.dropna(subset=["strike_price", "won"])
    trades["won"] = trades["won"].astype(int)
    print(f"loaded {len(trades)} v3/v4 resolutions")
    print(f"  date range: {trades['at'].min()} → {trades['at'].max()}")
    print(f"  symbols: {trades['symbol'].value_counts().to_dict()}")
    print(f"  sleeves: {trades['sleeve_id'].nunique()}")

    # 2. Load polymarket markets (slug ↔ strike_price)
    mkts = pd.read_csv(MIN_CSV)
    mkts["window_start_at"] = pd.to_datetime(mkts["window_start_unix"], unit="s", utc=True)
    print(f"\nloaded {len(mkts)} polymarket markets (universe)")

    # 3. Match trades to markets via (symbol, tf, strike_price proximity, time proximity)
    # The trade's `at` is roughly within 5min after window_start. strike_price should match exactly
    # (rounding may differ). Use round(strike, 2) as join key + symbol + tf.
    trades["strike_round"] = trades["strike_price"].round(0)
    mkts = mkts.dropna(subset=["strike_price"]).copy()
    mkts["strike_round"]   = mkts["strike_price"].round(0)

    # Do a left-join on (symbol-via-slug, tf, strike_round)
    # btc_markets_minimal slugs all start with btc-updown- so only BTC. Filter.
    trades_btc = trades[trades["symbol"] == "BTC"].copy()
    print(f"\nBTC-only trades: {len(trades_btc)}")

    # Use merge on (tf, strike_round) — within BTC universe
    mkts_btc = mkts[["slug", "timeframe", "window_start_unix", "window_start_at", "strike_round"]].rename(
        columns={"timeframe": "tf"}
    )
    matched = trades_btc.merge(mkts_btc, on=["tf", "strike_round"], how="left", suffixes=("", "_mkt"))

    # If multiple polymarket markets share the same strike (unlikely for 5m), pick closest by time
    matched["time_diff_s"] = (matched["at"] - matched["window_start_at"]).dt.total_seconds().abs()
    matched = matched.sort_values(["sleeve_id", "at", "time_diff_s"]).drop_duplicates(
        subset=["sleeve_id", "at"], keep="first"
    )
    matched_n = matched["slug"].notna().sum()
    print(f"matched to polymarket slug: {matched_n}/{len(trades_btc)}")

    # 4. Load Phase 7 features and join
    p7 = pd.read_parquet(P7)
    print(f"\nloaded {len(p7)} Phase 7 feature rows")

    enriched = matched.merge(
        p7[["slug", "imb_t", "imb_slope_2m"]],
        on="slug", how="left"
    )
    has_p7 = enriched["imb_slope_2m"].notna()
    print(f"trades with Phase 7 features: {has_p7.sum()}/{len(enriched)}")

    # 5. Compute Phase 7 percentile threshold from full Phase 7 distribution
    p95 = p7["imb_slope_2m"].abs().quantile(0.95)
    p90 = p7["imb_slope_2m"].abs().quantile(0.90)
    p75 = p7["imb_slope_2m"].abs().quantile(0.75)
    p50 = p7["imb_slope_2m"].abs().quantile(0.50)
    print(f"\nPhase 7 |slope_2m| percentiles: p50={p50:.4f} p75={p75:.4f} p90={p90:.4f} p95={p95:.4f}")

    # 6. For each trade, compute Phase 7's predicted direction (CONTRARIAN to slope sign)
    # AND check if Phase 7 has a strong opinion (|slope| > p75/p90/p95)
    enriched["p7_predicted_direction"] = np.where(
        enriched["imb_slope_2m"] < 0, "UP", "DOWN"
    )
    enriched["p7_strong_p75"] = enriched["imb_slope_2m"].abs() >= p75
    enriched["p7_strong_p90"] = enriched["imb_slope_2m"].abs() >= p90
    enriched["p7_strong_p95"] = enriched["imb_slope_2m"].abs() >= p95
    enriched["p7_agrees"] = enriched["p7_predicted_direction"] == enriched["signal"]

    # 7. Per-sleeve breakdown
    print("\n=== PER SLEEVE: Phase 7 agreement effect ===")
    for sleeve in sorted(enriched["sleeve_id"].unique()):
        sub = enriched[(enriched["sleeve_id"] == sleeve) & has_p7]
        if len(sub) < 5:
            continue
        n = len(sub)
        hit_overall = sub["won"].mean()
        # When Phase 7 has STRONG opinion AND agrees → presumably best filter
        for thr_name, mask_col in [("p75", "p7_strong_p75"), ("p90", "p7_strong_p90"), ("p95", "p7_strong_p95")]:
            agrees = sub[sub[mask_col] & sub["p7_agrees"]]
            disagrees = sub[sub[mask_col] & ~sub["p7_agrees"]]
            print(f"  {sleeve:30s} n={n:3d} hit={hit_overall:.1%} | "
                  f"|slope|>={thr_name}: agree n={len(agrees):3d} hit={agrees['won'].mean():.1%} "
                  f"vs disagree n={len(disagrees):3d} hit={disagrees['won'].mean() if len(disagrees) else 0:.1%}")

    # 8. v4 specifically — detailed view
    print("\n=== BTC v4 DETAIL — every trade with Phase 7 context ===")
    v4 = enriched[enriched["sleeve_id"] == "poly_updown_btc_5m_v4"].copy()
    if len(v4) > 0:
        v4_view = v4[["at", "signal", "outcome", "won", "pnl_usd", "imb_t", "imb_slope_2m",
                      "p7_predicted_direction", "p7_agrees"]].sort_values("at")
        print(v4_view.to_string(index=False))
        print(f"\nv4 BTC overall: n={len(v4)} hit={v4['won'].mean():.1%} pnl=${v4['pnl_usd'].sum():.2f}")
        v4_with_p7 = v4[v4["imb_slope_2m"].notna()]
        if len(v4_with_p7) > 0:
            agree = v4_with_p7[v4_with_p7["p7_agrees"]]
            disagree = v4_with_p7[~v4_with_p7["p7_agrees"]]
            print(f"  WHEN Phase 7 AGREES: n={len(agree)} hit={agree['won'].mean():.1%} pnl=${agree['pnl_usd'].sum():.2f}")
            print(f"  WHEN Phase 7 DISAGREES: n={len(disagree)} hit={disagree['won'].mean():.1%} pnl=${disagree['pnl_usd'].sum():.2f}")

    # 9. Aggregate: combined v3+v4 family as a single portfolio
    print("\n=== ENTIRE V3+V4 FAMILY: Phase 7 filter effect ===")
    fam = enriched[has_p7 & enriched["sleeve_id"].str.contains("_v3|_v4")]
    print(f"family universe: n={len(fam)} hit={fam['won'].mean():.1%} pnl=${fam['pnl_usd'].sum():.2f}")
    for thr_name, mask_col in [("p50", None), ("p75", "p7_strong_p75"), ("p90", "p7_strong_p90"), ("p95", "p7_strong_p95")]:
        if mask_col is None:
            sub_strong = fam
        else:
            sub_strong = fam[fam[mask_col]]
        agree = sub_strong[sub_strong["p7_agrees"]]
        disagree = sub_strong[~sub_strong["p7_agrees"]]
        print(f"  |slope|>={thr_name}:  agree n={len(agree)} hit={agree['won'].mean() if len(agree) else 0:.1%} pnl=${agree['pnl_usd'].sum() if len(agree) else 0:.2f} | "
              f"disagree n={len(disagree)} hit={disagree['won'].mean() if len(disagree) else 0:.1%} pnl=${disagree['pnl_usd'].sum() if len(disagree) else 0:.2f}")

    # Persist enriched table
    out_csv = ROOT / "strategy_lab" / "results" / "meta_classifier" / "v4_phase7_crossref.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")


if __name__ == "__main__":
    main()
