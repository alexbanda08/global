"""Markov regime-conditional variants of S4 + S8.

Hypotheses tested:
  M-A  S4 only-when both M1V AND M5V agree (regime-stacked)
  M-B  S4 only-when M5V matches BUT m1v does NOT (regime-disagreement = imminent shift)
  M-C  S4 only on STRICT BULL/BEAR (regime ∈ {0, 1}, exclude transitions / sideways)
  M-D  S8 + M1V agree
  M-E  S4 + S8 union × (M1V_pass AND M5V_pass) = double-regime confirmation
  M-F  Asymmetric: BULL regime → UP fires only; BEAR regime → DOWN fires only
  M-G  Recently-shifted regime — fire only when regime changed in last 5 min (proxy: m1v_regime != m5v_regime)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
P5M = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
P15M = ROOT / "data" / "v4" / "canonical" / "_results" / "master_15m_panel.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "markov_conditional_strategies.csv"


def s4_base(d):
    return ((d["fair_edge_bp"] > 500).fillna(False)
            & d["cvd_agree_30s"].astype(bool)
            & (d["dev_bps"].abs() >= 8))


def s8_base(d):
    return d["macd_agree"].astype(bool) & (d["rvol_30_300"] > 1.2).fillna(False)


def dedup(sub):
    return (sub.sort_values(["asset","slug","direction","fire_offset_s"])
              .drop_duplicates(["asset","slug","direction"], keep="first")
              .reset_index(drop=True))


def score(sub, label):
    if len(sub) < 30:
        return {"label": label, "n": len(sub)}
    pnl = sub["pnl_legacy_usd"].to_numpy()
    n = len(pnl); wr = float(sub["won"].mean()); s = float(pnl.sum()); pt = s/n
    sd = float(pnl.std(ddof=1)) if n>1 else 0
    loss = pnl[pnl<0]; sd_dn = float(loss.std(ddof=1)) if len(loss)>1 else 0
    sharpe_pt = pt/sd if sd>0 else 0
    sortino_pt = pt/sd_dn if sd_dn>0 else 0
    eq = np.cumsum(pnl); peak = np.maximum.accumulate(eq)
    dd = float((eq-peak).min())
    span = sub["fire_us"].max() - sub["fire_us"].min()
    days = max(1.0, span/1e6/86400.0)
    tpy = n*365/days; sharpe_ann = sharpe_pt*np.sqrt(tpy)
    py = s*365/days; calmar = py/abs(dd) if dd!=0 else 0
    # walk-forward
    st = sub.sort_values("fire_us").reset_index(drop=True)
    cut = int(0.70*len(st)); tr, te = st.iloc[:cut], st.iloc[cut:]
    ts = float(tr["pnl_legacy_usd"].sum()); es = float(te["pnl_legacy_usd"].sum())
    wf = es/ts if ts!=0 else float("nan")
    # binom
    ev = float(sub["entry_vwap"].mean())
    bp = float(sstats.binomtest(int(sub["won"].sum()), n, p=ev,
                                 alternative="greater").pvalue)
    return {
        "label": label, "n": n, "days": round(days,1),
        "WR_pct": round(wr*100,2),
        "per_tr": round(pt,3),
        "sum_pnl": round(s,2),
        "per_day": round(s/days,2),
        "sharpe_pt": round(sharpe_pt,3),
        "sortino_pt": round(sortino_pt, 3) if sortino_pt < 1e10 else "inf",
        "sharpe_ann": round(sharpe_ann,2),
        "calmar": round(calmar,2),
        "max_dd": round(dd,2),
        "vwap_implied_wr_pct": round(ev*100,2),
        "wr_edge_pp": round((wr-ev)*100,2),
        "binom_p": round(bp,6),
        "wf_ret": round(wf,2) if np.isfinite(wf) else None,
        "train_WR": round(float(tr["won"].mean())*100,2),
        "test_WR": round(float(te["won"].mean())*100,2),
    }


def run_panel(d, tf_label, min_offset):
    rows = []
    base = (d["fire_offset_s"] >= min_offset)
    s4 = s4_base(d) & base
    s8 = s8_base(d) & base

    m1v = d["m1v_pass"].astype(bool)
    m5v = d["m5v_pass"].astype(bool)
    m1f = d["m1f_pass"].astype(bool)
    m5f = d["m5f_pass"].astype(bool)
    m1v_reg = d["m1v_regime"]
    m5v_reg = d["m5v_regime"]

    # Baselines for comparison
    rows.append(score(dedup(d[s4]), f"BASE_S4_{tf_label}"))
    rows.append(score(dedup(d[s8]), f"BASE_S8_{tf_label}"))
    rows.append(score(dedup(d[s4|s8]), f"BASE_S4∪S8_{tf_label}"))

    # M-A: S4 + both M1V & M5V pass
    rows.append(score(dedup(d[s4 & m1v & m5v]), f"M-A_S4+M1V+M5V_{tf_label}"))

    # M-B: S4 + M5V passes but M1V doesn't (regime disagreement = imminent shift, expected to FAIL but worth testing)
    rows.append(score(dedup(d[s4 & m5v & ~m1v]), f"M-B_S4+M5V+~M1V_{tf_label}"))

    # M-C: S4 + strict regime (regime ∈ {0, 1}, exclude -1 = unknown / sideways)
    rows.append(score(dedup(d[s4 & m5v_reg.isin([0, 1]) & m1v_reg.isin([0, 1])]),
                       f"M-C_S4+strict_regime_{tf_label}"))

    # M-D: S8 + M1V
    rows.append(score(dedup(d[s8 & m1v]), f"M-D_S8+M1V_{tf_label}"))
    rows.append(score(dedup(d[s8 & m5v]), f"M-D2_S8+M5V_{tf_label}"))

    # M-E: union × (M1V & M5V both pass)
    rows.append(score(dedup(d[(s4|s8) & m1v & m5v]), f"M-E_(S4∪S8)+M1V+M5V_{tf_label}"))

    # M-F: Asymmetric (BULL regime → UP only; BEAR regime → DOWN only)
    bull_up = (m1v_reg == 1) & (d["direction"] == "UP")
    bear_dn = (m1v_reg == 0) & (d["direction"] == "DOWN")
    asy = bull_up | bear_dn
    rows.append(score(dedup(d[s4 & asy]), f"M-F_S4+asymmetric_M1V_{tf_label}"))
    rows.append(score(dedup(d[s8 & asy]), f"M-F2_S8+asymmetric_M1V_{tf_label}"))
    rows.append(score(dedup(d[(s4|s8) & asy]), f"M-F3_(S4∪S8)+asymmetric_M1V_{tf_label}"))

    # M-G: Recent regime shift proxy — M1V != M5V (fast regime diverges from slow)
    regime_shift = (m1v_reg != m5v_reg) & m1v_reg.isin([0,1]) & m5v_reg.isin([0,1])
    rows.append(score(dedup(d[s4 & regime_shift]), f"M-G_S4+regime_shift_{tf_label}"))
    rows.append(score(dedup(d[s8 & regime_shift]), f"M-G2_S8+regime_shift_{tf_label}"))

    # Use M1F (fixed) instead of M1V for comparison
    rows.append(score(dedup(d[s4 & m1f]), f"M-H_S4+M1F_{tf_label}"))
    rows.append(score(dedup(d[s8 & m1f]), f"M-H2_S8+M1F_{tf_label}"))

    return rows


def main():
    all_rows = []
    print("[5m]")
    d5 = pd.read_parquet(P5M)
    all_rows.extend(run_panel(d5, "5m", min_offset=120))
    print(f"  5m panel: {len(d5):,} fires, {len(all_rows)} configs")

    print("[15m]")
    d15 = pd.read_parquet(P15M)
    all_rows.extend(run_panel(d15, "15m", min_offset=240))
    print(f"  15m panel: {len(d15):,} fires, cumulative {len(all_rows)} configs")

    out = pd.DataFrame(all_rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"\n[write] {OUT}")
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 270)
    pd.set_option("display.max_colwidth", 60)
    # sort by sum_pnl
    print(out.sort_values("sum_pnl", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
