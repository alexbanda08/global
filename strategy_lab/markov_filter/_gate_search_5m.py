"""
Exhaustive combinatorial gate search on 5m crypto up-down markets.

Inputs:
  - fv_cvd_spike_overlay.parquet         (Baseline_v1/v2 only, 1s features)
  - per_trade_markov.parquet             (all variants, Markov mpass)
  - new_hod_top8.json                    (refreshed HoD per cell)

Outputs:
  - gate_search_5m.csv                   (all WR>=0.55, n>=30 configs)
  - GATE_SEARCH_5M_2026_05_23.md         (deployable report)

Method:
  9 binary gates × 5m cells × {Baseline_v1, Baseline_v2}
  2^9 = 512 subsets per cell, ~6 cells = ~3072 evaluations. Pure pandas.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
FV_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "fv_cvd_spike_overlay.parquet"
MK_PATH = (
    ROOT
    / "data" / "v4" / "canonical" / "_results"
    / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"
)
HOD_PATH = (
    ROOT
    / "strategy_lab" / "markov_filter" / "_results"
    / "hod_refresh" / "2026_05_22" / "new_hod_top8.json"
)
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "gate_search_5m.csv"
OUT_MD = ROOT / "strategy_lab" / "reports" / "GATE_SEARCH_5M_2026_05_23.md"

GATES = [
    "hod_pass",
    "f7_pass",
    "m1v_pass",
    "m5v_pass",
    "cvd_agree",
    "spike_no_anti",
    "edge_ge_2pp",
    "mag_in_sweetspot",
    "cvd_strong",
]
N_GATES = len(GATES)

MIN_N = 30
MIN_WR = 0.55       # save threshold for CSV
DEPLOY_WR = 0.60    # report threshold


def variant_to_fam(v: str) -> str:
    return {"Baseline_v1": "momo", "Baseline_v2": "momo_v2"}[v]


def cell_label(asset: str, tf: str) -> str:
    return f"{asset.lower()}_{tf}"


def main() -> None:
    fv = pd.read_parquet(FV_PATH)
    mk = pd.read_parquet(MK_PATH)
    with open(HOD_PATH) as f:
        hod = json.load(f)

    # ----- inner join to attach Markov mpass to baseline rows
    mk_keep = mk[
        [
            "variant", "slug",
            "mpass_w20_1m_voladaptive", "mpass_w20_5m_voladaptive",
        ]
    ].copy()
    df = fv.merge(mk_keep, on=["variant", "slug"], how="inner")
    print(f"[join] {len(fv)} fv + markov => {len(df)} rows")

    # Filter to 5m only
    df = df[df["tf"] == "5m"].reset_index(drop=True)
    print(f"[filter 5m] {len(df)} rows")

    # ----- derived columns
    df["fire_hour"] = df["fire_s"].apply(
        lambda s: datetime.fromtimestamp(int(s), tz=timezone.utc).hour
    )
    df["fam"] = df["variant"].map(variant_to_fam)
    df["cell"] = df.apply(lambda r: cell_label(r["asset"], r["tf"]), axis=1)
    df["key"] = df["fam"] + "__" + df["cell"]
    df["abs_ret_2m"] = df["ret_2m"].abs()
    df["mag_ratio"] = df["abs_ret_2m"] / df["threshold"]

    # HOD pass per row
    def hod_check(row) -> bool:
        hours = hod.get(row["key"])
        if hours is None:
            return False
        return int(row["fire_hour"]) in set(hours)

    df["hod_pass"] = df.apply(hod_check, axis=1)

    # F7 pass: signal-consistent RSI
    rsi = df["rsi_14"].fillna(50.0)
    sig = df["signal"]
    df["f7_pass"] = ((sig == "UP") & (rsi > 50)) | ((sig == "DOWN") & (rsi < 50))

    df["m1v_pass"] = df["mpass_w20_1m_voladaptive"].fillna(False).astype(bool)
    df["m5v_pass"] = df["mpass_w20_5m_voladaptive"].fillna(False).astype(bool)
    df["cvd_agree"] = df["cvd_agree"].fillna(False).astype(bool)

    spike = df["spike_5s_bps"]
    anti_up = (sig == "UP") & (spike < -5)
    anti_dn = (sig == "DOWN") & (spike > 5)
    df["spike_no_anti"] = ~(anti_up | anti_dn).fillna(False)

    df["edge_ge_2pp"] = (df["edge"].fillna(-1) >= 0.02)
    df["mag_in_sweetspot"] = (df["mag_ratio"] >= 1.0) & (df["mag_ratio"] < 2.0)

    # cvd_strong: per-cell |slope| > 1.5x median
    abs_slope = df["cvd_30s_slope"].abs()
    med = df.groupby("key")["cvd_30s_slope"].transform(lambda s: s.abs().median())
    df["cvd_strong"] = (abs_slope > med * 1.5).fillna(False)

    # Sanity: gate marginals per cell
    print("\n[gate marginals per cell]")
    for k, g in df.groupby("key"):
        n = len(g)
        wr = g["won"].mean()
        line = f"  {k}: n={n} WR={wr:.3f} | "
        line += " ".join(
            f"{gate}={g[gate].mean():.2f}" for gate in GATES
        )
        print(line)

    # ----- enumerate 2^9 subsets per cell
    rows_out: list[dict] = []
    keys = sorted(df["key"].unique())
    for key in keys:
        sub = df[df["key"] == key]
        # Precompute boolean arrays per gate
        gate_arrs = {g: sub[g].values.astype(bool) for g in GATES}
        won = sub["won"].values.astype(bool)
        pnl = sub["pnl_legacy_usd"].values.astype(float)

        for mask_bits in range(1 << N_GATES):
            if mask_bits == 0:
                # baseline (no gates applied)
                sel = np.ones(len(sub), dtype=bool)
                gate_list: list[str] = []
            else:
                gate_list = [GATES[i] for i in range(N_GATES) if mask_bits & (1 << i)]
                sel = np.ones(len(sub), dtype=bool)
                for g in gate_list:
                    sel &= gate_arrs[g]
            n = int(sel.sum())
            if n < MIN_N:
                continue
            w_arr = won[sel]
            p_arr = pnl[sel]
            wr = float(w_arr.mean())
            mean_pnl = float(p_arr.mean())
            std_pnl = float(p_arr.std(ddof=0)) if n > 1 else 0.0
            sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0
            sum_pnl = float(p_arr.sum())
            # Max consecutive losses (just trades in fire-time order within selection)
            # Order by fire_s for time-coherent streaks
            order = np.argsort(sub["fire_s"].values[sel])
            losses = (~w_arr[order]).astype(int)
            mcl = 0
            cur = 0
            for x in losses:
                if x:
                    cur += 1
                    mcl = max(mcl, cur)
                else:
                    cur = 0

            if wr < MIN_WR:
                continue

            score = wr * np.sqrt(n) * (1.0 if mean_pnl > 0 else 0.0)
            rows_out.append(
                dict(
                    key=key,
                    fam=key.split("__")[0],
                    cell=key.split("__")[1],
                    n_gates=len(gate_list),
                    gates="+".join(gate_list) if gate_list else "<baseline>",
                    n=n,
                    wr=round(wr, 4),
                    avg_pnl=round(mean_pnl, 4),
                    sum_pnl=round(sum_pnl, 3),
                    sharpe=round(sharpe, 4),
                    max_consec_loss=mcl,
                    score=round(score, 4),
                )
            )

    out = pd.DataFrame(rows_out).sort_values(["key", "score"], ascending=[True, False])
    print(f"\n[search] kept {len(out)} configs (n>=30, WR>=0.55)")
    out.to_csv(OUT_CSV, index=False)
    print(f"[write] {OUT_CSV}")

    # ----- build markdown report
    md_lines: list[str] = []
    md_lines.append("# Gate search — 5m up-down momo (combinatorial 2^9)")
    md_lines.append("")
    md_lines.append("**Generated:** 2026-05-23  ")
    md_lines.append(
        "**Data:** `fv_cvd_spike_overlay.parquet` (Baseline_v1/v2) ⨝ `per_trade_markov.parquet` "
        "on `(variant, slug)`; restricted to `tf=5m`."
    )
    md_lines.append(
        f"**Universe:** {len(df)} fires across {df['key'].nunique()} cells. "
        f"Window: 28d up to 2026-05-21 20:10 UTC."
    )
    md_lines.append(
        "**Gates (9):** `hod_pass`, `f7_pass`, `m1v_pass`, `m5v_pass`, `cvd_agree`, "
        "`spike_no_anti`, `edge_ge_2pp`, `mag_in_sweetspot`, `cvd_strong`."
    )
    md_lines.append("")
    md_lines.append("**Method:** enumerate 2^9=512 gate subsets per cell, AND-combined; "
                    f"keep n>={MIN_N} & WR>={MIN_WR:.2f}; rank by "
                    "`score = WR · √n · 1[avg_pnl>0]`. Report deployable cells "
                    f"(WR>={DEPLOY_WR:.2f}) and minimal-gate variant.")
    md_lines.append("")

    # Baseline (no gates) per cell for reference
    md_lines.append("## Baseline (no gates) per cell")
    md_lines.append("")
    md_lines.append("| cell | fam | n | WR | $/tr | sum_pnl |")
    md_lines.append("|---|---|---:|---:|---:|---:|")
    for key in keys:
        sub = df[df["key"] == key]
        n = len(sub)
        wr = sub["won"].mean()
        m = sub["pnl_legacy_usd"].mean()
        s = sub["pnl_legacy_usd"].sum()
        fam, cell = key.split("__")
        md_lines.append(f"| {cell} | {fam} | {n} | {wr:.3f} | {m:+.4f} | {s:+.2f} |")
    md_lines.append("")

    # Per cell sections
    md_lines.append("## Per-cell top configs")
    md_lines.append("")
    no_deploy: list[str] = []
    for key in keys:
        cell_df = out[out["key"] == key]
        deploy = cell_df[cell_df["wr"] >= DEPLOY_WR].copy()
        # Sort deploy by score desc
        deploy = deploy.sort_values(["score", "n"], ascending=[False, False])
        md_lines.append(f"### `{key}`")
        md_lines.append("")
        if deploy.empty:
            md_lines.append(
                f"**No deployable config** (no subset reaches WR ≥ {DEPLOY_WR:.2f} "
                f"with n ≥ {MIN_N})."
            )
            no_deploy.append(key)
            # show best by score even at WR<60 for context
            ctx = cell_df.sort_values("score", ascending=False).head(5)
            if not ctx.empty:
                md_lines.append("")
                md_lines.append(
                    f"_Best configs with WR ≥ {MIN_WR:.2f} (for context):_"
                )
                md_lines.append("")
                md_lines.append(
                    "| rank | gates | n | WR | $/tr | sum | sharpe | mcl |"
                )
                md_lines.append("|---:|---|---:|---:|---:|---:|---:|---:|")
                for i, r in enumerate(ctx.itertuples(index=False), 1):
                    md_lines.append(
                        f"| {i} | {r.gates} | {r.n} | {r.wr:.3f} | "
                        f"{r.avg_pnl:+.4f} | {r.sum_pnl:+.2f} | {r.sharpe:.3f} | {r.max_consec_loss} |"
                    )
            md_lines.append("")
            continue

        md_lines.append(
            f"**Top {min(5, len(deploy))} deployable configs** "
            f"(WR ≥ {DEPLOY_WR:.2f}, n ≥ {MIN_N}):"
        )
        md_lines.append("")
        md_lines.append("| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |")
        md_lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
        for i, r in enumerate(deploy.head(5).itertuples(index=False), 1):
            md_lines.append(
                f"| {i} | {r.gates} | {r.n} | {r.wr:.3f} | "
                f"{r.avg_pnl:+.4f} | {r.sum_pnl:+.2f} | {r.sharpe:.3f} | "
                f"{r.max_consec_loss} | {r.score:.3f} |"
            )
        md_lines.append("")

        # Minimal deployable: smallest n_gates that still hits WR>=0.60
        min_gates = deploy["n_gates"].min()
        minimal = deploy[deploy["n_gates"] == min_gates].sort_values(
            ["score", "n"], ascending=[False, False]
        ).head(1)
        if not minimal.empty:
            r = minimal.iloc[0]
            md_lines.append(
                f"**Minimal deployable** ({int(r['n_gates'])} gate{'s' if r['n_gates']!=1 else ''}): "
                f"`{r['gates']}` → n={int(r['n'])}, WR={r['wr']:.3f}, "
                f"$/tr={r['avg_pnl']:+.4f}, sum=${r['sum_pnl']:+.2f}."
            )
            md_lines.append("")

    # Cross-cell insights
    md_lines.append("## Cross-cell insights")
    md_lines.append("")
    if no_deploy:
        md_lines.append(
            f"**Cells with NO deployable config (WR ≥ {DEPLOY_WR:.2f}, n ≥ {MIN_N}):** "
            + ", ".join(f"`{k}`" for k in no_deploy)
        )
    else:
        md_lines.append(f"All {len(keys)} cells have at least one deployable config.")
    md_lines.append("")

    # Gate-frequency analysis: how often does each gate appear in deployable configs per cell?
    deploy_all = out[out["wr"] >= DEPLOY_WR].copy()
    if not deploy_all.empty:
        md_lines.append("### Gate frequency in deployable configs (per cell)")
        md_lines.append("")
        header = "| cell |" + "".join(f" {g} |" for g in GATES)
        sep = "|---|" + "|".join(["---:" for _ in GATES]) + "|"
        md_lines.append(header)
        md_lines.append(sep)
        for key in keys:
            cell_dep = deploy_all[deploy_all["key"] == key]
            if cell_dep.empty:
                md_lines.append(f"| {key} | " + " | ".join("·" for _ in GATES) + " |")
                continue
            total = len(cell_dep)
            counts = []
            for g in GATES:
                c = cell_dep["gates"].apply(lambda s: g in s.split("+")).sum()
                pct = c / total
                counts.append(f"{pct:.2f}")
            md_lines.append(f"| {key} | " + " | ".join(counts) + " |")
        md_lines.append("")
        md_lines.append(
            "_Values = fraction of deployable configs (per cell) that include each gate._"
        )
        md_lines.append("")

        # Most common single gate combos (size 1 and 2) across all deployable cells
        md_lines.append("### Best single-gate filters (WR uplift over baseline)")
        md_lines.append("")
        md_lines.append("| cell | gate | n | WR | uplift_pp | $/tr |")
        md_lines.append("|---|---|---:|---:|---:|---:|")
        for key in keys:
            sub = df[df["key"] == key]
            base_wr = float(sub["won"].mean())
            single = out[(out["key"] == key) & (out["n_gates"] == 1)]
            if single.empty:
                continue
            single = single.sort_values("wr", ascending=False).head(3)
            for r in single.itertuples(index=False):
                up = (r.wr - base_wr) * 100
                md_lines.append(
                    f"| {key} | {r.gates} | {r.n} | {r.wr:.3f} | {up:+.1f} | {r.avg_pnl:+.4f} |"
                )
        md_lines.append("")
    else:
        md_lines.append("No deployable configs found in any cell.")
        md_lines.append("")

    # Save
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[write] {OUT_MD}")
    print(f"\n[done] no_deploy_cells={no_deploy}")


if __name__ == "__main__":
    main()
