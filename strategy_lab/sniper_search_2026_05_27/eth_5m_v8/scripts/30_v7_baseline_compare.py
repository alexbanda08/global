"""Reproduce V7 baseline on same 60/20/20 lockbox split as V8 for apples-to-apples comparison."""
import os
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
UNIV = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
RES = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8\_results")

V7_PICKS = [
    ("V7_c1", 60, ["g_tr_above_cloud", "g_entry_vwap_in_band", "g_hurst_mp_trend_with"]),
    ("V7_c2", 60, ["g_tr_above_ema50", "g_hurst_trending", "g_parent15m_ranging"]),
    ("V7_c3", 60, ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_parent15m_ranging"]),
    ("V7_c4", 90, ["g_tr_above_ema200", "g_entry_vwap_in_band", "g_regime_ranging_at_ws", "g_xa_3source_trend_with"]),
    ("V7_c5", 60, ["g_tr_above_cloud", "g_hurst_trending", "g_entry_vwap_in_band", "g_parent15m_ranging"]),
]


def metrics(pnl, won, fire_us, stake=25.0):
    if len(pnl) == 0:
        return None
    pnl_s = pnl * (stake / 25.0)
    ord_idx = np.argsort(fire_us)
    pnl_o = pnl_s[ord_idx]; won_o = won[ord_idx]
    cum = np.cumsum(pnl_o); peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w: cur += 1; mxls = max(mxls, cur)
        else: cur = 0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(day_idx, weights=pnl_s)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(n=len(pnl_s), wr=float(won.mean()), sum=float(pnl_s.sum()),
                dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
                sharpe=float(sharpe), active_days=len(unique_days))


def main():
    df = pd.read_parquet(UNIV)
    df["day"] = pd.to_datetime(df["fire_us"], unit="us").dt.date
    days_sorted = sorted(df["day"].unique())
    n_total = len(days_sorted)
    n_train = int(n_total * 0.60); n_val = int(n_total * 0.20)
    train_days = set(days_sorted[:n_train])
    val_days = set(days_sorted[n_train:n_train + n_val])
    lockbox_days = set(days_sorted[n_train + n_val:])
    days_l = len(lockbox_days); days_full = n_total

    rows = []
    for cand_id, offset, gates in V7_PICKS:
        sub = df[df["fire_offset_s"] == offset].copy()
        for g in gates:
            if g not in sub.columns:
                print(f"  WARN: {cand_id} missing gate {g}")
                sub = sub.iloc[0:0]; break
            sub = sub[sub[g].fillna(0).astype(int) >= 1]
        if len(sub) == 0:
            print(f"!! {cand_id}: 0 rows")
            continue
        sub_l = sub[sub["day"].isin(lockbox_days)]
        m_l = metrics(sub_l["pnl_legacy_usd"].values, sub_l["won"].values.astype(bool), sub_l["fire_us"].values)
        m_f = metrics(sub["pnl_legacy_usd"].values, sub["won"].values.astype(bool), sub["fire_us"].values)
        proj_32d = (m_l["dpt"] * m_l["n"] / days_l) * 32.66 if m_l else 0
        proj_full = (m_f["dpt"] * m_f["n"] / days_full) * 32.66 if m_f else 0
        proj_honest = min(proj_32d, proj_full)
        rows.append(dict(
            cand=cand_id, offset=offset, gate_stack="&".join(gates),
            n_lockbox=m_l["n"] if m_l else 0,
            wr_lockbox=round(m_l["wr"], 4) if m_l else 0.0,
            dpt_25_lockbox=round(m_l["dpt"], 3) if m_l else 0.0,
            sum_25_lockbox=round(m_l["sum"], 2) if m_l else 0.0,
            dd_25_lockbox=round(m_l["dd"], 2) if m_l else 0.0,
            n_full=m_f["n"] if m_f else 0,
            dpt_25_full=round(m_f["dpt"], 3) if m_f else 0.0,
            sum_25_full=round(m_f["sum"], 2) if m_f else 0.0,
            proj_32d=round(proj_32d, 2),
            proj_full=round(proj_full, 2),
            proj_honest=round(proj_honest, 2),
        ))

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(RES, "v7_baseline_in_v8_splits.csv"), index=False)
    print(out.to_string())


if __name__ == "__main__":
    main()
