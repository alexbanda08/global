"""Backtest top configs from gate_sweep_master + LightGBM threshold.

Runs the full robustness battery (per-trade Sharpe/Sortino, bootstrap CI, 70/30
walk-forward, binomial null vs vwap-implied break-even) on each candidate
strategy, and writes a deploy-ready scorecard.

Outputs:
  data/v4/canonical/_results/overnight_top_configs_scorecard.csv
  strategy_lab/reports/OVERNIGHT_NEW_5M_STRATEGIES_2026_05_23.md
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
PREDS = ROOT / "data" / "v4" / "canonical" / "_results" / "lgbm_preds_5m.parquet"
GATE  = ROOT / "data" / "v4" / "canonical" / "_results" / "gate_sweep_master.csv"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "overnight_top_configs_scorecard.csv"
OUT_MD  = ROOT / "strategy_lab" / "reports" / "OVERNIGHT_NEW_5M_STRATEGIES_2026_05_23.md"

NOTIONAL = 25.0


def metrics_for_fires(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0: return {"n": 0}
    pnl = sub["pnl_legacy_usd"].to_numpy()
    wr  = float(sub["won"].mean())
    per_tr  = float(pnl.mean())
    sum_pnl = float(pnl.sum())
    sd = float(pnl.std(ddof=1)) if n > 1 else 0.0
    loss = pnl[pnl < 0]
    sd_dn = float(loss.std(ddof=1)) if len(loss) > 1 else 0.0
    sharpe_pt  = (per_tr / sd)    if sd    > 0 else 0.0
    sortino_pt = (per_tr / sd_dn) if sd_dn > 0 else 0.0
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak).min() if len(eq) else 0.0
    span_us = sub["fire_us"].max() - sub["fire_us"].min()
    days = max(1.0, span_us / 1e6 / 86400.0)
    trades_per_year = n * 365.0 / days
    sharpe_ann = sharpe_pt * np.sqrt(trades_per_year)
    pnl_per_year = sum_pnl * 365.0 / days
    calmar = (pnl_per_year / abs(dd)) if dd != 0 else 0.0
    return {
        "n": n, "wr": round(wr, 4), "per_tr": round(per_tr, 3),
        "sum_pnl": round(sum_pnl, 2),
        "sharpe_pt": round(sharpe_pt, 3),
        "sortino_pt": round(sortino_pt, 3),
        "sharpe_ann": round(sharpe_ann, 2),
        "calmar": round(calmar, 2),
        "max_dd": round(float(dd), 2),
        "tpy": int(trades_per_year),
        "days": round(days, 1),
    }


def walk_forward_5050(sub: pd.DataFrame) -> dict:
    if len(sub) < 40: return {"wf_ret": np.nan}
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    mid = len(sub) // 2
    tr, te = sub.iloc[:mid], sub.iloc[mid:]
    ts = float(tr["pnl_legacy_usd"].sum())
    es = float(te["pnl_legacy_usd"].sum())
    return {
        "train_n": int(len(tr)), "test_n": int(len(te)),
        "train_sum": round(ts, 2), "test_sum": round(es, 2),
        "train_wr": round(float(tr["won"].mean()) * 100, 2),
        "test_wr":  round(float(te["won"].mean()) * 100, 2),
        "wf_ret": round(es / ts, 2) if ts != 0 else np.nan,
    }


def block_bootstrap_ci(pnl: np.ndarray, n_iter: int = 2000,
                        block_prob: float = 0.1, seed: int = 42) -> dict:
    if len(pnl) < 40: return {}
    rng = np.random.default_rng(seed); n = len(pnl)
    sums = np.empty(n_iter)
    for k in range(n_iter):
        idxs = np.empty(n, dtype=np.int64); i = 0
        while i < n:
            start = rng.integers(0, n)
            blen  = rng.geometric(block_prob)
            for b in range(blen):
                if i >= n: break
                idxs[i] = (start + b) % n; i += 1
        sums[k] = pnl[idxs].sum()
    return {
        "sum_ci_lo": round(float(np.quantile(sums, 0.025)), 2),
        "sum_ci_hi": round(float(np.quantile(sums, 0.975)), 2),
    }


def binomial_vs_vwap(sub: pd.DataFrame) -> dict:
    if len(sub) < 30: return {}
    expected_wr = float(sub["entry_vwap"].mean())
    n = len(sub); n_won = int(sub["won"].sum())
    p = float(sstats.binomtest(n_won, n, p=expected_wr,
                                alternative="greater").pvalue)
    return {
        "real_wr_pct":     round(float(sub["won"].mean()) * 100, 2),
        "expected_wr_pct": round(expected_wr * 100, 2),
        "wr_edge_pp":      round((sub["won"].mean() - expected_wr) * 100, 2),
        "binom_p":         round(p, 5),
    }


def full_scorecard(sub: pd.DataFrame, label: str) -> dict:
    out = {"label": label}
    out.update(metrics_for_fires(sub))
    out.update(walk_forward_5050(sub))
    if len(sub) >= 40:
        out.update(block_bootstrap_ci(sub["pnl_legacy_usd"].to_numpy()))
    out.update(binomial_vs_vwap(sub))
    return out


# ---------------------------------------------------------------------
# Candidate strategy builder — parses gate_sweep keys back into masks
# ---------------------------------------------------------------------
def build_gate_columns(d: pd.DataFrame) -> pd.DataFrame:
    g = pd.DataFrame(index=d.index)
    g["dir_UP"]   = d["direction"] == "UP"
    g["dir_DOWN"] = d["direction"] == "DOWN"
    g["fair_edge_pos"]    = d["fair_edge_bp"] >  0
    g["fair_edge_strong"] = d["fair_edge_bp"] >  500
    g["cvd_agree_30s"]    = d["cvd_agree_30s"].astype(bool)
    g["cvd_agree_60s"]    = d["cvd_agree_60s"].astype(bool)
    g["cvd_agree_120s"]   = d["cvd_agree_120s"].astype(bool)
    g["macd_agree"]       = d["macd_agree"].astype(bool)
    g["m1v_pass"] = d["m1v_pass"].astype(bool)
    g["m5v_pass"] = d["m5v_pass"].astype(bool)
    g["m1f_pass"] = d["m1f_pass"].astype(bool)
    g["m5f_pass"] = d["m5f_pass"].astype(bool)
    g["f7_pass"]  = d["f7_pass"].astype(bool)
    g["cross_partial"] = d["cross_partial_agree"].astype(bool)
    g["cross_full"]    = d["cross_full_agree"].astype(bool)
    g["micro_imb_up"]   = (d["imb5"] >  0.10).fillna(False) & g["dir_UP"]
    g["micro_imb_down"] = (d["imb5"] < -0.10).fillna(False) & g["dir_DOWN"]
    g["micro_dev_up"]   = (d["micro_minus_mid_bp"] >  20).fillna(False) & g["dir_UP"]
    g["micro_dev_down"] = (d["micro_minus_mid_bp"] < -20).fillna(False) & g["dir_DOWN"]
    g["spread_tight"]   = (d["spread_bp"] < 100).fillna(False)
    g["rvol_elevated"]  = (d["rvol_30_300"] > 1.2).fillna(False)
    g["rvol_high"]      = (d["rvol_60_900"] > 1.5).fillna(False)
    return g


def parse_key_to_mask(key: str, d: pd.DataFrame, g: pd.DataFrame) -> pd.Series:
    parts = key.split("|")
    asset, off_s, dev_lbl, gates_s = parts[0], parts[1], parts[2], parts[3]
    m = pd.Series(True, index=d.index)
    if asset != "ALL": m &= (d["asset"] == asset)
    if off_s != "any": m &= (d["fire_offset_s"] == int(off_s))
    abs_dev = d["dev_bps"].abs()
    if dev_lbl == "≥3bp":  m &= (abs_dev >= 3)
    elif dev_lbl == "≥5bp":  m &= (abs_dev >= 5)
    elif dev_lbl == "≥8bp":  m &= (abs_dev >= 8)
    elif dev_lbl == "≥12bp": m &= (abs_dev >= 12)
    if gates_s != "0g":
        for gname in gates_s.split("+"):
            m &= g[gname]
    return m


def main():
    if not PANEL.exists():
        print(f"PANEL missing: {PANEL}"); sys.exit(1)
    d = pd.read_parquet(PANEL)
    print(f"[load] panel: {len(d):,} rows")

    g = build_gate_columns(d)
    sweep = pd.read_csv(GATE)
    print(f"[load] gate sweep: {len(sweep):,} configs")
    top = sweep.head(40).copy()

    rows = []
    # baseline: every fire (no gating)
    rows.append(full_scorecard(d, "BASELINE_all_fires"))
    # baseline: VWAP cont winner equivalent: BTC, off=240, dev∈[5,10], m1v_pass
    btc240 = (d[(d["asset"] == "BTC") & (d["fire_offset_s"] == 240) &
               (d["dev_bps"].abs().between(5, 10)) & g["m1v_pass"]])
    rows.append(full_scorecard(btc240, "WINNER_REF_btc240_5to10_m1v"))

    # top gate sweep configs
    for _, sr in top.iterrows():
        mask = parse_key_to_mask(sr["key"], d, g)
        rows.append(full_scorecard(d[mask], sr["key"]))

    # LightGBM threshold strategies (if preds exist)
    if PREDS.exists():
        dp = pd.read_parquet(PREDS)
        for q in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
            thr = float(dp["pred_won"].quantile(q))
            sub = dp[dp["pred_won"] >= thr]
            rows.append(full_scorecard(sub, f"LGBM_q{int(q*100)}_thr{thr:.3f}"))
            # OOS only
            sub_test = dp[(dp["split"] == "test") & (dp["pred_won"] >= thr)]
            rows.append(full_scorecard(sub_test,
                                       f"LGBM_q{int(q*100)}_OOS_only"))
    else:
        print("[warn] no LGBM preds yet — skip LGBM threshold rows")

    out = pd.DataFrame(rows)
    out = out.sort_values("sum_pnl", ascending=False).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"[write] {OUT_CSV}")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 90)
    print(out.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
