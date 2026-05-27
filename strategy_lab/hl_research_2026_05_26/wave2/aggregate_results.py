"""
Schema-adaptive aggregator for Wave 2 + 3 results.
Each agent produced its own CSV schema; this maps them into a canonical form.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

WAVE2_DIR = Path(__file__).parent
OUT_DIR = WAVE2_DIR.parent

CANONICAL_COLS = [
    "source", "strategy_id", "hypothesis", "asset", "tf",
    "n_trades", "win_rate", "dpt_usd", "sharpe", "max_dd_usd",
    "p_value", "perm_p", "boot_lo", "gates_passed", "n_gates_total",
    "notes",
]


def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _i(x):
    try:
        return int(float(x))
    except Exception:
        return None


def map_w2a(df: pd.DataFrame) -> pd.DataFrame:
    """W2a: liq cascade."""
    out = pd.DataFrame()
    out["source"] = "W2a"
    out["strategy_id"] = df["strategy_id"]
    out["hypothesis"] = df["hypothesis"]
    out["asset"] = df["asset"]
    out["tf"] = df["tf"]
    out["n_trades"] = df["n_trades"].apply(_i)
    out["win_rate"] = df["win_rate"].apply(_f)
    out["dpt_usd"] = df["dollar_per_trade"].apply(_f)
    out["sharpe"] = df["sharpe"].apply(_f)
    out["max_dd_usd"] = df["max_dd"].apply(_f)
    out["p_value"] = df["p_value"].apply(_f)
    out["perm_p"] = df["permutation_p"].apply(_f)
    out["boot_lo"] = df["bootstrap_ci_lo"].apply(_f)
    out["gates_passed"] = df["gate_pass"]
    out["n_gates_total"] = 4
    out["notes"] = df["notes"]
    return out


def map_w2b(df: pd.DataFrame) -> pd.DataFrame:
    """W2b: funding + basis."""
    out = pd.DataFrame()
    out["source"] = "W2b"
    out["strategy_id"] = df["label"]
    out["hypothesis"] = df["hypothesis"]
    out["asset"] = df["asset"]
    out["tf"] = df["hold_h"].astype(str) + "h_hold"
    out["n_trades"] = df["n_trades"].apply(_i)
    out["win_rate"] = df["win_rate"].apply(_f)
    out["dpt_usd"] = df["avg_pnl_usd"].apply(_f)
    out["sharpe"] = df["sharpe"].apply(_f)
    out["max_dd_usd"] = None
    out["p_value"] = df["g1_p"].apply(_f)
    out["perm_p"] = df["g4_perm_p"].apply(_f)
    out["boot_lo"] = df["boot_lo"].apply(_f)
    # Count gates passed
    gpcols = ["g1_pass", "g2_pnl_pos", "g3_wf_stable", "g4_pass", "boot_pos"]
    def _gp(row):
        passed = []
        for c, label in zip(gpcols, ["G1","G2","G3","G4","G6"]):
            v = row.get(c)
            if v in (True, "True", "true", 1, "1"):
                passed.append(label)
        return ",".join(passed) if passed else "none"
    out["gates_passed"] = df.apply(_gp, axis=1)
    out["n_gates_total"] = 5
    out["notes"] = df["status"]
    return out


def map_w2c(df: pd.DataFrame) -> pd.DataFrame:
    """W2c: lead-lag + pairs."""
    out = pd.DataFrame()
    out["source"] = "W2c"
    out["strategy_id"] = df["test"].astype(str) + "_" + df["leader"].astype(str) + "_to_" + df["follower"].astype(str)
    out["hypothesis"] = df["hypothesis"]
    out["asset"] = df["follower"]
    out["tf"] = df["window"]
    out["n_trades"] = df["n"].apply(_i)
    out["win_rate"] = df["win_rate"].apply(_f)
    out["dpt_usd"] = df["mean_pnl"].apply(_f)
    out["sharpe"] = df["sharpe"].apply(_f)
    out["max_dd_usd"] = None
    out["p_value"] = df["p"].apply(_f)
    out["perm_p"] = df["perm_p"].apply(_f)
    out["boot_lo"] = None
    # Gates: positive sharpe, positive sum_pnl, p<0.05, perm_p<0.05
    def _gp(row):
        p = []
        try:
            if _f(row.get("sharpe", 0)) and _f(row.get("sharpe", 0)) > 0: p.append("G_pos_sharpe")
            if _f(row.get("sum_pnl", 0)) and _f(row.get("sum_pnl", 0)) > 0: p.append("G_pos_pnl")
            if _f(row.get("p", 1)) and _f(row.get("p", 1)) < 0.05: p.append("G1")
            if _f(row.get("perm_p", 1)) and _f(row.get("perm_p", 1)) < 0.05: p.append("G4")
        except Exception:
            pass
        return ",".join(p) if p else "none"
    out["gates_passed"] = df.apply(_gp, axis=1)
    out["n_gates_total"] = 4
    out["notes"] = df["direction"].fillna("") + "/" + df["thr_pct"].astype(str)
    return out


def map_w2d(df: pd.DataFrame) -> pd.DataFrame:
    """W2d: cyclops + markov."""
    out = pd.DataFrame()
    out["source"] = "W2d"
    out["strategy_id"] = df["asset"] + "_" + df["tf"] + "_" + df["variant"]
    out["hypothesis"] = "N9_cyclops_N4_markov_sizing"
    out["asset"] = df["asset"]
    out["tf"] = df["tf"]
    out["n_trades"] = df["n_trades"].apply(_i)
    out["win_rate"] = df["win_rate"].apply(_f)
    out["dpt_usd"] = df["avg_pnl_usd"].apply(_f)
    out["sharpe"] = df["sharpe"].apply(_f)
    out["max_dd_usd"] = df["max_dd_usd"].apply(_f)
    out["p_value"] = None
    out["perm_p"] = None
    out["boot_lo"] = None
    out["gates_passed"] = "n/a"
    out["n_gates_total"] = 0
    out["notes"] = "lev=" + df["avg_lev"].astype(str)
    return out


def map_w2e(df: pd.DataFrame) -> pd.DataFrame:
    """W2e: SMS port."""
    out = pd.DataFrame()
    out["source"] = "W2e"
    out["strategy_id"] = df["asset"] + "_" + df["tf"] + "_" + df["variant"]
    out["hypothesis"] = "N_sms_port"
    out["asset"] = df["asset"]
    out["tf"] = df["tf"]
    out["n_trades"] = df["n_trades"].apply(_i)
    out["win_rate"] = df["win_rate"].apply(_f)
    out["dpt_usd"] = df["avg_pnl_usd"].apply(_f)
    out["sharpe"] = df["sharpe"].apply(_f)
    out["max_dd_usd"] = df["max_dd_usd"].apply(_f)
    out["p_value"] = df["g1_binom_p"].apply(_f)
    out["perm_p"] = df["g4_perm_p"].apply(_f)
    out["boot_lo"] = df["g6_pnl_ci_lo"].apply(_f)
    def _gp(row):
        p = []
        if _f(row.get("g1_binom_p", 1)) and _f(row.get("g1_binom_p", 1)) < 0.05: p.append("G1")
        if _f(row.get("total_pnl_usd", 0)) and _f(row.get("total_pnl_usd", 0)) > 0: p.append("G2")
        if _f(row.get("g4_perm_p", 1)) and _f(row.get("g4_perm_p", 1)) < 0.05: p.append("G4")
        if _f(row.get("g6_pnl_ci_lo", -1)) and _f(row.get("g6_pnl_ci_lo", -1)) > 0: p.append("G6")
        return ",".join(p) if p else "none"
    out["gates_passed"] = df.apply(_gp, axis=1)
    out["n_gates_total"] = 4
    out["notes"] = ""
    return out


def map_w3(df: pd.DataFrame) -> pd.DataFrame:
    """W3: meta-classifier walkforward."""
    out = pd.DataFrame()
    out["source"] = "W3"
    # Use lgb (lightgbm) results — typically stronger than RF
    out["strategy_id"] = df["asset"] + "_" + df["tf"] + "_" + df["target"] + "_w" + df["window"].astype(str) + "_lgb"
    out["hypothesis"] = "N8_meta_classifier_lgb"
    out["asset"] = df["asset"]
    out["tf"] = df["tf"]
    out["n_trades"] = df["lgb_n_trades"].apply(_i)
    out["win_rate"] = df["lgb_acc"].apply(_f)
    out["dpt_usd"] = None  # ML model not converted to per-trade $ here
    out["sharpe"] = df["lgb_sharpe_oos"].apply(_f)
    out["max_dd_usd"] = None
    out["p_value"] = None
    out["perm_p"] = None
    out["boot_lo"] = None
    # AUC > 0.51 considered minimal edge
    def _gp(row):
        p = []
        auc = _f(row.get("lgb_auc"))
        if auc and auc > 0.51: p.append("G_auc_edge")
        sh = _f(row.get("lgb_sharpe_oos"))
        if sh and sh > 0: p.append("G_pos_sharpe")
        if sh and sh > 1.0: p.append("G_sharpe_gt_1")
        return ",".join(p) if p else "none"
    out["gates_passed"] = df.apply(_gp, axis=1)
    out["n_gates_total"] = 3
    out["notes"] = "auc=" + df["lgb_auc"].apply(lambda v: f"{_f(v):.3f}" if _f(v) is not None else "n/a")
    return out


MAPPERS = {
    "W2a_results.csv": map_w2a,
    "W2b_results.csv": map_w2b,
    "W2c_results.csv": map_w2c,
    "W2d_results.csv": map_w2d,
    "W2e_results.csv": map_w2e,
    "W3_walkforward_results.csv": map_w3,
}


def main():
    frames = []
    for fname, mapper in MAPPERS.items():
        p = WAVE2_DIR / fname
        if not p.exists():
            print(f"  skip (missing): {fname}")
            continue
        df = pd.read_csv(p)
        mapped = mapper(df)
        # Ensure column order
        mapped = mapped[CANONICAL_COLS]
        frames.append(mapped)
        print(f"  {fname}: {len(mapped)} rows")
    master = pd.concat(frames, ignore_index=True)

    # Compute n_gates_passed
    master["n_gates_passed"] = master["gates_passed"].fillna("").apply(
        lambda s: 0 if s in ("", "none", "n/a") else len([x for x in s.split(",") if x.strip()])
    )

    # Rank score = sharpe + 0.5 * (gates_passed / max(1, n_gates_total))
    def _score(row):
        s = _f(row.get("sharpe")) or 0.0
        gp = row.get("n_gates_passed", 0) or 0
        gt = row.get("n_gates_total", 0) or 0
        ratio = gp / gt if gt > 0 else 0.0
        n = _i(row.get("n_trades")) or 0
        # Penalize low-n (< 20) and reward sufficient sample (>= 50)
        size_penalty = -1.0 if n < 20 else (0.0 if n < 50 else 0.3)
        return s + 0.5 * ratio + size_penalty

    master["rank_score"] = master.apply(_score, axis=1)
    master = master.sort_values("rank_score", ascending=False).reset_index(drop=True)
    master.to_csv(OUT_DIR / "MASTER_TABLE.csv", index=False)

    # Markdown — top 30 + family summary
    top = master.head(30).copy()
    md = ["# Wave 2 + 3 Master Table — HL Strategy Research", ""]
    md.append(f"**Total cells tested**: {len(master):,}")
    md.append("")
    md.append("**Family summary**:")
    md.append("")
    fam = master.groupby("source").agg(
        n_cells=("strategy_id", "count"),
        max_sharpe=("sharpe", "max"),
        median_sharpe=("sharpe", "median"),
        n_passing_3plus_gates=("n_gates_passed", lambda s: (s >= 3).sum()),
    )
    md.append(fam.to_markdown())
    md.append("")
    md.append("## Top-30 ranked (rank_score = sharpe + 0.5 × gate_ratio − size_penalty)")
    md.append("")
    md.append("| # | Source | Strategy | Asset | TF | n | WR | $/tr | Sharpe | p | perm-p | Gates | Notes |")
    md.append("|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    for i, r in top.iterrows():
        def fmt(v, prec=2):
            if v is None: return "—"
            try:
                fv = float(v)
                if not np.isfinite(fv): return "—"
                return f"{fv:.{prec}f}"
            except Exception:
                return str(v)[:20]
        md.append(
            f"| {i+1} | {r['source']} | {str(r['strategy_id'])[:50]} | {r['asset']} | {r['tf']} "
            f"| {r['n_trades']} | {fmt(r['win_rate'], 3)} | {fmt(r['dpt_usd'], 2)} | {fmt(r['sharpe'], 2)} "
            f"| {fmt(r['p_value'], 4)} | {fmt(r['perm_p'], 4)} | {str(r['gates_passed'])[:30]} | {str(r['notes'])[:30]} |"
        )
    md.append("")
    md.append("## Deploy candidates (n ≥ 30, sharpe ≥ 1.5, ≥ 3 gates passed)")
    md.append("")
    candidates = master[
        (master["n_trades"].fillna(0) >= 30)
        & (master["sharpe"].fillna(-99) >= 1.5)
        & (master["n_gates_passed"] >= 3)
    ].copy()
    md.append(f"**{len(candidates)} candidate(s)** meet all 3 criteria.")
    md.append("")
    if len(candidates) > 0:
        md.append("| Source | Strategy | Asset | TF | n | WR | $/tr | Sharpe | Gates |")
        md.append("|---|---|---|---|---:|---:|---:|---:|---|")
        for _, r in candidates.iterrows():
            def fmt(v, prec=2):
                if v is None: return "—"
                try:
                    fv = float(v); return f"{fv:.{prec}f}" if np.isfinite(fv) else "—"
                except: return "—"
            md.append(
                f"| {r['source']} | {str(r['strategy_id'])[:60]} | {r['asset']} | {r['tf']} "
                f"| {r['n_trades']} | {fmt(r['win_rate'], 3)} | {fmt(r['dpt_usd'], 2)} | {fmt(r['sharpe'], 2)} "
                f"| {r['gates_passed']} |"
            )
    (OUT_DIR / "MASTER_TABLE.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'MASTER_TABLE.csv'} ({len(master)} rows)")
    print(f"Wrote {OUT_DIR / 'MASTER_TABLE.md'}")
    print(f"\nDeploy candidates (n>=30, sharpe>=1.5, gates>=3): {len(candidates)}")


if __name__ == "__main__":
    main()
