"""Extra validation on the trimmed S8+S4 ensemble:
  1. Per-asset breakdown (BTC / ETH / SOL)
  2. Per-fire-offset breakdown
  3. Rolling 5-fold time-series CV (each fold trains on past, tests on future)
  4. Stress test: drop the highest-pnl 5 % of fires and re-score
  5. Direction-asymmetric stats (UP vs DOWN)
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "extra_validation_trimmed.csv"


def trimmed_fires(d):
    m_s8 = d["macd_agree"].astype(bool) & (d["rvol_30_300"] > 1.2).fillna(False)
    m_s4 = ((d["fair_edge_bp"] > 500).fillna(False) & d["cvd_agree_30s"].astype(bool)
             & (d["dev_bps"].abs() >= 8))
    m = m_s8 | m_s4
    sub = d[m].copy()
    sub["rule"] = np.where(m_s4[m].values, "S4", "S8")
    sub = sub.sort_values(["asset","slug","direction","fire_offset_s"])
    sub = sub.drop_duplicates(["asset","slug","direction"], keep="first").reset_index(drop=True)
    return sub


def basic_stats(sub: pd.DataFrame) -> dict:
    if len(sub) < 2:
        return {"n": len(sub), "WR_pct": 0.0, "per_tr": 0.0, "sum_pnl": 0.0}
    pnl = sub["pnl_legacy_usd"].to_numpy()
    n = len(pnl)
    days = max(1.0, (sub.fire_us.max() - sub.fire_us.min()) / 1e6 / 86400)
    return {
        "n": n, "days": round(days, 1),
        "WR_pct": round(float(sub["won"].mean()) * 100, 2),
        "per_tr": round(float(pnl.mean()), 3),
        "sum_pnl": round(float(pnl.sum()), 2),
        "per_day": round(float(pnl.sum()) / days, 2),
        "max_dd": round(float(np.minimum.accumulate(np.cumsum(pnl) -
                          np.maximum.accumulate(np.cumsum(pnl))).min()), 2),
    }


def main():
    d = pd.read_parquet(PANEL)
    sub = trimmed_fires(d)
    print(f"[load] trimmed ensemble: {len(sub):,} fires across "
          f"{sub.fire_us.min()/1e6:.0f} → {sub.fire_us.max()/1e6:.0f}")

    rows = []
    # 1. Per-asset
    print("\n=== Per asset ===")
    for a in ("BTC", "ETH", "SOL"):
        s = sub[sub.asset == a]
        st = basic_stats(s); st["bucket"] = f"asset={a}"; rows.append(st)
        print(f"  {a:3s}  n={st['n']:>5}  WR={st['WR_pct']:5.2f}%  "
              f"sum=${st['sum_pnl']:>+8.2f}  $/day={st['per_day']:>+7.2f}")

    # 2. Per-offset
    print("\n=== Per fire_offset_s ===")
    for off in sorted(sub.fire_offset_s.unique()):
        s = sub[sub.fire_offset_s == off]
        st = basic_stats(s); st["bucket"] = f"offset={off}"; rows.append(st)
        print(f"  off={off:>3d}  n={st['n']:>5}  WR={st['WR_pct']:5.2f}%  "
              f"sum=${st['sum_pnl']:>+8.2f}")

    # 3. Per direction
    print("\n=== Per direction ===")
    for dirn in ("UP", "DOWN"):
        s = sub[sub.direction == dirn]
        st = basic_stats(s); st["bucket"] = f"direction={dirn}"; rows.append(st)
        print(f"  {dirn:5s} n={st['n']:>5}  WR={st['WR_pct']:5.2f}%  "
              f"sum=${st['sum_pnl']:>+8.2f}")

    # 4. Rolling 5-fold time-series CV
    print("\n=== 5-fold rolling time CV ===")
    sub_t = sub.sort_values("fire_us").reset_index(drop=True)
    folds = np.array_split(sub_t, 5)
    for k, f in enumerate(folds):
        st = basic_stats(f); st["bucket"] = f"fold{k+1}of5"; rows.append(st)
        print(f"  fold{k+1}  n={st['n']:>5}  days={st['days']:>4.1f}  "
              f"WR={st['WR_pct']:5.2f}%  sum=${st['sum_pnl']:>+8.2f}  "
              f"$/day={st['per_day']:>+7.2f}")

    # 5. Stress test — drop top 5 % PnL fires (largest single-fire profits)
    cut = sub["pnl_legacy_usd"].quantile(0.95)
    s = sub[sub["pnl_legacy_usd"] <= cut]
    st = basic_stats(s); st["bucket"] = "drop_top5pct_PnL"; rows.append(st)
    print(f"\n=== Stress: drop top 5 % PnL fires ===")
    print(f"  cut at ${cut:.2f}, remaining n={st['n']:,}, sum=${st['sum_pnl']:+.2f}")

    # 6. Stress test — drop bottom 5 % (worst losers)
    cut = sub["pnl_legacy_usd"].quantile(0.05)
    s = sub[sub["pnl_legacy_usd"] >= cut]
    st = basic_stats(s); st["bucket"] = "drop_bottom5pct_PnL"; rows.append(st)
    print(f"  drop bottom 5 %: n={st['n']:,}, sum=${st['sum_pnl']:+.2f}")

    # 7. Per rule (S8 vs S4)
    print("\n=== Per rule (S8 vs S4) ===")
    for r in ("S8", "S4"):
        s = sub[sub.rule == r]
        st = basic_stats(s); st["bucket"] = f"rule={r}"; rows.append(st)
        print(f"  {r}  n={st['n']:>5}  WR={st['WR_pct']:5.2f}%  "
              f"sum=${st['sum_pnl']:>+8.2f}")

    # 8. Per asset × direction
    print("\n=== Per asset × direction ===")
    for a in ("BTC","ETH","SOL"):
        for di in ("UP","DOWN"):
            s = sub[(sub.asset==a) & (sub.direction==di)]
            st = basic_stats(s); st["bucket"] = f"{a}_{di}"; rows.append(st)
            print(f"  {a:3s} {di:4s}  n={st['n']:>5}  WR={st['WR_pct']:5.2f}%  "
                  f"sum=${st['sum_pnl']:>+8.2f}")

    out = pd.DataFrame(rows).reindex(columns=["bucket","n","days","WR_pct",
                                                "per_tr","sum_pnl","per_day","max_dd"])
    out.to_csv(OUT, index=False)
    print(f"\n[write] {OUT}")


if __name__ == "__main__":
    main()
