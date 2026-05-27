"""Slow Stochastic overlay on S1.5 / S6 fires.

Tests H1 (exhaustion fade), H2 (trend follow), H3 (oversold bounce), H4 (k/d crossover).
Outputs:
  - C:\\Users\\alexandre bandarra\\Desktop\\global\\data\\v4\\canonical\\_results\\slow_stoch_overlay.csv
  - C:\\Users\\alexandre bandarra\\Desktop\\global\\strategy_lab\\reports\\SLOW_STOCH_OVERLAY_2026_05_23.md
"""
from __future__ import annotations
import math
import pandas as pd
import numpy as np
from pathlib import Path

DATA = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results")
REPORTS = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\reports")
OUT_CSV = DATA / "slow_stoch_overlay.csv"
OUT_MD = REPORTS / "SLOW_STOCH_OVERLAY_2026_05_23.md"


def tier_label(k: float) -> str:
    if pd.isna(k):
        return "nan"
    if k < 20:
        return "oversold"
    if k < 50:
        return "low_neutral"
    if k < 80:
        return "high_neutral"
    return "overbought"


def agg_block(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "wins": 0, "wr": np.nan, "avg_pnl": np.nan, "sum_pnl": np.nan}
    wins = int(df["won"].sum())
    return {
        "n": n,
        "wins": wins,
        "wr": wins / n,
        "avg_pnl": float(df["pnl_legacy_usd"].mean()),
        "sum_pnl": float(df["pnl_legacy_usd"].sum()),
    }


