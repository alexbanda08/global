"""V7 c2 base + V8 new gates one at a time. Find refinements."""
import os
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
UNIV = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
RES = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8\_results")

V7_BASES = [
    ("V7c2_base", 60, ["g_tr_above_ema50", "g_hurst_trending", "g_parent15m_ranging"]),
    ("V7c3_base", 60, ["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_parent15m_ranging"]),
    ("V7c5_base", 60, ["g_tr_above_cloud", "g_hurst_trending", "g_entry_vwap_in_band", "g_parent15m_ranging"]),
]

V8_ADDS = [
    "g_sol_trend_slope_with", "g_2a_btc_sol_trend_with", "g_3a_unanimity_trend",
    "g_tod_asia_morning", "g_tod_european_morning",
    "g_tod_us_afternoon", "g_tod_us_evening", "g_tod_europe_us_window",
    "g_q_prev15m_agrees", "g_q_15m_streak_agrees",
    "g_grandparent_trend_with", "g_grandparent_strong_trend_with", "g_l_mtf_unanimity",
]


def metrics(pnl, won, fire_us):
    if len(pnl) == 0: return None
    pnl_s = pnl
    ord_idx = np.argsort(fire_us); pnl_o = pnl_s[ord_idx]; won_o = won[ord_idx]
    cum = np.cumsum(pnl_o); peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w: cur += 1; mxls = max(mxls, cur)
        else: cur = 0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    return dict(n=len(pnl_s), wr=float(won.mean()), sum=float(pnl_s.sum()),
                dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
                active_days=len(unique_days))


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
    for base_id, offset, base_gates in V7_BASES:
        sub_base = df[df["fire_offset_s"] == offset].copy()
        for g in base_gates:
            sub_base = sub_base[sub_base[g].fillna(0).astype(int) >= 1]
        # Baseline metric
        m_l_b = metrics(sub_base[sub_base["day"].isin(lockbox_days)]["pnl_legacy_usd"].values,
                         sub_base[sub_base["day"].isin(lockbox_days)]["won"].values.astype(bool),
                         sub_base[sub_base["day"].isin(lockbox_days)]["fire_us"].values)
        m_f_b = metrics(sub_base["pnl_legacy_usd"].values, sub_base["won"].values.astype(bool), sub_base["fire_us"].values)
        proj_full_b = (m_f_b["dpt"] * m_f_b["n"] / days_full) * 32.66
        print(f"\n=== {base_id} (offset={offset}, baseline) ===")
        print(f"  lock: n={m_l_b['n']} wr={m_l_b['wr']*100:.1f}% dpt={m_l_b['dpt']:.2f} sum={m_l_b['sum']:.0f} dd={m_l_b['dd']:.0f}")
        print(f"  full: n={m_f_b['n']} wr={m_f_b['wr']*100:.1f}% dpt={m_f_b['dpt']:.2f} sum={m_f_b['sum']:.0f} proj_full={proj_full_b:.0f}")

        for v8 in V8_ADDS:
            sub = sub_base[sub_base[v8].fillna(0).astype(int) >= 1].copy()
            if len(sub) == 0:
                continue
            sub_l = sub[sub["day"].isin(lockbox_days)]
            sub_t = sub[sub["day"].isin(train_days)]
            sub_v = sub[sub["day"].isin(val_days)]
            m_l = metrics(sub_l["pnl_legacy_usd"].values, sub_l["won"].values.astype(bool), sub_l["fire_us"].values)
            m_f = metrics(sub["pnl_legacy_usd"].values, sub["won"].values.astype(bool), sub["fire_us"].values)
            if m_l is None or m_l["n"] < 25: continue
            m_t = metrics(sub_t["pnl_legacy_usd"].values, sub_t["won"].values.astype(bool), sub_t["fire_us"].values) if len(sub_t) else None
            m_v = metrics(sub_v["pnl_legacy_usd"].values, sub_v["won"].values.astype(bool), sub_v["fire_us"].values) if len(sub_v) else None
            proj_32d = (m_l["dpt"] * m_l["n"] / days_l) * 32.66
            proj_full = (m_f["dpt"] * m_f["n"] / days_full) * 32.66 if m_f else 0
            proj_honest = min(proj_32d, proj_full)
            rows.append(dict(
                base=base_id, add=v8, gate_stack="&".join(base_gates + [v8]),
                offset=offset,
                n_train=m_t["n"] if m_t else 0, dpt_train=round(m_t["dpt"], 3) if m_t else 0,
                n_val=m_v["n"] if m_v else 0, dpt_val=round(m_v["dpt"], 3) if m_v else 0,
                n_lockbox=m_l["n"], wr_lockbox=round(m_l["wr"], 4),
                dpt_25_lockbox=round(m_l["dpt"], 3), sum_25_lockbox=round(m_l["sum"], 2),
                dd_25_lockbox=round(m_l["dd"], 2), loss_streak=m_l["loss_streak"],
                n_full=m_f["n"], wr_full=round(m_f["wr"], 4),
                dpt_25_full=round(m_f["dpt"], 3), sum_25_full=round(m_f["sum"], 2),
                proj_32d=round(proj_32d, 2), proj_full=round(proj_full, 2),
                proj_honest=round(proj_honest, 2),
                # delta vs base
                d_n_lock=int(m_l["n"] - m_l_b["n"]),
                d_wr_lock=round(m_l["wr"] - m_l_b["wr"], 4),
                d_dpt_lock=round(m_l["dpt"] - m_l_b["dpt"], 3),
                d_sum_lock=round(m_l["sum"] - m_l_b["sum"], 2),
                d_proj_honest=round(proj_honest - min((m_l_b["dpt"] * m_l_b["n"] / days_l) * 32.66, proj_full_b), 2),
            ))

    out = pd.DataFrame(rows).sort_values("proj_honest", ascending=False)
    out.to_csv(os.path.join(RES, "v7_plus_v8_refinement.csv"), index=False)
    # Show best per base
    for base_id, offset, base_gates in V7_BASES:
        sub = out[out.base == base_id].sort_values("proj_honest", ascending=False).head(8)
        if len(sub) == 0: continue
        print(f"\n--- TOP V8 adds for {base_id} ---")
        print(sub[["add", "n_lockbox", "wr_lockbox", "dpt_25_lockbox", "sum_25_lockbox", "dd_25_lockbox",
                   "n_full", "sum_25_full", "proj_honest", "d_proj_honest"]].to_string())


if __name__ == "__main__":
    main()
