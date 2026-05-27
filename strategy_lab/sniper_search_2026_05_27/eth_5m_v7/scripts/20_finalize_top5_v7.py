"""Finalize V7 ETH 5m top 5 candidates.

Pick diverse top 5 from v7_top30_unique:
- c1: BEST $/TR — g_tr_above_cloud & g_entry_vwap_in_band & g_hurst_mp_trend_with (Path H)
- c2: BEST SUM — g_tr_above_ema50 & g_hurst_trending & g_parent15m_ranging (Path F)
- c3: V6 c3 + V7 lift — g_tr_above_cloud & g_ribbon_agrees & g_mp_skew_with & g_hurst_trending & g_parent15m_ranging
- c4: BEST BTC-CROSS — g_tr_above_ema200 & g_entry_vwap_in_band & g_regime_ranging_at_ws & g_xa_3source_trend_with (Path C/F combo)
- c5: BALANCED — g_tr_above_cloud & g_hurst_trending & g_entry_vwap_in_band & g_parent15m_ranging

For each:
- Reconstruct fires from V7 universe
- Compute train/val/lockbox metrics @ const $25
- Cumulative PnL plot
- Save fires_lockbox CSV
"""
import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
UNIV = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet")
RES = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7/_results")
PLOT_DIR = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7")
os.makedirs(RES, exist_ok=True)

TOP5 = [
    dict(
        sleeve_id="v7_c1_off60_cloud_vwap_hurst_mp",
        offset=60,
        gates=["g_tr_above_cloud", "g_entry_vwap_in_band", "g_hurst_mp_trend_with"],
        v7_path="H (hurst x mp_skew direction-aware)",
        rationale="Best $/tr +$14 — direction-aware hurst+mp combined with cloud filter and vwap band",
    ),
    dict(
        sleeve_id="v7_c2_off60_ema50_hurst_parent_ranging",
        offset=60,
        gates=["g_tr_above_ema50", "g_hurst_trending", "g_parent15m_ranging"],
        v7_path="F (15m parent ranging confluence)",
        rationale="Best sum_28d $2,908 — ETH 5m winners inside a 15m ranging parent",
    ),
    dict(
        sleeve_id="v7_c3_off60_v6c3_plus_parent_ranging",
        offset=60,
        gates=["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending", "g_parent15m_ranging"],
        v7_path="F (V6 c3 base + parent ranging filter)",
        rationale="V6 c3 winner enhanced with V7 parent-ranging filter — quality > quantity",
    ),
    dict(
        sleeve_id="v7_c4_off90_xa_3source_parent_ranging",
        offset=90,
        gates=["g_tr_above_ema200", "g_entry_vwap_in_band", "g_regime_ranging_at_ws", "g_xa_3source_trend_with"],
        v7_path="C+F (cross-asset 3-source + parent ranging)",
        rationale="BTC + ETH + 15m trend unanimity — high-$/tr signal at offset=90",
    ),
    dict(
        sleeve_id="v7_c5_off60_cloud_hurst_vwap_parent",
        offset=60,
        gates=["g_tr_above_cloud", "g_hurst_trending", "g_entry_vwap_in_band", "g_parent15m_ranging"],
        v7_path="F+H (cloud + hurst + parent ranging + vwap band)",
        rationale="Highest objective among balanced 4-gate sleeves",
    ),
]


def metrics(pnl, won, fire_us, stake=25.0):
    if len(pnl) == 0:
        return dict(n=0, wr=0, sum=0, dpt=0, dd=0, loss_streak=0, sharpe=0, active_days=0)
    s = stake / 25.0
    pnl_s = pnl * s
    ord_idx = np.argsort(fire_us)
    pnl_o = pnl_s[ord_idx]
    won_o = won[ord_idx]
    cum = np.cumsum(pnl_o)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cur, mxls = 0, 0
    for w in won_o:
        if not w:
            cur += 1
            mxls = max(mxls, cur)
        else:
            cur = 0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    uniq, idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(idx, weights=pnl_s)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(
        n=int(len(pnl_s)), wr=float(won.mean()), sum=float(pnl_s.sum()),
        dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
        sharpe=float(sharpe), active_days=int(len(uniq)),
    )


