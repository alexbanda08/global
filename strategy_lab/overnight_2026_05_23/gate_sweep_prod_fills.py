"""Indicator-overlay gate sweep on production fills.

For each (strategy, asset, tf, f7_mode='off') cell, evaluate each candidate
gate (built from the prod_fills_with_indicators.parquet feature panel) as
an AND-filter on top of the production fire. Report n / WR% / sum_pnl /
per_tr / uplift_$ / uplift_WR_pp / binom_p (one-sided) vs the un-gated baseline.

Output CSV: data/v4/canonical/_results/indicator_overlay_on_prod_fills.csv
Inbox MD : strategy_lab/reports/_indicator_overlay_inbox.md

Run: py strategy_lab/overnight_2026_05_23/gate_sweep_prod_fills.py
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import binomtest

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PT = ROOT / "data" / "v4" / "canonical" / "_results" / "prod_fills_with_indicators.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "indicator_overlay_on_prod_fills.csv"
OUT_MD  = ROOT / "strategy_lab" / "reports" / "_indicator_overlay_inbox.md"


def gate_specs():
    """Each gate -> (label, predicate over panel df)."""
    def g(name, fn): return (name, fn)
    return [
        g("baseline", lambda d: np.ones(len(d), dtype=bool)),
        g("macd_agree", lambda d: d.macd_agree.fillna(False).to_numpy()),
        g("cvd_agree_30s", lambda d: d.cvd_agree_30s.fillna(False).to_numpy()),
        g("cvd_agree_30s_AND_60s",
            lambda d: (d.cvd_agree_30s.fillna(False) & d.cvd_agree_60s.fillna(False)).to_numpy()),
        g("cvd_agree_30s_AND_macd",
            lambda d: (d.cvd_agree_30s.fillna(False) & d.macd_agree.fillna(False)).to_numpy()),
        g("fair_edge_bp_gt_0",
            lambda d: (d.fair_edge_bp > 0).fillna(False).to_numpy()),
        g("fair_edge_bp_gt_500",
            lambda d: (d.fair_edge_bp > 500).fillna(False).to_numpy()),
        g("fair_edge_bp_gt_500_AND_cvd30",
            lambda d: ((d.fair_edge_bp > 500).fillna(False) &
                       d.cvd_agree_30s.fillna(False)).to_numpy()),
        g("rvol_30_300_gt_1p2",
            lambda d: (d.rvol_30_300 > 1.2).fillna(False).to_numpy()),
        g("m1v_pass", lambda d: d.m1v_pass.fillna(False).to_numpy()),
        g("m5v_pass", lambda d: d.m5v_pass.fillna(False).to_numpy()),
        g("m1v_AND_m5v",
            lambda d: (d.m1v_pass.fillna(False) & d.m5v_pass.fillna(False)).to_numpy()),
        g("cross_partial_agree", lambda d: d.cross_partial_agree.fillna(False).to_numpy()),
        g("cross_full_agree", lambda d: d.cross_full_agree.fillna(False).to_numpy()),
        g("imb5_signal_aligned_0p10",
            lambda d: (((d.imb5 > 0.10) & (d.direction == "UP")) |
                       ((d.imb5 < -0.10) & (d.direction == "DOWN"))).fillna(False).to_numpy()),
        g("spread_bp_lt_100",
            lambda d: (d.spread_bp < 100).fillna(False).to_numpy()),
    ]


def binom_p_one_sided(k_gate, n_gate, p_base):
    """One-sided binomial p-value: P(K >= k_gate | n=n_gate, p=p_base)."""
    if n_gate == 0 or not np.isfinite(p_base):
        return float("nan")
    p_base = max(min(p_base, 1.0), 0.0)
    return float(binomtest(int(k_gate), int(n_gate), p=p_base, alternative="greater").pvalue)


def sweep():
    df = pd.read_parquet(PT)
    print(f"Loaded {len(df):,} fires")
    df = df[df.f7_mode == "off"].copy()    # already filtered, but be explicit
    gates = gate_specs()

    rows = []
    for (strat, asset, tf), grp in df.groupby(["strategy", "asset", "tf"]):
        n_total = len(grp)
        # baseline
        won_arr = grp.won.to_numpy().astype(bool)
        pnl_arr = grp.pnl_legacy_usd.to_numpy()
        base_wr = won_arr.mean() if n_total else float("nan")
        base_sum = pnl_arr.sum()
        base_per = pnl_arr.mean() if n_total else float("nan")
        for label, fn in gates:
            mask = fn(grp)
            n_gate = int(mask.sum())
            if n_gate == 0:
                rows.append(dict(strategy=strat, asset=asset, tf=tf, f7_mode="off",
                                 gate=label, n_total=n_total, n_gate=0,
                                 frac=0.0, wr=float("nan"), wr_base=base_wr,
                                 wr_uplift_pp=float("nan"),
                                 sum_pnl=0.0, sum_pnl_base=base_sum,
                                 per_tr=float("nan"), per_tr_base=base_per,
                                 uplift_per_tr=float("nan"),
                                 uplift_sum_selectivity=0.0,
                                 uplift_sum=-base_sum, binom_p=float("nan")))
                continue
            won_g = won_arr[mask]; pnl_g = pnl_arr[mask]
            wr = won_g.mean()
            sum_pnl = pnl_g.sum()
            per_tr = pnl_g.mean()
            if label == "baseline":
                binp = float("nan")
            else:
                binp = binom_p_one_sided(int(won_g.sum()), n_gate, base_wr)
            # Selectivity uplift: per-trade uplift × n_gate (= "$ of extra value
            # on the subset you keep" vs "what you'd have made on the same n
            # at the ungated per-trade rate"). This is a cleaner read than
            # sum_pnl_gate - sum_pnl_total (which conflates subset size with edge).
            uplift_sum_selectivity = (per_tr - base_per) * n_gate
            rows.append(dict(strategy=strat, asset=asset, tf=tf, f7_mode="off",
                             gate=label, n_total=n_total, n_gate=n_gate,
                             frac=n_gate/n_total, wr=wr, wr_base=base_wr,
                             wr_uplift_pp=(wr - base_wr) * 100,
                             sum_pnl=sum_pnl, sum_pnl_base=base_sum,
                             per_tr=per_tr, per_tr_base=base_per,
                             uplift_per_tr=per_tr - base_per,
                             uplift_sum_selectivity=uplift_sum_selectivity,
                             uplift_sum=sum_pnl - base_sum, binom_p=binp))

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {len(out):,} rows -> {OUT_CSV}")
    return out


def write_report(out: pd.DataFrame):
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    # Drop empty-mask rows (gates that select zero fires) from rankings — they
    # produce phantom "uplift" by avoiding all losers but capture zero value.
    out = out[out.n_gate > 0].copy()
    out["sig"] = (out.binom_p < 0.05) & (out.n_gate >= 20) & (out.gate != "baseline")
    out["marg"] = (out.binom_p < 0.10) & (out.n_gate >= 20) & (out.gate != "baseline")

    # Headline winners ranked by selectivity uplift ($, signed). Selectivity =
    # (per_tr_gate - per_tr_base) * n_gate — "$ extra on the kept subset".
    cand = out[out.sig & (out.uplift_sum_selectivity > 0)].copy()
    cand = cand.sort_values("uplift_sum_selectivity", ascending=False)
    cand_marg = out[out.marg & (out.uplift_sum_selectivity > 0) & ~out.sig].copy()
    cand_marg = cand_marg.sort_values("uplift_sum_selectivity", ascending=False)

    # Duds: significant negative selectivity uplift
    dud = out[(out.gate != "baseline") & (out.n_gate >= 50) &
              (out.uplift_sum_selectivity < 0)].copy()
    dud = dud.sort_values("uplift_sum_selectivity", ascending=True)

    def fmt_per_sleeve_top(strat, asset, tf):
        sub = out[(out.strategy==strat) & (out.asset==asset) & (out.tf==tf) & (out.gate != "baseline")].copy()
        base_row = out[(out.strategy==strat) & (out.asset==asset) & (out.tf==tf) & (out.gate=="baseline")].iloc[0]
        sub = sub.sort_values("uplift_sum_selectivity", ascending=False).head(3)
        lines = []
        lines.append(f"### {strat} / {asset} / {tf}  (n={int(base_row.n_total)}, WR={base_row.wr*100:.1f}%, sum=${base_row.sum_pnl:.2f}, per_tr=${base_row.per_tr:.4f})")
        for _,r in sub.iterrows():
            if r.binom_p < 0.05 and r.n_gate >= 20: sig_flag = "**"
            elif r.binom_p < 0.10 and r.n_gate >= 20: sig_flag = " *"
            else: sig_flag = "  "
            lines.append(
                f"  {sig_flag}{r.gate:<32s} n={int(r.n_gate):>4d}/{int(r.n_total):<4d}"
                f"  WR={r.wr*100:5.1f}% ({r.wr_uplift_pp:+5.1f}pp)"
                f"  sel_upl=${r.uplift_sum_selectivity:>+8.2f}"
                f"  per_tr=${r.per_tr:>+.4f}  p={r.binom_p:.3f}"
            )
        return "\n".join(lines)

    sleeves = sorted(out[["strategy","asset","tf"]].drop_duplicates().itertuples(index=False, name=None))

    lines = []
    lines.append("# Indicator-overlay gate sweep on production fills")
    lines.append(f"Built: 2026-05-24  |  Source: `data/v4/canonical/_results/prod_fills_with_indicators.parquet`")
    lines.append(f"CSV  : `{OUT_CSV.as_posix()}`")
    lines.append(f"Build: `strategy_lab/overnight_2026_05_23/build_prod_fills_panel.py`")
    lines.append(f"Sweep: `strategy_lab/overnight_2026_05_23/gate_sweep_prod_fills.py`")
    lines.append("")
    lines.append("Universe: f7_mode='off' from `fills.csv` (6,675 fires).")
    lines.append("Gate features computed fresh at production `fire_us` (momo_v1: ws_s+120, momo_v2: ws_s+60, sniper: ws_s+window_s).")
    lines.append("PnL is the production `pnl` column (legacy 2%-on-profit fees, $25 stake).")
    lines.append("`sel_upl` = (per_tr_gate - per_tr_base) x n_gate — selectivity uplift (extra $ on the kept subset vs ungated rate).")
    lines.append("Significance: one-sided binomial p (gate WR vs ungated baseline WR) + n_gate >= 20. `**` p<0.05, `*` p<0.10.")
    lines.append("")

    # --- Headline winners ---
    lines.append("## Headline winners (binom p<0.05, n_gate>=20)")
    if len(cand):
        for _,r in cand.head(10).iterrows():
            lines.append(
                f"- **{r.strategy:<8s} / {r.asset} / {r.tf}**  `{r.gate}`"
                f"  n={int(r.n_gate)}/{int(r.n_total)}  WR={r.wr*100:.1f}% ({r.wr_uplift_pp:+.1f}pp)"
                f"  sel_upl=${r.uplift_sum_selectivity:+.2f}  per_tr=${r.per_tr:+.4f}  p={r.binom_p:.3f}"
            )
    else:
        lines.append("- (no gate passed p<0.05 + n_gate>=20)")
    lines.append("")

    lines.append("## Marginal winners (0.05 < p < 0.10, n_gate>=20)")
    if len(cand_marg):
        for _,r in cand_marg.head(10).iterrows():
            lines.append(
                f"- `{r.strategy:<8s} / {r.asset} / {r.tf}`  `{r.gate}`"
                f"  n={int(r.n_gate)}/{int(r.n_total)}  WR={r.wr*100:.1f}% ({r.wr_uplift_pp:+.1f}pp)"
                f"  sel_upl=${r.uplift_sum_selectivity:+.2f}  per_tr=${r.per_tr:+.4f}  p={r.binom_p:.3f}"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    # --- Headline duds ---
    lines.append("## Headline duds (largest negative sel_upl, n_gate>=50)")
    for _,r in dud.head(10).iterrows():
        lines.append(
            f"- `{r.strategy:<8s} / {r.asset} / {r.tf}`  `{r.gate}`"
            f"  n={int(r.n_gate)}/{int(r.n_total)}  WR={r.wr*100:.1f}% ({r.wr_uplift_pp:+.1f}pp)"
            f"  sel_upl=${r.uplift_sum_selectivity:+.2f}  per_tr=${r.per_tr:+.4f}"
        )
    lines.append("")

    # --- Per-sleeve top-3 ---
    lines.append("## Per-sleeve top-3 gates by uplift_sum")
    lines.append("")
    for strat,asset,tf in sleeves:
        lines.append(fmt_per_sleeve_top(strat, asset, tf))
        lines.append("")

    lines.append("## Re-run")
    lines.append("```")
    lines.append("py strategy_lab/overnight_2026_05_23/build_prod_fills_panel.py")
    lines.append("py strategy_lab/overnight_2026_05_23/gate_sweep_prod_fills.py")
    lines.append("```")

    text = "\n".join(lines)
    # Cap at ~250 lines
    text_lines = text.splitlines()
    if len(text_lines) > 250:
        text_lines = text_lines[:248] + ["", "_(truncated to 250 lines)_"]
        text = "\n".join(text_lines)
    OUT_MD.write_text(text, encoding="utf-8")
    print(f"Wrote report -> {OUT_MD}  ({len(text.splitlines())} lines)")


def main():
    out = sweep()
    write_report(out)
    # Quick stdout summary
    print("\nTop 10 selectivity uplift (significant, n_gate>=20):")
    cand = out[(out.gate != "baseline") & (out.binom_p < 0.05) & (out.n_gate >= 20)].copy()
    cand = cand.sort_values("uplift_sum_selectivity", ascending=False).head(10)
    for _,r in cand.iterrows():
        print(f"  {r.strategy}/{r.asset}/{r.tf}  {r.gate:<32s}  n={int(r.n_gate)}/{int(r.n_total)}"
              f"  WR={r.wr*100:.1f}% ({r.wr_uplift_pp:+.1f}pp)  sel_upl=${r.uplift_sum_selectivity:+.2f}  p={r.binom_p:.3f}")
    print("\nMarginal (0.05<p<0.10, n>=20):")
    marg = out[(out.gate != "baseline") & (out.binom_p < 0.10) & (out.binom_p >= 0.05) & (out.n_gate >= 20)].copy()
    marg = marg.sort_values("uplift_sum_selectivity", ascending=False).head(10)
    for _,r in marg.iterrows():
        print(f"  {r.strategy}/{r.asset}/{r.tf}  {r.gate:<32s}  n={int(r.n_gate)}/{int(r.n_total)}"
              f"  WR={r.wr*100:.1f}% ({r.wr_uplift_pp:+.1f}pp)  sel_upl=${r.uplift_sum_selectivity:+.2f}  p={r.binom_p:.3f}")


if __name__ == "__main__":
    main()
