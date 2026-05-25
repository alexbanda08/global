"""DOWN-only + late-offset zoom variants.

Tests:
  D-A  S4 DOWN-only, min_offset >= 120 (5m)
  D-B  S8 DOWN-only, min_offset >= 120 (5m)
  D-C  (S4 ∪ S8) DOWN-only (5m + 15m)
  L-A  S4 late-zoom, min_offset >= 240 (5m) — high conviction
  L-B  S8 late-zoom, min_offset >= 240 (5m)
  L-C  S4 ETH 15m, no min-offset (best variant from prior sweep)
  L-D  S4 SOL 15m, min_offset >= 240
  KE-A Kelly-light: bet 2× when fair_edge_bp > 1000
  KE-B Kelly-light asymmetric: bet 2× DOWN signals (since DOWN has higher WR)
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
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "down_only_and_late_zoom.csv"


def s4(d): return ((d["fair_edge_bp"] > 500).fillna(False)
                    & d["cvd_agree_30s"].astype(bool)
                    & (d["dev_bps"].abs() >= 8))
def s8(d): return d["macd_agree"].astype(bool) & (d["rvol_30_300"] > 1.2).fillna(False)
def dedup(sub): return (sub.sort_values(["asset","slug","direction","fire_offset_s"])
                          .drop_duplicates(["asset","slug","direction"], keep="first")
                          .reset_index(drop=True))


def score(sub, label, kelly_mult_col=None):
    if len(sub) < 30: return {"label": label, "n": len(sub)}
    # Apply kelly multiplier to pnl if specified (simulates 2x sizing)
    pnl = sub["pnl_legacy_usd"].to_numpy()
    if kelly_mult_col is not None:
        mult = sub[kelly_mult_col].to_numpy()
        pnl = pnl * mult
    n=len(pnl); wr=float(sub["won"].mean()); s=float(pnl.sum()); pt=s/n
    sd=float(pnl.std(ddof=1)) if n>1 else 0
    loss=pnl[pnl<0]; sd_dn=float(loss.std(ddof=1)) if len(loss)>1 else 0
    sharpe_pt=pt/sd if sd>0 else 0
    sortino_pt=pt/sd_dn if sd_dn>0 else 0
    eq=np.cumsum(pnl); peak=np.maximum.accumulate(eq); dd=float((eq-peak).min())
    span=sub["fire_us"].max()-sub["fire_us"].min()
    days=max(1.0, span/1e6/86400.0)
    tpy=n*365/days; sharpe_ann=sharpe_pt*np.sqrt(tpy)
    py=s*365/days; calmar=py/abs(dd) if dd!=0 else 0
    # walk-forward
    st=sub.sort_values("fire_us").reset_index(drop=True)
    cut=int(0.70*len(st)); tr,te=st.iloc[:cut], st.iloc[cut:]
    if kelly_mult_col is not None:
        ts=float((tr["pnl_legacy_usd"]*tr[kelly_mult_col]).sum())
        es=float((te["pnl_legacy_usd"]*te[kelly_mult_col]).sum())
    else:
        ts=float(tr["pnl_legacy_usd"].sum()); es=float(te["pnl_legacy_usd"].sum())
    wf=es/ts if ts!=0 else float("nan")
    ev=float(sub["entry_vwap"].mean())
    bp=float(sstats.binomtest(int(sub["won"].sum()), n, p=ev, alternative="greater").pvalue)
    return {
        "label": label, "n": n, "days": round(days,1),
        "WR_pct": round(wr*100,2),
        "per_tr": round(pt,3),
        "sum_pnl": round(s,2),
        "per_day": round(s/days,2),
        "sharpe_pt": round(sharpe_pt,3),
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


def main():
    d5 = pd.read_parquet(P5M)
    d15 = pd.read_parquet(P15M)
    print(f"5m: {len(d5):,}, 15m: {len(d15):,}")

    rows = []

    # ============ DOWN-only variants on 5m ============
    DOWN = d5["direction"] == "DOWN"
    UP   = d5["direction"] == "UP"
    off_120 = d5["fire_offset_s"] >= 120

    s4_5 = s4(d5); s8_5 = s8(d5)

    # Baselines (re-confirm)
    rows.append(score(dedup(d5[s4_5 & off_120]), "BASE_S4_5m_off120"))
    rows.append(score(dedup(d5[s8_5 & off_120]), "BASE_S8_5m_off120"))
    rows.append(score(dedup(d5[(s4_5|s8_5) & off_120]), "BASE_UNION_5m_off120"))

    # DOWN-only
    rows.append(score(dedup(d5[s4_5 & off_120 & DOWN]), "D-A_S4_DOWN_5m_off120"))
    rows.append(score(dedup(d5[s8_5 & off_120 & DOWN]), "D-B_S8_DOWN_5m_off120"))
    rows.append(score(dedup(d5[(s4_5|s8_5) & off_120 & DOWN]), "D-C_UNION_DOWN_5m_off120"))

    # UP-only for comparison
    rows.append(score(dedup(d5[s4_5 & off_120 & UP]), "U-A_S4_UP_5m_off120"))
    rows.append(score(dedup(d5[s8_5 & off_120 & UP]), "U-B_S8_UP_5m_off120"))

    # ============ Late-offset zoom 5m ============
    off_240 = d5["fire_offset_s"] >= 240
    off_180 = d5["fire_offset_s"] >= 180
    rows.append(score(dedup(d5[s4_5 & off_180]), "L-A1_S4_5m_off180"))
    rows.append(score(dedup(d5[s4_5 & off_240]), "L-A2_S4_5m_off240"))
    rows.append(score(dedup(d5[s8_5 & off_180]), "L-B1_S8_5m_off180"))
    rows.append(score(dedup(d5[s8_5 & off_240]), "L-B2_S8_5m_off240"))
    rows.append(score(dedup(d5[(s4_5|s8_5) & off_180]), "L-C1_UNION_5m_off180"))
    rows.append(score(dedup(d5[(s4_5|s8_5) & off_240]), "L-C2_UNION_5m_off240"))

    # Late + DOWN
    rows.append(score(dedup(d5[(s4_5|s8_5) & off_240 & DOWN]), "L-D1_UNION_DOWN_5m_off240"))
    rows.append(score(dedup(d5[s4_5 & off_240 & DOWN]), "L-D2_S4_DOWN_5m_off240"))

    # ============ Kelly-light: 2x sizing when fair_edge_bp > 1000 ============
    kelly_2x = (d5["fair_edge_bp"] > 1000).fillna(False)
    d5_kelly = d5.copy()
    d5_kelly["kelly_mult"] = np.where(kelly_2x, 2.0, 1.0)
    sub_kelly = dedup(d5_kelly[s4_5 & off_120])
    rows.append(score(sub_kelly, "KE-A_S4_5m_off120_kelly2x_fairedge1000",
                       kelly_mult_col="kelly_mult"))
    sub_kelly = dedup(d5_kelly[(s4_5|s8_5) & off_120])
    rows.append(score(sub_kelly, "KE-A2_UNION_5m_off120_kelly2x_fairedge1000",
                       kelly_mult_col="kelly_mult"))

    # Kelly asymmetric: bet 2x on DOWN (higher WR)
    d5_kelly_dn = d5.copy()
    d5_kelly_dn["kelly_mult"] = np.where(DOWN, 2.0, 1.0)
    sub = dedup(d5_kelly_dn[s4_5 & off_120])
    rows.append(score(sub, "KE-B_S4_5m_kelly2x_DOWN", kelly_mult_col="kelly_mult"))
    sub = dedup(d5_kelly_dn[(s4_5|s8_5) & off_120])
    rows.append(score(sub, "KE-B2_UNION_5m_kelly2x_DOWN", kelly_mult_col="kelly_mult"))

    # ============ 15m variants ============
    DOWN15 = d15["direction"] == "DOWN"
    s4_15 = s4(d15); s8_15 = s8(d15)
    rows.append(score(dedup(d15[s4_15]), "L-E_S4_ETH_SOL_15m_any_offset"))
    rows.append(score(dedup(d15[s4_15 & (d15["asset"]=="ETH")]),
                       "L-F_S4_ETH_15m_any_off"))
    rows.append(score(dedup(d15[s4_15 & (d15["asset"]=="SOL") & (d15["fire_offset_s"] >= 240)]),
                       "L-G_S4_SOL_15m_off240"))
    rows.append(score(dedup(d15[s4_15 & DOWN15]), "D-E_S4_DOWN_15m_any_offset"))

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 300)
    pd.set_option("display.max_colwidth", 50)
    print(out.sort_values("sum_pnl", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
