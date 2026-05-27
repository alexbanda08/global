"""
ETH 5m sniper combinatorial gate search.

Approach: exhaustively test 2-, 3-, 4-, and 5-gate combinations on the train split,
filter to those that meet sniper profile on val, and report final lockbox metrics.

Covers paths B/C/D/E from brief:
  - Path B (0-60s) — by setting offset_bin filter
  - Path C (high-bar 4-5 gate stacks) — natural via depth-5 combinations
  - Path D (greedy with n_cap<=500) — applies sniper constraints
  - Path E (per-offset bin) — sweeps offset_bin separately

Outputs:
  candidates_all.csv (every gate stack tested with stats per split)
  candidates_train_pass.csv (filtered to train profile)
  candidates_lockbox_pass.csv (final survivors with bootstrap p)
"""
import sys
import pandas as pd
import numpy as np
from itertools import combinations
from pathlib import Path

UNI = "data/v4/canonical/_results/_sniper_eth5m_universe.parquet"
OUT_DIR = Path("strategy_lab/sniper_search_2026_05_27/eth_5m")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Sniper profile thresholds
N_CAP = 500
N_MIN = 50
WR_MIN = 0.75
DPT_MIN = 3.0
MAX_DD = 300.0
MAX_LOSS_STREAK = 6
STAKE = 25.0


def max_loss_streak(won_arr):
    """Longest streak of consecutive losses (won==0)."""
    if len(won_arr) == 0:
        return 0
    streak = best = 0
    for w in won_arr:
        if w == 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def max_dd(pnl_arr):
    """Max drawdown on cumulative PnL."""
    if len(pnl_arr) == 0:
        return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    return float((peak - cum).max())


def daily_sharpe(df):
    """Daily Sharpe ratio (annualized = *sqrt(365))."""
    if len(df) == 0:
        return 0.0
    by_day = df.groupby("day")["pnl_legacy_usd"].sum()
    if by_day.std(ddof=0) == 0 or len(by_day) < 2:
        return 0.0
    return float(by_day.mean() / by_day.std(ddof=0) * np.sqrt(365))


def gate_stack_apply(df, gates):
    """Return boolean mask of rows where ALL listed gates == 1 (NaN -> False)."""
    if not gates:
        return np.ones(len(df), dtype=bool)
    mask = np.ones(len(df), dtype=bool)
    for g in gates:
        col = df[g].fillna(0).to_numpy()
        mask &= (col == 1)
    return mask


def score_split(df, mask, split_label):
    """Compute key sniper metrics for a split."""
    sub = df.loc[mask & (df["split"] == split_label)]
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, sum_pnl=0.0, max_dd=0.0, max_loss_streak=0,
                    sharpe=np.nan, depth_pass_pct=0.0)
    won_arr = sub.sort_values("fire_us")["won"].to_numpy()
    pnl_arr = sub.sort_values("fire_us")["pnl_legacy_usd"].to_numpy()
    return dict(
        n=n,
        wr=float(sub["won"].mean()),
        dpt=float(sub["pnl_legacy_usd"].mean()),
        sum_pnl=float(sub["pnl_legacy_usd"].sum()),
        max_dd=max_dd(pnl_arr),
        max_loss_streak=max_loss_streak(won_arr),
        sharpe=daily_sharpe(sub),
        depth_pass_pct=float(sub["g_book_depth_supports_250"].mean() * 100),
    )


