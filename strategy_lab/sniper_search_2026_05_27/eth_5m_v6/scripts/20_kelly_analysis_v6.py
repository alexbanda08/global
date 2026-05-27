"""V6 Kelly analysis + report generation for ETH 5m.

For each top sleeve:
1. Reconstruct gated fires from universe parquet
2. Build conviction buckets by # of optional gates passing
3. Compute empirical WR per bucket -> Kelly-25 stake recommendation
4. Simulate variable-stake PnL vs constant $25 PnL on lockbox
5. Generate cumulative_pnl_kelly_vs_const PNG per sleeve
6. Write top_5_candidates_v6.csv + kelly_stake_table_{sleeve_id}.csv

Conviction method = Option B: empirical WR per gate-count bucket
"""
import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
UNIV = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet")
V6_VALID = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v6/_results/v6_validated.csv")
RES_DIR = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v6/_results")
PLOT_DIR = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v6")
os.makedirs(RES_DIR, exist_ok=True)

STAKE_MIN = 5.0
STAKE_MAX = 25.0

# Top-5 picks (diverse gate stacks, all from V6 strong-survivor pool).
# Each "extra_atoms" list provides optional gates for conviction scoring
# (those NOT in the main stack but that, if passing, indicate higher conviction).
TOP5 = [
    dict(
        sleeve_id="v6_c1_off60_hurst_mpskew_bb_band",
        offset=60,
        required=["g_bb_pos_with", "g_mp_skew_with", "g_hurst_trending", "g_entry_vwap_in_band"],
        extra=[
            "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_cloud", "g_tr_stack_with",
            "g_ribbon_agrees", "g_rf_with", "g_cci_with",
            "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
            "g_tr_in_active_session", "g_regime_ranging_at_ws",
        ],
    ),
    dict(
        sleeve_id="v6_c2_off60_hurst_mpskew_bb_band_narrow",
        offset=60,
        required=["g_bb_pos_with", "g_sms_no_liquidity_above", "g_hurst_trending", "g_entry_vwap_in_band_narrow"],
        extra=[
            "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_cloud", "g_tr_stack_with",
            "g_ribbon_agrees", "g_rf_with", "g_cci_with", "g_mp_skew_with",
            "g_sms_liq_reclaim_with", "g_tr_in_active_session", "g_regime_ranging_at_ws",
        ],
    ),
    dict(
        sleeve_id="v6_c3_off60_cloud_ribbon_mpskew_hurst",
        offset=60,
        required=["g_tr_above_cloud", "g_ribbon_agrees", "g_mp_skew_with", "g_hurst_trending"],
        extra=[
            "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_stack_with",
            "g_rf_with", "g_bb_pos_with", "g_cci_with",
            "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
            "g_tr_in_active_session", "g_regime_ranging_at_ws", "g_entry_vwap_in_band_wide",
        ],
    ),
    dict(
        sleeve_id="v6_c4_off60_ema200_cci_mpskew_hurst",
        offset=60,
        required=["g_tr_above_ema200", "g_cci_with", "g_mp_skew_with", "g_hurst_trending"],
        extra=[
            "g_tr_above_ema50", "g_tr_above_cloud", "g_tr_stack_with",
            "g_rf_with", "g_bb_pos_with", "g_ribbon_agrees",
            "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above",
            "g_tr_in_active_session", "g_regime_ranging_at_ws", "g_entry_vwap_in_band_wide",
        ],
    ),
    # V5 c2 verification under V6 lockbox -> at offset=120
    dict(
        sleeve_id="v6_c5_off120_v5winner_verify",
        offset=120,
        required=["g_tr_above_ema200", "g_mp_skew_with", "g_sms_liq_reclaim_with", "g_tr_in_active_session"],
        extra=[
            "g_tr_above_ema50", "g_tr_above_cloud", "g_tr_stack_with",
            "g_rf_with", "g_bb_pos_with", "g_ribbon_agrees", "g_cci_with",
            "g_sms_no_liquidity_above", "g_hurst_trending", "g_regime_ranging_at_ws",
        ],
    ),
]


