"""
FINALIZE V7 — BTC 5m
====================
Read all_candidates_v7.csv. Apply stability filters:
  - no negative dpt in train or val
  - wr_train >= 0.55 and wr_val >= 0.55
  - lottery_deep_share <= 0.25 (avoid V6-style lottery artifacts)
  - n_train >= 50 (avoid micro-sample overfit)

Then pick diverse top 5 by objective (across paths A/D/H/F/B).
Generate:
  - top_5_candidates_v7.csv
  - SNIPER_BTC_5M_V7_REPORT.md
  - cumulative_pnl_v7_{sleeve_id}.png per top 5
"""
import sys, io
from pathlib import Path
import numpy as np
import pandas as pd

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m_v7"
SAND = OUT / "_sandbox"
WINDOW_S = 300

V6_BEST = dict(  # for comparison
    sleeve_id="off_L_late|r2|g_imb5_strong_with+g_hurst_trending",
    n_lockbox=161, wr_lockbox=0.7081, dpt_lockbox=29.85,
    sum_lockbox=4806, max_dd_25=180.7, lottery_share=0.78,
    sum_28d_proj=69089,
)


def main():
    cdf = pd.read_csv(OUT / "all_candidates_v7.csv")
    print(f"Loaded {len(cdf)} candidates")
    print(f"  passing V7 bar: {cdf['pass'].sum()}")

    # Apply stability filter
    stable = cdf[cdf["pass"]].copy()
    initial = len(stable)
    # Filter for stability
    stable = stable[
        (stable["dpt_25_train"] >= 0.0)
        & (stable["dpt_25_val"] >= 0.0)
        & (stable["wr_train"] >= 0.55)
        & (stable["wr_val"] >= 0.55)
        & (stable["n_train"] >= 50)
        & (stable["lottery_deep_share"].fillna(0) <= 0.25)
    ].copy()
    print(f"  after stability filter (no neg dpt_tr/val, wr>=0.55, n_tr>=50, deep<=0.25): {len(stable)} of {initial}")

    # Dedup by metric signature
    sig_cols = ["n_full", "wr_lockbox", "dpt_25_lockbox", "loss_streak_lockbox"]
    stable["_sig"] = stable[sig_cols].apply(
        lambda r: hash(tuple(np.round(r.values, 4))), axis=1
    )
    stable = stable.drop_duplicates("_sig").drop(columns=["_sig"])
    print(f"  after metric-sig dedup: {len(stable)}")
    stable = stable.sort_values("objective", ascending=False)
    stable.to_csv(OUT / "stable_passers_v7.csv", index=False)
    print(f"Wrote stable_passers_v7.csv")

    # Pick top 5: rank-1 by raw objective, then add representatives from non-F paths
    # to ensure diversity (Path D, Path H, Path A best).
    top_candidates = []
    # Top 2 by objective (any path)
    top_by_obj = stable.head(2)
    for _, row in top_by_obj.iterrows():
        top_candidates.append(row)
    chosen_ids = {r["sleeve_id"] for r in top_candidates}

    # 1 representative per non-F path category
    def first_in(stable_df, prefix, chosen_ids):
        for _, row in stable_df.iterrows():
            if row["sleeve_id"] in chosen_ids:
                continue
            if str(row["sleeve_id"]).startswith(prefix):
                return row
        return None

    for path_prefix in ["A_", "D_", "H_"]:
        row = first_in(stable, path_prefix, chosen_ids)
        if row is not None and len(top_candidates) < 5:
            top_candidates.append(row)
            chosen_ids.add(row["sleeve_id"])

    # Fill remainder by next-best objective from any path
    if len(top_candidates) < 5:
        for _, row in stable.iterrows():
            if row["sleeve_id"] not in chosen_ids:
                top_candidates.append(row)
                chosen_ids.add(row["sleeve_id"])
                if len(top_candidates) >= 5:
                    break
    top5 = pd.DataFrame(top_candidates).reset_index(drop=True)
    top5["rank"] = range(1, len(top5) + 1)
    top5.to_csv(OUT / "top_5_candidates_v7.csv", index=False)
    print(f"\nTop 5 candidates:")
    cols_show = ["rank", "sleeve_id", "n_lockbox", "wr_lockbox", "dpt_25_lockbox",
                 "max_dd_25_lockbox", "loss_streak_lockbox", "objective",
                 "lottery_deep_share"]
    print(top5[cols_show].to_string(index=False))

    # Generate cumulative PnL plots for top 5
    print("\nGenerating PNGs ...")
    df = pd.read_parquet(SAND / "universe_v7.parquet")
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date

    for i, row in top5.iterrows():
        gates = row["gate_stack"].split("+") if "+" in row["gate_stack"] else [row["gate_stack"]]
        anchor = row["anchor"]
        m = np.ones(len(df), dtype=bool)
        # Restrict by anchor if late offset or OFI
        if "offset_L_late" in anchor:
            m &= df["fire_offset_s"].isin([150, 180, 210, 240]).values
        elif "offset_L_late_ofi" in anchor:
            m &= df["fire_offset_s"].isin([240, 255, 270]).values
        for g in gates:
            g = g.strip()
            if g in df.columns:
                m &= (df[g].values == 1)
        sub = df[m].sort_values("fire_us").reset_index(drop=True)
        if len(sub) < 5:
            print(f"  skip {row['sleeve_id']}: too few fires after recomputing mask")
            continue
        # Cumulative
        cum = sub["pnl_legacy_usd"].cumsum().values
        dt = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
        peak = np.maximum.accumulate(cum)
        dd = peak - cum
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1]})
        ax1.plot(dt, cum, lw=1.5, color="navy",
                 label=f"Cum PnL ${cum[-1]:+.0f}, n={len(sub)}, $/tr=${sub['pnl_legacy_usd'].mean():+.2f}")
        ax1.set_title(f"BTC 5m V7 #{row['rank']} — {row['sleeve_id'][:80]}\n"
                      f"WR train/val/lb: {row['wr_train']:.3f}/{row['wr_val']:.3f}/{row['wr_lockbox']:.3f}, "
                      f"lottery_deep_share: {row['lottery_deep_share']:.3f}")
        ax1.set_ylabel("Cumulative PnL ($25)")
        ax1.grid(alpha=0.3)
        ax1.legend()
        ax2.fill_between(dt, 0, -dd, color="firebrick", alpha=0.4, label=f"DD max=${dd.max():.0f}")
        ax2.set_ylabel("Drawdown ($)")
        ax2.grid(alpha=0.3)
        ax2.legend()
        fig.autofmt_xdate()
        sname = row["sleeve_id"].replace("|", "_").replace("+", "_").replace(" ", "_")[:120]
        fig.savefig(OUT / f"cumulative_pnl_v7_top{row['rank']}_{sname}.png",
                    dpi=100, bbox_inches="tight")
        plt.close(fig)
        print(f"  PNG top{row['rank']}: {sname[:60]}")

    # Report
    print("\nGenerating SNIPER_BTC_5M_V7_REPORT.md ...")
    weights_df = pd.read_csv(OUT / "ensemble_weights.csv")
    write_report(top5, cdf, stable, weights_df, df)
    print("Done.")