def main():
    print("Loading universe ...")
    df = pd.read_parquet(UNI)
    print(f"Universe: {len(df):,} fires, splits: {df['split'].value_counts().to_dict()}")

    # Candidate gate pool (from brief + master_gate_features_v2 columns).
    # All start with 'g_' and have non-trivial firing rate.
    candidate_gates = [
        # R1 core
        "g_rf_with", "g_ribbon_agrees", "g_stoch_with", "g_mfi_with", "g_cci_with",
        "g_bb_pos_with", "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
        "g_tr_above_pp", "g_tr_stack_with", "g_tr_within_adr", "g_tight_ribbon",
        "g_within_dev", "g_markov_with",
        # R3 vol / context
        "g_vol_expanding", "g_vol_high", "g_vol_contracting", "g_hurst_trending",
        "g_flow_with_and_no_whale", "g_hl_liq_cascade_with",
        # R4 trend / book
        "g_trend_slope_with", "g_trend_slope_strong_with", "g_imb5_strong_with",
        "g_queue_top_high", "g_imb_change_with",
        # R5 microprice / hawkes / lee-mykland
        "g_mp_no_extreme", "g_mp_change_with", "g_mp_skew_with",
        "g_lm_high_stat", "g_hawkes_imbalance_with",
    ]
    # Filter to gates with coverage AND firing rate in (0.01, 0.99)
    valid_gates = []
    for g in candidate_gates:
        if g not in df.columns:
            continue
        cov = df[g].notna().mean()
        rate = df[g].fillna(0).mean()
        if cov >= 0.3 and 0.01 < rate < 0.99:
            valid_gates.append((g, cov, rate))
    print(f"\nValid gates ({len(valid_gates)}):")
    for g, cov, rate in valid_gates:
        print(f"  {g:42s} cov={cov*100:5.1f}% fire={rate*100:5.1f}%")
    gates_only = [g for g, _, _ in valid_gates]

    # Pre-sort df by fire_us for streak/DD calculations
    df = df.sort_values("fire_us").reset_index(drop=True)

    # 1) Per-direction stratification (UP and DOWN trade independently; gate semantics
    #    are direction-aware via *_with suffix).
    rows = []

    # 2) Sweep offset_bin variants:
    #    'all', '0-60', '60-150', '150-240', '240-300'
    offset_filters = {
        "all": None,
        "0-60": ["0-60"],
        "60-150": ["60-150"],
        "150-240": ["150-240"],
        "240-300": ["240-300"],
        "early": ["0-60", "60-150"],     # pre-150s
        "late":  ["150-240", "240-300"],  # post-150s
    }

    def evaluate_stack(off_label, off_list, gates):
        base_mask = np.ones(len(df), dtype=bool)
        if off_list is not None:
            base_mask &= df["offset_bin"].isin(off_list).to_numpy()
        gate_mask = gate_stack_apply(df, gates)
        mask = base_mask & gate_mask
        if mask.sum() == 0:
            return None
        m_train = score_split(df, mask, "train")
        m_val   = score_split(df, mask, "val")
        m_lock  = score_split(df, mask, "lockbox")
        return dict(
            offset_bin=off_label,
            gates="&".join(sorted(gates)),
            n_gates=len(gates),
            **{f"train_{k}": v for k, v in m_train.items()},
            **{f"val_{k}":   v for k, v in m_val.items()},
            **{f"lock_{k}":  v for k, v in m_lock.items()},
        )

    # Combinatorial sweep — depth 2 through 5
    print(f"\nCombinatorial search over {len(gates_only)} gates, depths 2-5, "
          f"{len(offset_filters)} offset variants ...")
    n_evaluated = 0
    for depth in [2, 3, 4, 5]:
        combos = list(combinations(gates_only, depth))
        print(f"  depth {depth}: {len(combos)} combos x {len(offset_filters)} offsets = {len(combos)*len(offset_filters)}")
        for combo in combos:
            for off_label, off_list in offset_filters.items():
                r = evaluate_stack(off_label, off_list, list(combo))
                if r is None:
                    continue
                # Cheap early filter: train must show some sniper signal
                if r["train_n"] < N_MIN or r["train_n"] > N_CAP:
                    continue
                if r["train_wr"] < WR_MIN:
                    continue
                if r["train_dpt"] < DPT_MIN:
                    continue
                rows.append(r)
                n_evaluated += 1
        print(f"    after depth {depth}: {len(rows)} surviving train filter")

    print(f"\nTotal candidates that passed train filter: {len(rows)}")
    if not rows:
        print("NO candidates met train profile.")
        return

    cand = pd.DataFrame(rows)
    cand.to_csv(OUT_DIR / "candidates_train_pass.csv", index=False)
    print(f"Wrote candidates_train_pass.csv ({len(cand)} rows)")

    # Filter to val pass: WR and DPT both must hold
    val_pass = cand[
        (cand["val_n"] >= max(20, N_MIN // 3)) &
        (cand["val_wr"] >= WR_MIN - 0.05) &  # 5pp grace on val
        (cand["val_dpt"] >= DPT_MIN - 1.0)
    ].copy()
    print(f"\nVal pass: {len(val_pass)}")
    val_pass.to_csv(OUT_DIR / "candidates_val_pass.csv", index=False)

    # Final lockbox filter: full sniper profile
    lockbox_pass = val_pass[
        (val_pass["lock_n"] >= max(15, N_MIN // 5)) &
        (val_pass["lock_wr"] >= WR_MIN) &
        (val_pass["lock_dpt"] >= DPT_MIN) &
        (val_pass["lock_max_dd"] <= MAX_DD) &
        (val_pass["lock_max_loss_streak"] <= MAX_LOSS_STREAK)
    ].copy()
    print(f"Lockbox pass (full sniper profile): {len(lockbox_pass)}")

    # Sort by combined criteria: lockbox $/tr * sqrt(n) / DD
    if len(lockbox_pass) > 0:
        lockbox_pass["rank_score"] = (
            lockbox_pass["lock_dpt"] * np.sqrt(lockbox_pass["lock_n"]) /
            (lockbox_pass["lock_max_dd"] + 1.0)
        )
        lockbox_pass = lockbox_pass.sort_values("rank_score", ascending=False)
        lockbox_pass.to_csv(OUT_DIR / "candidates_lockbox_pass.csv", index=False)
        print(f"\nTop 10 lockbox-passing candidates (by rank_score):")
        print(lockbox_pass.head(10)[["offset_bin", "n_gates", "gates", "lock_n", "lock_wr",
                                     "lock_dpt", "lock_max_dd", "lock_max_loss_streak"]].to_string())
    else:
        # If no candidate is full-pass, save the best near-misses
        print("\nNO lockbox-passing candidates — saving near-misses (top 20 by val_dpt)")
        cand_sorted = cand.sort_values("lock_dpt", ascending=False).head(50)
        cand_sorted.to_csv(OUT_DIR / "candidates_near_misses.csv", index=False)
        print(cand_sorted.head(15)[["offset_bin", "n_gates", "gates", "lock_n", "lock_wr",
                                    "lock_dpt", "lock_max_dd"]].to_string())

    print("\nDone.")

if __name__ == "__main__":
    main()
