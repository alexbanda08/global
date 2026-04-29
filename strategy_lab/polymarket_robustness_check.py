"""
polymarket_robustness_check.py — small-sample-appropriate validation for alt-strategies.

Forward-walk on 5-day data has inadequate power for fine stacks (< 100 holdout trades).
Use these instead:

  1. Cross-asset hour-rank stability — Spearman correlation of hourly ROI rankings
     across BTC, ETH, SOL. If all 3 assets independently agree on which hours are
     good, that's 3 confirmations of one signal — strong evidence vs overfitting.

  2. Permutation test — sample N random subsets of 12 hours, compute ROI lift
     vs unfiltered. Is our chosen "good hours" selection an outlier in the
     permutation distribution?

  3. Bootstrap CI — resample filtered trades with replacement, compute 95% CI
     on filtered ROI. Does the CI exclude the unfiltered baseline ROI?

  4. Day-by-day decomposition — apply each stack day-by-day. Is the lift
     consistent or driven by 1 anomalous day?

Reads: results/polymarket/time_of_day_per_trade.csv (1152 trades with hour_utc, dow, asset, pnl)

Outputs:
  results/polymarket/robustness_check.csv
  reports/POLYMARKET_ROBUSTNESS_CHECK.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)

GOOD_HOURS = {3, 5, 8, 9, 10, 11, 12, 13, 14, 17, 19, 21}
BAD_HOURS = {0, 2, 4, 7, 16}
EUROPE_HOURS = set(range(8, 13))


def spearman(x, y):
    """Manual Spearman correlation (avoid scipy dep)."""
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    return float(np.corrcoef(rx, ry)[0, 1])


def load():
    """Load per-trade data with hour, day, asset, pnl, signal."""
    df = pd.read_csv(HERE/"results"/"polymarket"/"time_of_day_per_trade.csv")
    df["dt"] = pd.to_datetime(df.ws, unit="s", utc=True)
    df["date"] = df.dt.dt.date
    return df


# === Test 1: Cross-asset hour-rank stability ===
def cross_asset_stability(df):
    """Compute hourly ROI per asset, then Spearman rank correlation between assets."""
    by_asset_hour = {}
    for asset in df.asset.unique():
        sub = df[df.asset == asset]
        roi_by_hour = []
        for h in range(24):
            t = sub[sub.hour_utc == h]
            roi = t.pnl.mean() * 100 if len(t) > 0 else float("nan")
            roi_by_hour.append({"hour": h, "roi": roi, "n": len(t)})
        by_asset_hour[asset] = pd.DataFrame(roi_by_hour)

    # Pairwise Spearman on hours where both assets have data
    pairs = []
    assets = sorted(by_asset_hour.keys())
    for i, a in enumerate(assets):
        for b in assets[i+1:]:
            df_a = by_asset_hour[a]
            df_b = by_asset_hour[b]
            valid = df_a.roi.notna() & df_b.roi.notna()
            if valid.sum() < 4:
                continue
            rho = spearman(df_a.roi[valid], df_b.roi[valid])
            pairs.append({"pair": f"{a}↔{b}", "rho": rho, "n_hours": int(valid.sum())})

    # Best/worst hours per asset (top 5 / bot 5)
    overlap = []
    for asset in assets:
        d = by_asset_hour[asset].sort_values("roi", ascending=False)
        top5 = set(d.head(5).hour.values)
        bot5 = set(d.tail(5).hour.values)
        overlap.append({"asset": asset, "top5": sorted(top5), "bot5": sorted(bot5)})

    # Top-5 hour intersection across all 3
    top5_sets = [set(o["top5"]) for o in overlap]
    bot5_sets = [set(o["bot5"]) for o in overlap]
    top5_intersection = set.intersection(*top5_sets) if top5_sets else set()
    bot5_intersection = set.intersection(*bot5_sets) if bot5_sets else set()

    return {
        "by_asset_hour": by_asset_hour,
        "pairs": pairs,
        "overlap": overlap,
        "top5_all_assets": sorted(top5_intersection),
        "bot5_all_assets": sorted(bot5_intersection),
    }


# === Test 2: Permutation test ===
def permutation_test(df, n_perm=10000, n_keep=12):
    """How rare is our chosen good-hours selection?"""
    overall_roi = df.pnl.mean() * 100
    actual_roi_filtered = df[df.hour_utc.isin(GOOD_HOURS)].pnl.mean() * 100
    actual_lift = actual_roi_filtered - overall_roi

    # Random selection of n_keep hours, repeat n_perm times
    perm_lifts = []
    all_hours = list(range(24))
    for _ in range(n_perm):
        chosen = set(RNG.choice(all_hours, size=n_keep, replace=False))
        sub = df[df.hour_utc.isin(chosen)]
        if len(sub) < 50:
            continue
        lift = sub.pnl.mean() * 100 - overall_roi
        perm_lifts.append(lift)
    perm_lifts = np.array(perm_lifts)

    p_value = (perm_lifts >= actual_lift).mean()
    return {
        "actual_lift": actual_lift,
        "actual_roi_filtered": actual_roi_filtered,
        "overall_roi": overall_roi,
        "perm_n": len(perm_lifts),
        "perm_mean_lift": float(perm_lifts.mean()),
        "perm_std_lift": float(perm_lifts.std()),
        "perm_p_value": float(p_value),
        "perm_95_lift": float(np.quantile(perm_lifts, 0.95)),
    }


# === Test 3: Bootstrap CI ===
def bootstrap_ci(pnls, n_boot=10000, alpha=0.05):
    pnls = np.array(pnls)
    if len(pnls) == 0:
        return {"n": 0, "mean": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    samples = RNG.choice(pnls, size=(n_boot, len(pnls)), replace=True).mean(axis=1)
    return {
        "n": len(pnls),
        "mean": float(pnls.mean()),
        "ci_lo": float(np.quantile(samples, alpha/2)),
        "ci_hi": float(np.quantile(samples, 1 - alpha/2)),
    }


# === Test 4: Day-by-day decomposition ===
def day_by_day(df, stack_filter, stack_name):
    """Apply stack per day, compute daily ROI."""
    df_stack = df[stack_filter(df)]
    rows = []
    for d in sorted(df.date.unique()):
        sub = df_stack[df_stack.date == d]
        if len(sub) == 0:
            rows.append({"date": str(d), "n": 0, "hit": float("nan"), "roi": float("nan")})
            continue
        rows.append({
            "date": str(d),
            "n": len(sub),
            "hit": float((sub.pnl > 0).mean()),
            "roi": float(sub.pnl.mean() * 100),
        })
    overall = df_stack.pnl.mean() * 100
    return {"stack": stack_name, "overall_roi": overall, "n_total": len(df_stack), "by_day": rows}


# === Main ===
def main():
    df = load()
    print(f"Loaded {len(df)} trades")

    # ----- Test 1: cross-asset stability -----
    cas = cross_asset_stability(df)
    print("\n=== Test 1: Cross-asset hour-rank stability ===")
    for p in cas["pairs"]:
        rating = "STRONG" if p["rho"] > 0.5 else ("MEDIUM" if p["rho"] > 0.25 else "WEAK")
        print(f"  Spearman {p['pair']:12s} rho={p['rho']:+.3f} (n_hours={p['n_hours']}) [{rating}]")
    print(f"  Top-5-best hours common to ALL 3 assets: {cas['top5_all_assets']}")
    print(f"  Bot-5-worst hours common to ALL 3 assets: {cas['bot5_all_assets']}")
    print(f"  Our GOOD_HOURS selection: {sorted(GOOD_HOURS)}")
    overlap_good = set(GOOD_HOURS) & set(cas['top5_all_assets'])
    print(f"  Overlap of our GOOD_HOURS with universal top-5: {len(overlap_good)} / 5 ({sorted(overlap_good)})")

    # ----- Test 2: permutation test -----
    print("\n=== Test 2: Permutation test (10,000 random 12-hour subsets) ===")
    perm = permutation_test(df, n_perm=10000, n_keep=12)
    print(f"  Overall (no filter) ROI: {perm['overall_roi']:+.2f}%")
    print(f"  Our filter (good hours) ROI: {perm['actual_roi_filtered']:+.2f}%")
    print(f"  Lift: {perm['actual_lift']:+.2f}pp")
    print(f"  Permutation distribution: mean lift {perm['perm_mean_lift']:+.2f}pp, "
          f"std {perm['perm_std_lift']:.2f}pp, 95pct lift {perm['perm_95_lift']:+.2f}pp")
    print(f"  p-value (P[random ≥ actual]): {perm['perm_p_value']:.4f}")
    if perm['perm_p_value'] < 0.05:
        print(f"  → Lift is statistically significant at alpha=0.05")
    else:
        print(f"  → Lift NOT statistically significant — could be cherry-picking")

    # ----- Test 3: Bootstrap CIs for each stack -----
    print("\n=== Test 3: Bootstrap 95% CI on filtered vs baseline ROI ===")
    overall = df.pnl.mean() * 100
    print(f"  baseline (no filter): {len(df)} trades, ROI {overall:+.2f}%")

    stacks = [
        ("good_hours_only",  lambda x: x.hour_utc.isin(GOOD_HOURS)),
        ("bad_excluded",     lambda x: ~x.hour_utc.isin(BAD_HOURS)),
        ("europe_only",      lambda x: x.hour_utc.isin(EUROPE_HOURS)),
    ]
    boot_rows = []
    for name, f in stacks:
        sub = df[f(df)]
        ci = bootstrap_ci(sub.pnl.values * 100)  # scale by 100 to get ROI%
        ci_excludes_baseline = ci["ci_lo"] > overall
        print(f"  {name:20s} n={ci['n']:>4d} mean ROI {ci['mean']:+.2f}% "
              f"95% CI [{ci['ci_lo']:+.2f}%, {ci['ci_hi']:+.2f}%] "
              f"{'STAT.SIG.' if ci_excludes_baseline else 'overlaps baseline'}")
        boot_rows.append({"stack": name, **ci, "excludes_baseline": ci_excludes_baseline})

    # ----- Test 4: Day-by-day decomposition -----
    print("\n=== Test 4: Day-by-day breakdown ===")
    day_results = []
    for name, f in stacks:
        d = day_by_day(df, f, name)
        day_results.append(d)
        print(f"\n  Stack: {name} (overall {d['overall_roi']:+.2f}%, n={d['n_total']})")
        for row in d["by_day"]:
            roi_str = f"{row['roi']:+.2f}%" if not np.isnan(row['roi']) else "—"
            hit_str = f"{row['hit']*100:.1f}%" if not np.isnan(row['hit']) else "—"
            print(f"    {row['date']}: n={row['n']:>3d} hit={hit_str:>6s} ROI={roi_str:>8s}")

    # ----- Write report -----
    out_md_lines = ["# Robustness Check — alt-strategies on small (5-day) sample\n",
                    "Forward-walk holdout has inadequate power on 5-day data for stacked filters. "
                    "Using small-sample-appropriate tests instead.\n"]

    out_md_lines.append("\n## 1. Cross-asset hour-rank stability\n")
    out_md_lines.append("Each asset's hourly ROI ranking is computed independently. "
                        "If 3 unrelated assets agree on which hours are good, the signal is robust.\n")
    out_md_lines.append("| Pair | Spearman ρ | n_hours | Verdict |")
    out_md_lines.append("|---|---|---|---|")
    for p in cas["pairs"]:
        v = "STRONG (>0.5)" if p["rho"] > 0.5 else ("MEDIUM (0.25-0.5)" if p["rho"] > 0.25 else "WEAK (<0.25)")
        out_md_lines.append(f"| {p['pair']} | {p['rho']:+.3f} | {p['n_hours']} | {v} |")
    out_md_lines.append(f"\n**Top-5 best hours (intersection of all 3 assets):** {cas['top5_all_assets']}")
    out_md_lines.append(f"**Bot-5 worst hours (intersection):** {cas['bot5_all_assets']}")
    out_md_lines.append(f"\nOur cross-asset GOOD_HOURS choice was: {sorted(GOOD_HOURS)}")
    out_md_lines.append(f"Overlap with universal top-5: **{len(overlap_good)}/5** ({sorted(overlap_good)})")

    out_md_lines.append("\n## 2. Permutation test on time-of-day filter\n")
    out_md_lines.append(f"10,000 random 12-hour subsets sampled. Compared lift of our chosen subset to permutation distribution.\n")
    out_md_lines.append(f"- Overall (unfiltered) ROI: **{perm['overall_roi']:+.2f}%**")
    out_md_lines.append(f"- Our filter ROI: **{perm['actual_roi_filtered']:+.2f}%**")
    out_md_lines.append(f"- Actual lift: **{perm['actual_lift']:+.2f}pp**")
    out_md_lines.append(f"- Permutation 95th percentile lift: {perm['perm_95_lift']:+.2f}pp")
    out_md_lines.append(f"- **p-value**: {perm['perm_p_value']:.4f}")
    if perm['perm_p_value'] < 0.05:
        out_md_lines.append(f"- **Verdict: SIGNIFICANT** at α=0.05. Random hour selections rarely beat our pick.")
    elif perm['perm_p_value'] < 0.10:
        out_md_lines.append(f"- **Verdict: MARGINAL** (0.05 < p < 0.10). Suggestive, not conclusive.")
    else:
        out_md_lines.append(f"- **Verdict: NOT SIGNIFICANT**. Our pick is not unusually good — likely cherry-picked.")

    out_md_lines.append("\n## 3. Bootstrap 95% CI on filtered ROI vs baseline\n")
    out_md_lines.append(f"Baseline (no filter): n={len(df)}, ROI **{overall:+.2f}%**\n")
    out_md_lines.append("| Stack | n | Mean ROI | 95% CI | Excludes baseline? |")
    out_md_lines.append("|---|---|---|---|---|")
    for r in boot_rows:
        out_md_lines.append(f"| {r['stack']} | {r['n']} | {r['mean']:+.2f}% | "
                            f"[{r['ci_lo']:+.2f}%, {r['ci_hi']:+.2f}%] | "
                            f"{'**YES** — significant' if r['excludes_baseline'] else 'no — overlap'} |")

    out_md_lines.append("\n## 4. Day-by-day breakdown\n")
    for d in day_results:
        out_md_lines.append(f"\n### {d['stack']} (overall {d['overall_roi']:+.2f}%, n={d['n_total']})")
        out_md_lines.append("| Date | n | Hit% | ROI |")
        out_md_lines.append("|---|---|---|---|")
        for row in d["by_day"]:
            roi_str = f"{row['roi']:+.2f}%" if not np.isnan(row['roi']) else "—"
            hit_str = f"{row['hit']*100:.1f}%" if not np.isnan(row['hit']) else "—"
            out_md_lines.append(f"| {row['date']} | {row['n']} | {hit_str} | {roi_str} |")

    out_md_lines.append("\n## Verdict\n")
    out_md_lines.append("Combining all 4 tests:")
    out_md_lines.append(f"- Cross-asset hour rank stability: see Spearman table above")
    out_md_lines.append(f"- Permutation p-value: {perm['perm_p_value']:.4f}")
    out_md_lines.append(f"- Bootstrap CIs: see Test 3")
    out_md_lines.append(f"- Day-by-day stability: see Test 4 — look for consistent lift across all 5 days")
    out_md_lines.append(f"\n**Action:** if (a) Spearman ≥ 0.4 between all asset pairs, AND (b) permutation p < 0.05, "
                        "AND (c) bootstrap CI excludes baseline, AND (d) at least 4/5 days show lift, the strategy is "
                        "robust enough to deploy at small stake. Otherwise, wait for more data.")

    out_md = HERE/"reports"/"POLYMARKET_ROBUSTNESS_CHECK.md"
    out_md.write_text("\n".join(out_md_lines), encoding="utf-8")
    print(f"\nWrote {out_md}")

    # Also write CSV with daily data
    daily_rows = []
    for d in day_results:
        for row in d["by_day"]:
            daily_rows.append({"stack": d["stack"], **row})
    pd.DataFrame(daily_rows).to_csv(HERE/"results"/"polymarket"/"robustness_daily.csv", index=False)


if __name__ == "__main__":
    main()
