"""Per-sleeve × per-asset × per-timeframe scorecard.

Loads both master_5m_panel.parquet and master_15m_panel.parquet, applies S8 / S4
with timeframe-appropriate min_offset, deduplicates per (slug, direction),
runs full robustness battery per (rule × asset × tf) cell.

5m: min_offset = 120s (40 % of 300s slot)
15m: min_offset = 360s (40 % of 900s slot)
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
P5M  = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
P15M = ROOT / "data" / "v4" / "canonical" / "_results" / "master_15m_panel.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "per_sleeve_per_asset_tf.csv"

MIN_OFFSET = {"5m": 120, "15m": 360}


def s8_mask(d):
    return d["macd_agree"].astype(bool) & (d["rvol_30_300"] > 1.2).fillna(False)


def s4_mask(d):
    return ((d["fair_edge_bp"] > 500).fillna(False) & d["cvd_agree_30s"].astype(bool)
            & (d["dev_bps"].abs() >= 8))


def scorecard(sub: pd.DataFrame, label: str) -> dict:
    if len(sub) == 0:
        return {"label": label, "n": 0}
    pnl = sub["pnl_legacy_usd"].to_numpy()
    n = len(pnl); wr = float(sub["won"].mean()); s = float(pnl.sum()); per_tr = s/n
    sd = float(pnl.std(ddof=1)) if n>1 else 0.0
    loss = pnl[pnl<0]; sd_dn = float(loss.std(ddof=1)) if len(loss)>1 else 0.0
    sharpe_pt = per_tr/sd if sd>0 else 0; sortino_pt = per_tr/sd_dn if sd_dn>0 else 0
    eq = np.cumsum(pnl); peak = np.maximum.accumulate(eq); dd = float((eq-peak).min())
    span = sub["fire_us"].max() - sub["fire_us"].min()
    days = max(1.0, span/1e6/86400.0)
    tpy = n*365/days; sharpe_ann = sharpe_pt*np.sqrt(tpy)
    py = s*365/days; calmar = py/abs(dd) if dd!=0 else 0
    # walk-forward
    sub_t = sub.sort_values("fire_us").reset_index(drop=True)
    cut = int(0.70*len(sub_t)); tr, te = sub_t.iloc[:cut], sub_t.iloc[cut:]
    ts = float(tr["pnl_legacy_usd"].sum()); es = float(te["pnl_legacy_usd"].sum())
    wf_ret = es/ts if ts!=0 else float("nan")
    # binom
    ev = float(sub["entry_vwap"].mean())
    bp = float(sstats.binomtest(int(sub["won"].sum()), n, p=ev,
                                 alternative="greater").pvalue) if n>=30 else 1.0
    # bootstrap
    if n>=40:
        rng=np.random.default_rng(42); sums=np.empty(2000)
        for k in range(2000):
            idxs=np.empty(n,dtype=np.int64); i=0
            while i<n:
                start=rng.integers(0,n); blen=rng.geometric(0.1)
                for b in range(blen):
                    if i>=n: break
                    idxs[i]=(start+b)%n; i+=1
            sums[k]=pnl[idxs].sum()
        ci_lo=float(np.quantile(sums,0.025)); ci_hi=float(np.quantile(sums,0.975))
    else: ci_lo=ci_hi=float("nan")
    # direction
    up = sub[sub["direction"]=="UP"]; dn = sub[sub["direction"]=="DOWN"]
    up_wr = float(up["won"].mean()) if len(up)>0 else 0
    dn_wr = float(dn["won"].mean()) if len(dn)>0 else 0
    # daily
    sub_d = sub.copy()
    sub_d["date"] = pd.to_datetime(sub_d["fire_us"], unit="us", utc=True).dt.date
    daily = sub_d.groupby("date")["pnl_legacy_usd"].sum()
    pct_prof = float((daily>0).mean())*100 if len(daily)>0 else 0
    return {
        "label": label, "n": n, "days_traded": int(len(daily)),
        "WR_pct": round(wr*100,2),
        "per_tr": round(per_tr,3),
        "sum_pnl": round(s,2),
        "per_day": round(s/days,2),
        "sharpe_pt": round(sharpe_pt,3),
        "sharpe_ann": round(sharpe_ann,2),
        "calmar": round(calmar,2),
        "max_dd": round(dd,2),
        "vwap_implied_wr_pct": round(ev*100,2),
        "wr_edge_pp": round((wr-ev)*100,2),
        "binom_p": round(bp,6),
        "boot_sum_lo": round(ci_lo,2),
        "boot_sum_hi": round(ci_hi,2),
        "train_n": int(len(tr)), "test_n": int(len(te)),
        "train_WR": round(float(tr["won"].mean())*100,2) if len(tr) else 0,
        "test_WR": round(float(te["won"].mean())*100,2) if len(te) else 0,
        "train_sum": round(ts,2), "test_sum": round(es,2),
        "wf_ret": round(wf_ret,2) if np.isfinite(wf_ret) else None,
        "n_UP": int(len(up)), "n_DOWN": int(len(dn)),
        "UP_WR_pct": round(up_wr*100,2), "DOWN_WR_pct": round(dn_wr*100,2),
        "UP_sum": round(float(up["pnl_legacy_usd"].sum()),2) if len(up)>0 else 0,
        "DOWN_sum": round(float(dn["pnl_legacy_usd"].sum()),2) if len(dn)>0 else 0,
        "pct_profitable_days": round(pct_prof,1),
    }


def dedup(sub):
    return (sub.sort_values(["asset","slug","direction","fire_offset_s"])
              .drop_duplicates(["asset","slug","direction"], keep="first")
              .reset_index(drop=True))


def main():
    rows = []
    panels = {"5m": pd.read_parquet(P5M), "15m": pd.read_parquet(P15M)}
    for tf, d in panels.items():
        print(f"[{tf}] panel: {len(d):,} fires")
        minoff = MIN_OFFSET[tf]
        m_s8 = s8_mask(d) & (d["fire_offset_s"] >= minoff)
        m_s4 = s4_mask(d) & (d["fire_offset_s"] >= minoff)
        for asset in ("BTC","ETH","SOL"):
            s_s8 = dedup(d[m_s8 & (d["asset"]==asset)])
            s_s4 = dedup(d[m_s4 & (d["asset"]==asset)])
            s_un = dedup(d[(m_s8|m_s4) & (d["asset"]==asset)])
            rows.append(scorecard(s_s8, f"S8_{asset}_{tf}"))
            rows.append(scorecard(s_s4, f"S4_{asset}_{tf}"))
            rows.append(scorecard(s_un, f"S8+S4_{asset}_{tf}_union"))
    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n[write] {OUT_CSV}")
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 260)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
