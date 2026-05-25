"""Stack the top 4 rule-based strategies into a non-overlapping portfolio.

For each (asset, slug, direction), fire at the EARLIEST offset where ANY rule
passes. The rule selected becomes the "sleeve" label. Each slug × direction
fires AT MOST ONCE.

Then full robustness battery on the combined fire set.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT_FIRES = ROOT / "data" / "v4" / "canonical" / "_results" / "ensemble_top_fires.csv"
OUT_SCORE = ROOT / "data" / "v4" / "canonical" / "_results" / "ensemble_top_scorecard.csv"


def build_gates(d):
    g = pd.DataFrame(index=d.index)
    g["fair_edge_pos"]    = (d["fair_edge_bp"] > 0).fillna(False)
    g["fair_edge_strong"] = (d["fair_edge_bp"] > 500).fillna(False)
    g["cvd_agree_30s"]    = d["cvd_agree_30s"].astype(bool)
    g["cvd_agree_60s"]    = d["cvd_agree_60s"].astype(bool)
    g["macd_agree"]       = d["macd_agree"].astype(bool)
    g["m5v_pass"]         = d["m5v_pass"].astype(bool)
    g["rvol_elevated"]    = (d["rvol_30_300"] > 1.2).fillna(False)
    return g


# Rules in priority order
RULES = [
    # (label, conds, asset, dev_min, offsets)
    ("S4_fairstrong_cvd30",     ["fair_edge_strong","cvd_agree_30s"],            None, 8, None),
    ("S8_macd_rvolelv",          ["macd_agree","rvol_elevated"],                  None, 0, None),
    ("S3_fairpos_cvd60_macd",    ["fair_edge_pos","cvd_agree_60s","macd_agree"],  None, 0, None),
    ("S15_SOL_fairstrong_cvd60_m5v",["fair_edge_strong","cvd_agree_60s","m5v_pass"], "SOL", 0, None),
]


def main():
    d = pd.read_parquet(PANEL)
    g = build_gates(d)
    print(f"[load] {len(d):,} rows")

    fires = []
    for label, conds, asset, dev_min, offsets in RULES:
        m = pd.Series(True, index=d.index)
        if asset is not None: m &= (d["asset"] == asset)
        if dev_min > 0:        m &= (d["dev_bps"].abs() >= dev_min)
        if offsets is not None: m &= d["fire_offset_s"].isin(offsets)
        for c in conds: m &= g[c]
        sub = d[m].copy()
        sub["rule"] = label
        fires.append(sub)
    cat = pd.concat(fires, ignore_index=True)
    print(f"  raw fires across all rules: {len(cat):,}")

    # Per (asset, slug, direction): pick the FIRE with the EARLIEST offset across all rules
    cat_sorted = cat.sort_values(["asset","slug","direction","fire_offset_s"])
    dedup = cat_sorted.drop_duplicates(["asset","slug","direction"], keep="first")
    print(f"  deduped fires: {len(dedup):,}")
    dedup.to_csv(OUT_FIRES, index=False)
    print(f"  [write] {OUT_FIRES}")

    # Full robustness battery
    def score(sub, label):
        n = len(sub)
        pnl = sub["pnl_legacy_usd"].to_numpy()
        wr = float(sub["won"].mean())
        sum_pnl = float(pnl.sum())
        per_tr = sum_pnl / n
        sd = float(pnl.std(ddof=1)) if n > 1 else 0.0
        loss = pnl[pnl < 0]; sd_dn = float(loss.std(ddof=1)) if len(loss) > 1 else 0.0
        sharpe_pt = per_tr / sd if sd > 0 else 0.0
        sortino_pt = per_tr / sd_dn if sd_dn > 0 else 0.0
        eq = np.cumsum(pnl)
        peak = np.maximum.accumulate(eq)
        dd = float((eq - peak).min())
        span_us = sub["fire_us"].max() - sub["fire_us"].min()
        days = max(1.0, span_us / 1e6 / 86400.0)
        tpy = n * 365.0 / days
        sharpe_ann = sharpe_pt * np.sqrt(tpy)
        pnl_per_year = sum_pnl * 365 / days
        calmar = pnl_per_year / abs(dd) if dd != 0 else 0.0
        # walk-forward
        sub2 = sub.sort_values("fire_us").reset_index(drop=True)
        cut = int(0.7 * len(sub2)); tr = sub2.iloc[:cut]; te = sub2.iloc[cut:]
        wf_ret = float(te["pnl_legacy_usd"].sum()) / float(tr["pnl_legacy_usd"].sum()) if len(tr) > 0 and tr["pnl_legacy_usd"].sum() != 0 else float("nan")
        # binom
        ev = float(sub["entry_vwap"].mean())
        p = float(sstats.binomtest(int(sub["won"].sum()), n, p=ev,
                                    alternative="greater").pvalue) if n >= 30 else 1.0
        # bootstrap on sum
        rng = np.random.default_rng(42); sums = np.empty(2000); bp_geom = 0.1
        if n >= 40:
            for k in range(2000):
                idxs = np.empty(n, dtype=np.int64); i = 0
                while i < n:
                    start = rng.integers(0, n); blen = rng.geometric(bp_geom)
                    for b in range(blen):
                        if i >= n: break
                        idxs[i] = (start + b) % n; i += 1
                sums[k] = pnl[idxs].sum()
            ci_lo = float(np.quantile(sums, 0.025)); ci_hi = float(np.quantile(sums, 0.975))
        else: ci_lo = ci_hi = float("nan")
        return {
            "label": label, "n": n, "days": round(days,1),
            "wr_pct": round(wr*100, 2),
            "per_tr": round(per_tr, 3),
            "sum_pnl": round(sum_pnl, 2),
            "per_day": round(sum_pnl/days, 2),
            "sharpe_pt": round(sharpe_pt, 3),
            "sortino_pt": round(sortino_pt, 3),
            "sharpe_ann": round(sharpe_ann, 2),
            "calmar": round(calmar, 2),
            "max_dd": round(dd, 2),
            "train_wr": round(float(tr["won"].mean())*100, 2),
            "test_wr":  round(float(te["won"].mean())*100, 2),
            "train_sum": round(float(tr["pnl_legacy_usd"].sum()), 2),
            "test_sum":  round(float(te["pnl_legacy_usd"].sum()), 2),
            "wf_ret": round(wf_ret, 2) if np.isfinite(wf_ret) else "—",
            "boot_sum_lo": round(ci_lo, 2),
            "boot_sum_hi": round(ci_hi, 2),
            "real_wr_pct": round(wr*100, 2),
            "vwap_implied_wr_pct": round(ev*100, 2),
            "wr_edge_pp": round((wr - ev)*100, 2),
            "binom_p": round(p, 6),
        }

    rows = [score(dedup, "ENSEMBLE_S4+S8+S3+S15_dedup_first_offset")]
    # also score each rule standalone (deduped)
    for label, conds, asset, dev_min, offsets in RULES:
        m = pd.Series(True, index=d.index)
        if asset is not None: m &= (d["asset"] == asset)
        if dev_min > 0:        m &= (d["dev_bps"].abs() >= dev_min)
        if offsets is not None: m &= d["fire_offset_s"].isin(offsets)
        for c in conds: m &= g[c]
        sub = d[m].copy()
        sub = sub.sort_values(["asset","slug","direction","fire_offset_s"])
        sub = sub.drop_duplicates(["asset","slug","direction"], keep="first")
        rows.append(score(sub, f"STANDALONE_{label}"))
    sc = pd.DataFrame(rows).sort_values("sum_pnl", ascending=False).reset_index(drop=True)
    OUT_SCORE.parent.mkdir(parents=True, exist_ok=True)
    sc.to_csv(OUT_SCORE, index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 90)
    print(sc.to_string(index=False))


if __name__ == "__main__":
    main()
