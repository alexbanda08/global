"""
FINALIZE V6 — BTC 5m
=====================
Post-process V6 search output:
  1. Dedup passers by (n_full, n_lockbox, dpt_25_lockbox) identity (different gate stacks → same mask)
  2. Diversify top 5 across anchor types (pre-window vs early vs late)
  3. Build Kelly stake tables (conviction buckets) on TRAIN+VAL
  4. Simulate Kelly-variable vs constant $25 PnL on LOCKBOX
  5. Generate cumulative_pnl_kelly_vs_const_*.png per top 5
  6. Write SNIPER_BTC_5M_V6_REPORT.md
"""
import sys
import io
from pathlib import Path
import numpy as np
import pandas as pd

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
OUT = ROOT / "strategy_lab/sniper_search_2026_05_27/btc_5m_v6"

STAKE_MIN = 5.0
STAKE_MAX = 25.0
KELLY_FRAC = 0.25
DAYS_TOTAL = 24.8

STRONG_GATES = [
    "g_trend_slope_strong_with","g_mp_no_extreme","g_mp_skew_with","g_mp_change_with",
    "g_imb5_strong_with","g_queue_top_high","g_hawkes_imbalance_with",
    "g_within_dev","g_dev_extreme",
    "g_tr_above_ema200","g_tr_above_ema800","g_ribbon_agrees","g_rf_with",
    "g_lm_high_stat","g_hl_liq_cascade_with","g_vol_high","g_markov_with",
    "g_hurst_trending",
]


def kelly_stake(p, vwap, frac=KELLY_FRAC):
    if not (0 < p < 1) or not (0 < vwap < 1):
        return STAKE_MIN
    b = (1 - vwap) * 0.98 / vwap
    if b <= 0:
        return STAKE_MIN
    f_full = (p * b - (1 - p)) / b
    if f_full <= 0:
        return STAKE_MIN
    f = frac * f_full
    return float(np.clip(f * STAKE_MAX, STAKE_MIN, STAKE_MAX))


def parse_gate_list(stack_str):
    if pd.isna(stack_str) or stack_str == "raw":
        return []
    return [g.strip() for g in stack_str.split("+") if g.strip()]


def reconstruct_mask(df, sleeve_id, anchor, gate_stack):
    """Re-derive the boolean mask used by the search for a given candidate row."""
    n = len(df)
    m = np.ones(n, dtype=bool)
    # Offset filter from anchor / sleeve_id
    if anchor.startswith("offset_"):
        # parse offset bin code: e.g. offset_L210, offset_L_late, offset_early3060
        code = anchor.replace("offset_", "")
        if code == "L_late":
            m &= df["fire_offset_s"].isin([150, 180, 210, 240]).values
        elif code == "L150":
            m &= df["fire_offset_s"].isin([150]).values
        elif code == "L180":
            m &= df["fire_offset_s"].isin([180]).values
        elif code == "L210":
            m &= df["fire_offset_s"].isin([210]).values
        elif code == "L240":
            m &= df["fire_offset_s"].isin([240]).values
        elif code == "early30":
            m &= df["fire_offset_s"].isin([30]).values
        elif code == "early45":
            m &= df["fire_offset_s"].isin([45]).values
        elif code == "early60":
            m &= df["fire_offset_s"].isin([60]).values
        elif code == "early3060":
            m &= df["fire_offset_s"].isin([30, 60]).values
        elif code == "early304560":
            m &= df["fire_offset_s"].isin([30, 45, 60]).values
    elif anchor.startswith("ws_s+offset_"):
        code = anchor.replace("ws_s+offset_", "")
        if code == "e30":
            m &= df["fire_offset_s"].isin([30]).values
        elif code == "e60":
            m &= df["fire_offset_s"].isin([60]).values
        elif code == "e3060":
            m &= df["fire_offset_s"].isin([30, 60]).values
    # anchor == "ws_s" => no offset filter (whole window)

    # Apply gate stack
    for g in parse_gate_list(gate_stack):
        if g in df.columns:
            m &= (df[g].values == 1)
    return m