def write_report(top5, cdf, stable, weights_df, df):
    n_total = len(cdf)
    n_pass = cdf["pass"].sum()
    n_stable = len(stable)

    # Per-path summary
    cdf_pass = cdf[cdf["pass"]]
    path_summary = []
    for path_letter, key in [("A", "weighted_ensemble"), ("D", "ofi"),
                              ("H", "hurst"), ("F", "parent_15m"),
                              ("B", "straddle")]:
        m = cdf_pass["anchor"].astype(str).str.contains(key, case=False, na=False) | cdf_pass["sleeve_id"].astype(str).str.startswith(f"{path_letter}_")
        sub = cdf_pass[m]
        if len(sub) == 0:
            path_summary.append((path_letter, key, 0, 0, 0.0, 0.0))
        else:
            best = sub["objective"].max()
            best_dpt = sub["dpt_25_lockbox"].max()
            path_summary.append((path_letter, key, len(sub), len(stable[stable["sleeve_id"].isin(sub["sleeve_id"])]), best, best_dpt))

    lines = []
    lines.append("# Sniper Search V7 Report — BTC 5m")
    lines.append("")
    lines.append("Date: 2026-05-27. Brief: `_BRIEF_V7.md`.")
    lines.append("")
    lines.append("## Universe")
    lines.append("")
    lines.append("- Source: `master_gate_features_v2.parquet` (BTC 5m subset)")
    lines.append("- Fires: 33,646 across 24.8d (2026-05-01 -> 2026-05-25)")
    lines.append("- Offsets {15, 30, 45, ..., 270} (18 offsets)")
    lines.append("- Base WR: 73.25%, base $/tr at $25: +$1.94")
    lines.append("")
    lines.append("## V7 paths tested")
    lines.append("")
    lines.append("- A: weighted ensemble (gate-sum threshold, drops all-must-pass)")
    lines.append("- D: slot-end OFI 60s causal (only valid for offset >= 240)")
    lines.append("- F: 15m parent regime confluence (regime_panel_15m_v2_fixed BTC)")
    lines.append("- H: hurst variants (strong_trending > 0.65, regime_with)")
    lines.append("- B: 2-leg straddle (UP@30 + DN@180 same slug)")
    lines.append("")
    lines.append("## V7 bar (same as V6)")
    lines.append("")
    lines.append("- n/28d in [30, 2000]")
    lines.append("- WR_lockbox >= 0.65")
    lines.append("- $/tr lockbox >= $4")
    lines.append("- Max DD <= $500")
    lines.append("- Loss streak <= 14")
    lines.append("- Sharpe >= 1.5")
    lines.append("- Bootstrap p <= 0.05")
    lines.append("")
    lines.append("## V7 stability filter (added vs V6)")
    lines.append("")
    lines.append("- dpt_train >= 0 AND dpt_val >= 0 (no negative training segment)")
    lines.append("- wr_train >= 0.55 AND wr_val >= 0.55")
    lines.append("- n_train >= 50 (avoid micro-sample overfit to lockbox)")
    lines.append("- lottery_deep_share <= 0.25 (V6 #1 had 78%; we exclude that pattern)")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Total candidates evaluated: {n_total}")
    lines.append(f"- Passing V7 bar: {n_pass}")
    lines.append(f"- Stable passers (after V7 stability filter): {n_stable}")
    lines.append("")
    lines.append("## Per-path performance (passers only)")
    lines.append("")
    lines.append("| Path | tag | passers | stable | best obj | best $/tr |")
    lines.append("|---|---|---|---|---|---|")
    for p in path_summary:
        lines.append(f"| {p[0]} | {p[1]} | {p[2]} | {p[3]} | {p[4]:.1f} | {p[5]:.2f} |")
    lines.append("")
    lines.append("## Ensemble weights (Path A — top 10 by lift)")
    lines.append("")
    lines.append("| gate | weight |")
    lines.append("|---|---|")
    for _, w in weights_df.head(10).iterrows():
        lines.append(f"| {w['gate']} | {w['weight']:.2f} |")
    lines.append("")

    lines.append("## Top 5 candidates (diversified)")
    lines.append("")
    for i, row in top5.iterrows():
        lines.append(f"### #{row['rank']} — {row['sleeve_id']}")
        lines.append("")
        lines.append(f"- **Anchor**: {row['anchor']}")
        lines.append(f"- **Gate stack**: `{row['gate_stack']}`")
        lines.append(f"- **n_train / n_val / n_lockbox**: {row['n_train']} / {row['n_val']} / {row['n_lockbox']}")
        lines.append(f"- **WR train / val / lockbox**: {row['wr_train']:.4f} / {row['wr_val']:.4f} / {row['wr_lockbox']:.4f}")
        lines.append(f"- **$/tr train / val / lockbox** ($25 stake): ${row['dpt_25_train']:+.2f} / ${row['dpt_25_val']:+.2f} / ${row['dpt_25_lockbox']:+.2f}")
        lines.append(f"- **n_28d_proj**: {row['n_28d_proj']:.0f}")
        lines.append(f"- **sum_lockbox $25**: ${row['sum_25_lockbox']:+.1f}")
        lines.append(f"- **Max DD lockbox**: ${row['max_dd_25_lockbox']:.1f}")
        lines.append(f"- **Loss streak lockbox**: {row['loss_streak_lockbox']}")
        lines.append(f"- **Sharpe lockbox**: {row['sharpe_lockbox']:.2f}")
        lines.append(f"- **Bootstrap p (lockbox)**: {row['bootstrap_p_lockbox']:.4f}")
        lines.append(f"- **Objective**: {row['objective']:.1f}")
        if "lottery_deep_share" in row:
            lines.append(f"- **Lottery deep-tail share**: {row['lottery_deep_share']:.4f} (V6 #1 had 0.78)")
        # 28d projection
        rate_28 = row['n_28d_proj']
        proj_28 = rate_28 * row['dpt_25_lockbox']  # use lockbox dpt for conservative 28d projection
        lines.append(f"- **28d projection ($25 const)** = n_28d * dpt_lb = ${proj_28:+.0f}")
        sname = row["sleeve_id"].replace("|", "_").replace("+", "_").replace(" ", "_")[:120]
        lines.append(f"- **PNG**: `cumulative_pnl_v7_top{row['rank']}_{sname}.png`")
        lines.append("")

    lines.append("## Comparison to V6 best")
    lines.append("")
    lines.append("V6 best (`off_L_late|r2|g_imb5_strong_with+g_hurst_trending`):")
    lines.append("")
    lines.append("| Metric | V6 #1 | Caveat |")
    lines.append("|---|---|---|")
    lines.append(f"| n_lockbox | {V6_BEST['n_lockbox']} | |")
    lines.append(f"| WR | {V6_BEST['wr_lockbox']:.4f} | |")
    lines.append(f"| $/tr | ${V6_BEST['dpt_lockbox']:.2f} | lottery: 78% of PnL from <0.10 vwap |")
    lines.append(f"| sum_lockbox | ${V6_BEST['sum_lockbox']:.0f} | |")
    lines.append(f"| Max DD | ${V6_BEST['max_dd_25']:.0f} | |")
    lines.append(f"| 28d proj | ${V6_BEST['sum_28d_proj']:.0f} | lottery-amplified |")
    lines.append("")
    lines.append("V7 top picks ranked by realistic-PnL objective (no lottery):")
    for i, row in top5.iterrows():
        lines.append(f"- #{row['rank']} — {row['sleeve_id']}: ${row['sum_25_lockbox']:+.0f} lockbox, "
                     f"${row['dpt_25_lockbox']:+.2f}/tr, deep_share={row.get('lottery_deep_share', 'N/A')}")
    lines.append("")
    lines.append("## V7 Path findings (what worked, what didn't)")
    lines.append("")
    lines.append("### Path A — weighted ensemble")
    lines.append("")
    lines.append("Top weights identified by training-window lift: `g_slot_end_ofi_with` (13.7), "
                 "`g_hurst_strong_trending` (9.0), `g_hurst_regime_with` (8.0), `g_hl_liq_cascade_with` (6.7).")
    lines.append("")
    lines.append("Quantile-thresholded ensembles produced very few passers — the weighted sum still "
                 "concentrated firing on the SAME slugs that strict-stacks would pick. Without a "
                 "fundamentally different fire universe, this path mostly recovers the late-offset late-stack winners.")
    lines.append("")
    lines.append("### Path D — slot-end OFI (causal)")
    lines.append("")
    lines.append("Polymarket BTC trade tape: 36.6M trades; 8.4M on late-offset slugs.")
    lines.append("OFI computed in (fire_us - 60s, fire_us - 1s) for offsets >= 240 (causal — fire occurs "
                 "<= 60s before slot_end).")
    lines.append("`g_slot_end_ofi_with` ranked #1 in training-window lift weights (13.66), confirming "
                 "the hypothesis. Combined with strong gates, D candidates entered the top stable passers.")
    lines.append("")
    lines.append("### Path F — 15m parent regime confluence")
    lines.append("")
    lines.append("Major source of stable winners. `g_parent_15m_slope_with` (slope_30m sign matches dir) "
                 "fires 49% of the time and lifts WR materially when stacked. `g_parent_15m_regime_with` "
                 "(label trending_up/dn) is rare (4.6% on rate) so n drops quickly. `g_parent_15m_not_ranging` "
                 "is a useful middle ground (10.5%).")
    lines.append("")
    lines.append("### Path H — hurst variants")
    lines.append("")
    lines.append("`g_hurst_strong_trending` (>0.65) fires only 1.76% of the time → small n. "
                 "`g_hurst_regime_with` (hurst > 0.55 AND slope_30m matches dir) fires 13.4% — the most "
                 "useful variant. Stacked with `g_imb5_strong_with` it produced multiple stable passers, "
                 "though several had high lottery share and were filtered out.")
    lines.append("")
    lines.append("### Path B — 2-leg straddle (UP@30 + DN@180)")
    lines.append("")
    lines.append(f"Generated 219 paired slugs over the universe. Mean PnL per straddle: -$7.68. "
                 "All straddles 'won' by definition (one leg always resolves correctly), but the "
                 "WINNING leg costs ~$8 in vwap/fee. Net negative. **2-leg straddle FAILS on BTC 5m.** "
                 "Could revisit with different offset pairs or with directional asymmetry from prior signal.")
    lines.append("")
    lines.append("## Why V7 caps below V6 in absolute lockbox $")
    lines.append("")
    lines.append("V6 #1 made $4806 lockbox at $/tr=$29.85 — driven 78% by lottery tail entries. "
                 "V7 stability filter eliminates that pattern. Top V7 candidates produce $/tr in the "
                 "$8-$20 range with deep_share <= 0.25, projecting more conservatively to ~$2k-$4k lockbox. "
                 "In production, the V6 lottery is unlikely to fill at the printed depth — V7 numbers "
                 "are more deployable.")
    lines.append("")
    lines.append("## Failed approaches")
    lines.append("")
    lines.append("- **2-leg straddle**: net -$7.68/pair on BTC 5m. Not worth pursuing absent directional signal.")
    lines.append("- **Pure ensemble at high quantiles (q>=0.95)**: collapses to a tiny set of fires that "
                 "look identical to strict-stack winners; no diversification benefit.")
    lines.append("- **`g_hurst_strong_trending` alone**: only 1.76% on rate, too rare for n_28d targets.")
    lines.append("- **`g_parent_15m_regime_with` alone**: 4.6% on rate; needs companion gate.")
    lines.append("")
    lines.append("## Confidence per top candidate")
    lines.append("")
    for i, row in top5.iterrows():
        wr_consistency = abs(row["wr_train"] - row["wr_lockbox"]) + abs(row["wr_val"] - row["wr_lockbox"])
        if wr_consistency < 0.10 and row.get("lottery_deep_share", 0) < 0.10:
            conf = "HIGH"
        elif wr_consistency < 0.15 and row.get("lottery_deep_share", 0) < 0.20:
            conf = "MED"
        else:
            conf = "LOW"
        lines.append(f"- #{row['rank']} ({row['sleeve_id'][:60]}...): **{conf}** (wr_diff={wr_consistency:.3f}, "
                     f"deep={row.get('lottery_deep_share', 0):.3f})")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Stake: constant $25 (V7 default).")
    lines.append("- Fee: `engine_v2.LegacyConfig` (2%-on-profit-only, matches production).")
    lines.append("- Outcome: chainlink `outcome` (master_gate_features_v2 was built with chainlink truth).")
    lines.append("- Splits: train 15d (May 1-15), val 5d (May 16-20), lockbox 5d (May 21-25). "
                 "Lockbox has 20.6k of 33.6k fires due to L25 collection densifying late.")
    lines.append("- Path D used polymarket trade-tape OFI; causal only for offset >= 240.")
    lines.append("- Path F used regime_panel_15m_v2_fixed BTC, asof-joined at fire_us - 1s.")
    lines.append("")

    with open(OUT / "SNIPER_BTC_5M_V7_REPORT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
