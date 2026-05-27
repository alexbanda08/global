"""
Schema-adaptive aggregator for Wave 2-PERP (A/B/C/D/E/F) results.
Outputs MASTER_TABLE_PERP.{csv,md} with canonical schema.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

WAVE_DIR = Path(__file__).parent
OUT_DIR = WAVE_DIR.parent

CANON = [
    "source", "strategy_id", "family", "asset", "tf",
    "n_trades", "win_rate", "avg_pnl_usd", "total_pnl_usd",
    "sharpe_ann", "oos_sharpe_ann", "calmar", "max_dd_usd", "profit_factor",
    "avg_bars_held", "avg_fees", "avg_funding",
    "perm_p", "gates_passed", "beats_bh", "notes",
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


def _b(x):
    return x in (True, "True", "true", 1, "1", 1.0)


def map_A(df):
    o = pd.DataFrame()
    o["source"] = "A_trend"
    o["strategy_id"] = df["strategy_id"]
    o["family"] = df["family"]
    o["asset"] = df["asset"]
    o["tf"] = df["tf"]
    o["n_trades"] = df["n_trades"].apply(_i)
    o["win_rate"] = df["win_rate"].apply(_f)
    o["avg_pnl_usd"] = df["avg_pnl_usd"].apply(_f)
    o["total_pnl_usd"] = df["total_pnl_usd"].apply(_f)
    o["sharpe_ann"] = df["sharpe_ann"].apply(_f)
    o["oos_sharpe_ann"] = df["oos_sharpe"].apply(_f) if "oos_sharpe" in df else None
    o["calmar"] = df["calmar"].apply(_f)
    o["max_dd_usd"] = df["max_dd_usd"].apply(_f)
    o["profit_factor"] = df["profit_factor"].apply(_f)
    o["avg_bars_held"] = df["avg_bars_held"].apply(_f)
    o["avg_fees"] = df["avg_fees"].apply(_f)
    o["avg_funding"] = df["avg_funding"].apply(_f)
    o["perm_p"] = None
    o["gates_passed"] = None
    o["beats_bh"] = df["beats_bh_sharpe"].apply(_b) if "beats_bh_sharpe" in df else None
    o["notes"] = df["variant"]
    return o


def map_B(df):
    o = pd.DataFrame()
    o["source"] = "B_mean_rev"
    o["strategy_id"] = df["strategy_id"]
    o["family"] = df["family"]
    o["asset"] = df["asset"]
    o["tf"] = df["tf"]
    o["n_trades"] = df["n_trades"].apply(_i)
    o["win_rate"] = df["win_rate"].apply(_f)
    o["avg_pnl_usd"] = df["avg_pnl_usd"].apply(_f)
    o["total_pnl_usd"] = df["total_pnl_usd"].apply(_f)
    o["sharpe_ann"] = df["sharpe_ann"].apply(_f)
    o["oos_sharpe_ann"] = df["oos_sharpe"].apply(_f)
    o["calmar"] = df["calmar"].apply(_f)
    o["max_dd_usd"] = df["max_dd_usd"].apply(_f)
    o["profit_factor"] = df["profit_factor"].apply(_f)
    o["avg_bars_held"] = df["avg_bars_held"].apply(_f)
    o["avg_fees"] = df["avg_fees"].apply(_f)
    o["avg_funding"] = df["avg_funding"].apply(_f)
    o["perm_p"] = None
    o["gates_passed"] = None
    o["beats_bh"] = None
    o["notes"] = df["variant"]
    return o


def map_C(df):
    o = pd.DataFrame()
    o["source"] = "C_breakout"
    o["strategy_id"] = df["strategy_id"]
    o["family"] = df["strategy_family"]
    o["asset"] = df["asset"]
    o["tf"] = df["tf"]
    o["n_trades"] = df["n_trades"].apply(_i)
    o["win_rate"] = df["win_rate"].apply(_f)
    o["avg_pnl_usd"] = df["avg_pnl_usd"].apply(_f)
    o["total_pnl_usd"] = df["total_pnl_usd"].apply(_f)
    o["sharpe_ann"] = df["sharpe_ann"].apply(_f)
    o["oos_sharpe_ann"] = df["oos_sharpe_ann"].apply(_f)
    o["calmar"] = df["calmar"].apply(_f)
    o["max_dd_usd"] = df["max_dd_usd"].apply(_f)
    o["profit_factor"] = df["profit_factor"].apply(_f)
    o["avg_bars_held"] = df["avg_bars_held"].apply(_f)
    o["avg_fees"] = None
    o["avg_funding"] = None
    o["perm_p"] = df["perm_p_value"].apply(_f)
    o["gates_passed"] = df["gates_passed_n"].astype(str) + "/6"
    o["beats_bh"] = df["gate_beats_bh"].apply(_b)
    o["notes"] = df["variant"]
    return o


def map_D(df):
    o = pd.DataFrame()
    o["source"] = "D_carry"
    o["strategy_id"] = df["label"]
    o["family"] = df["family"]
    o["asset"] = df["asset"]
    o["tf"] = "h" + df["hold_h"].astype(str)
    o["n_trades"] = df["n_trades"].apply(_i)
    o["win_rate"] = df["win_rate"].apply(_f)
    o["avg_pnl_usd"] = df["avg_pnl_usd"].apply(_f)
    o["total_pnl_usd"] = df["total_pnl_usd"].apply(_f)
    o["sharpe_ann"] = df["sharpe"].apply(_f)
    o["oos_sharpe_ann"] = df["g3_wf_mean_sharpe"].apply(_f)
    o["calmar"] = None
    o["max_dd_usd"] = None
    o["profit_factor"] = None
    o["avg_bars_held"] = None
    o["avg_fees"] = df["avg_fees"].apply(_f)
    o["avg_funding"] = df["avg_funding"].apply(_f)
    o["perm_p"] = df["g4_perm_p"].apply(_f)
    def _gp(row):
        flags = ["g1_pass","g2_pass","g3_wf_stable","g4_pass","g5_pass","g6_pass","g7_pass"]
        n = sum(_b(row.get(f)) for f in flags)
        return f"{n}/7"
    o["gates_passed"] = df.apply(_gp, axis=1)
    o["beats_bh"] = None
    o["notes"] = "z=" + df["z_thresh"].astype(str)
    return o


def map_E(df):
    o = pd.DataFrame()
    o["source"] = "E_regime"
    o["strategy_id"] = df["strategy"].astype(str) + "_" + df["asset"] + "_" + df["tf"] + "_" + df["variant"].astype(str)
    o["family"] = df["strategy"]
    o["asset"] = df["asset"]
    o["tf"] = df["tf"]
    o["n_trades"] = df["n_trades"].apply(_i)
    o["win_rate"] = df["win_rate"].apply(_f)
    o["avg_pnl_usd"] = df["avg_pnl_usd"].apply(_f)
    o["total_pnl_usd"] = df["total_pnl_usd"].apply(_f)
    o["sharpe_ann"] = df["sharpe_ann"].apply(_f)
    o["oos_sharpe_ann"] = None
    o["calmar"] = df["calmar"].apply(_f)
    o["max_dd_usd"] = df["max_dd_usd"].apply(_f)
    o["profit_factor"] = df["profit_factor"].apply(_f)
    o["avg_bars_held"] = df["avg_bars_held"].apply(_f)
    o["avg_fees"] = df["avg_fees"].apply(_f)
    o["avg_funding"] = df["avg_funding"].apply(_f)
    o["perm_p"] = None
    o["gates_passed"] = None
    o["beats_bh"] = None
    o["notes"] = df["variant"]
    return o


def map_F(df):
    """F_summary.csv is more useful than F_results.csv (per-window) — aggregate level."""
    o = pd.DataFrame()
    o["source"] = "F_ml"
    o["strategy_id"] = df["strategy"] + "_" + df["asset"] + "_" + df["tf"]
    o["family"] = df["strategy"]
    o["asset"] = df["asset"]
    o["tf"] = df["tf"]
    o["n_trades"] = df["sum_trades"].apply(_i)
    o["win_rate"] = df["mean_win_rate"].apply(_f)
    o["avg_pnl_usd"] = df["mean_avg_pnl"].apply(_f)
    o["total_pnl_usd"] = df["sum_pnl"].apply(_f)
    o["sharpe_ann"] = df["mean_sharpe_ann"].apply(_f)
    o["oos_sharpe_ann"] = df["mean_sharpe_ann"].apply(_f)  # F is OOS by walkforward
    o["calmar"] = None
    o["max_dd_usd"] = None
    o["profit_factor"] = None
    o["avg_bars_held"] = None
    o["avg_fees"] = df["sum_fees"].apply(_f)
    o["avg_funding"] = df["sum_funding"].apply(_f)
    o["perm_p"] = None
    def _g(r):
        if _b(r.get("all_windows_pos_pnl")) and _b(r.get("quality_pass")): return "4/4_wins+quality"
        if _b(r.get("all_windows_pos_pnl")): return "4/4_wins"
        return "partial"
    o["gates_passed"] = df.apply(_g, axis=1)
    o["beats_bh"] = None
    o["notes"] = "auc=" + df["mean_auc"].apply(lambda v: f"{_f(v):.3f}" if _f(v) else "n/a")
    return o


MAPPERS = {
    "A_results.csv": map_A,
    "B_results.csv": map_B,
    "C_results.csv": map_C,
    "D_results.csv": map_D,
    "E_results.csv": map_E,
    "F_summary.csv": map_F,
}


def main():
    frames = []
    for fname, mapper in MAPPERS.items():
        p = WAVE_DIR / fname
        if not p.exists():
            print(f"  skip {fname} (missing)")
            continue
        df = pd.read_csv(p)
        try:
            mapped = mapper(df)
        except Exception as e:
            print(f"  ERROR mapping {fname}: {e}")
            continue
        for c in CANON:
            if c not in mapped.columns:
                mapped[c] = None
        mapped = mapped[CANON]
        frames.append(mapped)
        print(f"  {fname}: {len(mapped)} rows")
    if not frames:
        print("No frames.")
        return
    master = pd.concat(frames, ignore_index=True)

    # Score: prefer OOS sharpe over IS; require n>=30; reward beating BH
    def _score(row):
        n = _i(row.get("n_trades")) or 0
        if n < 30:
            return -5.0
        s = _f(row.get("oos_sharpe_ann"))
        if s is None:
            s = _f(row.get("sharpe_ann")) or 0.0
        bh = 0.3 if row.get("beats_bh") is True else 0.0
        # Calmar bonus
        c = _f(row.get("calmar")) or 0.0
        c = min(c, 5.0) * 0.05
        # Profit factor bonus
        pf = _f(row.get("profit_factor")) or 0.0
        pf_b = 0.1 if pf > 1.5 else 0.0
        return s + bh + c + pf_b

    master["rank_score"] = master.apply(_score, axis=1)
    master = master.sort_values("rank_score", ascending=False).reset_index(drop=True)
    master.to_csv(OUT_DIR / "MASTER_TABLE_PERP.csv", index=False)

    # MD with top 40 + family summary + deploy candidates
    top = master.head(40).copy()
    md = ["# PERP-NATIVE Master Table (Wave 2-PERP)", ""]
    md.append(f"**Total cells**: {len(master):,} across 6 families")
    md.append("")
    md.append("## Family summary")
    md.append("")
    fam = master.groupby("source").agg(
        n=("strategy_id","count"),
        max_oos_sharpe=("oos_sharpe_ann","max"),
        median_oos_sharpe=("oos_sharpe_ann","median"),
        max_sharpe=("sharpe_ann","max"),
    ).round(2)
    md.append(fam.to_markdown())
    md.append("")
    md.append("## Top-40 (rank by OOS Sharpe + BH-beat bonus + calmar bonus, n>=30)")
    md.append("")
    md.append("| # | Source | Strategy | Asset | TF | n | WR | OOS Sharpe | Sharpe | Calmar | PF | MDD | Gates | BeatBH | Notes |")
    md.append("|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|")
    for i, r in top.iterrows():
        def fmt(v, prec=2):
            try:
                fv = float(v)
                if not np.isfinite(fv): return "—"
                return f"{fv:.{prec}f}"
            except: return "—"
        md.append(
            f"| {i+1} | {r['source']} | {str(r['strategy_id'])[:50]} | {r['asset']} | {r['tf']} "
            f"| {r['n_trades']} | {fmt(r['win_rate'],2)} | {fmt(r['oos_sharpe_ann'])} | {fmt(r['sharpe_ann'])} "
            f"| {fmt(r['calmar'])} | {fmt(r['profit_factor'])} | {fmt(r['max_dd_usd'],0)} "
            f"| {str(r['gates_passed'])[:8]} | {r['beats_bh']} | {str(r['notes'])[:25]} |"
        )
    md.append("")

    # Deploy candidates: n>=50, OOS sharpe >= 1.5, beats BH OR all-gates-pass
    cand = master[(master["n_trades"].fillna(0) >= 50)
                  & (master["oos_sharpe_ann"].fillna(-99) >= 1.5)].copy()
    md.append(f"## Deploy candidates (n>=50, OOS Sharpe>=1.5): **{len(cand)}**")
    md.append("")
    if len(cand) > 0:
        md.append("| Source | Strategy | Asset | TF | n | WR | OOS Sharpe | Calmar | PF | MDD | Gates | BeatsBH | Notes |")
        md.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|")
        for _, r in cand.iterrows():
            def fmt(v, prec=2):
                try:
                    fv = float(v); return f"{fv:.{prec}f}" if np.isfinite(fv) else "—"
                except: return "—"
            md.append(
                f"| {r['source']} | {str(r['strategy_id'])[:60]} | {r['asset']} | {r['tf']} "
                f"| {r['n_trades']} | {fmt(r['win_rate'],2)} | {fmt(r['oos_sharpe_ann'])} "
                f"| {fmt(r['calmar'])} | {fmt(r['profit_factor'])} | {fmt(r['max_dd_usd'],0)} "
                f"| {r['gates_passed']} | {r['beats_bh']} | {str(r['notes'])[:30]} |"
            )
    (OUT_DIR / "MASTER_TABLE_PERP.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'MASTER_TABLE_PERP.csv'} ({len(master)} rows)")
    print(f"Wrote {OUT_DIR / 'MASTER_TABLE_PERP.md'}")
    print(f"Deploy candidates (n>=50, OOS sharpe>=1.5): {len(cand)}")


if __name__ == "__main__":
    main()
