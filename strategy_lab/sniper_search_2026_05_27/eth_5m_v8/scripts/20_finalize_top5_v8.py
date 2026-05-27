"""V8 ETH 5m: finalize top 5 candidates, generate per-fire details, cumulative PnL plots.

Top 5 = highest proj_honest per V8 path family + one V7 reference (best honest).
Reproduce full per-split metrics, save lockbox fires per candidate, plot cumulative PnL.
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
UNIV = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
RES = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8\_results")
PLOT_DIR = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8")
RANKED = os.path.join(RES, "v8_ranked.csv")
OUT_TOP5 = os.path.join(RES, "top_5_candidates_v8.csv")


# Top 5 hand-picked by V8 path (one per path) — sourced from 16_v8_new_analysis output
TOP5_PICKS = [
    ("c1_pathL_grandparent",   60, ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with"],
     "Path L 1h grandparent: ETH 5m sniper aligned with 4-bar 15m trend"),
    ("c2_pathK_TOD_eu_us",    120, ["g_hurst_trend_with", "g_trend_slope_with", "g_cci_with", "g_tod_europe_us_window"],
     "Path K TOD: confluence + cci + restrict to 07-19 UTC active session"),
    ("c3_pathQ_prev15m",       60, ["g_tr_above_ema50", "g_trend_slope_with", "g_q_prev15m_agrees"],
     "Path Q: 5m fire + previous 15m slot winner agrees with direction"),
    ("c4_pathJ_sol_xa",        90, ["g_tr_above_ema50", "g_parent15m_ranging", "g_trend_slope_with", "g_sol_trend_slope_with"],
     "Path J 2-asset confluence: ETH + SOL trends agree + parent 15m ranging"),
    ("c5_pathL_mtf_unanimity", 60, ["g_tr_above_ema50", "g_hurst_trend_with", "g_grandparent_trend_with", "g_q_prev15m_agrees"],
     "Path L+Q: 1h grandparent trend AND prev 15m winner agrees (deep MTF)"),
]


def metrics(pnl, won, fire_us, stake=25.0):
    if len(pnl) == 0:
        return None
    pnl_s = pnl * (stake / 25.0)
    ord_idx = np.argsort(fire_us)
    pnl_o = pnl_s[ord_idx]
    won_o = won[ord_idx]
    cum = np.cumsum(pnl_o)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w:
            cur += 1; mxls = max(mxls, cur)
        else:
            cur = 0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(day_idx, weights=pnl_s)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(n=len(pnl_s), wr=float(won.mean()), sum=float(pnl_s.sum()),
                dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
                sharpe=float(sharpe), active_days=len(unique_days))


def bootstrap_p(pnl, fire_us, n_iter=500, seed=42):
    if len(pnl) < 5 or pnl.mean() <= 0:
        return 1.0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    unique_days, day_idx = np.unique(days_arr, return_inverse=True)
    if len(unique_days) < 2:
        return 1.0
    day_pnls = [pnl[day_idx == i] for i in range(len(unique_days))]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, len(day_pnls), size=len(day_pnls))
        means[i] = np.concatenate([day_pnls[j] for j in idx]).mean()
    return float((means <= 0).mean())


def main():
    print(f"Loading {UNIV}")
    df = pd.read_parquet(UNIV)
    df["day"] = pd.to_datetime(df["fire_us"], unit="us").dt.date

    days_sorted = sorted(df["day"].unique())
    n_total = len(days_sorted)
    n_train = int(n_total * 0.60); n_val = int(n_total * 0.20)
    train_days = set(days_sorted[:n_train])
    val_days = set(days_sorted[n_train:n_train + n_val])
    lockbox_days = set(days_sorted[n_train + n_val:])
    days_l = len(lockbox_days); days_v = len(val_days); days_t = len(train_days); days_full = n_total
    print(f"train={days_t}d val={days_v}d lockbox={days_l}d full={days_full}d")
    print(f"lockbox span: {min(lockbox_days)} -> {max(lockbox_days)}")

    rows_out = []
    for cand_id, offset, gates, note in TOP5_PICKS:
        sub = df[df["fire_offset_s"] == offset].copy()
        for g in gates:
            sub = sub[sub[g].fillna(0).astype(int) >= 1]
        sub = sub.copy()
        if len(sub) == 0:
            print(f"!! {cand_id} returned 0 fires")
            continue

        sub_t = sub[sub["day"].isin(train_days)]
        sub_v = sub[sub["day"].isin(val_days)]
        sub_l = sub[sub["day"].isin(lockbox_days)]

        m_t = metrics(sub_t["pnl_legacy_usd"].values, sub_t["won"].values.astype(bool), sub_t["fire_us"].values)
        m_v = metrics(sub_v["pnl_legacy_usd"].values, sub_v["won"].values.astype(bool), sub_v["fire_us"].values)
        m_l = metrics(sub_l["pnl_legacy_usd"].values, sub_l["won"].values.astype(bool), sub_l["fire_us"].values)
        m_f = metrics(sub["pnl_legacy_usd"].values, sub["won"].values.astype(bool), sub["fire_us"].values)
        bp_l = bootstrap_p(sub_l["pnl_legacy_usd"].values, sub_l["fire_us"].values)

        proj_32d  = (m_l["dpt"] * m_l["n"] / days_l) * 32.66 if m_l else 0.0
        proj_full = (m_f["dpt"] * m_f["n"] / days_full) * 32.66 if m_f else 0.0
        proj_honest = min(proj_32d, proj_full)

        rows_out.append(dict(
            cand=cand_id, offset=offset, depth=len(gates), gate_stack="&".join(gates),
            n_train=m_t["n"] if m_t else 0,
            wr_train=round(m_t["wr"], 4) if m_t else 0.0,
            dpt_25_train=round(m_t["dpt"], 3) if m_t else 0.0,
            sum_25_train=round(m_t["sum"], 2) if m_t else 0.0,
            n_val=m_v["n"] if m_v else 0,
            wr_val=round(m_v["wr"], 4) if m_v else 0.0,
            dpt_25_val=round(m_v["dpt"], 3) if m_v else 0.0,
            sum_25_val=round(m_v["sum"], 2) if m_v else 0.0,
            n_lockbox=m_l["n"] if m_l else 0,
            wr_lockbox=round(m_l["wr"], 4) if m_l else 0.0,
            dpt_25_lockbox=round(m_l["dpt"], 3) if m_l else 0.0,
            sum_25_lockbox=round(m_l["sum"], 2) if m_l else 0.0,
            dd_25_lockbox=round(m_l["dd"], 2) if m_l else 0.0,
            loss_streak=m_l["loss_streak"] if m_l else 0,
            sharpe=round(m_l["sharpe"], 3) if m_l else 0.0,
            active_days_lockbox=m_l["active_days"] if m_l else 0,
            bootstrap_p_lockbox=round(bp_l, 4),
            n_full=m_f["n"] if m_f else 0,
            wr_full=round(m_f["wr"], 4) if m_f else 0.0,
            dpt_25_full=round(m_f["dpt"], 3) if m_f else 0.0,
            sum_25_full=round(m_f["sum"], 2) if m_f else 0.0,
            proj_32d=round(proj_32d, 2),
            proj_full=round(proj_full, 2),
            proj_honest=round(proj_honest, 2),
            note=note,
        ))

        # save fires
        sub_save = sub[["slug", "ws_s", "fire_us", "fire_offset_s", "direction", "won",
                         "entry_vwap", "pnl_legacy_usd"]].copy()
        sub_save["day"] = pd.to_datetime(sub_save["fire_us"], unit="us").dt.date
        sub_save["split"] = sub_save["day"].apply(
            lambda d: "train" if d in train_days else ("val" if d in val_days else "lockbox"))
        sub_save.to_csv(os.path.join(RES, f"fires_v8_{cand_id}.csv"), index=False)

        # plot cumulative PnL
        s = sub.sort_values("fire_us").copy()
        s["cum"] = s["pnl_legacy_usd"].cumsum()
        s["dt"] = pd.to_datetime(s["fire_us"], unit="us", utc=True)
        fig, ax = plt.subplots(figsize=(13, 5))
        for split_name, days_set, color in [("train", train_days, "tab:blue"),
                                              ("val", val_days, "tab:orange"),
                                              ("lockbox", lockbox_days, "tab:green")]:
            ss = s[pd.to_datetime(s["fire_us"], unit="us").dt.date.isin(days_set)]
            if len(ss) == 0:
                continue
            ax.plot(ss["dt"], ss["cum"], color=color, label=f"{split_name} (n={len(ss)})", linewidth=1.6)
        ax.axhline(0, color="grey", linewidth=0.5)
        ax.set_title(f"V8 ETH 5m | {cand_id}\n{'&'.join(gates)} @ off={offset}\n"
                     f"lockbox: WR={m_l['wr']*100:.1f}% $/tr={m_l['dpt']:.2f} sum=${m_l['sum']:.0f} DD=${m_l['dd']:.0f} proj_honest=${proj_honest:.0f}")
        ax.set_ylabel("cumulative PnL ($)")
        ax.set_xlabel("fire time")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plot_path = os.path.join(PLOT_DIR, f"cumulative_pnl_v8_{cand_id}.png")
        fig.savefig(plot_path, dpi=110)
        plt.close(fig)
        print(f"saved {plot_path}")

    out = pd.DataFrame(rows_out)
    out.to_csv(OUT_TOP5, index=False)
    print(f"\nTop 5 written -> {OUT_TOP5}")
    print(out[["cand", "offset", "depth", "n_lockbox", "wr_lockbox",
               "dpt_25_lockbox", "sum_25_lockbox", "dd_25_lockbox",
               "n_full", "dpt_25_full", "sum_25_full",
               "proj_32d", "proj_full", "proj_honest"]].to_string())


if __name__ == "__main__":
    main()