def bootstrap_p(pnl, fire_us, n_iter=1000, seed=42):
    if len(pnl) < 5:
        return 1.0
    if pnl.mean() <= 0:
        return 1.0
    days_arr = (fire_us // 86_400_000_000).astype(np.int64)
    uniq, idx = np.unique(days_arr, return_inverse=True)
    if len(uniq) < 2:
        return 1.0
    by_day = [pnl[idx == i] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        sel = rng.integers(0, len(by_day), size=len(by_day))
        means[i] = np.concatenate([by_day[j] for j in sel]).mean()
    return float((means <= 0).mean())


def main():
    print(f"Loading {UNIV}")
    df = pd.read_parquet(UNIV)
    df["day"] = pd.to_datetime(df["fire_us"], unit="us").dt.date
    days_sorted = sorted(df["day"].unique())
    n_lockbox = max(4, int(len(days_sorted) * 0.15))
    n_val = max(4, int(len(days_sorted) * 0.18))
    lockbox = set(days_sorted[-n_lockbox:])
    val = set(days_sorted[-(n_lockbox + n_val):-n_lockbox])
    train = set(days_sorted[:-(n_lockbox + n_val)])
    print(f"  train={len(train)}d, val={len(val)}d, lockbox={len(lockbox)}d")

    rows = []
    for sl in TOP5:
        offset = sl["offset"]
        gates = sl["gates"]
        print(f"\n=== {sl['sleeve_id']} (off={offset}) ===")
        print(f"  gates: {gates}")
        pool = df[df["fire_offset_s"] == offset].copy()
        m = np.ones(len(pool), dtype=bool)
        for g in gates:
            if g not in pool.columns:
                print(f"  MISSING gate {g}")
                continue
            m &= (pool[g].fillna(0).astype(float).values >= 1.0)
        gated = pool[m].copy().reset_index(drop=True)
        if len(gated) == 0:
            print("  EMPTY")
            continue
        gt = gated[gated["day"].isin(train)]
        gv = gated[gated["day"].isin(val)]
        gl = gated[gated["day"].isin(lockbox)]
        mt = metrics(gt["pnl_legacy_usd"].values, gt["won"].values.astype(bool), gt["fire_us"].values)
        mv = metrics(gv["pnl_legacy_usd"].values, gv["won"].values.astype(bool), gv["fire_us"].values)
        ml = metrics(gl["pnl_legacy_usd"].values, gl["won"].values.astype(bool), gl["fire_us"].values)
        bp = bootstrap_p(gl["pnl_legacy_usd"].values, gl["fire_us"].values)
        print(f"  TRAIN n={mt['n']} WR={mt['wr']:.3f} dpt=${mt['dpt']:.2f}")
        print(f"  VAL   n={mv['n']} WR={mv['wr']:.3f} dpt=${mv['dpt']:.2f}")
        print(f"  LOCK  n={ml['n']} WR={ml['wr']:.3f} dpt=${ml['dpt']:.2f} sum=${ml['sum']:.2f} dd=${ml['dd']:.2f} ls={ml['loss_streak']} sharpe={ml['sharpe']:.2f} bp={bp:.4f}")

        sum_28d = mt["sum"] + mv["sum"] + ml["sum"]
        rows.append(dict(
            sleeve_id=sl["sleeve_id"],
            anchor=f"offset_{offset}s",
            gate_stack="&".join(gates),
            v7_path=sl["v7_path"],
            n_train=mt["n"], n_val=mv["n"], n_lockbox=ml["n"],
            wr_train=round(mt["wr"], 4), wr_val=round(mv["wr"], 4), wr_lockbox=round(ml["wr"], 4),
            dpt_25_train=round(mt["dpt"], 3), dpt_25_val=round(mv["dpt"], 3), dpt_25_lockbox=round(ml["dpt"], 3),
            sum_lockbox_25=round(ml["sum"], 2), sum_28d_const=round(sum_28d, 2),
            max_dd_25=round(ml["dd"], 2), loss_streak=ml["loss_streak"],
            sharpe=round(ml["sharpe"], 2), bootstrap_p_lockbox=round(bp, 4),
            objective=round(ml["dpt"] * np.sqrt(ml["n"]), 3),
            v7_path_summary=sl["v7_path"], rationale=sl["rationale"],
        ))

        # Save lockbox fires
        gl_sorted = gl.sort_values("fire_us").copy()
        gl_sorted["cum_pnl_25"] = gl_sorted["pnl_legacy_usd"].cumsum()
        gl_sorted[["slug", "fire_us", "fire_offset_s", "direction", "entry_vwap",
                    "won", "pnl_legacy_usd", "cum_pnl_25"]].to_csv(
            os.path.join(RES, f"lockbox_fires_{sl['sleeve_id']}.csv"), index=False)

        # Plot — cumulative PnL across full 33d
        gated_sorted = gated.sort_values("fire_us").copy()
        gated_sorted["cum_pnl_25"] = gated_sorted["pnl_legacy_usd"].cumsum()
        gated_sorted["split"] = "train"
        gated_sorted.loc[gated_sorted["day"].isin(val), "split"] = "val"
        gated_sorted.loc[gated_sorted["day"].isin(lockbox), "split"] = "lockbox"
        plot_path = os.path.join(PLOT_DIR, f"cumulative_pnl_{sl['sleeve_id']}.png")
        fig, ax = plt.subplots(figsize=(11, 6))
        x = np.arange(len(gated_sorted))
        for split, color in [("train", "tab:blue"), ("val", "tab:orange"), ("lockbox", "tab:green")]:
            mask = (gated_sorted["split"] == split).values
            if mask.sum() > 0:
                ax.plot(x[mask], gated_sorted["cum_pnl_25"].values[mask], label=split, color=color, linewidth=1.7)
        ax.set_title(f"{sl['sleeve_id']} (off={offset}) — const $25 cumulative PnL (33d)\n"
                     f"Gates: {' & '.join(gates)}\n"
                     f"Lockbox: n={ml['n']} WR={ml['wr']*100:.1f}% dpt=${ml['dpt']:.2f} sum=${ml['sum']:.0f} DD=${ml['dd']:.0f}")
        ax.set_xlabel("Fire # (chronological)")
        ax.set_ylabel("Cumulative PnL ($)")
        ax.axhline(0, color="black", lw=0.5, ls="--")
        ax.legend()
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_path, dpi=100)
        plt.close()
        print(f"  -> {plot_path}")

    out_csv = os.path.join(RES, "top_5_candidates_v7.csv")
    df_rows = pd.DataFrame(rows)
    df_rows.to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}")
    print(df_rows.to_string())


if __name__ == "__main__":
    main()