def metrics(pnl_arr, won_arr, fire_us_arr, stake=25.0):
    if len(pnl_arr) == 0:
        return dict(n=0, wr=0, sum=0, dpt=0, dd=0, loss_streak=0, sharpe=0, active_days=0)
    s = stake / 25.0
    pnl_s = pnl_arr * s
    ord_idx = np.argsort(fire_us_arr)
    pnl_o = pnl_s[ord_idx]
    won_o = won_arr[ord_idx]
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
    days_arr = (fire_us_arr // 86_400_000_000).astype(np.int64)
    uniq, idx = np.unique(days_arr, return_inverse=True)
    by_day = np.bincount(idx, weights=pnl_s)
    sharpe = (by_day.mean() / by_day.std() * np.sqrt(365)) if (by_day.std() > 0 and len(by_day) > 1) else 0.0
    return dict(
        n=int(len(pnl_s)), wr=float(won_arr.mean()), sum=float(pnl_s.sum()),
        dpt=float(pnl_s.mean()), dd=dd, loss_streak=mxls,
        sharpe=float(sharpe), active_days=int(len(uniq)),
    )


def bootstrap_p(pnl_arr, fire_us_arr, stake=25.0, n_iter=1000, seed=42):
    if len(pnl_arr) < 5:
        return 1.0
    pnl_s = pnl_arr * (stake / 25.0)
    if pnl_s.mean() <= 0:
        return 1.0
    days_arr = (fire_us_arr // 86_400_000_000).astype(np.int64)
    uniq, idx = np.unique(days_arr, return_inverse=True)
    if len(uniq) < 2:
        return 1.0
    by_day = [pnl_s[idx == i] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        sel = rng.integers(0, len(by_day), size=len(by_day))
        means[i] = np.concatenate([by_day[j] for j in sel]).mean()
    return float((means <= 0).mean())


def kelly_stake_from_p(p, vwap, kelly_frac=0.25, stake_min=STAKE_MIN, stake_max=STAKE_MAX):
    """Compute Kelly stake given win probability and entry vwap (quarter-Kelly per brief §1)."""
    if vwap <= 0 or vwap >= 1:
        return stake_min
    # b = profit per $ risked if won (legacy 2% on profit)
    b = (1 - vwap) * 0.98 / vwap
    if b <= 0:
        return stake_min
    f_full = (p * b - (1 - p)) / b
    f_kelly = max(0, kelly_frac * f_full)
    stake = f_kelly * stake_max
    return float(np.clip(stake, stake_min, stake_max))


def full_kelly_stake(p, vwap, stake_min=STAKE_MIN, stake_max=STAKE_MAX):
    """Full-Kelly stake (operator's $25 = full-Kelly bankroll fraction cap)."""
    if vwap <= 0 or vwap >= 1:
        return stake_min
    b = (1 - vwap) * 0.98 / vwap
    if b <= 0:
        return stake_min
    f_full = max(0, (p * b - (1 - p)) / b)
    stake = f_full * stake_max
    return float(np.clip(stake, stake_min, stake_max))


def linear_conviction_stake(conviction, stake_min=STAKE_MIN, stake_max=STAKE_MAX):
    """Linear in conviction score in [0,1]."""
    stake = stake_min + (stake_max - stake_min) * conviction
    return float(np.clip(stake, stake_min, stake_max))


def analyze_sleeve(df_univ, sleeve, lockbox_days_set, train_days_set, val_days_set, force_train_dpt=False):
    """Return dict with metrics, kelly_table, fires_with_stakes."""
    offset = sleeve["offset"]
    required = sleeve["required"]
    extra = sleeve["extra"]

    pool = df_univ[df_univ["fire_offset_s"] == offset].copy()
    # Build masks for required gates
    avail_req = [g for g in required if g in pool.columns]
    avail_extra = [g for g in extra if g in pool.columns]
    if len(avail_req) < len(required):
        missing = set(required) - set(avail_req)
        print(f"  WARN missing required gates: {missing}")
        return None

    req_mask = np.ones(len(pool), dtype=bool)
    for g in avail_req:
        req_mask &= (pool[g].fillna(0).astype(float).values >= 1.0)

    gated = pool[req_mask].copy().reset_index(drop=True)
    if len(gated) < 10:
        return None

    # Compute conviction = # of extra gates passing
    extra_passing = np.zeros(len(gated), dtype=int)
    for g in avail_extra:
        extra_passing += (gated[g].fillna(0).astype(float).values >= 1.0).astype(int)
    gated["extra_passing"] = extra_passing
    max_extra = len(avail_extra)
    gated["conviction"] = extra_passing / max(1, max_extra)

    # Split into train / val / lockbox
    gated_t = gated[gated["day"].isin(train_days_set)].copy()
    gated_v = gated[gated["day"].isin(val_days_set)].copy()
    gated_l = gated[gated["day"].isin(lockbox_days_set)].copy()

    # ---- Build kelly stake table: empirical WR per conviction bucket ON TRAIN ----
    # Define 4 buckets by extra_passing thirds
    if len(gated_t) >= 30:
        # Bucket by extra_passing count
        bucket_edges = np.percentile(extra_passing, [25, 50, 75])
        bucket_edges = np.unique(np.concatenate([[0], bucket_edges, [max_extra + 1]]))
    else:
        bucket_edges = np.array([0, 1, 2, max_extra + 1])

    # Use simpler: bucket by extra_passing integer
    train_extra = gated_t["extra_passing"].values
    train_won = gated_t["won"].values.astype(bool)
    train_vwap = gated_t["entry_vwap"].values

    # Build per-bucket empirical p from TRAIN ONLY (no leakage)
    bucket_table = {}  # extra_passing_count -> (n_train, empirical_p, median_vwap)
    for c in range(0, max_extra + 1):
        sel = (train_extra == c)
        if sel.sum() < 5:
            continue
        bucket_table[c] = dict(
            n_train=int(sel.sum()),
            p_train=float(train_won[sel].mean()),
            median_vwap=float(np.median(train_vwap[sel])),
        )

    # Fallback: if too sparse, use overall train WR
    if len(bucket_table) == 0 and len(train_won) > 0:
        bucket_table[0] = dict(
            n_train=int(len(train_won)),
            p_train=float(train_won.mean()),
            median_vwap=float(np.median(train_vwap)),
        )

    # For each lockbox fire, get conviction bucket -> recommended stake under 3 modes
    def compute_stake_per_fire(g):
        s_kelly25, s_full, s_linear = [], [], []
        for _, row in g.iterrows():
            c = int(row["extra_passing"])
            if c in bucket_table:
                p = bucket_table[c]["p_train"]
            else:
                known = sorted(bucket_table.keys())
                if not known:
                    p = 0.5
                else:
                    nearest = min(known, key=lambda k: abs(k - c))
                    p = bucket_table[nearest]["p_train"]
            v = row["entry_vwap"]
            s_kelly25.append(kelly_stake_from_p(p, v))
            s_full.append(full_kelly_stake(p, v))
            s_linear.append(linear_conviction_stake(row["conviction"]))
        return np.array(s_kelly25), np.array(s_full), np.array(s_linear)

    # Apply to lockbox
    if len(gated_l) > 0:
        stake_l_k25, stake_l_full, stake_l_lin = compute_stake_per_fire(gated_l)
        # default "kelly" stake for plots = full-kelly (more dynamic range)
        stake_l = stake_l_full
    else:
        stake_l_k25 = np.array([])
        stake_l_full = np.array([])
        stake_l_lin = np.array([])
        stake_l = np.array([])
    if len(gated_v) > 0:
        _, stake_v, _ = compute_stake_per_fire(gated_v)
    else:
        stake_v = np.array([])
    if len(gated_t) > 0:
        _, stake_t, _ = compute_stake_per_fire(gated_t)
    else:
        stake_t = np.array([])

    # Now build kelly-variable PnL: pnl_kelly = pnl_legacy_usd * (stake/25)
    def kelly_pnl(g, stakes):
        if len(g) == 0:
            return np.array([])
        return g["pnl_legacy_usd"].values * (stakes / 25.0)

    pnl_kelly_l = kelly_pnl(gated_l, stake_l)

    # Constant $25 metrics
    m_train = metrics(gated_t["pnl_legacy_usd"].values, gated_t["won"].values.astype(bool),
                      gated_t["fire_us"].values, 25.0)
    m_val = metrics(gated_v["pnl_legacy_usd"].values, gated_v["won"].values.astype(bool),
                    gated_v["fire_us"].values, 25.0)
    m_lock_const = metrics(gated_l["pnl_legacy_usd"].values, gated_l["won"].values.astype(bool),
                           gated_l["fire_us"].values, 25.0)

    # Kelly-variable metrics (full kelly used for primary "kelly" metrics)
    if len(gated_l) > 0:
        ord_idx = np.argsort(gated_l["fire_us"].values)
        pnl_k_ord = pnl_kelly_l[ord_idx]
        won_k_ord = gated_l["won"].values.astype(bool)[ord_idx]
        cum_k = np.cumsum(pnl_k_ord)
        peak_k = np.maximum.accumulate(cum_k)
        dd_k = float((cum_k - peak_k).min())
        sum_k_lock = float(pnl_kelly_l.sum())
        mean_stake_l = float(stake_l.mean())
        min_stake_l = float(stake_l.min())
        max_stake_l = float(stake_l.max())

        # k25 mode
        pnl_k25 = gated_l["pnl_legacy_usd"].values * (stake_l_k25 / 25.0)
        sum_k25_lock = float(pnl_k25.sum())
        mean_stake_k25 = float(stake_l_k25.mean())

        # linear mode
        pnl_lin = gated_l["pnl_legacy_usd"].values * (stake_l_lin / 25.0)
        sum_lin_lock = float(pnl_lin.sum())
        mean_stake_lin = float(stake_l_lin.mean())
    else:
        dd_k = 0.0
        sum_k_lock = 0.0
        mean_stake_l = 0.0
        min_stake_l = 0.0
        max_stake_l = 0.0
        sum_k25_lock = 0.0
        mean_stake_k25 = 0.0
        sum_lin_lock = 0.0
        mean_stake_lin = 0.0

    bp_lock = bootstrap_p(gated_l["pnl_legacy_usd"].values, gated_l["fire_us"].values, 25.0)

    # ---- Kelly stake table for the report ----
    max_extra = len(avail_extra)
    stake_table = []
    for c in sorted(bucket_table.keys()):
        bt = bucket_table[c]
        p = bt["p_train"]
        v = bt["median_vwap"]
        s_k25 = kelly_stake_from_p(p, v)
        s_full = full_kelly_stake(p, v)
        s_lin = linear_conviction_stake(c / max(1, max_extra))
        if v > 0:
            shares_full = s_full / v
            won_payout = shares_full * (1 - v) * 0.98
            lost_payout = -s_full
        else:
            won_payout = 0
            lost_payout = 0
        stake_table.append(dict(
            extra_passing=c,
            conviction=round(c / max(1, max_extra), 3),
            n_train=bt["n_train"],
            p_train=round(p, 4),
            median_vwap=round(v, 4),
            kelly25_stake=round(s_k25, 2),
            full_kelly_stake=round(s_full, 2),
            linear_stake=round(s_lin, 2),
            example_won_full_kelly=round(won_payout, 2),
            example_lost_full_kelly=round(lost_payout, 2),
        ))

    # ---- Full per-fire data for plotting ----
    if len(gated_l) > 0:
        ord_idx = np.argsort(gated_l["fire_us"].values)
        gl_sorted = gated_l.iloc[ord_idx].copy()
        gl_sorted["stake_kelly_full"] = stake_l_full[ord_idx]
        gl_sorted["stake_kelly_25"] = stake_l_k25[ord_idx]
        gl_sorted["stake_linear"] = stake_l_lin[ord_idx]
        gl_sorted["pnl_const25"] = gl_sorted["pnl_legacy_usd"].values
        gl_sorted["pnl_kelly_full"] = gl_sorted["pnl_legacy_usd"].values * (stake_l_full[ord_idx] / 25.0)
        gl_sorted["pnl_kelly_25"] = gl_sorted["pnl_legacy_usd"].values * (stake_l_k25[ord_idx] / 25.0)
        gl_sorted["pnl_linear"] = gl_sorted["pnl_legacy_usd"].values * (stake_l_lin[ord_idx] / 25.0)
        gl_sorted["cum_const25"] = gl_sorted["pnl_const25"].cumsum()
        gl_sorted["cum_kelly_full"] = gl_sorted["pnl_kelly_full"].cumsum()
        gl_sorted["cum_kelly_25"] = gl_sorted["pnl_kelly_25"].cumsum()
        gl_sorted["cum_linear"] = gl_sorted["pnl_linear"].cumsum()
    else:
        gl_sorted = pd.DataFrame()

    return dict(
        sleeve_id=sleeve["sleeve_id"],
        offset=offset,
        required=required,
        extra=avail_extra,
        n_required=len(avail_req),
        n_extra=len(avail_extra),
        m_train=m_train,
        m_val=m_val,
        m_lock_const=m_lock_const,
        sum_k_lock=sum_k_lock,
        dd_k_lock=dd_k,
        mean_stake_l=mean_stake_l,
        min_stake_l=min_stake_l,
        max_stake_l=max_stake_l,
        sum_k25_lock=sum_k25_lock,
        mean_stake_k25=mean_stake_k25,
        sum_lin_lock=sum_lin_lock,
        mean_stake_lin=mean_stake_lin,
        bp_lock=bp_lock,
        stake_table=stake_table,
        gated_lockbox=gl_sorted,
        train_days=len(train_days_set),
        val_days=len(val_days_set),
        lockbox_days=len(lockbox_days_set),
    )


def main():
    print(f"Loading universe {UNIV}")
    df = pd.read_parquet(UNIV)
    df["day"] = pd.to_datetime(df["fire_us"], unit="us").dt.date
    days_sorted = sorted(df["day"].unique())
    print(f"  total days: {len(days_sorted)} [{days_sorted[0]} .. {days_sorted[-1]}]")

    # 3-way split: lockbox last 15%, val next 18% before lockbox, train rest
    n_lockbox = max(4, int(len(days_sorted) * 0.15))
    n_val = max(4, int(len(days_sorted) * 0.18))
    lockbox = set(days_sorted[-n_lockbox:])
    val = set(days_sorted[-(n_lockbox + n_val):-n_lockbox])
    train = set(days_sorted[:-(n_lockbox + n_val)])
    print(f"  train: {len(train)}d, val: {len(val)}d, lockbox: {len(lockbox)}d")

    summaries = []
    for sleeve in TOP5:
        print(f"\n=== {sleeve['sleeve_id']} (offset={sleeve['offset']}) ===")
        r = analyze_sleeve(df, sleeve, lockbox, train, val)
        if r is None:
            print("  SKIPPED (no required gates available or empty)")
            continue
        m_tr, m_v, m_l = r["m_train"], r["m_val"], r["m_lock_const"]
        print(f"  TRAIN n={m_tr['n']} WR={m_tr['wr']:.3f} dpt=${m_tr['dpt']:.2f}")
        print(f"  VAL   n={m_v['n']} WR={m_v['wr']:.3f} dpt=${m_v['dpt']:.2f}")
        print(f"  LOCK(const25) n={m_l['n']} WR={m_l['wr']:.3f} dpt=${m_l['dpt']:.2f} sum=${m_l['sum']:.2f} dd=${m_l['dd']:.2f} ls={m_l['loss_streak']} bp={r['bp_lock']:.4f}")
        print(f"  LOCK(kelly25) sum=${r['sum_k_lock']:.2f} dd=${r['dd_k_lock']:.2f} mean_stake=${r['mean_stake_l']:.2f}")
        summaries.append(r)

        # Save kelly stake table per sleeve
        stake_df = pd.DataFrame(r["stake_table"])
        stake_path = os.path.join(RES_DIR, f"kelly_stake_table_{sleeve['sleeve_id']}.csv")
        stake_df.to_csv(stake_path, index=False)
        print(f"  -> {stake_path}")

        # Save gated lockbox per-fire detail
        if not r["gated_lockbox"].empty:
            det_path = os.path.join(RES_DIR, f"lockbox_fires_{sleeve['sleeve_id']}.csv")
            r["gated_lockbox"][["slug", "fire_us", "fire_offset_s", "direction", "entry_vwap",
                                "won", "pnl_legacy_usd", "extra_passing", "conviction",
                                "stake_kelly_full", "stake_kelly_25", "stake_linear",
                                "pnl_const25", "pnl_kelly_full", "pnl_kelly_25", "pnl_linear",
                                "cum_const25", "cum_kelly_full", "cum_kelly_25", "cum_linear"]].to_csv(det_path, index=False)
            print(f"  -> {det_path}")

            # Plot — 2 panels: cumulative PnL + stake histogram
            plot_path = os.path.join(PLOT_DIR, f"cumulative_pnl_kelly_vs_const_{sleeve['sleeve_id']}.png")
            fig, axes = plt.subplots(2, 1, figsize=(11, 9))
            x = np.arange(len(r["gated_lockbox"]))
            axes[0].plot(x, r["gated_lockbox"]["cum_const25"].values,
                         label=f"Const $25  sum=${r['m_lock_const']['sum']:.0f}", linewidth=2)
            axes[0].plot(x, r["gated_lockbox"]["cum_kelly_full"].values,
                         label=f"Full Kelly (avg ${r['mean_stake_l']:.1f})  sum=${r['sum_k_lock']:.0f}",
                         linewidth=2, alpha=0.85)
            axes[0].plot(x, r["gated_lockbox"]["cum_kelly_25"].values,
                         label=f"Quarter-Kelly (avg ${r['mean_stake_k25']:.1f})  sum=${r['sum_k25_lock']:.0f}",
                         linewidth=1.5, alpha=0.8, linestyle="--")
            axes[0].plot(x, r["gated_lockbox"]["cum_linear"].values,
                         label=f"Linear conviction (avg ${r['mean_stake_lin']:.1f})  sum=${r['sum_lin_lock']:.0f}",
                         linewidth=1.5, alpha=0.8, linestyle=":")
            axes[0].set_title(f"{sleeve['sleeve_id']} — Lockbox cumulative PnL (4 stake modes)")
            axes[0].set_xlabel("Fire # (chronological)")
            axes[0].set_ylabel("Cumulative PnL ($)")
            axes[0].legend(loc="upper left", fontsize=9)
            axes[0].grid(alpha=0.3)

            axes[1].hist(r["gated_lockbox"]["stake_kelly_full"].values, bins=20, edgecolor="black", alpha=0.7, label="full Kelly")
            axes[1].hist(r["gated_lockbox"]["stake_linear"].values, bins=20, edgecolor="black", alpha=0.5, label="linear conv")
            axes[1].set_title("Stake distribution (lockbox)")
            axes[1].set_xlabel("Stake ($)")
            axes[1].set_ylabel("# fires")
            axes[1].legend()
            axes[1].grid(alpha=0.3)
            plt.tight_layout()
            plt.savefig(plot_path, dpi=100)
            plt.close()
            print(f"  -> {plot_path}")

    # ---- top_5_candidates_v6.csv ----
    rows = []
    for r in summaries:
        rows.append(dict(
            sleeve_id=r["sleeve_id"],
            anchor=f"offset_{r['offset']}s",
            gate_stack="&".join(r["required"]),
            conviction_method="B_empirical_WR_per_extra_count",
            n_train=r["m_train"]["n"],
            n_val=r["m_val"]["n"],
            n_lockbox=r["m_lock_const"]["n"],
            wr_train=round(r["m_train"]["wr"], 4),
            wr_val=round(r["m_val"]["wr"], 4),
            wr_lockbox=round(r["m_lock_const"]["wr"], 4),
            dpt_25_lockbox=round(r["m_lock_const"]["dpt"], 3),
            sum_25_28d_const=round(r["m_train"]["sum"] + r["m_val"]["sum"] + r["m_lock_const"]["sum"], 2),
            sum_25_28d_kelly_full=round(r["sum_k_lock"], 2),
            sum_lock_kelly_25=round(r["sum_k25_lock"], 2),
            sum_lock_kelly_full=round(r["sum_k_lock"], 2),
            sum_lock_linear=round(r["sum_lin_lock"], 2),
            sum_lock_const=round(r["m_lock_const"]["sum"], 2),
            max_dd_25=round(r["m_lock_const"]["dd"], 2),
            loss_streak=r["m_lock_const"]["loss_streak"],
            sharpe=round(r["m_lock_const"]["sharpe"], 2),
            bootstrap_p_lockbox=round(r["bp_lock"], 4),
            mean_stake_kelly_full=round(r["mean_stake_l"], 2),
            mean_stake_kelly_25=round(r["mean_stake_k25"], 2),
            mean_stake_linear=round(r["mean_stake_lin"], 2),
        ))
    out_csv = os.path.join(RES_DIR, "top_5_candidates_v6.csv")
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}")
    print(pd.DataFrame(rows).to_string())

    # Save a master summary JSON for the report
    import json
    summary_path = os.path.join(RES_DIR, "top_5_summaries.json")
    # Strip non-JSON-serializable items
    json_safe = []
    for r in summaries:
        rj = dict(
            sleeve_id=r["sleeve_id"], offset=r["offset"],
            required=r["required"], extra=r["extra"],
            n_required=r["n_required"], n_extra=r["n_extra"],
            m_train=r["m_train"], m_val=r["m_val"], m_lock_const=r["m_lock_const"],
            sum_k_lock_full=r["sum_k_lock"], sum_k25_lock=r["sum_k25_lock"], sum_lin_lock=r["sum_lin_lock"],
            dd_k_lock=r["dd_k_lock"],
            mean_stake_full=r["mean_stake_l"], min_stake_full=r["min_stake_l"], max_stake_full=r["max_stake_l"],
            mean_stake_k25=r["mean_stake_k25"], mean_stake_lin=r["mean_stake_lin"],
            bp_lock=r["bp_lock"], stake_table=r["stake_table"],
        )
        json_safe.append(rj)
    with open(summary_path, "w") as f:
        json.dump(json_safe, f, indent=2, default=str)
    print(f"-> {summary_path}")


if __name__ == "__main__":
    main()
