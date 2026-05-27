"""Task 1: RF vs Ribbon overlap analysis.

Joins s15_with_rf + s15_with_ta_and_markov on (slug, fire_us), computes:
  - Jaccard between (rf_dir agrees with bet) and (ribbon_color agrees with bet)
  - Pearson between rf_dir and sign(ribbon_lead_slope_bps)
  - Conditional probabilities both ways
  - WR on the disagreement subset (does RF know something ribbon doesn't?)

Outputs: strategy_lab/reports/RF_RIBBON_OVERLAP_2026_05_25.md
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT = ROOT / "strategy_lab" / "reports" / "RF_RIBBON_OVERLAP_2026_05_25.md"


def overlap_metrics(df: pd.DataFrame, name: str) -> dict:
    dir_up = (df["direction"] == "UP")
    dir_dn = (df["direction"] == "DOWN")
    rf_with = (((df["rf_dir"] > 0) & dir_up) | ((df["rf_dir"] < 0) & dir_dn)).fillna(False)
    ribbon_with = ((df["ribbon_color"].isin([1, 4]) & dir_up) | (df["ribbon_color"].isin([2, 3]) & dir_dn)).fillna(False)

    both = (rf_with & ribbon_with).sum()
    either = (rf_with | ribbon_with).sum()
    rf_only = (rf_with & ~ribbon_with).sum()
    rib_only = (~rf_with & ribbon_with).sum()
    neither = ((~rf_with) & (~ribbon_with)).sum()
    n = len(df)
    jaccard = both / either if either else 0.0

    # Pearson rf_dir vs sign(ribbon_slope)
    rf = df["rf_dir"].astype("float64").fillna(0.0).values
    rs = np.sign(df["ribbon_lead_slope_bps"].astype("float64").fillna(0.0).values)
    if rf.std() and rs.std():
        pearson = float(np.corrcoef(rf, rs)[0, 1])
    else:
        pearson = float("nan")

    # Conditional: P(ribbon | rf), P(rf | ribbon)
    p_ribbon_given_rf = both / rf_with.sum() if rf_with.sum() else float("nan")
    p_rf_given_ribbon = both / ribbon_with.sum() if ribbon_with.sum() else float("nan")

    # WR on disagreement subsets
    # rf yes, ribbon no
    sub1 = df[rf_with & ~ribbon_with]
    sub2 = df[~rf_with & ribbon_with]
    sub3 = df[rf_with & ribbon_with]
    sub4 = df[(~rf_with) & (~ribbon_with)]

    def stats(s):
        if len(s) == 0:
            return {"n": 0, "WR": float("nan"), "sum_pnl": 0.0, "dpt": float("nan")}
        return {
            "n": int(len(s)),
            "WR": float(s["won"].mean()),
            "sum_pnl": float(s["pnl_legacy_usd"].sum()),
            "dpt": float(s["pnl_legacy_usd"].mean()),
        }

    return {
        "name": name,
        "n_total": int(n),
        "rf_with": int(rf_with.sum()),
        "ribbon_with": int(ribbon_with.sum()),
        "both": int(both),
        "either": int(either),
        "rf_only": int(rf_only),
        "ribbon_only": int(rib_only),
        "neither": int(neither),
        "jaccard": float(jaccard),
        "pearson_rfdir_ribbonslope": pearson,
        "P(ribbon|rf)": p_ribbon_given_rf,
        "P(rf|ribbon)": p_rf_given_ribbon,
        "both_stats": stats(sub3),
        "rfonly_stats": stats(sub1),
        "ribonly_stats": stats(sub2),
        "neither_stats": stats(sub4),
    }


def main():
    print("Loading joined frames...")
    s15 = pd.read_parquet(RES / "s15_joined_all.parquet")
    s6 = pd.read_parquet(RES / "s6_joined_all.parquet")
    v15m = pd.read_parquet(RES / "v15m_joined_all.parquet")

    m_s15 = overlap_metrics(s15, "S1.5 5m")
    m_s6 = overlap_metrics(s6, "S6 5m spike")
    m_v15m = overlap_metrics(v15m, "v15m S7 15m")

    # per-asset for S1.5
    per_asset = {}
    for asset in ("BTC", "ETH", "SOL"):
        per_asset[asset] = overlap_metrics(s15[s15.asset == asset], f"S1.5 {asset}")

    # build markdown report
    lines = ["# RF vs Ribbon Overlap Analysis — 2026-05-25", ""]
    lines.append("Joins `s15_joined_all.parquet` (S1.5 5m fires) + computes Jaccard / Pearson / conditional")
    lines.append("probabilities between **rf_dir-agrees-with-bet** and **ribbon_color-agrees-with-bet**, then WR on disagreement subsets.")
    lines.append("")
    lines.append("**Universe**: 28-day window 2026-05-01 → 2026-05-21, chainlink-resolved fires only, legacy 2%-on-profit fee model.")
    lines.append("")

    for m in [m_s15, m_s6, m_v15m]:
        lines.append(f"## {m['name']}")
        lines.append("")
        lines.append(f"- **n total**: {m['n_total']:,}")
        lines.append(f"- **rf agrees with bet**: {m['rf_with']:,} ({m['rf_with']/m['n_total']*100:.1f}%)")
        lines.append(f"- **ribbon agrees with bet**: {m['ribbon_with']:,} ({m['ribbon_with']/m['n_total']*100:.1f}%)")
        lines.append(f"- **both agree**: {m['both']:,}")
        lines.append(f"- **either agree**: {m['either']:,}")
        lines.append(f"- **Jaccard**: **{m['jaccard']:.3f}**")
        lines.append(f"- **Pearson (rf_dir × sign(ribbon_slope))**: {m['pearson_rfdir_ribbonslope']:.3f}")
        lines.append(f"- **P(ribbon|rf)**: {m['P(ribbon|rf)']:.3f}")
        lines.append(f"- **P(rf|ribbon)**: {m['P(rf|ribbon)']:.3f}")
        lines.append("")
        lines.append("Disagreement / agreement subsets:")
        lines.append("")
        lines.append("| Subset | n | WR | sum_pnl_usd | $/tr |")
        lines.append("|---|---:|---:|---:|---:|")
        for k, label in [("both_stats", "BOTH agree"), ("rfonly_stats", "RF only"),
                         ("ribonly_stats", "Ribbon only"), ("neither_stats", "NEITHER")]:
            s = m[k]
            wr = f"{s['WR']:.3f}" if not np.isnan(s['WR']) else "—"
            dpt = f"{s['dpt']:+.4f}" if not np.isnan(s['dpt']) else "—"
            lines.append(f"| {label} | {s['n']:,} | {wr} | {s['sum_pnl']:+.2f} | {dpt} |")
        lines.append("")

    lines.append("## Per-asset (S1.5 5m only)")
    lines.append("")
    lines.append("| Asset | n | RF agrees | Ribbon agrees | Jaccard | Pearson | P(rib|rf) | P(rf|rib) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for asset in ("BTC", "ETH", "SOL"):
        m = per_asset[asset]
        lines.append(f"| {asset} | {m['n_total']:,} | {m['rf_with']:,} | {m['ribbon_with']:,} | "
                     f"{m['jaccard']:.3f} | {m['pearson_rfdir_ribbonslope']:+.3f} | "
                     f"{m['P(ribbon|rf)']:.3f} | {m['P(rf|ribbon)']:.3f} |")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if m_s15["jaccard"] > 0.85:
        lines.append("- **RF and ribbon are HIGHLY OVERLAPPING** (Jaccard > 0.85). Including both in a")
        lines.append("  stack adds little marginal info — pick one. The RF/ribbon stack tests should focus")
        lines.append("  on which is the SHARPER signal, not stacking them together.")
    elif m_s15["jaccard"] > 0.65:
        lines.append("- **RF and ribbon are SUBSTANTIALLY overlapping** (Jaccard 0.65-0.85). Stacking both")
        lines.append("  provides modest filter tightening but mostly trims the same fires. Look for cases")
        lines.append("  where RF-only or ribbon-only have higher WR — that's the marginal signal.")
    else:
        lines.append("- **RF and ribbon are NEARLY INDEPENDENT** (Jaccard < 0.65). Stacking them in an")
        lines.append("  AND-conjunction will meaningfully tighten the filter. RF-only and ribbon-only")
        lines.append("  subsets each likely contain a distinct signal.")
    lines.append("")
    lines.append("If `RF only` WR > `Ribbon only` WR, RF has signal ribbon misses (and vice versa).")
    lines.append("If `BOTH` WR > marginal subsets, the AND-conjunction is genuinely tightening.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")

    # also print headline to stdout
    print(f"\nS1.5 5m Jaccard(RF, ribbon): {m_s15['jaccard']:.3f}")
    print(f"S1.5 5m P(rib|rf)={m_s15['P(ribbon|rf)']:.3f}, P(rf|rib)={m_s15['P(rf|ribbon)']:.3f}")


if __name__ == "__main__":
    main()
