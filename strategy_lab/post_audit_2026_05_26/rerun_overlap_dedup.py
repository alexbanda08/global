"""TASK 3 + 5: Re-run overlap-audit pipeline on CLEAN panels.

Steps:
  1. Build sleeve fire matrix on CLEAN (v2_fixed) panels.
  2. Greedy primary portfolio selection (same logic as PP's 03_dedup).
  3. Compute marginal contribution per sleeve with corrected (28/3.96) scaling.
  4. Final deploy manifest with per-sleeve status.

Output:
  data/v4/canonical/_results/_post_audit_2026_05_26/fired_by_sleeve_clean.parquet
  data/v4/canonical/_results/_post_audit_2026_05_26/sleeve_summary_clean.csv
  data/v4/canonical/_results/final_deploy_manifest_v2_post_audit.csv
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
FW = RES / "_full_window_2026_05_26"
OUT = RES / "_post_audit_2026_05_26"
OUT.mkdir(parents=True, exist_ok=True)

LOCKBOX_DAYS = 3.96
SCALE_28D = 28.0 / LOCKBOX_DAYS  # = 7.07x

# Same sleeve registry as 01_build_fire_matrix.py
SLEEVES = [
    dict(id="S6TA_btc_top1", asset="BTC", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50", "g_ribbon_agrees"],
         direction="BOTH", base="s6_hybrid_v1"),
    dict(id="S6TA_eth_top1", asset="ETH", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"],
         direction="BOTH", base="s6_hybrid_v1"),
    dict(id="poly_updown_btc_5m_s6_hybrid_v1", asset="BTC", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50", "g_ribbon_agrees"],
         direction="BOTH", base="s6_hybrid_v1"),
    dict(id="poly_updown_eth_5m_s6_hybrid_v1", asset="ETH", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"],
         direction="BOTH", base="s6_hybrid_v1"),
    dict(id="poly_updown_sol_5m_s6_hybrid_v1", asset="SOL", tf="5m", off=(60, 150),
         gates=["g_mfi_with", "g_bb_pos_with", "g_ribbon_agrees"],
         direction="BOTH", base="s6_hybrid_v1"),
    dict(id="poly_updown_btc_5m_s15_hybrid_v1", asset="BTC", tf="5m", off=(150, 240),
         gates=["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with", "g_tight_ribbon"],
         direction="BOTH", base="s15_hybrid_v1"),
    dict(id="poly_updown_eth_5m_s15_hybrid_v1", asset="ETH", tf="5m", off=(150, 240),
         gates=["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with", "g_bb_pos_with", "g_cci_with"],
         direction="BOTH", base="s15_hybrid_v1"),
    dict(id="S7_btc_5m_base", asset="BTC", tf="5m", off=(120, 300),
         gates=["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50",
                "g_tr_above_ema200", "g_ribbon_agrees"],
         direction="BOTH", base="s7_cyclops"),
    dict(id="R1_btc_5m_s6_top2", asset="BTC", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_rf_with", "g_ribbon_agrees"],
         direction="BOTH", base="s6_top2"),
    dict(id="R1_btc_5m_s6_lite", asset="BTC", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_ribbon_agrees"],
         direction="BOTH", base="s6_lite"),
    dict(id="R1_eth_5m_s6_tight_pos_cloud", asset="ETH", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees", "g_tr_above_cloud",
                "g_tight_ribbon"],
         direction="BOTH", base="s6_tight"),
    dict(id="R2_btc_5m_s1_5_3bps", asset="BTC", tf="5m", off=(60, 180),
         gates=["g_within_dev", "g_rf_strong", "g_ribbon_agrees"],
         direction="BOTH", base="s1_5"),
    dict(id="R4_POOL_15m_600_720_ribbon_slope_vwap", asset="BTC", tf="15m", off=(600, 720),
         gates=["g_ribbon_agrees", "g_rf_strong", "g_within_dev"],
         direction="BOTH", base="15m_pool_ribbon_slope"),
    dict(id="R5_microprice_univ_5m_rf_ribbon", asset="UNIV", tf="5m", off=(60, 300),
         gates=["__mp_no_extreme__", "g_rf_with", "g_ribbon_agrees"],
         direction="BOTH", base="microprice"),
    dict(id="R5_hawkes_btc_5m_off120", asset="BTC", tf="5m", off=(90, 150),
         gates=["__hawkes_imb_with__"],
         direction="HAWKES", base="hawkes"),
    dict(id="R5_hawkes_eth_5m_off120", asset="ETH", tf="5m", off=(90, 150),
         gates=["__hawkes_imb_with__"],
         direction="HAWKES", base="hawkes"),
    dict(id="R5_hawkes_sol_5m_off120", asset="SOL", tf="5m", off=(90, 150),
         gates=["__hawkes_imb_with__"],
         direction="HAWKES", base="hawkes"),
    dict(id="R5_eth_s6_v1_plus_mp_no_extreme", asset="ETH", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees", "__mp_no_extreme__"],
         direction="BOTH", base="s6_hybrid_v1+mp"),
    dict(id="R5_eth_s6_v1_plus_mp_change_with", asset="ETH", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees", "__mp_change_with__"],
         direction="BOTH", base="s6_hybrid_v1+mp_change"),
    dict(id="R5_btc_s6_v1_plus_lm_high_stat", asset="BTC", tf="5m", off=(60, 150),
         gates=["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50",
                "g_ribbon_agrees", "__lm_high_stat__"],
         direction="BOTH", base="s6_hybrid_v1+lm"),
    dict(id="R5_btc_s15_v1_plus_mp_no_extreme", asset="BTC", tf="5m", off=(150, 240),
         gates=["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with", "g_tight_ribbon", "__mp_no_extreme__"],
         direction="BOTH", base="s15_hybrid_v1+mp"),
]


def main():
    print("Loading CLEAN base panels (v2_fixed) …")
    panels = {}
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            p = FW / f"oos_fires_{asset}_{tf}_v2_fixed.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                for g in [c for c in df.columns if c.startswith("g_")]:
                    df[g] = pd.to_numeric(df[g], errors="coerce").fillna(0).astype(int)
                panels[(asset, tf)] = df
                print(f"  {asset} {tf}: {len(df):,}")

    # Load overlays
    print("Loading R5 overlays…")
    mp = pd.read_parquet(RES / "microprice_panel.parquet")[
        ["asset", "slug", "tf", "fire_us", "fire_offset_s", "mp_skew",
         "mp_weighted_skew", "mp_up_dev_change_500ms"]].copy()
    mp["g_mp_no_extreme"] = (mp["mp_skew"].abs() < 50).astype(int)
    mp["mp_change_sign"] = np.sign(mp["mp_up_dev_change_500ms"]).fillna(0).astype(int)
    hk = pd.read_parquet(RES / "hawkes_panel.parquet")
    hk = hk.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    lm = pd.read_parquet(RES / "lm_at_fires_5m.parquet")[
        ["asset", "slug", "fire_us", "fire_offset_s", "lm_L_stat_at_fire"]].copy()
    lm["g_lm_high_stat"] = (lm["lm_L_stat_at_fire"] > 5.97).fillna(False).astype(int)

    # Iterate sleeves
    records = []
    print("\nApplying gate stacks per sleeve…")
    for slv in SLEEVES:
        sid = slv["id"]
        asset, tf, off, gates, dpick, base_name = (
            slv["asset"], slv["tf"], slv["off"], slv["gates"],
            slv["direction"], slv["base"]
        )
        if asset == "UNIV":
            if tf == "5m":
                df = pd.concat([panels.get((a, "5m"), pd.DataFrame()) for a in ("BTC", "ETH", "SOL")],
                               ignore_index=True)
            else:
                df = pd.concat([panels.get((a, "15m"), pd.DataFrame()) for a in ("BTC", "ETH")],
                               ignore_index=True)
        else:
            df = panels.get((asset, tf), pd.DataFrame())
        if df.empty:
            continue
        df = df[(df["fire_offset_s"] >= off[0]) & (df["fire_offset_s"] <= off[1])].copy()

        overlays = [g for g in gates if g.startswith("__")]
        cores = [g for g in gates if not g.startswith("__")]

        m = pd.Series(True, index=df.index)
        skip = False
        for g in cores:
            if g not in df.columns:
                skip = True
                break
            m &= (df[g] == 1)
        if skip:
            continue
        df = df[m].copy()
        if df.empty:
            continue

        for og in overlays:
            if og == "__mp_no_extreme__":
                df = df.merge(mp[["slug", "fire_us", "g_mp_no_extreme"]],
                              on=["slug", "fire_us"], how="left")
                df = df[df["g_mp_no_extreme"] == 1]
            elif og == "__mp_change_with__":
                df = df.merge(mp[["slug", "fire_us", "mp_change_sign"]],
                              on=["slug", "fire_us"], how="left")
                dir_num = df["direction"].map({"UP": 1, "DOWN": -1}).fillna(0).astype(int)
                df = df[df["mp_change_sign"] == dir_num]
            elif og == "__lm_high_stat__":
                df = df.merge(lm[["slug", "fire_us", "g_lm_high_stat"]],
                              on=["slug", "fire_us"], how="left")
                df = df[df["g_lm_high_stat"] == 1]
            elif og == "__hawkes_imb_with__":
                asset_lc = df["asset"].iloc[0] if len(df) else None
                hk_a = hk[hk["asset"] == asset_lc].sort_values("ts_us")
                if len(hk_a) == 0:
                    df = df.iloc[0:0]
                    continue
                df = df.sort_values("fire_us")
                df = pd.merge_asof(df, hk_a[["ts_us", "lambda_imbalance"]],
                                    left_on="fire_us", right_on="ts_us",
                                    direction="backward", tolerance=10_000_000)
                df = df.dropna(subset=["lambda_imbalance"])
                df = df[df["lambda_imbalance"].abs() > 0.3]
                hawkes_dir = np.where(df["lambda_imbalance"] > 0, "UP", "DOWN")
                df = df[df["direction"] == hawkes_dir]

        if dpick == "UP":
            df = df[df["direction"] == "UP"]
        elif dpick == "DOWN":
            df = df[df["direction"] == "DOWN"]
        # HAWKES already filtered

        if df.empty:
            continue
        df["sleeve_id"] = sid
        df["base"] = base_name
        df["asset_norm"] = df["asset"]
        df["tf_norm"] = df["tf"]
        df["offset_lo"] = off[0]
        df["offset_hi"] = off[1]
        df["gate_stack_str"] = "&".join(gates)
        keep = ["sleeve_id", "base", "asset_norm", "tf_norm", "offset_lo", "offset_hi",
                "gate_stack_str", "slug", "fire_us", "fire_offset_s", "direction",
                "outcome", "won", "pnl_legacy_usd"]
        for k in keep:
            if k not in df.columns:
                df[k] = np.nan
        df_out = df[keep].copy()
        n = len(df_out)
        wr = df_out["won"].mean() * 100 if n else 0
        pnl_sum = df_out["pnl_legacy_usd"].sum()
        per_tr = df_out["pnl_legacy_usd"].mean() if n else 0
        print(f"  {sid:50s}  n={n:6d}  WR={wr:5.1f}%  $/tr=${per_tr:6.2f}  sum=${pnl_sum:9.0f}")
        records.append(df_out)

    fired = pd.concat(records, ignore_index=True)
    print(f"\nTOTAL fires across {len(records)} sleeves: {len(fired):,}")
    fired.to_parquet(OUT / "fired_by_sleeve_clean.parquet", compression="snappy")

    summary = fired.groupby("sleeve_id").agg(
        n=("won", "size"),
        wr=("won", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
        per_tr=("pnl_legacy_usd", "mean"),
        asset=("asset_norm", "first"),
        tf=("tf_norm", "first"),
        offset_lo=("offset_lo", "first"),
        offset_hi=("offset_hi", "first"),
    ).reset_index().sort_values("sum_pnl", ascending=False)
    summary["sum_28d"] = summary["sum_pnl"] * SCALE_28D
    summary["wr_pct"] = summary["wr"] * 100
    summary = summary[["sleeve_id", "asset", "tf", "offset_lo", "offset_hi",
                        "n", "wr_pct", "per_tr", "sum_pnl", "sum_28d"]]
    summary.to_csv(OUT / "sleeve_summary_clean.csv", index=False)

    # Greedy primary portfolio selection (slug-overlap dedup)
    print("\nGreedy primary portfolio selection…")
    pos_sleeves = summary[summary["sum_pnl"] > 0]["sleeve_id"].tolist()

    primary_ids = []
    primary_fires = pd.DataFrame(columns=fired.columns)
    rest_ids = pos_sleeves.copy()
    while rest_ids:
        # For each candidate, compute marginal pnl on slugs not already in primary
        best_id, best_marg = None, -1e9
        if len(primary_fires) > 0:
            pri_key = set(zip(primary_fires["slug"], primary_fires["fire_us"].astype("int64"),
                              primary_fires["direction"]))
        else:
            pri_key = set()
        for sid in rest_ids:
            sub = fired[fired["sleeve_id"] == sid]
            if sub.empty:
                continue
            keys = list(zip(sub["slug"], sub["fire_us"].astype("int64"), sub["direction"]))
            idx_new = [i for i, k in enumerate(keys) if k not in pri_key]
            marg = sub.iloc[idx_new]["pnl_legacy_usd"].sum()
            if marg > best_marg:
                best_marg, best_id = marg, sid
        if best_id is None or best_marg <= 0:
            break
        primary_ids.append(best_id)
        rest_ids.remove(best_id)
        primary_fires = pd.concat([primary_fires, fired[fired["sleeve_id"] == best_id]],
                                  ignore_index=True)
        print(f"  + {best_id:50s}  marginal=${best_marg:8.0f}  primary_size={len(primary_ids)}")

    print(f"\nPrimary portfolio: {len(primary_ids)} sleeves")
    primary_df = pd.DataFrame({"sleeve_id": primary_ids,
                                "rank": range(1, len(primary_ids) + 1)})
    primary_df.to_csv(OUT / "primary_portfolio_greedy_clean.csv", index=False)

    # Compute marginal contribution per sleeve when added to primary
    marginal_rows = []
    primary_key = set(zip(primary_fires["slug"],
                          primary_fires["fire_us"].astype("int64"),
                          primary_fires["direction"]))
    for sid in summary["sleeve_id"]:
        sub = fired[fired["sleeve_id"] == sid]
        if sub.empty:
            marginal_rows.append(dict(sleeve_id=sid, marginal_n=0,
                                       marginal_28d=0,
                                       in_primary=sid in primary_ids))
            continue
        if sid in primary_ids:
            others = [s for s in primary_ids if s != sid]
            other_fires = set(zip(
                fired[fired["sleeve_id"].isin(others)]["slug"],
                fired[fired["sleeve_id"].isin(others)]["fire_us"].astype("int64"),
                fired[fired["sleeve_id"].isin(others)]["direction"]
            ))
            keys = list(zip(sub["slug"], sub["fire_us"].astype("int64"), sub["direction"]))
            idx_u = [i for i, k in enumerate(keys) if k not in other_fires]
            marg_df = sub.iloc[idx_u]
            marg_n = len(marg_df)
            marg_28d = marg_df["pnl_legacy_usd"].sum() * SCALE_28D
            marginal_rows.append(dict(sleeve_id=sid, marginal_n=marg_n,
                                       marginal_28d=marg_28d, in_primary=True))
        else:
            keys = list(zip(sub["slug"], sub["fire_us"].astype("int64"), sub["direction"]))
            idx_outside = [i for i, k in enumerate(keys) if k not in primary_key]
            marg_df = sub.iloc[idx_outside]
            marg_n = len(marg_df)
            marg_28d = marg_df["pnl_legacy_usd"].sum() * SCALE_28D
            marginal_rows.append(dict(sleeve_id=sid, marginal_n=marg_n,
                                       marginal_28d=marg_28d, in_primary=False))
    marg_df = pd.DataFrame(marginal_rows)

    manifest = summary.merge(marg_df, on="sleeve_id", how="left")

    def status_for(row):
        if row["sum_pnl"] <= 0:
            return "SKIP_NEGATIVE_PNL"
        if row["sleeve_id"] in primary_ids:
            return "DEPLOY"
        if row["marginal_28d"] > 50:
            return "PAPER_FIRST"
        return "SKIP_OVERLAP"
    manifest["status"] = manifest.apply(status_for, axis=1)
    manifest["recommended_notional_share"] = manifest["status"].map(
        {"DEPLOY": 1.0, "PAPER_FIRST": 0.5,
         "SKIP_OVERLAP": 0.0, "SKIP_NEGATIVE_PNL": 0.0})

    overlap_rows = []
    for sid in summary["sleeve_id"]:
        sub = fired[fired["sleeve_id"] == sid]
        if sub.empty:
            overlap_rows.append((sid, 0))
            continue
        sub_fires_set = set(zip(sub["slug"], sub["fire_us"].astype("int64"), sub["direction"]))
        pri_excl = primary_fires[primary_fires["sleeve_id"] != sid]
        pri_set = set(zip(pri_excl["slug"], pri_excl["fire_us"].astype("int64"),
                          pri_excl["direction"]))
        if not sub_fires_set:
            op = 0
        else:
            op = len(sub_fires_set & pri_set) / len(sub_fires_set) * 100
        overlap_rows.append((sid, op))
    ov_df = pd.DataFrame(overlap_rows, columns=["sleeve_id", "overlap_with_primary_pct"])
    manifest = manifest.merge(ov_df, on="sleeve_id", how="left")

    manifest["_sort"] = manifest.apply(lambda r: (
        0 if r["status"] == "DEPLOY" else (1 if r["status"] == "PAPER_FIRST" else 2),
        -r["sum_28d"] if r["status"] == "DEPLOY" else (-r["marginal_28d"] if r["status"] == "PAPER_FIRST" else 0)
    ), axis=1)
    manifest = manifest.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
    manifest["deploy_priority"] = range(1, len(manifest) + 1)

    final_cols = ["deploy_priority", "sleeve_id", "status", "asset", "tf",
                  "offset_lo", "offset_hi",
                  "n", "wr_pct", "per_tr", "sum_pnl", "sum_28d",
                  "marginal_n", "marginal_28d",
                  "overlap_with_primary_pct", "recommended_notional_share"]
    final = manifest[final_cols].copy()
    out_path = RES / "final_deploy_manifest_v2_post_audit.csv"
    final.to_csv(out_path, index=False)
    print(f"\nSAVED -> {out_path}")
    print(final.to_string(index=False))

    deploy_set = set(final[final["status"] == "DEPLOY"]["sleeve_id"])
    deploy_fires = fired[fired["sleeve_id"].isin(deploy_set)].drop_duplicates(
        subset=["slug", "fire_us", "direction"]
    )
    deploy_sum = deploy_fires["pnl_legacy_usd"].sum()
    deploy_28d = deploy_sum * SCALE_28D
    paper_set = set(final[final["status"] == "PAPER_FIRST"]["sleeve_id"])
    paper_fires = fired[fired["sleeve_id"].isin(paper_set)].drop_duplicates(
        subset=["slug", "fire_us", "direction"]
    )
    # Subtract paper from deploy fires (not in deploy)
    deploy_keys = set(zip(deploy_fires["slug"], deploy_fires["fire_us"].astype("int64"),
                           deploy_fires["direction"]))
    paper_keys = list(zip(paper_fires["slug"], paper_fires["fire_us"].astype("int64"),
                           paper_fires["direction"]))
    paper_marg_idx = [i for i, k in enumerate(paper_keys) if k not in deploy_keys]
    paper_marg_fires = paper_fires.iloc[paper_marg_idx]
    paper_sum = paper_marg_fires["pnl_legacy_usd"].sum() * 0.5  # half notional
    paper_28d = paper_sum * SCALE_28D

    print(f"\n=== FINAL POST-AUDIT DEPLOY ROSTER ===")
    print(f"Lockbox window: 3.96 days (May 21-25)")
    print(f"DEPLOY: {len(deploy_set)} sleeves, unique fires: {len(deploy_fires):,}")
    print(f"  DEPLOY sum_28d  ($25 notional): ${deploy_28d:>10,.0f}")
    print(f"  PAPER 0.5x add ($25 notional):  ${paper_28d:>10,.0f}")
    combined = deploy_28d + paper_28d
    print(f"  COMBINED        ($25 notional): ${combined:>10,.0f}")
    print(f"  COMBINED        ($250 notional):${combined*10:>10,.0f}")
    print(f"  COMBINED        ($250 annual):  ${combined*10*13:>10,.0f}")


if __name__ == "__main__":
    main()