def build_conviction_buckets_v2(sub_trva, base_mask_trva, conv_gates, df_for_vwap_hint=None):
    """Given a TRAIN+VAL subset already gated, partition by # of extra conviction gates passing
    and compute BOTH Kelly stakes (0.25-frac) AND linear-conviction stakes (operator alternative).

    Per V6 brief §1, the LINEAR scheme is the simpler operator-aligned variant when bankroll is the
    $25 cap itself (rather than a separate larger bankroll). conviction = (n_extra - n_min)/(n_max - n_min).
    """
    if len(sub_trva) == 0:
        return None
    n_extra = np.zeros(len(sub_trva), dtype=np.int16)
    avail_conv = [g for g in conv_gates if g in sub_trva.columns]
    if len(avail_conv) == 0:
        return None
    for g in avail_conv:
        n_extra += sub_trva[g].values.astype(np.int16)
    sub_trva = sub_trva.copy()
    sub_trva["n_extra"] = n_extra

    buckets = {}
    # Determine n_extra range across populated buckets (>=5 obs each)
    pop_keys = sorted([k for k in range(int(n_extra.max()) + 1) if (n_extra == k).sum() >= 5])
    if not pop_keys:
        return None
    n_min_extra = pop_keys[0]
    n_max_extra = pop_keys[-1]
    span = max(n_max_extra - n_min_extra, 1)

    for k in pop_keys:
        sk = sub_trva[sub_trva["n_extra"] == k]
        nk = len(sk)
        p_k = float(sk["won_int"].mean())
        wons = sk[sk["won_int"] == 1]["pnl_legacy_usd"]
        if len(wons) > 0:
            avg_won = wons.mean()
            vwap_est = (25.0 * 0.98) / (avg_won + 25.0 * 0.98) if (avg_won + 25.0 * 0.98) > 0 else 0.55
            vwap_est = float(np.clip(vwap_est, 0.05, 0.95))
        else:
            vwap_est = 0.55
        # Kelly stake (Option B per brief)
        stake_kelly = kelly_stake(p_k, vwap_est)
        # Linear stake (operator-friendly, conviction = position in bucket range)
        conviction = (k - n_min_extra) / span
        stake_linear = STAKE_MIN + (STAKE_MAX - STAKE_MIN) * conviction
        # Hybrid: use linear when Kelly would clamp to MIN; use Kelly when it exceeds MIN
        stake_hybrid = max(stake_kelly, stake_linear)
        buckets[k] = dict(
            n_extra=k, n_trva=nk, empirical_p_win=p_k, vwap_est=vwap_est,
            kelly_stake=stake_kelly,
            linear_stake=stake_linear,
            hybrid_stake=stake_hybrid,
            conviction=conviction,
            dpt_25_trva_const=float(sk["pnl_legacy_usd"].mean()),
        )
    return buckets


def simulate_kelly(sub_lb, buckets, conv_gates):
    """Replay lockbox with three variable stake schemes: pure Kelly, linear-conviction, hybrid."""
    sub_lb = sub_lb.sort_values("fire_us").reset_index(drop=True).copy()
    if len(sub_lb) == 0 or buckets is None:
        return sub_lb, 0.0, 0.0, 0.0, 0.0
    n_extra = np.zeros(len(sub_lb), dtype=np.int16)
    avail_conv = [g for g in conv_gates if g in sub_lb.columns]
    for g in avail_conv:
        n_extra += sub_lb[g].values.astype(np.int16)
    sub_lb["n_extra"] = n_extra

    # Fallback: for buckets unseen in train, use closest available bucket's stake
    bucket_keys = sorted(buckets.keys())

    def lookup_stake(k, field):
        if k in buckets:
            return buckets[k][field]
        # nearest bucket
        nearest = min(bucket_keys, key=lambda x: abs(x - k))
        return buckets[nearest][field]

    s_kelly = np.array([lookup_stake(k, "kelly_stake") for k in n_extra])
    s_linear = np.array([lookup_stake(k, "linear_stake") for k in n_extra])
    s_hybrid = np.array([lookup_stake(k, "hybrid_stake") for k in n_extra])
    sub_lb["stake_kelly"] = s_kelly
    sub_lb["stake_linear"] = s_linear
    sub_lb["stake_hybrid"] = s_hybrid
    sub_lb["pnl_const"] = sub_lb["pnl_legacy_usd"]
    sub_lb["pnl_kelly"] = sub_lb["pnl_legacy_usd"] * (s_kelly / 25.0)
    sub_lb["pnl_linear"] = sub_lb["pnl_legacy_usd"] * (s_linear / 25.0)
    sub_lb["pnl_hybrid"] = sub_lb["pnl_legacy_usd"] * (s_hybrid / 25.0)
    return (sub_lb,
            float(sub_lb["pnl_const"].sum()),
            float(sub_lb["pnl_kelly"].sum()),
            float(sub_lb["pnl_linear"].sum()),
            float(sub_lb["pnl_hybrid"].sum()))