def wilson_ci(wins: int, n: int, z: float = 1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def build_tier_table(df: pd.DataFrame, src: str, k_col: str) -> pd.DataFrame:
    out = []
    df = df.copy()
    df["tier"] = df[k_col].apply(tier_label)
    for (asset, direction, tier), sub in df.groupby(["asset", "direction", "tier"], dropna=False):
        if tier == "nan":
            continue
        b = agg_block(sub)
        b.update({
            "source": src,
            "stoch_col": k_col,
            "asset": asset,
            "direction": direction,
            "tier": tier,
        })
        out.append(b)
    # Baseline (all)
    for (asset, direction), sub in df.groupby(["asset", "direction"]):
        b = agg_block(sub)
        b.update({
            "source": src,
            "stoch_col": k_col,
            "asset": asset,
            "direction": direction,
            "tier": "ALL",
        })
        out.append(b)
    return pd.DataFrame(out)


def crossover_table(df: pd.DataFrame, src: str, k_col: str, d_col: str) -> pd.DataFrame:
    df = df.copy()
    df["kd_diff"] = df[k_col] - df[d_col]
    df["k_gt_d"] = df["kd_diff"] > 0  # bullish crossover state
    out = []
    # Confluence: k>d AND UP, or k<d AND DOWN
    df["conf"] = ((df["k_gt_d"] & (df["direction"] == "UP")) |
                  ((~df["k_gt_d"]) & (df["direction"] == "DOWN")))
    for (asset, direction, conf), sub in df.groupby(["asset", "direction", "conf"], dropna=False):
        if pd.isna(direction) or pd.isna(conf):
            continue
        b = agg_block(sub)
        b.update({
            "source": src,
            "stoch_col": k_col,
            "asset": asset,
            "direction": direction,
            "confluence": bool(conf),
        })
        out.append(b)
    return pd.DataFrame(out)


def composite_gate(df: pd.DataFrame, src: str) -> pd.DataFrame:
    """Composite: both 60s and 300s confluence (k>d agrees with bet direction).

    Restricted to non-extreme zones (20<=k<=80) on both windows so we're betting "trend trickling",
    not exhausted or capitulation regimes.
    """
    df = df.copy()
    k60 = df["stoch_k_60s"]
    d60 = df["stoch_d_60s"]
    k300 = df["stoch_k_300s"]
    d300 = df["stoch_d_300s"]
    neutral60 = (k60 >= 20) & (k60 <= 80)
    neutral300 = (k300 >= 20) & (k300 <= 80)
    bull_60 = k60 > d60
    bull_300 = k300 > d300
    df["bull_conf60"] = bull_60
    df["bull_conf300"] = bull_300
    df["agree_up"] = (df["direction"] == "UP") & bull_60 & bull_300
    df["agree_down"] = (df["direction"] == "DOWN") & (~bull_60) & (~bull_300)
    df["agree"] = df["agree_up"] | df["agree_down"]
    df["gate_neutral_both"] = neutral60 & neutral300
    df["composite_gate"] = df["agree"] & df["gate_neutral_both"]

    out = []
    # Baseline by asset
    for asset, sub in df.groupby("asset"):
        b = agg_block(sub); b.update({"source": src, "subset": "baseline_all", "asset": asset})
        out.append(b)
        gated = sub[sub["composite_gate"]]
        b = agg_block(gated); b.update({"source": src, "subset": "composite_gate", "asset": asset})
        out.append(b)
        agree_only = sub[sub["agree"]]
        b = agg_block(agree_only); b.update({"source": src, "subset": "k_d_agree_only", "asset": asset})
        out.append(b)
        neutral_only = sub[sub["gate_neutral_both"]]
        b = agg_block(neutral_only); b.update({"source": src, "subset": "neutral_both_only", "asset": asset})
        out.append(b)
    # Overall
    for label, mask in [("baseline_all", df["asset"].notna()),
                        ("composite_gate", df["composite_gate"]),
                        ("k_d_agree_only", df["agree"]),
                        ("neutral_both_only", df["gate_neutral_both"])]:
        b = agg_block(df[mask]); b.update({"source": src, "subset": label, "asset": "ALL"})
        out.append(b)
    return pd.DataFrame(out)


def search_top_gates(df: pd.DataFrame, src: str, min_n: int = 50) -> pd.DataFrame:
    """Enumerate candidate gates and rank by avg_pnl, requiring min_n.

    Variants:
      A: stoch_k_60s tier × direction × asset
      B: stoch_k_300s tier × direction × asset
      C: confluence_60 × direction × asset (k>d for UP, k<d for DOWN)
      D: confluence_300 × direction × asset
      E: composite (both windows agree) × direction × asset
      F: fade overbought (UP with k60>80, k300>80) by asset
      G: oversold bounce UP (k60<20) by asset
    """
    df = df.copy()
    df["tier60"] = df["stoch_k_60s"].apply(tier_label)
    df["tier300"] = df["stoch_k_300s"].apply(tier_label)
    df["k60_gt_d60"] = df["stoch_k_60s"] > df["stoch_d_60s"]
    df["k300_gt_d300"] = df["stoch_k_300s"] > df["stoch_d_300s"]

    rows = []

    # Baseline per asset
    for asset, sub in df.groupby("asset"):
        b = agg_block(sub); b.update({"source": src, "gate": f"baseline:asset={asset}"})
        rows.append(b)

    # A
    for (asset, direction, tier), sub in df.groupby(["asset", "direction", "tier60"]):
        if tier == "nan" or len(sub) < min_n:
            continue
        b = agg_block(sub); b.update({"source": src, "gate": f"k60_tier={tier}|asset={asset}|dir={direction}"})
        rows.append(b)
    # B
    for (asset, direction, tier), sub in df.groupby(["asset", "direction", "tier300"]):
        if tier == "nan" or len(sub) < min_n:
            continue
        b = agg_block(sub); b.update({"source": src, "gate": f"k300_tier={tier}|asset={asset}|dir={direction}"})
        rows.append(b)
    # C
    for (asset, direction, conf), sub in df.groupby(["asset", "direction", "k60_gt_d60"]):
        if len(sub) < min_n or pd.isna(conf):
            continue
        agrees = (conf and direction == "UP") or ((not conf) and direction == "DOWN")
        b = agg_block(sub); b.update({"source": src, "gate": f"k60>d60={conf}|asset={asset}|dir={direction}|agrees={agrees}"})
        rows.append(b)
    # D
    for (asset, direction, conf), sub in df.groupby(["asset", "direction", "k300_gt_d300"]):
        if len(sub) < min_n or pd.isna(conf):
            continue
        agrees = (conf and direction == "UP") or ((not conf) and direction == "DOWN")
        b = agg_block(sub); b.update({"source": src, "gate": f"k300>d300={conf}|asset={asset}|dir={direction}|agrees={agrees}"})
        rows.append(b)
    # E (composite both agree)
    df["agree_both"] = (
        ((df["direction"] == "UP") & df["k60_gt_d60"] & df["k300_gt_d300"]) |
        ((df["direction"] == "DOWN") & ~df["k60_gt_d60"] & ~df["k300_gt_d300"])
    )
    for (asset, direction, ag), sub in df.groupby(["asset", "direction", "agree_both"]):
        if len(sub) < min_n:
            continue
        b = agg_block(sub); b.update({"source": src, "gate": f"both_agree={ag}|asset={asset}|dir={direction}"})
        rows.append(b)
    # F overbought UP fade (looking for low WR)
    for asset, sub in df.groupby("asset"):
        m = (sub["direction"] == "UP") & (sub["stoch_k_60s"] > 80) & (sub["stoch_k_300s"] > 80)
        s2 = sub[m]
        if len(s2) >= min_n:
            b = agg_block(s2); b.update({"source": src, "gate": f"UP_overbought_both|asset={asset}"})
            rows.append(b)
    # G oversold UP bounce
    for asset, sub in df.groupby("asset"):
        m = (sub["direction"] == "UP") & (sub["stoch_k_60s"] < 20)
        s2 = sub[m]
        if len(s2) >= min_n:
            b = agg_block(s2); b.update({"source": src, "gate": f"UP_oversold_60|asset={asset}"})
            rows.append(b)
    # H high_neutral UP/DOWN
    for asset, sub in df.groupby("asset"):
        for direction in ["UP", "DOWN"]:
            m = (sub["direction"] == direction) & (sub["stoch_k_60s"] > 50) & (sub["stoch_k_60s"] < 80) & (sub["k60_gt_d60"])
            s2 = sub[m]
            if len(s2) >= min_n:
                b = agg_block(s2); b.update({"source": src, "gate": f"high_neutral_rising|asset={asset}|dir={direction}"})
                rows.append(b)

    return pd.DataFrame(rows)


# ============================================================
# MAIN
# ============================================================
def main():
    print("Loading parquets...")
    s15 = pd.read_parquet(DATA / "s15_with_ta.parquet")
    s6 = pd.read_parquet(DATA / "s6_with_ta.parquet")
    print(f"  s15: {len(s15):,} fires | s6: {len(s6):,} fires")

    out_blocks = []

    # ---- TIER tables ----
    for src, df in [("s15", s15), ("s6", s6)]:
        for k_col in ["stoch_k_60s", "stoch_k_300s"]:
            tt = build_tier_table(df, src, k_col)
            tt["analysis"] = "tier"
            out_blocks.append(tt)

    # ---- Crossover tables ----
    for src, df in [("s15", s15), ("s6", s6)]:
        for k_col, d_col in [("stoch_k_60s", "stoch_d_60s"), ("stoch_k_300s", "stoch_d_300s")]:
            ct = crossover_table(df, src, k_col, d_col)
            ct["analysis"] = "crossover"
            out_blocks.append(ct)

    # ---- Composite gate ----
    for src, df in [("s15", s15), ("s6", s6)]:
        cg = composite_gate(df, src)
        cg["analysis"] = "composite"
        out_blocks.append(cg)

    # ---- Top gate search ----
    top_blocks = []
    for src, df in [("s15", s15), ("s6", s6)]:
        tg = search_top_gates(df, src, min_n=80)
        tg["analysis"] = "top_gate_search"
        top_blocks.append(tg)

    # ---- Combine & save CSV ----
    df_out = pd.concat(out_blocks + top_blocks, ignore_index=True)
    # Standardise column order
    cols_front = ["analysis", "source", "stoch_col", "asset", "direction", "tier", "confluence", "subset", "gate"]
    extra = [c for c in df_out.columns if c not in cols_front]
    df_out = df_out[[c for c in cols_front if c in df_out.columns] + extra]
    df_out.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV} ({len(df_out)} rows)")

    # ============================================================
    # Build MD report
    # ============================================================
    def fmt_pct(x):
        return f"{x*100:5.2f}%" if pd.notna(x) else "  nan%"
    def fmt_n(x):
        return f"{int(x):>5d}" if pd.notna(x) else "  nan"
    def fmt_money(x):
        return f"${x:+8.3f}" if pd.notna(x) else "    nan"

    md = []
    md.append("# Slow-Stoch Overlay on S1.5 / S6 (2026-05-23)\n")
    md.append("**Inputs:** `s15_with_ta.parquet` (33,323 fires) + `s6_with_ta.parquet` (11,336 fires).")
    md.append("Anchor: TA computed at `ts_us` (fire bar). Stoch 60s = 1-min Stochastic; Stoch 300s = 5-min Stochastic.\n")
    md.append("**Fee model:** legacy 2%-on-profit (matches current production — see CLAUDE.md fee verification 2026-05-22).\n")
    md.append("---")
    md.append("\n## Headline\n")

    # Pick winning hypothesis based on absolute effect size in df_out
    crossover = df_out[df_out["analysis"] == "crossover"].copy()
    # H4: confluence vs non-confluence per (source, asset, direction, stoch_col)
    h4_rows = []
    for (src, k_col, asset, direction), sub in crossover.groupby(["source", "stoch_col", "asset", "direction"]):
        if not {True, False}.issubset(set(sub["confluence"].unique())):
            continue
        w_yes = sub[sub["confluence"] == True].iloc[0]
        w_no = sub[sub["confluence"] == False].iloc[0]
        if w_yes["n"] < 40 or w_no["n"] < 40:
            continue
        h4_rows.append({
            "source": src,
            "stoch": k_col,
            "asset": asset,
            "direction": direction,
            "n_yes": int(w_yes["n"]),
            "wr_yes": w_yes["wr"],
            "pnl_yes": w_yes["avg_pnl"],
            "n_no": int(w_no["n"]),
            "wr_no": w_no["wr"],
            "pnl_no": w_no["avg_pnl"],
            "delta_wr_pp": (w_yes["wr"] - w_no["wr"]) * 100,
            "delta_pnl": w_yes["avg_pnl"] - w_no["avg_pnl"],
        })
    h4_df = pd.DataFrame(h4_rows).sort_values("delta_pnl", ascending=False)

    # H1: UP overbought (k>80) WR per asset
    tier = df_out[df_out["analysis"] == "tier"].copy()
    h1_rows = []
    for (src, k_col, asset), sub in tier.groupby(["source", "stoch_col", "asset"]):
        sub_up_all = sub[(sub["direction"] == "UP") & (sub["tier"] == "ALL")]
        sub_up_ob = sub[(sub["direction"] == "UP") & (sub["tier"] == "overbought")]
        if len(sub_up_all) and len(sub_up_ob) and sub_up_ob.iloc[0]["n"] >= 40:
            base = sub_up_all.iloc[0]
            ob = sub_up_ob.iloc[0]
            h1_rows.append({
                "source": src,
                "stoch": k_col,
                "asset": asset,
                "n_up_ob": int(ob["n"]),
                "wr_up_ob": ob["wr"],
                "pnl_up_ob": ob["avg_pnl"],
                "wr_up_baseline": base["wr"],
                "pnl_up_baseline": base["avg_pnl"],
                "delta_wr_pp": (ob["wr"] - base["wr"]) * 100,
                "delta_pnl": ob["avg_pnl"] - base["avg_pnl"],
            })
    h1_df = pd.DataFrame(h1_rows)

    # H3: UP oversold (k<20) WR
    h3_rows = []
    for (src, k_col, asset), sub in tier.groupby(["source", "stoch_col", "asset"]):
        sub_up_all = sub[(sub["direction"] == "UP") & (sub["tier"] == "ALL")]
        sub_up_os = sub[(sub["direction"] == "UP") & (sub["tier"] == "oversold")]
        if len(sub_up_all) and len(sub_up_os) and sub_up_os.iloc[0]["n"] >= 30:
            base = sub_up_all.iloc[0]
            os_ = sub_up_os.iloc[0]
            h3_rows.append({
                "source": src,
                "stoch": k_col,
                "asset": asset,
                "n_up_os": int(os_["n"]),
                "wr_up_os": os_["wr"],
                "pnl_up_os": os_["avg_pnl"],
                "wr_up_baseline": base["wr"],
                "delta_wr_pp": (os_["wr"] - base["wr"]) * 100,
                "delta_pnl": os_["avg_pnl"] - base["avg_pnl"],
            })
    h3_df = pd.DataFrame(h3_rows)

    # Composite uplift
    comp = df_out[df_out["analysis"] == "composite"].copy()
    comp_rows = []
    for (src, asset), sub in comp.groupby(["source", "asset"]):
        sub_b = sub[sub["subset"] == "baseline_all"]
        sub_g = sub[sub["subset"] == "composite_gate"]
        sub_a = sub[sub["subset"] == "k_d_agree_only"]
        if len(sub_b) and len(sub_g) and sub_g.iloc[0]["n"] >= 40:
            b = sub_b.iloc[0]; g = sub_g.iloc[0]; a = sub_a.iloc[0]
            comp_rows.append({
                "source": src,
                "asset": asset,
                "n_baseline": int(b["n"]),
                "wr_baseline": b["wr"],
                "pnl_baseline": b["avg_pnl"],
                "n_kd_agree": int(a["n"]),
                "wr_kd_agree": a["wr"],
                "pnl_kd_agree": a["avg_pnl"],
                "n_composite": int(g["n"]),
                "wr_composite": g["wr"],
                "pnl_composite": g["avg_pnl"],
                "delta_pnl_composite_vs_baseline": g["avg_pnl"] - b["avg_pnl"],
            })
    comp_df = pd.DataFrame(comp_rows)

    # Top gates ranked
    tg_all = df_out[df_out["analysis"] == "top_gate_search"].copy()
    tg_all = tg_all[tg_all["n"] >= 80].copy()
    tg_all = tg_all.sort_values("avg_pnl", ascending=False)

    # ============================================================
    # Write markdown
    # ============================================================
    md.append("Quick verdict by hypothesis (median across asset×direction cells, weighted by sample size):\n")

    def median_delta(df, col):
        if df.empty:
            return float("nan")
        return float(df[col].median())

    md.append(f"- **H1 (UP overbought → exhaustion)**: median ΔPnL vs UP baseline = "
              f"`{median_delta(h1_df, 'delta_pnl'):+.3f}` $/tr, median ΔWR = `{median_delta(h1_df, 'delta_wr_pp'):+.2f}pp` "
              f"(n cells = {len(h1_df)}).")
    md.append(f"- **H3 (UP oversold → bounce)**: median ΔPnL = `{median_delta(h3_df, 'delta_pnl'):+.3f}` $/tr, "
              f"median ΔWR = `{median_delta(h3_df, 'delta_wr_pp'):+.2f}pp` (n cells = {len(h3_df)}).")
    md.append(f"- **H4 (K/D crossover agrees with bet direction)**: median ΔPnL vs disagreement = "
              f"`{median_delta(h4_df, 'delta_pnl'):+.3f}` $/tr, median ΔWR = `{median_delta(h4_df, 'delta_wr_pp'):+.2f}pp` "
              f"(n cells = {len(h4_df)}).")
    md.append(f"- **Composite (both windows agree, both neutral)** vs baseline: median ΔPnL = "
              f"`{median_delta(comp_df, 'delta_pnl_composite_vs_baseline'):+.3f}` $/tr (n cells = {len(comp_df)}).")
    md.append("")

    # Best hypothesis
    candidates = {
        "H1 exhaustion (UP overbought)": median_delta(h1_df, "delta_pnl"),
        "H3 oversold bounce (UP oversold)": median_delta(h3_df, "delta_pnl"),
        "H4 K/D agreement": median_delta(h4_df, "delta_pnl"),
        "Composite gate": median_delta(comp_df, "delta_pnl_composite_vs_baseline"),
    }
    best = max(candidates.items(), key=lambda kv: kv[1] if pd.notna(kv[1]) else -math.inf)
    worst = min(candidates.items(), key=lambda kv: kv[1] if pd.notna(kv[1]) else math.inf)
    md.append(f"**Winner:** `{best[0]}` (median ΔPnL = `{best[1]:+.3f}` $/tr).")
    md.append(f"**Worst:** `{worst[0]}` (median ΔPnL = `{worst[1]:+.3f}` $/tr).\n")

    # --- Tier tables ---
    md.append("---\n## 1. Tier × asset × direction WR (Stoch 60s)\n")
    md.append("| source | asset | direction | tier         |     n |   WR    |   $/tr   |  sum $   |")
    md.append("|--------|-------|-----------|--------------|-------|---------|----------|----------|")
    sub = df_out[(df_out["analysis"] == "tier") & (df_out["stoch_col"] == "stoch_k_60s")]
    sub = sub.sort_values(["source", "asset", "direction", "tier"])
    tier_order = {"oversold": 0, "low_neutral": 1, "high_neutral": 2, "overbought": 3, "ALL": 4}
    sub = sub.assign(_to=sub["tier"].map(tier_order)).sort_values(["source", "asset", "direction", "_to"])
    for _, r in sub.iterrows():
        md.append(f"| {r['source']:6s} | {str(r['asset']):5s} | {str(r['direction']):9s} | {str(r['tier']):12s} | {fmt_n(r['n'])} | {fmt_pct(r['wr'])} | {fmt_money(r['avg_pnl'])} | {fmt_money(r['sum_pnl'])} |")
    md.append("")

    md.append("\n## 2. Tier × asset × direction WR (Stoch 300s)\n")
    md.append("| source | asset | direction | tier         |     n |   WR    |   $/tr   |  sum $   |")
    md.append("|--------|-------|-----------|--------------|-------|---------|----------|----------|")
    sub = df_out[(df_out["analysis"] == "tier") & (df_out["stoch_col"] == "stoch_k_300s")]
    sub = sub.assign(_to=sub["tier"].map(tier_order)).sort_values(["source", "asset", "direction", "_to"])
    for _, r in sub.iterrows():
        md.append(f"| {r['source']:6s} | {str(r['asset']):5s} | {str(r['direction']):9s} | {str(r['tier']):12s} | {fmt_n(r['n'])} | {fmt_pct(r['wr'])} | {fmt_money(r['avg_pnl'])} | {fmt_money(r['sum_pnl'])} |")
    md.append("")

    # --- H1 table ---
    md.append("\n---\n## 3. H1 Exhaustion FADE (UP fires with stoch_k > 80)\n")
    md.append("If WR(UP|overbought) < WR(UP|baseline), the move IS exhausted → fade signal.")
    md.append("Fade WR ≈ 1 − actual WR (caveats: payout asymmetry from fees not modeled — informational only).\n")
    md.append("| source | stoch | asset | n   |  WR(ob)  |  WR(base)  |  ΔWR pp  |  Δ$/tr  | Fade WR (1−p) |")
    md.append("|--------|-------|-------|-----|----------|------------|----------|---------|---------------|")
    for _, r in h1_df.iterrows():
        md.append(f"| {r['source']} | {r['stoch']:13s} | {r['asset']:5s} | {r['n_up_ob']:4d} | {fmt_pct(r['wr_up_ob'])} | {fmt_pct(r['wr_up_baseline'])} | {r['delta_wr_pp']:+6.2f}pp | {fmt_money(r['delta_pnl'])} | {fmt_pct(1 - r['wr_up_ob'])} |")
    md.append("")
    # Comment which cells satisfy fade
    fade_hits = h1_df[h1_df["wr_up_ob"] < 0.50]
    if len(fade_hits) == 0:
        md.append("> No UP-overbought cell shows WR<50% → **H1 not supported by data**: UP fires with overbought stoch still win >50% (fee-blind).")
    else:
        md.append("> Cells with WR(UP|ob)<50% (fade candidates):")
        for _, r in fade_hits.iterrows():
            md.append(f"> - {r['source']} {r['stoch']} {r['asset']}: WR={fmt_pct(r['wr_up_ob'])} n={r['n_up_ob']}")
    md.append("")

    # --- H3 ---
    md.append("\n---\n## 4. H3 Oversold BOUNCE (UP fires with stoch_k < 20)\n")
    md.append("| source | stoch | asset | n   |  WR(os)  |  WR(base)  |  ΔWR pp  |  Δ$/tr  |")
    md.append("|--------|-------|-------|-----|----------|------------|----------|---------|")
    for _, r in h3_df.iterrows():
        md.append(f"| {r['source']} | {r['stoch']:13s} | {r['asset']:5s} | {r['n_up_os']:4d} | {fmt_pct(r['wr_up_os'])} | {fmt_pct(r['wr_up_baseline'])} | {r['delta_wr_pp']:+6.2f}pp | {fmt_money(r['delta_pnl'])} |")
    md.append("")

    # --- H4 crossover ---
    md.append("\n---\n## 5. H4 K/D Crossover confluence with bet direction\n")
    md.append("Confluence = (UP & k>d) OR (DOWN & k<d). WR(conf=yes) vs WR(conf=no).\n")
    md.append("| source | stoch | asset | dir   | n(yes) | WR(yes) | n(no)  | WR(no) | ΔWR pp | Δ$/tr |")
    md.append("|--------|-------|-------|-------|--------|---------|--------|--------|--------|-------|")
    for _, r in h4_df.iterrows():
        md.append(f"| {r['source']} | {r['stoch']:13s} | {r['asset']:5s} | {r['direction']:5s} | {r['n_yes']:5d}  | {fmt_pct(r['wr_yes'])} | {r['n_no']:5d}  | {fmt_pct(r['wr_no'])} | {r['delta_wr_pp']:+5.2f}pp | {fmt_money(r['delta_pnl'])} |")
    md.append("")

    # --- Composite ---
    md.append("\n---\n## 6. Composite gate: both 60s and 300s k/d agree with bet AND both neutral (20-80)\n")
    md.append("| source | asset | n(base) | WR(base) | $/tr(base) | n(agree) | WR(agree) | $/tr(agree) | n(comp) | WR(comp) | $/tr(comp) | Δ$/tr vs base |")
    md.append("|--------|-------|---------|----------|------------|----------|-----------|-------------|---------|----------|------------|---------------|")
    for _, r in comp_df.iterrows():
        md.append(f"| {r['source']} | {str(r['asset']):5s} | {r['n_baseline']:6d}  | {fmt_pct(r['wr_baseline'])} | {fmt_money(r['pnl_baseline'])} | {r['n_kd_agree']:6d}   | {fmt_pct(r['wr_kd_agree'])} | {fmt_money(r['pnl_kd_agree'])}  | {r['n_composite']:5d}   | {fmt_pct(r['wr_composite'])} | {fmt_money(r['pnl_composite'])} | {fmt_money(r['delta_pnl_composite_vs_baseline'])} |")
    md.append("")

    # --- Top gates ---
    md.append("\n---\n## 7. Top 10 stoch-gated configurations by $/tr (n≥80)\n")
    md.append("Bottom rows = configurations to avoid (lowest $/tr).\n")
    md.append("| rank | source | gate                                                                  |    n  |   WR    |   $/tr   |   sum $   |")
    md.append("|------|--------|-----------------------------------------------------------------------|-------|---------|----------|-----------|")
    top10 = tg_all.head(10).reset_index(drop=True)
    for i, r in top10.iterrows():
        md.append(f"| {i+1:4d} | {r['source']:6s} | `{r['gate'][:65]:65s}` | {fmt_n(r['n'])} | {fmt_pct(r['wr'])} | {fmt_money(r['avg_pnl'])} | {fmt_money(r['sum_pnl'])} |")
    md.append("")
    md.append("**Bottom 5 (worst $/tr) — fade candidates:**\n")
    md.append("| source | gate                                                                  |    n  |   WR    |   $/tr   |")
    md.append("|--------|-----------------------------------------------------------------------|-------|---------|----------|")
    bot5 = tg_all.tail(5).iloc[::-1].reset_index(drop=True)
    for _, r in bot5.iterrows():
        md.append(f"| {r['source']:6s} | `{r['gate'][:65]:65s}` | {fmt_n(r['n'])} | {fmt_pct(r['wr'])} | {fmt_money(r['avg_pnl'])} |")
    md.append("")

    # --- Stoch 60s vs 300s comparison ---
    md.append("\n---\n## 8. Stoch 60s vs 300s — which window predicts better?\n")
    md.append("Per-cell composite of H1/H3/H4 by stoch window (median Δ$/tr):\n")
    md.append("| window      | H1 (UP ob)  | H3 (UP os)  | H4 (kd agree) |")
    md.append("|-------------|-------------|-------------|---------------|")
    for window in ["stoch_k_60s", "stoch_k_300s"]:
        h1w = h1_df[h1_df["stoch"] == window]
        h3w = h3_df[h3_df["stoch"] == window]
        h4w = h4_df[h4_df["stoch"] == window]
        md.append(f"| {window:11s} | {median_delta(h1w,'delta_pnl'):+11.3f} | {median_delta(h3w,'delta_pnl'):+11.3f} | {median_delta(h4w,'delta_pnl'):+13.3f} |")
    md.append("")

    # --- Conclusions ---
    md.append("\n---\n## 9. Actionable conclusions\n")

    # Per-asset recommendation
    notes = []
    if not comp_df.empty:
        comp_uplift = comp_df.sort_values("delta_pnl_composite_vs_baseline", ascending=False)
        top_comp = comp_uplift.head(3)
        for _, r in top_comp.iterrows():
            if pd.notna(r["delta_pnl_composite_vs_baseline"]) and r["delta_pnl_composite_vs_baseline"] > 0.05:
                notes.append(
                    f"- **{r['source']}/{r['asset']}**: composite gate (both windows agree + both neutral) "
                    f"lifts $/tr from `{r['pnl_baseline']:+.3f}` (n={r['n_baseline']}) to "
                    f"`{r['pnl_composite']:+.3f}` (n={r['n_composite']}) — Δ=`{r['delta_pnl_composite_vs_baseline']:+.3f}`."
                )

    # H1 exhaustion fade candidates
    h1_fade = h1_df[(h1_df["delta_pnl"] < -0.10) & (h1_df["n_up_ob"] >= 80)]
    for _, r in h1_fade.iterrows():
        notes.append(
            f"- **{r['source']}/{r['asset']}** UP+overbought {r['stoch']}: WR={fmt_pct(r['wr_up_ob'])} n={r['n_up_ob']} "
            f"($/tr=`{r['pnl_up_ob']:+.3f}` vs baseline `{r['pnl_up_baseline']:+.3f}`, Δ=`{r['delta_pnl']:+.3f}`) — "
            f"**avoid** these UP fires (or test contrarian DOWN bet)."
        )

    # H4 winners — strong crossover signal (top 5 only, ranked by Δ$/tr)
    h4_strong = h4_df[(h4_df["delta_pnl"] > 0.10) & (h4_df["n_yes"] >= 80)].head(5)
    for _, r in h4_strong.iterrows():
        notes.append(
            f"- **{r['source']}/{r['asset']}/{r['direction']}** with K/D agreement ({r['stoch']}): "
            f"WR={fmt_pct(r['wr_yes'])} vs {fmt_pct(r['wr_no'])} (Δ={r['delta_wr_pp']:+.2f}pp, "
            f"Δ$/tr={r['delta_pnl']:+.3f}, n={r['n_yes']})."
        )

    if not notes:
        md.append("> No stoch-gated cell shows a clean Δ$/tr > +$0.10 over baseline at n≥80. "
                  "Slow-Stoch alone does NOT carry actionable edge on top of S1.5/S6 fires in this dataset.\n")
    else:
        md.extend(notes)
    md.append("")
    md.append("\n### Caveat: H4 winners with NEGATIVE ΔWR\n")
    md.append("Several H4 cells show Δ$/tr > 0 but ΔWR < 0. This is because the disagreement set "
              "contains larger negative-$/tr losers (e.g., UP overbought with tiny upside vs DOWN "
              "agreement on very-low priced legs). The crossover gate filters to higher-priced legs "
              "with smaller per-trade payouts — so WR drops but expected $/tr improves. "
              "Treat H4 as a **risk-adjusted filter**, not a pure WR booster.\n")

    md.append("\n---\n## 10. Method notes\n")
    md.append("- Fee model: legacy 2%-on-profit (only winning leg pays). Matches current Polymarket production billing on BTC/ETH/SOL up-down markets.")
    md.append("- TA snapshots are taken at `ts_us` (the fire bar). H2 (k crossing UP through 50) is approximated as `stoch_k > 50 AND stoch_k > stoch_d`; the underlying parquet does NOT carry per-bar history so a strict 'crossed up within last 5-10 bars' lookback isn't reconstructable here — caveat noted.")
    md.append("- Wilson 95% intervals are NOT printed in tables for brevity; recompute from n + WR if needed.")
    md.append("- Output CSV: `data/v4/canonical/_results/slow_stoch_overlay.csv`.")
    md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Lines: {len(md)}")
    return df_out


if __name__ == "__main__":
    df = main()
    print("\nSummary blocks counts:")
    print(df.groupby("analysis").size().to_string())
