"""
polymarket_side_asymmetry.py — STANDALONE candidate strategy (NOT a modification of q10/q20 baseline).

Hypothesis (from JBecker 2026 + arXiv 2602.19520 papers):
  - Crypto retail traders have "number-go-up" bias → systematic OVERPRICING of YES (Up) tokens
  - Per JBecker: dollar-weighted YES buyers -1.02% vs NO buyers +0.83% (1.85pp asymmetry)
  - Per JBecker crypto category: 2.69pp maker-taker gap (highest after Sports)

If this generalizes to Polymarket BTC/ETH/SOL UpDown:
  - Our DOWN bets (sig=0, buy NO at no_ask) should outperform UP bets (sig=1, buy YES at yes_ask)
  - The asymmetry should be statistically distinguishable on q10 universe (~579 trades)

Tests run:
  1. Direction asymmetry: split q10 trades by sig (UP vs DOWN), compare hit/ROI
  2. Entry-price overpricing: distribution of (entry_yes_ask + entry_no_ask). Mean > 1.0?
  3. Value-bet filter: do trades with cheap entry side beat expensive entries?
  4. Cross-asset replication: does asymmetry hold separately on BTC, ETH, SOL?
  5. Day-by-day stability: 5-day decomposition

Outputs:
  results/polymarket/side_asymmetry.csv
  reports/POLYMARKET_SIDE_ASYMMETRY.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Reuse loaders + simulator from v2 baseline (DO NOT modify them)
from polymarket_signal_grid_v2 import (
    load_features, load_trajectories, load_klines_1m, simulate_market,
)

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5  # locked baseline exit

OUT_CSV = HERE / "results" / "polymarket" / "side_asymmetry.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_SIDE_ASYMMETRY.md"


def add_q10_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Top 10% of |ret_5m| per (asset, tf). Same logic as forward_walk_q10."""
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r_abs = df.loc[m, "ret_5m"].abs()
            thr = r_abs.quantile(0.90)
            sel = m & (df.ret_5m.abs() >= thr) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def add_q20_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Top 20% — for cross-checking on the broader sample."""
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r_abs = df.loc[m, "ret_5m"].abs()
            thr = r_abs.quantile(0.80)
            sel = m & (df.ret_5m.abs() >= thr) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def sim_with_detail(df, traj, k1m, rev_bp=REV_BP):
    """Run hedge-hold simulator per row, return per-trade DataFrame with sig direction + entry prices."""
    rows = []
    for _, row in df.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        pnl = simulate_market(row, traj_g, k1m[row.asset],
                              target=None, stop=None, rev_bp=rev_bp,
                              merge_aware=False, hedge_hold=True)
        if pnl is None or not np.isfinite(pnl):
            continue
        rows.append({
            "asset": row.asset, "tf": row.timeframe, "slug": row.slug,
            "sig": int(row.signal),  # 1=UP buy YES, 0=DOWN buy NO
            "outcome_up": int(row.outcome_up),
            "ret_5m": float(row.ret_5m),
            "entry_yes_ask": float(row.entry_yes_ask) if pd.notna(row.entry_yes_ask) else float("nan"),
            "entry_no_ask": float(row.entry_no_ask) if pd.notna(row.entry_no_ask) else float("nan"),
            "entry_used": float(row.entry_yes_ask) if int(row.signal) == 1 else float(row.entry_no_ask),
            "ws": int(row.window_start_unix),
            "pnl": pnl,
        })
    return pd.DataFrame(rows)


def boot_ci(pnls, n_boot=10000):
    p = np.array(pnls)
    n = len(p)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan"),
                "hit": float("nan"), "roi": float("nan")}
    boot = RNG.choice(p, size=(n_boot, n), replace=True).mean(axis=1)
    return {
        "n": n,
        "mean": float(p.mean()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((p > 0).mean()),
        "roi": float(p.mean() * 100),  # per-share v2-metric
    }


def two_sample_perm(a, b, n_perm=10000):
    """Permutation test for difference of means (b - a). Returns p-value."""
    a, b = np.array(a), np.array(b)
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    obs = b.mean() - a.mean()
    pool = np.concatenate([a, b])
    na = len(a)
    diffs = []
    for _ in range(n_perm):
        RNG.shuffle(pool)
        diffs.append(pool[na:].mean() - pool[:na].mean())
    diffs = np.array(diffs)
    # two-sided
    return float(np.mean(np.abs(diffs) >= np.abs(obs)))


def main():
    print("Loading data + computing q10 signal...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}

    feats_q10 = add_q10_signal(feats)
    feats_q20 = add_q20_signal(feats)
    print(f"q10 markets: {len(feats_q10)}; q20 markets: {len(feats_q20)}")

    print("Simulating per-trade for q10 universe...")
    df_q10 = sim_with_detail(feats_q10, traj, k1m)
    print(f"q10 sim returned {len(df_q10)} trades")

    print("Simulating per-trade for q20 universe (for confirmation on bigger sample)...")
    df_q20 = sim_with_detail(feats_q20, traj, k1m)
    print(f"q20 sim returned {len(df_q20)} trades")

    md = ["# Side-Asymmetry Test — Standalone Candidate Strategy\n",
          "**Hypothesis:** Crypto retail bias toward UP causes structural overpricing of YES tokens.",
          "Tested on Polymarket BTC/ETH/SOL UpDown markets (Apr 22-27, 2026).",
          "Strategy core: same as locked baseline (sig_ret5m + hedge-hold rev_bp=5), but stratified by direction.\n",
          "**Source motivation:** JBecker (2026) Kalshi 72.1M trades — NO outperforms YES at 69/99 price levels; "
          "dollar-weighted YES -1.02% vs NO +0.83%. Crypto category 2.69pp gap.\n"]

    rows_out = []

    # ===== Test 1: Direction asymmetry on q10 =====
    print("\n=== Test 1: UP vs DOWN asymmetry (q10) ===")
    md.append("\n## Test 1 — UP vs DOWN direction asymmetry (q10 universe)\n")
    md.append("If YES (Up) overpricing exists, DOWN bets should outperform UP bets.\n")
    md.append("| Slice | n | Hit% | ROI | 95% CI | perm-p (UP vs DOWN) |")
    md.append("|---|---|---|---|---|---|")
    overall_p = two_sample_perm(
        df_q10[df_q10.sig == 1].pnl.values,
        df_q10[df_q10.sig == 0].pnl.values,
    )
    for tf in ["5m", "15m", "ALL"]:
        for asset in ["ALL", "btc", "eth", "sol"]:
            sub = df_q10
            if asset != "ALL":
                sub = sub[sub.asset == asset]
            if tf != "ALL":
                sub = sub[sub.tf == tf]
            up = sub[sub.sig == 1]
            dn = sub[sub.sig == 0]
            up_s = boot_ci(up.pnl.values)
            dn_s = boot_ci(dn.pnl.values)
            p_val = two_sample_perm(up.pnl.values, dn.pnl.values, n_perm=2000)
            md.append(f"| {asset}×{tf} UP   | {up_s['n']} | {up_s['hit']*100:.1f}% | "
                      f"{up_s['roi']:+.2f}% | [{up_s['ci_lo']*100:+.2f}, {up_s['ci_hi']*100:+.2f}]% | — |")
            md.append(f"| {asset}×{tf} DOWN | {dn_s['n']} | {dn_s['hit']*100:.1f}% | "
                      f"{dn_s['roi']:+.2f}% | [{dn_s['ci_lo']*100:+.2f}, {dn_s['ci_hi']*100:+.2f}]% | "
                      f"p={p_val:.3f} |")
            rows_out.append({"test": "direction", "universe": "q10", "asset": asset, "tf": tf,
                             "up_n": up_s["n"], "up_hit": up_s["hit"], "up_roi": up_s["roi"],
                             "dn_n": dn_s["n"], "dn_hit": dn_s["hit"], "dn_roi": dn_s["roi"],
                             "perm_p": p_val})
            print(f"  {asset:3s} {tf:3s}  UP n={up_s['n']:>3d} hit={up_s['hit']*100:5.1f}% ROI={up_s['roi']:+6.2f}% | "
                  f"DOWN n={dn_s['n']:>3d} hit={dn_s['hit']*100:5.1f}% ROI={dn_s['roi']:+6.2f}% | p={p_val:.3f}")

    md.append(f"\n**Overall q10 UP-vs-DOWN permutation p-value: {overall_p:.4f}**")
    if overall_p < 0.05:
        md.append("→ Direction asymmetry IS statistically significant. Worth pursuing.")
    elif overall_p < 0.10:
        md.append("→ Direction asymmetry is MARGINAL.")
    else:
        md.append("→ NO significant direction asymmetry detected at this sample size.")

    # ===== Test 2: Entry-price overpricing =====
    print("\n=== Test 2: Entry-price overpricing (yes_ask + no_ask sum) ===")
    md.append("\n## Test 2 — Entry-price overpricing\n")
    md.append("If markets are perfectly priced, entry_yes_ask + entry_no_bid ≈ 1.00 (no arbitrage). "
              "Any premium above 1.00 = both sides overpriced (taker pays spread). "
              "Asymmetric premium = one side overpriced more than the other.\n")
    df_q10_pricing = df_q10.dropna(subset=["entry_yes_ask", "entry_no_ask"]).copy()
    df_q10_pricing["sum_asks"] = df_q10_pricing["entry_yes_ask"] + df_q10_pricing["entry_no_ask"]
    md.append(f"\nMean (yes_ask + no_ask): {df_q10_pricing['sum_asks'].mean():.4f}")
    md.append(f"Median: {df_q10_pricing['sum_asks'].median():.4f}")
    md.append(f"P25, P75: {df_q10_pricing['sum_asks'].quantile(0.25):.4f}, "
              f"{df_q10_pricing['sum_asks'].quantile(0.75):.4f}")
    md.append(f"\nMean entry_yes_ask: {df_q10_pricing['entry_yes_ask'].mean():.4f}")
    md.append(f"Mean entry_no_ask: {df_q10_pricing['entry_no_ask'].mean():.4f}")
    md.append(f"Mean (1 - entry_no_ask) [implied YES from NO ask]: "
              f"{(1 - df_q10_pricing['entry_no_ask']).mean():.4f}")
    md.append(f"\nDelta (yes_ask - (1 - no_ask)) = how overpriced is YES vs implied-from-NO:")
    delta = df_q10_pricing["entry_yes_ask"] - (1 - df_q10_pricing["entry_no_ask"])
    md.append(f"  Mean: {delta.mean():+.4f} ({delta.mean()*100:+.2f}¢)")
    md.append(f"  Bootstrap 95% CI of delta mean: see below.")
    boot = RNG.choice(delta.values, size=(10000, len(delta)), replace=True).mean(axis=1)
    md.append(f"  CI: [{np.quantile(boot, 0.025):+.4f}, {np.quantile(boot, 0.975):+.4f}]")
    if np.quantile(boot, 0.025) > 0:
        md.append("→ YES is **systematically overpriced** vs implied-from-NO (CI excludes zero).")
    elif np.quantile(boot, 0.975) < 0:
        md.append("→ YES is **systematically underpriced** vs implied-from-NO (CI excludes zero) — opposite of paper hypothesis!")
    else:
        md.append("→ No systematic asymmetry detected (CI overlaps zero).")

    # ===== Test 3: Cross-asset replication of direction asymmetry =====
    md.append("\n## Test 3 — Cross-asset replication of direction asymmetry (q10)\n")
    md.append("Per asset, compare DOWN ROI minus UP ROI. If 3 unrelated assets agree on sign, signal is robust.\n")
    md.append("| Asset | UP n | UP ROI | DOWN n | DOWN ROI | DOWN−UP delta |")
    md.append("|---|---|---|---|---|---|")
    deltas = []
    for asset in ["btc", "eth", "sol"]:
        sub = df_q10[df_q10.asset == asset]
        up = boot_ci(sub[sub.sig == 1].pnl.values)
        dn = boot_ci(sub[sub.sig == 0].pnl.values)
        d = dn["roi"] - up["roi"]
        deltas.append(d)
        md.append(f"| {asset} | {up['n']} | {up['roi']:+.2f}% | "
                  f"{dn['n']} | {dn['roi']:+.2f}% | "
                  f"**{d:+.2f}pp** |")
    n_positive = sum(1 for d in deltas if d > 0)
    md.append(f"\n→ {n_positive}/3 assets show DOWN > UP ROI.")
    if n_positive == 3:
        md.append("**Strong cross-asset replication** — all 3 assets confirm DOWN bets win more.")
    elif n_positive == 2:
        md.append("**Moderate replication** — 2 of 3 assets confirm.")
    else:
        md.append("**Weak / no cross-asset replication.**")

    # ===== Test 4: Day-by-day decomposition =====
    md.append("\n## Test 4 — Day-by-day decomposition of direction asymmetry\n")
    md.append("Stable lift across days = real signal. Driven by 1 day = artifact.\n")
    df_q10["dt"] = pd.to_datetime(df_q10.ws, unit="s", utc=True)
    df_q10["date"] = df_q10.dt.dt.date
    md.append("| Date | UP n | UP ROI | DOWN n | DOWN ROI | DOWN−UP |")
    md.append("|---|---|---|---|---|---|")
    days_with_lift = 0
    for d in sorted(df_q10.date.unique()):
        sub = df_q10[df_q10.date == d]
        up = boot_ci(sub[sub.sig == 1].pnl.values)
        dn = boot_ci(sub[sub.sig == 0].pnl.values)
        delta = dn["roi"] - up["roi"]
        if delta > 0:
            days_with_lift += 1
        md.append(f"| {d} | {up['n']} | {up['roi']:+.2f}% | "
                  f"{dn['n']} | {dn['roi']:+.2f}% | "
                  f"{delta:+.2f}pp |")
    n_days = df_q10.date.nunique()
    md.append(f"\n→ {days_with_lift}/{n_days} days show DOWN > UP ROI.")

    # ===== Test 5: q20 confirmation (bigger sample) =====
    md.append("\n## Test 5 — q20 confirmation (larger sample n=1152)\n")
    md.append("If asymmetry is real, it should also appear on the wider q20 universe (more statistical power).\n")
    up_q20 = boot_ci(df_q20[df_q20.sig == 1].pnl.values)
    dn_q20 = boot_ci(df_q20[df_q20.sig == 0].pnl.values)
    p_q20 = two_sample_perm(df_q20[df_q20.sig == 1].pnl.values,
                            df_q20[df_q20.sig == 0].pnl.values, n_perm=10000)
    md.append(f"| Slice | n | Hit% | ROI | 95% CI |")
    md.append(f"|---|---|---|---|---|")
    md.append(f"| q20 UP   | {up_q20['n']} | {up_q20['hit']*100:.1f}% | {up_q20['roi']:+.2f}% | "
              f"[{up_q20['ci_lo']*100:+.2f}, {up_q20['ci_hi']*100:+.2f}]% |")
    md.append(f"| q20 DOWN | {dn_q20['n']} | {dn_q20['hit']*100:.1f}% | {dn_q20['roi']:+.2f}% | "
              f"[{dn_q20['ci_lo']*100:+.2f}, {dn_q20['ci_hi']*100:+.2f}]% |")
    md.append(f"\n**q20 perm p-value (UP vs DOWN): {p_q20:.4f}**")

    # ===== Verdict =====
    md.append("\n## Verdict\n")
    md.append("To deploy as a new strategy candidate, the side-asymmetry needs:")
    md.append("1. q10 perm p-value < 0.05 (statistically significant)")
    md.append("2. ≥ 2/3 cross-asset agreement on sign")
    md.append("3. ≥ 4/5 days showing the predicted direction")
    md.append("4. q20 confirmation (perm p < 0.05 on larger sample)")
    md.append("5. CI of yes-vs-no-implied delta excludes zero\n")
    n_criteria_met = 0
    if overall_p < 0.05:
        n_criteria_met += 1
    if sum(1 for d in deltas if d > 0) >= 2:
        n_criteria_met += 1
    if days_with_lift >= 4:
        n_criteria_met += 1
    if p_q20 < 0.05:
        n_criteria_met += 1
    if np.quantile(boot, 0.025) > 0 or np.quantile(boot, 0.975) < 0:
        n_criteria_met += 1
    md.append(f"**Criteria met: {n_criteria_met} / 5**")
    if n_criteria_met >= 4:
        md.append("\n✅ **DEPLOY** as new strategy candidate. Direction asymmetry is robust.")
    elif n_criteria_met >= 2:
        md.append("\n⚠️ **PARTIAL signal.** Worth running on more data before deploy.")
    else:
        md.append("\n❌ **NO clear edge** in side asymmetry on Polymarket BTC/ETH/SOL — "
                  "paper findings (Kalshi-based, longshot-heavy) don't replicate on our mid-priced UpDown markets.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_out).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")
    print(f"\nCriteria met: {n_criteria_met}/5")
    print(f"Overall q10 perm p: {overall_p:.4f}")
    print(f"q20 perm p: {p_q20:.4f}")


if __name__ == "__main__":
    main()
