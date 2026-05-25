"""Kelly tier sweep — find the optimal sizing curve on fair_edge_bp + direction."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
P5M = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "kelly_tier_sweep.csv"


def main():
    d = pd.read_parquet(P5M)
    m_s8 = d["macd_agree"].astype(bool) & (d["rvol_30_300"] > 1.2).fillna(False)
    m_s4 = ((d["fair_edge_bp"] > 500).fillna(False) & d["cvd_agree_30s"].astype(bool)
             & (d["dev_bps"].abs() >= 8))
    m = (m_s8 | m_s4) & (d["fire_offset_s"] >= 120)
    sub = (d[m].sort_values(["asset","slug","direction","fire_offset_s"])
              .drop_duplicates(["asset","slug","direction"], keep="first")
              .reset_index(drop=True))
    print(f"BASE_UNION_5m_off120: n={len(sub):,}")

    # ---- Fair-edge tier breakdown ----
    tiers = [(-1e9,0,"<=0bp"), (0,500,"0-500"), (500,1000,"500-1000"),
             (1000,1500,"1000-1500"), (1500,2000,"1500-2000"),
             (2000,3000,"2000-3000"), (3000,5000,"3000-5000"),
             (5000,1e9,">5000")]
    total_pnl = float(sub.pnl_legacy_usd.sum())
    print(f"\nFair-edge tier breakdown ({len(sub):,} fires, total ${total_pnl:.0f}):")
    print(f'{"tier":>12}  {"n":>5}  {"WR":>6}  {"per_tr":>8}  {"sum":>10}  {"%pnl":>6}')
    for lo, hi, lbl in tiers:
        s = sub[(sub.fair_edge_bp > lo) & (sub.fair_edge_bp <= hi)]
        if len(s) == 0: continue
        pn = float(s.pnl_legacy_usd.sum())
        print(f'{lbl:>12}  {len(s):>5}  {s.won.mean()*100:5.1f}%  ${s.pnl_legacy_usd.mean():>7.2f}  ${pn:>9.0f}  {pn/total_pnl*100:>5.1f}%')

    # ---- Kelly schemes ----
    def kelly_test(sub, mult_fn, label):
        mult = sub.apply(mult_fn, axis=1).to_numpy()
        pnl = sub.pnl_legacy_usd.to_numpy() * mult
        n = len(pnl); s = float(pnl.sum())
        days = max(1.0, (sub.fire_us.max() - sub.fire_us.min()) / 1e6 / 86400)
        eff_notional_avg = 25 * float(mult.mean())
        dd = float((np.cumsum(pnl) - np.maximum.accumulate(np.cumsum(pnl))).min())
        # walk-forward
        st = sub.sort_values("fire_us").reset_index(drop=True)
        cut = int(0.7 * len(st)); tr, te = st.iloc[:cut], st.iloc[cut:]
        mtr = tr.apply(mult_fn, axis=1).to_numpy()
        mte = te.apply(mult_fn, axis=1).to_numpy()
        ts = float((tr.pnl_legacy_usd.to_numpy() * mtr).sum())
        es = float((te.pnl_legacy_usd.to_numpy() * mte).sum())
        wf_ret = es / ts if ts != 0 else float("nan")
        return {
            "label": label, "n": n,
            "avg_kelly": round(float(mult.mean()), 3),
            "avg_notional": round(eff_notional_avg, 1),
            "sum_pnl": round(s, 2),
            "per_tr": round(s/n, 3),
            "per_day": round(s/days, 2),
            "max_dd": round(dd, 2),
            "dd_pct_of_sum": round(abs(dd)/s*100, 1) if s>0 else None,
            "wf_ret": round(wf_ret, 2) if np.isfinite(wf_ret) else None,
            "capital_eff_per_$_per_day": round(s/days/eff_notional_avg, 3),
        }

    rows = []
    rows.append(kelly_test(sub, lambda r: 1.0, "BASE_1x"))
    rows.append(kelly_test(sub, lambda r: 1.5 if r.fair_edge_bp > 500 else 1.0, "K1.5_at_500bp"))
    rows.append(kelly_test(sub, lambda r: 2.0 if r.fair_edge_bp > 1000 else 1.0, "K2_at_1000bp"))
    rows.append(kelly_test(sub, lambda r: 2.0 if r.fair_edge_bp > 1500 else 1.0, "K2_at_1500bp"))
    rows.append(kelly_test(sub, lambda r: 3.0 if r.fair_edge_bp > 1500 else 1.0, "K3_at_1500bp"))
    rows.append(kelly_test(sub, lambda r: 3.0 if r.fair_edge_bp > 2000 else 1.0, "K3_at_2000bp"))
    rows.append(kelly_test(sub, lambda r: (3.0 if r.fair_edge_bp > 1500 else
                                            (2.0 if r.fair_edge_bp > 500 else 1.0)),
                            "K_TIERED_500_1500"))
    rows.append(kelly_test(sub, lambda r: (4.0 if r.fair_edge_bp > 2500 else
                                            (2.0 if r.fair_edge_bp > 1000 else 1.0)),
                            "K_TIERED_1000_2500_4x"))
    rows.append(kelly_test(sub, lambda r: (4.0 if r.fair_edge_bp > 3000 else
                                            (3.0 if r.fair_edge_bp > 2000 else
                                              (2.0 if r.fair_edge_bp > 1000 else 1.0))),
                            "K_TIERED_1000_2000_3000"))
    rows.append(kelly_test(sub, lambda r: 1.5 if r.direction=="DOWN" else 1.0,
                            "K1.5_DOWN"))
    rows.append(kelly_test(sub, lambda r: 2.0 if r.direction=="DOWN" else 1.0,
                            "K2_DOWN"))
    rows.append(kelly_test(sub, lambda r: (2.0 if r.fair_edge_bp > 1000 else 1.0)
                                          * (1.5 if r.direction=="DOWN" else 1.0),
                            "K_FAIR_AND_DOWN"))
    # CAUTIOUS Kelly: cap at 2× total
    rows.append(kelly_test(sub, lambda r: min(2.0, (1.5 if r.fair_edge_bp > 500 else 1.0) * (1.5 if r.direction=="DOWN" else 1.0)),
                            "K_FAIR500_DOWN_capped_2x"))

    out = pd.DataFrame(rows).sort_values("per_day", ascending=False).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 300)
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