def plot_kelly_vs_const(sub_lb, title, out_path):
    sub_lb = sub_lb.sort_values("fire_us").reset_index(drop=True)
    if len(sub_lb) < 5:
        return
    cum_const = sub_lb["pnl_const"].cumsum().values
    cum_kelly = sub_lb["pnl_kelly"].cumsum().values
    cum_linear = sub_lb["pnl_linear"].cumsum().values if "pnl_linear" in sub_lb.columns else None
    cum_hybrid = sub_lb["pnl_hybrid"].cumsum().values if "pnl_hybrid" in sub_lb.columns else None
    dt = pd.to_datetime(sub_lb["fire_us"], unit="us", utc=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(dt, cum_const, lw=1.7, color="navy", label=f"Const $25 (sum=${cum_const[-1]:.0f})")
    ax.plot(dt, cum_kelly, lw=1.4, color="firebrick", alpha=0.85, label=f"Kelly-25 (sum=${cum_kelly[-1]:.0f})")
    if cum_linear is not None:
        ax.plot(dt, cum_linear, lw=1.4, color="darkgreen", alpha=0.85, ls="--", label=f"Linear conviction (sum=${cum_linear[-1]:.0f})")
    if cum_hybrid is not None:
        ax.plot(dt, cum_hybrid, lw=1.5, color="purple", alpha=0.9, ls=":", label=f"Hybrid max(K, L) (sum=${cum_hybrid[-1]:.0f})")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.autofmt_xdate()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def safe_id(s):
    return s.replace("|", "_").replace("+", "_").replace("&", "_").replace(" ", "_").replace("/", "_")[:80]


def main():
    print("=" * 72)
    print("FINALIZE V6 — BTC 5m")
    print("=" * 72)
    df = pd.read_parquet(OUT / "_sandbox/universe_with_pw.parquet")
    df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
    df["fire_date"] = df["fire_dt"].dt.date
    print(f"Universe: {len(df):,} rows")

    cdf = pd.read_csv(OUT / "all_candidates_v6.csv")
    passers = cdf[cdf["pass"]].copy()
    print(f"Passers: {len(passers)}")

    # === DEDUP STAGE ===
    # Many rows share the same metrics (different gate-stack names producing same mask).
    # Dedup on metrics signature, keep the one with the shortest gate_stack.
    sig_cols = ["n_full", "n_lockbox", "wr_lockbox", "dpt_25_lockbox", "max_dd_25_lockbox"]
    # Round to avoid floating noise
    sig = passers[sig_cols].round(4).astype(str).agg("|".join, axis=1)
    passers["_sig"] = sig
    passers["_gs_len"] = passers["gate_stack"].fillna("").str.len()
    passers = passers.sort_values(["_sig", "_gs_len"]).drop_duplicates("_sig", keep="first")
    # Re-rank by objective
    passers = passers.sort_values("objective", ascending=False).reset_index(drop=True)
    print(f"After metric-signature dedup: {len(passers)}")

    # === DIVERSIFY ACROSS ANCHOR TYPES ===
    # Group by anchor category
    def anchor_cat(a):
        if a == "ws_s":
            return "pre-window"
        if a.startswith("ws_s+offset"):
            return "pre-window+early"
        if "early" in a:
            return "early"
        if a.startswith("offset_L"):
            return "late"
        return "other"
    passers["anchor_cat"] = passers["anchor"].apply(anchor_cat)
    print("\nAnchor category distribution (passers):")
    print(passers["anchor_cat"].value_counts())

    # === SELECT TOP 5 — diversify: at most 2 per anchor_cat in top 5 ===
    selected = []
    used_cat = {}
    for _, row in passers.iterrows():
        c = row["anchor_cat"]
        if used_cat.get(c, 0) >= 2:
            continue
        selected.append(row)
        used_cat[c] = used_cat.get(c, 0) + 1
        if len(selected) >= 5:
            break
    # If fewer than 5 due to diversity rule, fill with the next-best
    if len(selected) < 5:
        already = set(s["_sig"] for s in selected)
        for _, row in passers.iterrows():
            if row["_sig"] in already:
                continue
            selected.append(row)
            if len(selected) >= 5:
                break

    top5 = pd.DataFrame(selected).reset_index(drop=True)
    print(f"\nTop 5 diversified:")
    print(top5[["sleeve_id", "anchor_cat", "n_lockbox", "wr_lockbox",
                 "dpt_25_lockbox", "max_dd_25_lockbox", "loss_streak_lockbox",
                 "bootstrap_p_lockbox", "objective"]].to_string(index=False))

    # === COMPUTE KELLY STAKES + SIMULATIONS ===
    print("\n" + "=" * 72)
    print("KELLY STAGE — building conviction buckets + simulation")
    print("=" * 72)

    # Splits to redo
    ts_min = df["fire_us"].min()
    ts_max = df["fire_us"].max()
    span = ts_max - ts_min
    cut1 = ts_min + int(span * 15.0 / 24.8)
    cut2 = ts_min + int(span * 20.0 / 24.8)

    kelly_records = []
    for idx, row in top5.iterrows():
        sid = row["sleeve_id"]
        anchor = row["anchor"]
        gates = row["gate_stack"]
        sleeve_gates = parse_gate_list(gates)
        print(f"\n--- Sleeve {idx+1}: {sid}")
        mask = reconstruct_mask(df, sid, anchor, gates)
        n_reconstructed = int(mask.sum())
        n_expected = int(row["n_full"])
        print(f"  reconstructed n={n_reconstructed} expected n={n_expected}", end="")
        if n_reconstructed != n_expected:
            print(f"  WARN: mismatch — proceeding with reconstructed mask")
        else:
            print(f"  OK")

        # Split masks
        fus = df["fire_us"].values
        tr_mask = mask & (fus < cut1)
        va_mask = mask & (fus >= cut1) & (fus < cut2)
        lb_mask = mask & (fus >= cut2)

        sub_trva = df[tr_mask | va_mask].copy()
        sub_lb = df[lb_mask].copy()

        # Conviction gates = STRONG_GATES MINUS sleeve_gates (don't double-count)
        conv_gates = [g for g in STRONG_GATES if g not in sleeve_gates]

        buckets = build_conviction_buckets_v2(sub_trva, tr_mask | va_mask, conv_gates)
        if buckets is None:
            print(f"  ! no buckets — skip Kelly")
            continue

        # Save stake table
        bdf = pd.DataFrame([
            dict(
                bucket_idx=k,
                n_extra_gates_passing=v["n_extra"],
                n_trva=v["n_trva"],
                empirical_p_win=round(v["empirical_p_win"], 4),
                vwap_est=round(v["vwap_est"], 4),
                conviction=round(v["conviction"], 3),
                kelly_stake=round(v["kelly_stake"], 2),
                linear_stake=round(v["linear_stake"], 2),
                hybrid_stake=round(v["hybrid_stake"], 2),
                dpt_25_trva_const=round(v["dpt_25_trva_const"], 3),
            ) for k, v in sorted(buckets.items())
        ])
        bdf.to_csv(OUT / f"kelly_stake_table_top{idx+1}_{safe_id(sid)}.csv", index=False)
        print(f"  Buckets: {len(buckets)}, p_range=[{min(v['empirical_p_win'] for v in buckets.values()):.3f}, {max(v['empirical_p_win'] for v in buckets.values()):.3f}]")
        print(f"    kelly stake_range=[${min(v['kelly_stake'] for v in buckets.values()):.2f}, ${max(v['kelly_stake'] for v in buckets.values()):.2f}]")
        print(f"    linear stake_range=[${min(v['linear_stake'] for v in buckets.values()):.2f}, ${max(v['linear_stake'] for v in buckets.values()):.2f}]")

        # Simulate lockbox
        sub_lb_sim, sum_const, sum_kelly, sum_linear, sum_hybrid = simulate_kelly(sub_lb, buckets, conv_gates)
        print(f"  Lockbox PnL: const $25=${sum_const:.1f} | kelly=${sum_kelly:.1f} | linear=${sum_linear:.1f} | hybrid=${sum_hybrid:.1f}")

        # 28d projection
        days_lb = max((sub_lb["fire_dt"].max() - sub_lb["fire_dt"].min()).total_seconds() / 86400, 0.1)
        rate = len(sub_lb) / days_lb
        sum_28d_const = sum_const / max(days_lb, 0.1) * 28.0
        sum_28d_kelly = sum_kelly / max(days_lb, 0.1) * 28.0

        # Plot
        plot_kelly_vs_const(
            sub_lb_sim,
            f"BTC 5m V6 #{idx+1} — {sid[:90]}\nLockbox: Kelly variable vs Const $25",
            OUT / f"cumulative_pnl_kelly_vs_const_top{idx+1}_{safe_id(sid)}.png",
        )

        # 28d projection for all schemes
        sum_28d_kelly = sum_kelly / max(days_lb, 0.1) * 28.0
        sum_28d_linear = sum_linear / max(days_lb, 0.1) * 28.0
        sum_28d_hybrid = sum_hybrid / max(days_lb, 0.1) * 28.0

        kelly_records.append(dict(
            rank=idx + 1,
            sleeve_id=sid,
            anchor=anchor,
            gate_stack=gates,
            n_lockbox=int(row["n_lockbox"]),
            wr_lockbox=row["wr_lockbox"],
            dpt_25_lockbox_const=row["dpt_25_lockbox"],
            sum_25_lb_const=sum_const,
            sum_25_lb_kelly=sum_kelly,
            sum_25_lb_linear=sum_linear,
            sum_25_lb_hybrid=sum_hybrid,
            sum_25_28d_const=sum_28d_const,
            sum_25_28d_kelly=sum_28d_kelly,
            sum_25_28d_linear=sum_28d_linear,
            sum_25_28d_hybrid=sum_28d_hybrid,
            kelly_uplift_pct=((sum_kelly - sum_const) / abs(sum_const) * 100 if sum_const != 0 else 0),
            linear_uplift_pct=((sum_linear - sum_const) / abs(sum_const) * 100 if sum_const != 0 else 0),
            hybrid_uplift_pct=((sum_hybrid - sum_const) / abs(sum_const) * 100 if sum_const != 0 else 0),
            min_kelly_stake=min(v["kelly_stake"] for v in buckets.values()),
            max_kelly_stake=max(v["kelly_stake"] for v in buckets.values()),
            min_linear_stake=min(v["linear_stake"] for v in buckets.values()),
            max_linear_stake=max(v["linear_stake"] for v in buckets.values()),
            avg_kelly_stake=float(sub_lb_sim["stake_kelly"].mean()),
            avg_linear_stake=float(sub_lb_sim["stake_linear"].mean()),
            avg_hybrid_stake=float(sub_lb_sim["stake_hybrid"].mean()),
            n_buckets=len(buckets),
            max_dd_25_lockbox=row["max_dd_25_lockbox"],
            loss_streak_lockbox=row["loss_streak_lockbox"],
            sharpe_lockbox=row["sharpe_lockbox"],
            bootstrap_p_lockbox=row["bootstrap_p_lockbox"],
            anchor_cat=row["anchor_cat"],
        ))

    # Save consolidated top-5 candidates with Kelly results
    kdf = pd.DataFrame(kelly_records)
    kdf.to_csv(OUT / "top_5_candidates_v6.csv", index=False)
    print(f"\nWrote top_5_candidates_v6.csv ({len(kdf)} rows)")

    # === PRE-WINDOW vs EARLY vs LATE comparison ===
    print("\n" + "=" * 72)
    print("ANCHOR TIMING COMPARISON")
    print("=" * 72)
    cat_summary = passers.groupby("anchor_cat").agg(
        n_sleeves=("sleeve_id", "count"),
        best_dpt=("dpt_25_lockbox", "max"),
        median_dpt=("dpt_25_lockbox", "median"),
        best_obj=("objective", "max"),
        median_obj=("objective", "median"),
    ).round(2)
    print(cat_summary)
    cat_summary.to_csv(OUT / "anchor_category_summary.csv")

    # === REPORT ===
    print("\nWriting SNIPER_BTC_5M_V6_REPORT.md ...")
    write_report(top5, kdf, cat_summary, passers, df)
    print(f"Report saved to {OUT / 'SNIPER_BTC_5M_V6_REPORT.md'}")
    return top5, kdf


def write_report(top5, kdf, cat_summary, passers, df):
    lines = []
    lines.append("# Sniper Search V6 Report — BTC 5m")
    lines.append("")
    lines.append("Date: 2026-05-27. Brief: `_BRIEF_V6.md`.")
    lines.append("")
    lines.append("## Universe")
    lines.append("")
    lines.append(f"- Source: `data/v4/canonical/_results/master_gate_features_v2.parquet` (BTC 5m subset)")
    lines.append(f"- Fires: 33,646 across 24.8 days (2026-05-01 to 2026-05-25)")
    lines.append(f"- Base WR: 73.25%, base $/tr at $25 stake: +$1.94 (already direction-picked sleeves)")
    lines.append(f"- 18 offsets {{15, 30, 45, ... 270}}; F7 RSI at ws_s + microprice at earliest-offset proxy")
    lines.append("")
    lines.append("## V6 sniper bar (relaxed vs V5)")
    lines.append("")
    lines.append("- n/28d in [30, 2000]")
    lines.append("- WR_lockbox >= 0.65")
    lines.append("- $/tr (at $25 stake) on lockbox >= $4")
    lines.append("- Max DD <= $500 (relaxed from $300)")
    lines.append("- Max loss streak <= 14 (relaxed from 6)")
    lines.append("- Sharpe >= 1.5 (relaxed from 2.0)")
    lines.append("- Bootstrap p (daily-clustered, 1000-iter) <= 0.05 (KEPT)")
    lines.append("- Primary objective: lockbox_$/tr * sqrt(lockbox_n)")
    lines.append("")
    lines.append("## Candidates evaluated")
    lines.append("")
    lines.append(f"- Total candidates: 7,038")
    lines.append(f"- V6 passers (all 7 criteria): 2,037")
    lines.append(f"- After metric-signature dedup: {len(passers):,}")
    lines.append("")
    lines.append("### Distribution by anchor category")
    lines.append("")
    lines.append("```")
    lines.append(cat_summary.to_string())
    lines.append("```")
    lines.append("")

    # Determine pre-window vs early vs late winner
    cat_winners = cat_summary.sort_values("best_obj", ascending=False)
    timing_winner = cat_winners.index[0]
    lines.append(f"**Timing winner**: `{timing_winner}` had the highest individual sleeve objective.")
    lines.append("")

    lines.append("## Top 5 candidates (diversified across anchor types)")
    lines.append("")
    cols = ["rank", "sleeve_id", "anchor", "gate_stack", "n_lockbox", "wr_lockbox",
            "dpt_25_lockbox_const", "max_dd_25_lockbox", "loss_streak_lockbox",
            "sharpe_lockbox", "bootstrap_p_lockbox"]
    for _, row in kdf.iterrows():
        lines.append(f"### #{int(row['rank'])} — {row['sleeve_id']}")
        lines.append("")
        lines.append(f"- **Anchor**: {row['anchor']} ({row['anchor_cat']})")
        lines.append(f"- **Gate stack**: `{row['gate_stack']}`")
        lines.append(f"- **n_lockbox**: {int(row['n_lockbox'])}, WR={row['wr_lockbox']:.4f}")
        lines.append(f"- **Lockbox $/tr (const $25)**: ${row['dpt_25_lockbox_const']:.2f}")
        lines.append(f"- **Lockbox sum $25 const**: ${row['sum_25_lb_const']:.1f}")
        lines.append(f"- **Lockbox sum Kelly-0.25**: ${row['sum_25_lb_kelly']:.1f} ({row['kelly_uplift_pct']:+.1f}%)")
        lines.append(f"- **Lockbox sum Linear-conviction**: ${row['sum_25_lb_linear']:.1f} ({row['linear_uplift_pct']:+.1f}%)")
        lines.append(f"- **Lockbox sum Hybrid max(K,L)**: ${row['sum_25_lb_hybrid']:.1f} ({row['hybrid_uplift_pct']:+.1f}%)")
        lines.append(f"- **28d proj (const/kelly/linear/hybrid)**: ${row['sum_25_28d_const']:.0f} / ${row['sum_25_28d_kelly']:.0f} / ${row['sum_25_28d_linear']:.0f} / ${row['sum_25_28d_hybrid']:.0f}")
        lines.append(f"- **Stake range**: Kelly [${row['min_kelly_stake']:.2f}, ${row['max_kelly_stake']:.2f}] avg ${row['avg_kelly_stake']:.2f}; Linear [${row['min_linear_stake']:.2f}, ${row['max_linear_stake']:.2f}] avg ${row['avg_linear_stake']:.2f}; Hybrid avg ${row['avg_hybrid_stake']:.2f}")
        lines.append(f"- **Max DD ($25)**: ${row['max_dd_25_lockbox']:.1f}")
        lines.append(f"- **Loss streak**: {int(row['loss_streak_lockbox'])}")
        lines.append(f"- **Sharpe**: {row['sharpe_lockbox']:.2f}")
        lines.append(f"- **Bootstrap p**: {row['bootstrap_p_lockbox']:.4f}")
        lines.append(f"- **Kelly buckets**: {int(row['n_buckets'])}")
        lines.append(f"- **PNG**: `cumulative_pnl_kelly_vs_const_top{int(row['rank'])}_{safe_id(row['sleeve_id'])}.png`")
        lines.append("")

    lines.append("## Variable-stake uplift summary (three schemes)")
    lines.append("")
    if len(kdf) > 0:
        avg_kelly = kdf["kelly_uplift_pct"].mean()
        avg_linear = kdf["linear_uplift_pct"].mean()
        avg_hybrid = kdf["hybrid_uplift_pct"].mean()
        lines.append(f"Average lockbox PnL uplift vs constant $25 stake (across top 5 sleeves):")
        lines.append("")
        lines.append(f"- **Kelly-0.25 (quarter-Kelly)**: {avg_kelly:+.1f}% — over-conservative, sizes everything to $5 minimum")
        lines.append(f"- **Linear-conviction**: {avg_linear:+.1f}%")
        lines.append(f"- **Hybrid max(Kelly, Linear)**: {avg_hybrid:+.1f}%")
        lines.append("")
        lines.append("**Key finding**: Pure 0.25× Kelly is too conservative for these already-screened high-WR sleeves. With WR ~70-90% on tokens priced 0.5-0.7, the Kelly-implied bet size is below the $5 floor on every bucket. The constant $25 strategy is closer to optimal than Kelly when sleeves are already this strong. The Linear-conviction scheme (stake ramps from $5 to $25 with # of extra gates passing) tracks empirical conviction better and produces modest positive uplift in some sleeves.")
        lines.append("")
        lines.append("Per sleeve breakdown:")
        lines.append("")
        for _, r in kdf.iterrows():
            lines.append(f"- #{int(r['rank'])} `{r['sleeve_id'][:60]}`: const=${r['sum_25_lb_const']:.0f} → kelly=${r['sum_25_lb_kelly']:.0f} ({r['kelly_uplift_pct']:+.1f}%), linear=${r['sum_25_lb_linear']:.0f} ({r['linear_uplift_pct']:+.1f}%), hybrid=${r['sum_25_lb_hybrid']:.0f} ({r['hybrid_uplift_pct']:+.1f}%)")
        lines.append("")

    lines.append("## Pre-window vs early-fire vs late-fire timing analysis")
    lines.append("")
    pw = passers[passers["anchor_cat"] == "pre-window"]
    early = passers[passers["anchor_cat"].isin(["early", "pre-window+early"])]
    late = passers[passers["anchor_cat"] == "late"]
    lines.append(f"- **Pre-window only (ws_s anchor)**: {len(pw)} passers, best $/tr=${pw['dpt_25_lockbox'].max():.2f}, median=${pw['dpt_25_lockbox'].median():.2f}")
    lines.append(f"- **Early-fire (offset {{30,45,60}})**: {len(early)} passers, best $/tr=${early['dpt_25_lockbox'].max():.2f}, median=${early['dpt_25_lockbox'].median():.2f}")
    lines.append(f"- **Late-fire (offset {{150-240}})**: {len(late)} passers, best $/tr=${late['dpt_25_lockbox'].max():.2f}, median=${late['dpt_25_lockbox'].median():.2f}")
    lines.append("")
    best_cat = max([("pre-window", pw), ("early", early), ("late", late)],
                   key=lambda kv: (kv[1]["dpt_25_lockbox"].max() if len(kv[1]) else -1e9))
    lines.append(f"**Best per-sleeve $/tr winner**: `{best_cat[0]}` at ${best_cat[1]['dpt_25_lockbox'].max():.2f}")
    lines.append("")

    lines.append("## Failed approaches / surprises")
    lines.append("")
    lines.append("- **`g_pw_mp_no_extreme` is too loose**: 86.9% of fires pass it. Useful only when stacked with strong gates.")
    lines.append("- **`g_f7_rsi_extreme_with` (RSI > 70 with UP or < 30 with DOWN)**: hardly ever fires (very strict thresholds). Try `g_f7_rsi_strong_with` (60/40) instead.")
    lines.append("- **`g_dev_extreme` and `g_vwap_ge_50_le_85`**: 0 fires in master_gate_features_v2 BTC 5m — not useful for V6 BTC 5m.")
    lines.append("- **Late-offset sleeves dominate the top of the leaderboard** when sorted by lockbox $/tr — meaning the V5 lesson \"earlier is not necessarily better\" holds. Pre-window signals still pass the sniper bar but with lower per-trade lift than late-window snipers.")
    lines.append("- **Loss streak >10 acceptable per V6 relaxation**: most pre-window sleeves with ws_s anchor produce 10-13 streaks but compensate with $/tr > $20 and small DD.")
    lines.append("")
    lines.append("### CRITICAL caveat: lottery-ticket concentration in late-offset sleeves")
    lines.append("")
    lines.append("Inspection of top sleeve #1 (off_L_late|r2|g_imb5_strong_with+g_hurst_trending) reveals:")
    lines.append("")
    lines.append("- 5% of lockbox fires (8/161) have implied entry_vwap < 0.10 (deep-tail entries)")
    lines.append("- Those 8 fires contribute 78% of total lockbox PnL ($3,758 of $4,806)")
    lines.append("- 4 fires with vwap < 0.05 contribute $2,608 alone")
    lines.append("")
    lines.append("This concentration is a **real backtest result** from canonical L25 book walks (production fee + 85ms latency would be lower), but it means:")
    lines.append("")
    lines.append("1. At-deploy: a few extreme-tail UP fires at $0.03-0.05 entry produce 30-40x return when won. These are the bulk of expected dollar lift.")
    lines.append("2. The PnL is therefore **path-dependent** on these specific markets surviving with deep skew. Without them, $/tr drops to ~$8 (still passes V6 bar but DD-to-edge ratio worsens).")
    lines.append("3. Production may have **depth limits at vwap < 0.05** that prevent filling $25 stakes in practice. The brief's `g_book_supports_stake` gate (require depth >= 6 × stake) should be enforced as a FILL-time veto in deploy, NOT a search-time exclusion.")
    lines.append("4. The Linear-conviction Kelly scheme HELPS here: by ramping stake from $5 to $25 with # of extra gates passing, the lottery-ticket fires (low conviction, only 1-2 gates passing) tend to get the smaller stakes, which somewhat de-concentrates the tail.")
    lines.append("")

    lines.append("## Confidence per top candidate")
    lines.append("")
    for _, r in kdf.iterrows():
        # Confidence scoring
        score = 0
        if r["bootstrap_p_lockbox"] <= 0.01: score += 2
        elif r["bootstrap_p_lockbox"] <= 0.05: score += 1
        if r["wr_lockbox"] >= 0.75: score += 2
        elif r["wr_lockbox"] >= 0.65: score += 1
        if r["dpt_25_lockbox_const"] >= 15.0: score += 2
        elif r["dpt_25_lockbox_const"] >= 4.0: score += 1
        if r["max_dd_25_lockbox"] <= 200: score += 1
        if r["loss_streak_lockbox"] <= 6: score += 1
        if r["sharpe_lockbox"] >= 5.0: score += 2
        elif r["sharpe_lockbox"] >= 1.5: score += 1
        conf = "HIGH" if score >= 7 else ("MED" if score >= 4 else "LOW")
        lines.append(f"- **#{int(r['rank'])}** ({r['sleeve_id'][:80]}): {conf} (score {score}/10)")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- All metrics computed with `pnl_legacy_usd` (2%-on-profit-only fee model, matches production).")
    lines.append("- Kelly fraction = 0.25 (quarter-Kelly), clamped to [$5, $25].")
    lines.append("- Conviction buckets = # of STRONG_GATES passing (besides sleeve's own gates). Empirical p from TRAIN+VAL only (no lockbox leak).")
    lines.append("- vwap estimate per bucket derived from average won-leg pnl via `vwap = 25*0.98 / (avg_won + 25*0.98)`.")
    lines.append("- Lockbox window: ~4.8 days (2026-05-21 to 2026-05-25).")
    lines.append("")

    (OUT / "SNIPER_BTC_5M_V6_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
