"""Regime-conditional WR analysis for top sleeves + portfolio comparison + gate search.

Tasks 3, 4, 5, 6, 7 from the regime-meta brief.

Inputs:
  - data/v4/canonical/_results/hybrid_gate_search_per_fire_regime.parquet
  - data/v4/canonical/_results/hybrid_features_5m_regime.parquet (for base S1.5 fires)
  - data/v4/canonical/_results/hybrid_features_15m_regime.parquet
  - data/v4/canonical/_results/s6_with_ta_regime.parquet
  - data/v4/canonical/_results/s15_with_ta_and_markov_regime.parquet
  - data/v4/canonical/_results/v15m_with_ta_and_markov_regime.parquet
  - data/v4/canonical/_results/hybrid_gate_search_top.csv

Outputs:
  - data/v4/canonical/_results/regime_sleeve_profile.csv
  - data/v4/canonical/_results/regime_portfolio_compare.csv
  - data/v4/canonical/_results/regime_gate_search.csv
  - data/v4/canonical/_results/regime_walkforward.csv
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES  = ROOT / "data" / "v4" / "canonical" / "_results"

WIN_START_US = int(dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc).timestamp() * 1e6)
WIN_END_US   = int(dt.datetime(2026, 5, 23, tzinfo=dt.timezone.utc).timestamp() * 1e6)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def wr_stats(df: pd.DataFrame, pnl_col: str = "pnl_legacy_usd",
             won_col: str = "won") -> dict:
    if df.empty:
        return dict(n=0, wins=0, WR=np.nan, sum_pnl=0.0, dpt=np.nan, sharpe_d=np.nan)
    n = len(df)
    pnl = df[pnl_col].astype(float)
    wins = int(df[won_col].astype(float).sum()) if won_col in df.columns else int((pnl > 0).sum())
    return dict(
        n=n,
        wins=wins,
        WR=wins / n,
        sum_pnl=float(pnl.sum()),
        dpt=float(pnl.mean()),
        sharpe_d=float(pnl.mean() / pnl.std()) if pnl.std() > 0 else np.nan,
    )


def sleeve_key(row) -> str:
    return f"{row['asset']}|{row['tf']}|{row['offset_bin']}|{row['gate_stack']}"


# ----------------------------------------------------------------------------
# Task 3 — Top sleeve regime profile (Tier-1 + S1.5 + S6)
# ----------------------------------------------------------------------------

def task3_top_sleeve_profile():
    df = pd.read_parquet(RES / "hybrid_gate_search_per_fire_regime.parquet")
    df = df[df["regime_label"].notna()].copy()
    print(f"Tier-1 per-fire (regime-labeled): {len(df):,}")

    # Top 7 Tier-1 sleeves from hybrid_gate_search_top.csv (dedup by sleeve key)
    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top = top.sort_values("sum_pnl", ascending=False)
    # Pick 1 best sleeve per (asset, tf, offset_bin) cell so we get DIVERSE
    # exposure rather than 7 near-clones of the same BTC s6 sleeve.
    seen_cells = set()
    sleeves = []
    for _, r in top.iterrows():
        k = (r["asset"], r["tf"], r["offset_bin"])
        if k in seen_cells:
            continue
        seen_cells.add(k)
        sleeves.append(r)
        if len(sleeves) >= 7:
            break
    top7 = pd.DataFrame(sleeves)
    print(f"Top 7 unique Tier-1 sleeves:")
    for _, s in top7.iterrows():
        print(f"  {s['asset']} {s['tf']} {s['offset_bin']} | {s['gate_stack'][:80]} | sum_pnl={s['sum_pnl']:.0f}")

    rows = []
    for _, s in top7.iterrows():
        mask = (
            (df["asset"] == s["asset"]) &
            (df["tf"] == s["tf"]) &
            (df["offset_bin"] == s["offset_bin"]) &
            (df["gate_stack"] == s["gate_stack"])
        )
        sub = df[mask]
        if sub.empty:
            continue
        overall = wr_stats(sub)
        sum_pnl_overall = overall["sum_pnl"]
        for regime in ["trending_up", "trending_dn", "ranging"]:
            r = wr_stats(sub[sub["regime_label"] == regime])
            r["sleeve_key"] = sleeve_key(s)
            r["asset"]      = s["asset"]
            r["tf"]         = s["tf"]
            r["offset_bin"] = s["offset_bin"]
            r["gate_stack"] = s["gate_stack"]
            r["sleeve_class"] = "tier1_top7"
            r["regime"]     = regime
            r["sum_pnl_pct_of_total"] = (r["sum_pnl"] / sum_pnl_overall) if sum_pnl_overall != 0 else np.nan
            r["overall_n"]   = overall["n"]
            r["overall_WR"]  = overall["WR"]
            r["overall_dpt"] = overall["dpt"]
            r["overall_sum"] = overall["sum_pnl"]
            rows.append(r)
    out_tier1 = pd.DataFrame(rows)

    # S1.5 base — top 10 by (asset, tf) groups within s15 panel
    s15 = pd.read_parquet(RES / "s15_with_ta_and_markov_regime.parquet")
    s15 = s15[s15["regime_label"].notna()]
    # Aggregate by (asset, direction) — top 10 (asset × direction × outcome)
    s15_rows = []
    # The S1.5 base sleeve identity = (asset, direction) — choose 10 highest-PnL combos
    g = s15.groupby(["asset", "direction"]).agg(
        n=("pnl_legacy_usd", "size"),
        sum_pnl=("pnl_legacy_usd", "sum"),
        WR=("won", "mean"),
        dpt=("pnl_legacy_usd", "mean"),
    ).reset_index().sort_values("sum_pnl", ascending=False).head(10)
    for _, s in g.iterrows():
        sub = s15[(s15["asset"] == s["asset"]) & (s15["direction"] == s["direction"])]
        overall = wr_stats(sub)
        for regime in ["trending_up", "trending_dn", "ranging"]:
            r = wr_stats(sub[sub["regime_label"] == regime])
            r["sleeve_key"] = f"S1.5|{s['asset']}|5m|{s['direction']}"
            r["asset"]      = s["asset"]
            r["tf"]         = "s15_5m"
            r["offset_bin"] = "all"
            r["gate_stack"] = f"direction={s['direction']}"
            r["sleeve_class"] = "s15_base_top10"
            r["regime"]     = regime
            r["sum_pnl_pct_of_total"] = (r["sum_pnl"] / overall["sum_pnl"]) if overall["sum_pnl"] != 0 else np.nan
            r["overall_n"]   = overall["n"]
            r["overall_WR"]  = overall["WR"]
            r["overall_dpt"] = overall["dpt"]
            r["overall_sum"] = overall["sum_pnl"]
            s15_rows.append(r)
    out_s15 = pd.DataFrame(s15_rows)

    # S6 base — top 10 by (asset, direction)
    s6 = pd.read_parquet(RES / "s6_with_ta_regime.parquet")
    s6 = s6[s6["regime_label"].notna()]
    g = s6.groupby(["asset", "direction"]).agg(
        n=("pnl_legacy_usd", "size"),
        sum_pnl=("pnl_legacy_usd", "sum"),
        WR=("won", "mean"),
        dpt=("pnl_legacy_usd", "mean"),
    ).reset_index().sort_values("sum_pnl", ascending=False).head(10)
    s6_rows = []
    for _, s in g.iterrows():
        sub = s6[(s6["asset"] == s["asset"]) & (s6["direction"] == s["direction"])]
        overall = wr_stats(sub)
        for regime in ["trending_up", "trending_dn", "ranging"]:
            r = wr_stats(sub[sub["regime_label"] == regime])
            r["sleeve_key"] = f"S6|{s['asset']}|5m|{s['direction']}"
            r["asset"]      = s["asset"]
            r["tf"]         = "s6_5m"
            r["offset_bin"] = "all"
            r["gate_stack"] = f"direction={s['direction']}"
            r["sleeve_class"] = "s6_base_top10"
            r["regime"]     = regime
            r["sum_pnl_pct_of_total"] = (r["sum_pnl"] / overall["sum_pnl"]) if overall["sum_pnl"] != 0 else np.nan
            r["overall_n"]   = overall["n"]
            r["overall_WR"]  = overall["WR"]
            r["overall_dpt"] = overall["dpt"]
            r["overall_sum"] = overall["sum_pnl"]
            s6_rows.append(r)
    out_s6 = pd.DataFrame(s6_rows)

    out = pd.concat([out_tier1, out_s15, out_s6], ignore_index=True)
    out_path = RES / "regime_sleeve_profile.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")

    # Print summary: regime-specific vs regime-agnostic
    print()
    print("=== Sleeve profile classification (Tier-1 top 7) ===")
    for k, grp in out_tier1.groupby("sleeve_key"):
        wrs = grp.set_index("regime")["WR"].to_dict()
        dpts = grp.set_index("regime")["dpt"].to_dict()
        wr_range = max(filter(np.isfinite, wrs.values()), default=0) - min(filter(np.isfinite, wrs.values()), default=0)
        flag = "REGIME-SPECIFIC" if wr_range > 0.10 else "regime-agnostic"
        print(f"  {flag:18}  {k}")
        for reg in ["trending_up","trending_dn","ranging"]:
            n = grp.set_index("regime").get("n", {}).get(reg, "?")
            print(f"     {reg:13} n={int(n) if pd.notna(n) else 0:>5} WR={wrs.get(reg, np.nan):.3f} dpt={dpts.get(reg, np.nan):+.3f}")

    return out


# ----------------------------------------------------------------------------
# Task 4 — Portfolio: always-on vs regime-routed
# ----------------------------------------------------------------------------

def task4_portfolio_compare():
    df = pd.read_parquet(RES / "hybrid_gate_search_per_fire_regime.parquet")
    df = df[df["regime_label"].notna()].copy()
    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top = top.sort_values("sum_pnl", ascending=False)
    # Pick 1 best sleeve per (asset, tf, offset_bin) cell so we get DIVERSE
    # exposure rather than 7 near-clones of the same BTC s6 sleeve.
    seen_cells = set()
    sleeves = []
    for _, r in top.iterrows():
        k = (r["asset"], r["tf"], r["offset_bin"])
        if k in seen_cells:
            continue
        seen_cells.add(k)
        sleeves.append(r)
        if len(sleeves) >= 7:
            break
    top7 = pd.DataFrame(sleeves)

    # Compute expected $/tr per (sleeve, regime) on the same data — leaks into
    # in-sample estimate; we'll redo with walk-forward in Task 7.
    regime_dpt = {}
    for _, s in top7.iterrows():
        mask = (
            (df["asset"] == s["asset"]) &
            (df["tf"] == s["tf"]) &
            (df["offset_bin"] == s["offset_bin"]) &
            (df["gate_stack"] == s["gate_stack"])
        )
        sub = df[mask]
        for regime in ["trending_up", "trending_dn", "ranging"]:
            sub_r = sub[sub["regime_label"] == regime]
            dpt = float(sub_r["pnl_legacy_usd"].mean()) if len(sub_r) else np.nan
            regime_dpt[(s["asset"], s["tf"], s["offset_bin"], s["gate_stack"], regime)] = dpt

    # Always-on PnL — sum every fire from every sleeve
    always_on_pnl = 0.0
    always_on_n   = 0
    always_on_pnl_list = []
    routed_pnl  = 0.0
    routed_n    = 0
    routed_pnl_list  = []
    for _, s in top7.iterrows():
        mask = (
            (df["asset"] == s["asset"]) &
            (df["tf"] == s["tf"]) &
            (df["offset_bin"] == s["offset_bin"]) &
            (df["gate_stack"] == s["gate_stack"])
        )
        sub = df[mask].copy()
        for _, fire in sub.iterrows():
            pnl = float(fire["pnl_legacy_usd"])
            always_on_pnl += pnl
            always_on_n   += 1
            always_on_pnl_list.append(pnl)
            dpt = regime_dpt.get((s["asset"], s["tf"], s["offset_bin"], s["gate_stack"], fire["regime_label"]), np.nan)
            if pd.notna(dpt) and dpt > 0:
                routed_pnl += pnl
                routed_n   += 1
                routed_pnl_list.append(pnl)

    # Sharpe (per-fire), max DD
    def metric(name, lst):
        arr = np.asarray(lst)
        if arr.size == 0:
            return None
        cum = np.cumsum(arr)
        dd  = np.max(np.maximum.accumulate(cum) - cum)
        return dict(
            label=name, n=len(arr),
            sum_pnl=float(arr.sum()), dpt=float(arr.mean()),
            sharpe=float(arr.mean() / arr.std()) if arr.std() > 0 else np.nan,
            max_DD=float(dd),
            WR=float((arr > 0).mean()),
        )

    rows = [metric("always_on", always_on_pnl_list), metric("regime_routed", routed_pnl_list)]
    out = pd.DataFrame([r for r in rows if r is not None])
    out_path = RES / "regime_portfolio_compare.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")
    print(out.to_string(index=False))
    return out, regime_dpt


# ----------------------------------------------------------------------------
# Task 5 — Regime as new gate
# ----------------------------------------------------------------------------

def task5_regime_as_gate():
    df = pd.read_parquet(RES / "hybrid_gate_search_per_fire_regime.parquet")
    df = df[df["regime_label"].notna()].copy()
    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top = top.sort_values("sum_pnl", ascending=False)
    # Pick 1 best sleeve per (asset, tf, offset_bin) cell so we get DIVERSE
    # exposure rather than 7 near-clones of the same BTC s6 sleeve.
    seen_cells = set()
    sleeves = []
    for _, r in top.iterrows():
        k = (r["asset"], r["tf"], r["offset_bin"])
        if k in seen_cells:
            continue
        seen_cells.add(k)
        sleeves.append(r)
        if len(sleeves) >= 7:
            break
    top7 = pd.DataFrame(sleeves)

    rows = []
    for _, s in top7.iterrows():
        mask = (
            (df["asset"] == s["asset"]) &
            (df["tf"] == s["tf"]) &
            (df["offset_bin"] == s["offset_bin"]) &
            (df["gate_stack"] == s["gate_stack"])
        )
        sub = df[mask].copy()
        if sub.empty:
            continue
        base = wr_stats(sub); base["gate"] = "base"
        rows.append({"sleeve_key": sleeve_key(s), **base})
        # g_trending_up_with_up: keep only fires where regime=trending_up AND direction=Up
        g1 = sub[(sub["regime_label"] == "trending_up") & (sub["direction"] == "Up")]
        a = wr_stats(g1); a["gate"] = "g_trending_up_with_up"
        rows.append({"sleeve_key": sleeve_key(s), **a})
        # g_trending_dn_with_dn
        g2 = sub[(sub["regime_label"] == "trending_dn") & (sub["direction"] == "Down")]
        b = wr_stats(g2); b["gate"] = "g_trending_dn_with_dn"
        rows.append({"sleeve_key": sleeve_key(s), **b})
        # g_ranging
        g3 = sub[sub["regime_label"] == "ranging"]
        c = wr_stats(g3); c["gate"] = "g_ranging"
        rows.append({"sleeve_key": sleeve_key(s), **c})
        # g_trend_agreeing: regime is trending AND direction agrees
        g4 = sub[((sub["regime_label"] == "trending_up") & (sub["direction"] == "Up")) |
                 ((sub["regime_label"] == "trending_dn") & (sub["direction"] == "Down"))]
        d = wr_stats(g4); d["gate"] = "g_trend_agrees"
        rows.append({"sleeve_key": sleeve_key(s), **d})

    out = pd.DataFrame(rows)
    out_path = RES / "regime_gate_search.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")
    return out


# ----------------------------------------------------------------------------
# Task 6 — Adverse-regime veto
# ----------------------------------------------------------------------------

def task6_adverse_veto():
    df = pd.read_parquet(RES / "hybrid_gate_search_per_fire_regime.parquet")
    df = df[df["regime_label"].notna()].copy()
    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top = top.sort_values("sum_pnl", ascending=False)
    # Pick 1 best sleeve per (asset, tf, offset_bin) cell so we get DIVERSE
    # exposure rather than 7 near-clones of the same BTC s6 sleeve.
    seen_cells = set()
    sleeves = []
    for _, r in top.iterrows():
        k = (r["asset"], r["tf"], r["offset_bin"])
        if k in seen_cells:
            continue
        seen_cells.add(k)
        sleeves.append(r)
        if len(sleeves) >= 7:
            break
    top7 = pd.DataFrame(sleeves)

    rows = []
    for _, s in top7.iterrows():
        mask = (
            (df["asset"] == s["asset"]) &
            (df["tf"] == s["tf"]) &
            (df["offset_bin"] == s["offset_bin"]) &
            (df["gate_stack"] == s["gate_stack"])
        )
        sub = df[mask].copy()
        if sub.empty:
            continue
        # Determine the worst regime by sum_pnl per sleeve
        per_regime = sub.groupby("regime_label")["pnl_legacy_usd"].agg(["sum", "count", "mean"]).reset_index()
        worst = per_regime.sort_values("mean").iloc[0]
        worst_regime = worst["regime_label"]
        worst_dpt    = worst["mean"]
        worst_sum    = worst["sum"]
        # With veto: drop fires in worst regime
        vetoed = sub[sub["regime_label"] != worst_regime]
        base   = wr_stats(sub)
        post   = wr_stats(vetoed)
        rows.append({
            "sleeve_key": sleeve_key(s),
            "asset": s["asset"], "tf": s["tf"],
            "worst_regime": worst_regime,
            "worst_n": int(worst["count"]),
            "worst_dpt": float(worst_dpt),
            "worst_sum_pnl": float(worst_sum),
            "base_n": base["n"], "base_WR": base["WR"], "base_dpt": base["dpt"], "base_sum": base["sum_pnl"],
            "veto_n": post["n"], "veto_WR": post["WR"], "veto_dpt": post["dpt"], "veto_sum": post["sum_pnl"],
            "delta_sum_pnl": post["sum_pnl"] - base["sum_pnl"],
            "delta_dpt": post["dpt"] - base["dpt"],
        })
    out = pd.DataFrame(rows)
    out_path = RES / "regime_adverse_veto.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")
    print(out[["sleeve_key", "worst_regime", "base_dpt", "veto_dpt", "base_sum", "veto_sum", "delta_sum_pnl"]].to_string(index=False))
    return out


# ----------------------------------------------------------------------------
# Task 7 — Walk-forward
# ----------------------------------------------------------------------------

def task7_walkforward():
    """20d train / 8d test simulation. Train on first 20d (Apr 30 -> May 20),
    test on next 3 days available (May 20 -> May 22). Compute regime-routed
    portfolio metrics on test."""
    df = pd.read_parquet(RES / "hybrid_gate_search_per_fire_regime.parquet")
    df = df[df["regime_label"].notna()].copy()
    df["day"] = (df["fire_us"] // 86_400_000_000).astype("int64")

    # Use Apr 30 -> May 20 as train (20d), May 20 -> end-of-window as test
    train_end_us = int(dt.datetime(2026, 5, 20, tzinfo=dt.timezone.utc).timestamp() * 1e6)
    train = df[df["fire_us"] < train_end_us]
    test  = df[df["fire_us"] >= train_end_us]
    print(f"train fires: {len(train):,} ({train['day'].nunique()} days)")
    print(f"test  fires: {len(test):,}  ({test['day'].nunique()} days)")

    top = pd.read_csv(RES / "hybrid_gate_search_top.csv")
    top = top.sort_values("sum_pnl", ascending=False)
    # Pick 1 best sleeve per (asset, tf, offset_bin) cell so we get DIVERSE
    # exposure rather than 7 near-clones of the same BTC s6 sleeve.
    seen_cells = set()
    sleeves = []
    for _, r in top.iterrows():
        k = (r["asset"], r["tf"], r["offset_bin"])
        if k in seen_cells:
            continue
        seen_cells.add(k)
        sleeves.append(r)
        if len(sleeves) >= 7:
            break
    top7 = pd.DataFrame(sleeves)

    # Learn regime $/tr on train
    train_dpt = {}
    for _, s in top7.iterrows():
        mask = (
            (train["asset"] == s["asset"]) &
            (train["tf"] == s["tf"]) &
            (train["offset_bin"] == s["offset_bin"]) &
            (train["gate_stack"] == s["gate_stack"])
        )
        sub = train[mask]
        for regime in ["trending_up", "trending_dn", "ranging"]:
            sub_r = sub[sub["regime_label"] == regime]
            train_dpt[(s["asset"], s["tf"], s["offset_bin"], s["gate_stack"], regime)] = \
                float(sub_r["pnl_legacy_usd"].mean()) if len(sub_r) else np.nan

    # Compute test PnL under always-on and regime-routed
    always_test = []
    routed_test = []
    veto_test   = []
    for _, s in top7.iterrows():
        mask = (
            (test["asset"] == s["asset"]) &
            (test["tf"] == s["tf"]) &
            (test["offset_bin"] == s["offset_bin"]) &
            (test["gate_stack"] == s["gate_stack"])
        )
        sub = test[mask]
        # Identify worst regime in train
        worst_regime = None
        if not train[mask.reindex(train.index, fill_value=False) | True].empty:
            tr_sub = train[(train["asset"] == s["asset"]) & (train["tf"] == s["tf"]) &
                           (train["offset_bin"] == s["offset_bin"]) & (train["gate_stack"] == s["gate_stack"])]
            if not tr_sub.empty:
                per_regime = tr_sub.groupby("regime_label")["pnl_legacy_usd"].mean()
                if len(per_regime):
                    worst_regime = per_regime.idxmin()
        for _, fire in sub.iterrows():
            pnl = float(fire["pnl_legacy_usd"])
            always_test.append(pnl)
            dpt = train_dpt.get((s["asset"], s["tf"], s["offset_bin"], s["gate_stack"], fire["regime_label"]), np.nan)
            if pd.notna(dpt) and dpt > 0:
                routed_test.append(pnl)
            if worst_regime is None or fire["regime_label"] != worst_regime:
                veto_test.append(pnl)

    # Bootstrap CIs on test
    def metric(name, lst, n_boot=2000, seed=42):
        arr = np.asarray(lst)
        if arr.size == 0:
            return dict(label=name, n=0)
        rng = np.random.default_rng(seed)
        boots_dpt = []
        boots_sum = []
        for _ in range(n_boot):
            ids = rng.integers(0, arr.size, arr.size)
            boots_dpt.append(arr[ids].mean())
            boots_sum.append(arr[ids].sum())
        boots_dpt = np.sort(boots_dpt); boots_sum = np.sort(boots_sum)
        cum = np.cumsum(arr); dd = np.max(np.maximum.accumulate(cum) - cum) if arr.size else 0
        return dict(
            label=name, n=arr.size,
            sum_pnl=float(arr.sum()), dpt=float(arr.mean()),
            dpt_ci_low=float(boots_dpt[int(0.025 * n_boot)]),
            dpt_ci_high=float(boots_dpt[int(0.975 * n_boot)]),
            sum_ci_low=float(boots_sum[int(0.025 * n_boot)]),
            sum_ci_high=float(boots_sum[int(0.975 * n_boot)]),
            max_DD=float(dd),
            WR=float((arr > 0).mean()),
        )

    rows = [metric("always_on_test", always_test),
            metric("regime_routed_test", routed_test),
            metric("worst_regime_veto_test", veto_test)]
    out = pd.DataFrame(rows)
    out_path = RES / "regime_walkforward.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote: {out_path}")
    print(out.to_string(index=False))
    return out


# ----------------------------------------------------------------------------
# Bonus: regime-vs-existing-gate overlap (g_ribbon_agrees)
# ----------------------------------------------------------------------------

def regime_vs_ribbon_overlap():
    """Compare regime gates against g_ribbon_agrees from hybrid_features. If regime
    is just rebuilding ribbon -> expose."""
    df = pd.read_parquet(RES / "hybrid_features_5m_regime.parquet")
    df = df[df["regime_label"].notna()].copy()
    # ribbon_alignment_pct from fire-time TA panel (NOT renamed for hybrid file because
    # original column kept its name). After augment the column was renamed only when
    # collision detected; verify presence.
    # fire-time TA panel ribbon (left side of asof) is *_x; regime-bar (right) is *_y
    if "ribbon_alignment_pct_x" in df.columns:
        rib_col = "ribbon_alignment_pct_x"
    elif "ribbon_alignment_pct" in df.columns:
        rib_col = "ribbon_alignment_pct"
    elif "ribbon_alignment_pct_regime" in df.columns:
        rib_col = "ribbon_alignment_pct_regime"
    else:
        print("no ribbon column found; available:", df.columns.tolist())
        return None
    print(f"  using ribbon col: {rib_col}")
    df["g_ribbon_align"] = df[rib_col] >= 70
    df["g_regime_trending"] = df["regime_label"].isin(["trending_up", "trending_dn"])
    ct = pd.crosstab(df["g_ribbon_align"], df["g_regime_trending"], margins=True)
    print("=== Overlap: ribbon_align>=70 vs regime in (trending_up|trending_dn) ===")
    print(ct)
    both = ((df["g_ribbon_align"]) & (df["g_regime_trending"])).sum()
    either = ((df["g_ribbon_align"]) | (df["g_regime_trending"])).sum()
    print(f"Jaccard: {both / either if either else 0:.3f}")
    eq = (df["g_ribbon_align"] == df["g_regime_trending"]).mean()
    print(f"Equal predictions: {eq:.3f}")
    # Also: split per-asset
    for a in df["asset"].unique():
        sub = df[df["asset"] == a]
        ja = ((sub["g_ribbon_align"]) & (sub["g_regime_trending"])).sum() / max(((sub["g_ribbon_align"]) | (sub["g_regime_trending"])).sum(), 1)
        eqa = (sub["g_ribbon_align"] == sub["g_regime_trending"]).mean()
        print(f"  {a}: Jaccard={ja:.3f}, equal={eqa:.3f}")
    return ct


if __name__ == "__main__":
    print("\n=== TASK 3: per-sleeve regime profile ===")
    task3_top_sleeve_profile()

    print("\n=== TASK 4: portfolio always-on vs regime-routed ===")
    task4_portfolio_compare()

    print("\n=== TASK 5: regime as new gate ===")
    task5_regime_as_gate()

    print("\n=== TASK 6: adverse-regime veto ===")
    task6_adverse_veto()

    print("\n=== TASK 7: walk-forward (20d train / 3d test) ===")
    task7_walkforward()

    print("\n=== BONUS: regime vs ribbon overlap ===")
    regime_vs_ribbon_overlap()
