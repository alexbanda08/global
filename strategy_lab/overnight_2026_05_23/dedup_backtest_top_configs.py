"""Dedup-aware backtest of the top configs from gate_sweep_master.

The raw gate sweep counted each offset as an independent fire. In production,
one slug × direction = at most ONE trade. This script enforces that by picking
the EARLIEST offset where the rule passes, per (asset, slug, direction).

Then runs the full robustness battery on the deduped sample:
  - per-trade Sharpe / Sortino / Calmar
  - cash-equity max DD
  - 70/30 chronological walk-forward
  - 2 000-iter block bootstrap CI on sum_pnl
  - binomial test of WR vs entry-vwap-implied break-even

Outputs:
  data/v4/canonical/_results/dedup_backtest_top_configs.csv
  strategy_lab/reports/OVERNIGHT_NEW_5M_STRATEGIES_2026_05_23.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
PREDS = ROOT / "data" / "v4" / "canonical" / "_results" / "lgbm_preds_5m.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "dedup_backtest_top_configs.csv"


# ---------------------------------------------------------------------
# Gate-mask builder (same as gate_sweep_master)
# ---------------------------------------------------------------------
def build_gates(d: pd.DataFrame) -> pd.DataFrame:
    g = pd.DataFrame(index=d.index)
    g["dir_UP"]   = d["direction"] == "UP"
    g["dir_DOWN"] = d["direction"] == "DOWN"
    g["fair_edge_pos"]    = (d["fair_edge_bp"] >  0).fillna(False)
    g["fair_edge_strong"] = (d["fair_edge_bp"] >  500).fillna(False)
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
    g["spread_tight"]   = (d["spread_bp"] < 100).fillna(False)
    g["rvol_elevated"]  = (d["rvol_30_300"] > 1.2).fillna(False)
    g["rvol_high"]      = (d["rvol_60_900"] > 1.5).fillna(False)
    return g


# ---------------------------------------------------------------------
# Strategy spec — list of (label, gate-names-AND, asset-filter, dev-min, offset-filter)
# ---------------------------------------------------------------------
STRATEGIES = [
    # ----- ALL-asset rules from gate sweep top -----
    ("S1_pooled_cvd30+cvd60+macd",         ["cvd_agree_30s","cvd_agree_60s","macd_agree"],   None, 0,  None),
    ("S2_pooled_fairpos+rvolelv",          ["fair_edge_pos","rvol_elevated"],                None, 0,  None),
    ("S3_pooled_fairpos+cvd60+macd",       ["fair_edge_pos","cvd_agree_60s","macd_agree"],   None, 0,  None),
    ("S4_pooled_fairstrong+cvd30",         ["fair_edge_strong","cvd_agree_30s"],             None, 8,  None),
    ("S5_pooled_fairstrong+rvolelv",       ["fair_edge_strong","rvol_elevated"],             None, 3,  None),
    ("S6_pooled_cvd60+cvd120+macd",        ["cvd_agree_60s","cvd_agree_120s","macd_agree"],  None, 0,  None),
    ("S7_pooled_fairpos+cvd30+rvolelv",    ["fair_edge_pos","cvd_agree_30s","rvol_elevated"],None, 0,  None),
    ("S8_pooled_macd+rvolelv",             ["macd_agree","rvol_elevated"],                   None, 0,  None),
    # ----- BTC -----
    ("S9_BTC_macd_only",                   ["macd_agree"],                                   "BTC",0,  None),
    ("S10_BTC_cvd30+macd",                 ["cvd_agree_30s","macd_agree"],                   "BTC",0,  None),
    ("S11_BTC_fairpos+cvd60+macd",         ["fair_edge_pos","cvd_agree_60s","macd_agree"],   "BTC",0,  None),
    # ----- ETH -----
    ("S12_ETH_fairpos+cvd30",              ["fair_edge_pos","cvd_agree_30s"],                "ETH",0,  None),
    ("S13_ETH_fairstrong+cvd30",           ["fair_edge_strong","cvd_agree_30s"],             "ETH",0,  None),
    # ----- SOL -----
    ("S14_SOL_fairpos+cvd60+m5v",          ["fair_edge_pos","cvd_agree_60s","m5v_pass"],     "SOL",0,  None),
    ("S15_SOL_fairstrong+cvd60+m5v",       ["fair_edge_strong","cvd_agree_60s","m5v_pass"],  "SOL",0,  None),
    # ----- Reference: existing VWAP cont winner -----
    ("REF_VWAPcont_btc240_5to10_m1v",      ["m1v_pass"],                                     "BTC",5,  [240]),
    # ----- Baseline: NO gates -----
    ("BASELINE_no_gates",                  [],                                               None, 0,  None),
]


def apply_strategy(d: pd.DataFrame, g: pd.DataFrame, gates, asset, dev_min, offsets):
    m = pd.Series(True, index=d.index)
    if asset is not None: m &= (d["asset"] == asset)
    if dev_min > 0:        m &= (d["dev_bps"].abs() >= dev_min)
    if offsets is not None:
        m &= (d["fire_offset_s"].isin(offsets))
    for gn in gates: m &= g[gn]
    # also enforce dev tier ≤10 for the REF
    return m


def dedup_to_first_offset(sub: pd.DataFrame) -> pd.DataFrame:
    """Per (asset, slug, direction), pick the EARLIEST passing fire_offset_s."""
    return (sub.sort_values(["asset", "slug", "direction", "fire_offset_s"])
              .drop_duplicates(["asset", "slug", "direction"], keep="first")
              .reset_index(drop=True))


# ---------------------------------------------------------------------
# Robustness battery
# ---------------------------------------------------------------------
def scorecard(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0: return {"n": 0}
    pnl = sub["pnl_legacy_usd"].to_numpy()
    wr  = float(sub["won"].mean())
    sum_pnl = float(pnl.sum())
    per_tr  = float(pnl.mean())
    sd  = float(pnl.std(ddof=1)) if n > 1 else 0.0
    loss = pnl[pnl < 0]
    sd_dn = float(loss.std(ddof=1)) if len(loss) > 1 else 0.0
    sharpe_pt  = (per_tr / sd) if sd > 0 else 0.0
    sortino_pt = (per_tr / sd_dn) if sd_dn > 0 else 0.0
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = float((eq - peak).min()) if len(eq) else 0.0
    span_us = sub["fire_us"].max() - sub["fire_us"].min()
    days = max(1.0, span_us / 1e6 / 86400.0)
    tpy = n * 365.0 / days
    sharpe_ann = sharpe_pt * np.sqrt(tpy)
    pnl_per_year = sum_pnl * 365.0 / days
    calmar = (pnl_per_year / abs(dd)) if dd != 0 else 0.0
    return {
        "n": n, "days": round(days, 1),
        "wr_pct": round(wr * 100, 2),
        "per_tr": round(per_tr, 3),
        "sum_pnl": round(sum_pnl, 2),
        "per_day": round(sum_pnl / days, 2),
        "sharpe_pt": round(sharpe_pt, 3),
        "sortino_pt": round(sortino_pt, 3),
        "sharpe_ann": round(sharpe_ann, 2),
        "calmar": round(calmar, 2),
        "max_dd": round(dd, 2),
    }


def walkforward(sub: pd.DataFrame) -> dict:
    if len(sub) < 40: return {"wf_ret": np.nan}
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    mid = int(0.70 * len(sub))
    tr, te = sub.iloc[:mid], sub.iloc[mid:]
    ts = float(tr["pnl_legacy_usd"].sum())
    es = float(te["pnl_legacy_usd"].sum())
    return {
        "train_n": int(len(tr)), "test_n": int(len(te)),
        "train_wr": round(float(tr["won"].mean()) * 100, 2),
        "test_wr":  round(float(te["won"].mean()) * 100, 2),
        "train_sum": round(ts, 2), "test_sum": round(es, 2),
        "wf_ret": round(es / ts, 2) if ts != 0 else np.nan,
    }


def bootstrap_ci(pnl: np.ndarray, n_iter=2000, block_prob=0.1, seed=42) -> dict:
    if len(pnl) < 40: return {}
    rng = np.random.default_rng(seed); n = len(pnl)
    sums = np.empty(n_iter)
    for k in range(n_iter):
        idxs = np.empty(n, dtype=np.int64); i = 0
        while i < n:
            start = rng.integers(0, n); blen = rng.geometric(block_prob)
            for b in range(blen):
                if i >= n: break
                idxs[i] = (start + b) % n; i += 1
        sums[k] = pnl[idxs].sum()
    return {
        "sum_ci_lo": round(float(np.quantile(sums, 0.025)), 2),
        "sum_ci_hi": round(float(np.quantile(sums, 0.975)), 2),
    }


def binom_test(sub: pd.DataFrame) -> dict:
    if len(sub) < 30: return {}
    expected_wr = float(sub["entry_vwap"].mean())
    n = len(sub); n_won = int(sub["won"].sum())
    p = float(sstats.binomtest(n_won, n, p=expected_wr,
                                alternative="greater").pvalue)
    return {
        "real_wr_pct":    round(float(sub["won"].mean()) * 100, 2),
        "vwap_implied_wr_pct": round(expected_wr * 100, 2),
        "wr_edge_pp":     round((sub["won"].mean() - expected_wr) * 100, 2),
        "binom_p":        round(p, 6),
    }


def main():
    d = pd.read_parquet(PANEL)
    print(f"[load] panel: {len(d):,} rows")
    g = build_gates(d)

    rows = []
    for label, gates, asset, dev_min, offsets in STRATEGIES:
        # Special handling for REF — also cap dev at 10
        m = apply_strategy(d, g, gates, asset, dev_min, offsets)
        if label.startswith("REF_VWAPcont"):
            m &= (d["dev_bps"].abs() <= 10)
        sub_raw = d[m]
        sub = dedup_to_first_offset(sub_raw)
        if len(sub) < 10:
            print(f"  [{label}] skip — only {len(sub)} after dedup")
            continue
        # Optionally limit BASELINE to a sample to keep csv small
        row = {"label": label,
                "spec": f"asset={asset} dev≥{dev_min} offsets={offsets} gates={'+'.join(gates) if gates else 'none'}",
                "n_raw": int(len(sub_raw))}
        row.update(scorecard(sub))
        row.update(walkforward(sub))
        if len(sub) >= 40:
            row.update(bootstrap_ci(sub["pnl_legacy_usd"].to_numpy()))
        row.update(binom_test(sub))
        rows.append(row)
        print(f"  [{label}] raw n={len(sub_raw):>5} → dedup n={len(sub):>4}  "
              f"WR={row.get('wr_pct',0):.2f}%  sum=${row.get('sum_pnl',0):>+8.2f}  "
              f"$/day={row.get('per_day',0):+.2f}  "
              f"sortino_pt={row.get('sortino_pt',0):+.3f}  "
              f"wf_ret={row.get('wf_ret','—')}  binom_p={row.get('binom_p',1):.4f}")

    out = pd.DataFrame(rows).sort_values("sum_pnl", ascending=False).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n[write] {OUT_CSV}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_colwidth", 110)
    print("\nFull scorecard:")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
