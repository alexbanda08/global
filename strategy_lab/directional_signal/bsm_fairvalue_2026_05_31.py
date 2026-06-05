"""
Black-Scholes Binary Fair Value vs CLOB Price — Backtest
=========================================================
Research hypothesis: an up-down slug is a binary option paying $1 if spot > strike
at slot_end. Theoretical win-prob for "Up" = N(d2), where
  d2 = (ln(S/K) - 0.5*σ²*τ) / (σ*√τ),  drift ≈ 0 over 5–15 min horizon.

Signal: edge = fair_prob_up - implied_up  (implied_up = u_vwap/(u_vwap+d_vwap))
  edge > +thr  → BSM says Up underpriced → buy Up
  edge < -thr  → BSM says Down underpriced → buy Down

Cells: btc_5m, eth_5m, eth_15m, sol_5m, sol_15m
Primary offsets: 60s (5m), 180s (15m)
Threshold sweep: 0.03, 0.05, 0.08, 0.12
Vol estimation: causal trailing realized vol from 1m klines, 30-min window

Usage:
  py -3 strategy_lab/directional_signal/bsm_fairvalue_2026_05_31.py

Output:
  data/v4/canonical/_results/bsm_fairvalue_results.csv  (per-cell gate summary)
  data/v4/canonical/_results/bsm_fairvalue_fires.parquet  (per-trade detail)
  data/v4/canonical/_results/bsm_fairvalue_plateau.csv  (thr x offset plateau)

2026-05-31 Alexandre Bandarra / Claude Code
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
RES = ROOT / "data" / "v4" / "canonical" / "_results"

from load import load_klines, asof_strict  # noqa: E402

# ---------------------------------------------------------------------------
# Import eval infrastructure (settle + gates)
# ---------------------------------------------------------------------------
try:
    from cyclops.validate.permutation import permutation_test
    from cyclops.validate.bootstrap import bootstrap_mean_ci
    from cyclops.validate.walkforward import walkforward_test
except Exception:
    def _settle_vec(won, shares, stake, fee=0.02):
        payoff = shares - stake
        return np.where(won, np.where(payoff > 0, payoff * (1 - fee), payoff), -stake)

    def permutation_test(fired, n_permutations=2000, seed=42, fee_rate=0.02):
        if fired.empty:
            return {"p_value": float("nan"), "observed_mean_pnl": float("nan"), "n_trades": 0}
        d = fired["direction"].values.astype("<U4")
        o = fired["outcome_truth"].values.astype("<U4")
        sh = fired["shares"].values.astype(float)
        st = fired["stake_usd"].values.astype(float)
        obs = float(fired["pnl_usd"].values.mean())
        rng = np.random.default_rng(seed)
        nm = np.empty(n_permutations)
        for i in range(n_permutations):
            p = rng.permutation(o)
            nm[i] = _settle_vec(d == p, sh, st, fee_rate).mean()
        return {"p_value": float((nm >= obs).sum() + 1) / (n_permutations + 1),
                "observed_mean_pnl": obs,
                "observed_wr": float((d == o).mean()),
                "n_trades": int(len(fired))}

    def bootstrap_mean_ci(fired, n_boot=10000, seed=42, alpha=0.05):
        if fired.empty:
            return {"ci_lower": float("nan"), "ci_upper": float("nan"),
                    "observed_mean_pnl": float("nan")}
        pnl = fired["pnl_usd"].values.astype(float)
        n = pnl.size
        rng = np.random.default_rng(seed)
        bm = pnl[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
        return {"ci_lower": float(np.quantile(bm, alpha / 2)),
                "ci_upper": float(np.quantile(bm, 1 - alpha / 2)),
                "observed_mean_pnl": float(pnl.mean())}

    def walkforward_test(fired, train_days=5, test_days=2, pass_threshold_frac=6 / 8):
        if fired.empty:
            return {"n_windows": 0, "n_positive": 0,
                    "verdict": "no_trades", "frac_positive": float("nan")}
        df = fired.copy()
        df["day_idx"] = (df["ws_s"] // 86400).astype(int)
        d0, d1 = df["day_idx"].min(), df["day_idx"].max()
        cur = d0 + train_days
        W = []
        while cur + test_days - 1 <= d1:
            sub = df[(df["day_idx"] >= cur) & (df["day_idx"] <= cur + test_days - 1)]
            if len(sub) >= 5:
                W.append(float(sub["pnl_usd"].mean()) > 0)
            cur += test_days
        nw = len(W)
        npos = sum(W)
        return {"n_windows": nw, "n_positive": npos,
                "frac_positive": (npos / nw) if nw else float("nan"),
                "verdict": "PASS" if nw >= 4 and npos / nw >= pass_threshold_frac
                else ("FAIL" if nw >= 4 else "insufficient_windows")}


# ---------------------------------------------------------------------------
# Cost models (legacy = production parity per CLAUDE.md)
# ---------------------------------------------------------------------------
SECS_PER_YEAR = 365.25 * 24 * 3600
FEE_LEGACY = 0.02   # 2% on profit only
FEE_REALISTIC = 0.07  # 7% taker curve + $0.01 tx (stress-test)
TX_COST = 0.01


def settle_legacy(won, shares, stake, fee=FEE_LEGACY):
    payoff = shares - stake
    return np.where(won, np.where(payoff > 0, payoff * (1 - fee), payoff), -stake)


def settle_realistic(won, shares, vwap, stake, fee_rate=FEE_REALISTIC, tx=TX_COST):
    fee_in = shares * fee_rate * vwap * (1 - vwap)
    gross_win = shares - stake
    return np.where(won, gross_win - fee_in, -stake - fee_in) - tx


SPREAD = {"btc": 0.02, "eth": 0.02, "sol": 0.025}
PX_LO, PX_HI = 0.55, 0.92
PRIMARY_OFFSET = {"5m": 60, "15m": 180}
WINDOW_S = {"5m": 300, "15m": 900}
THRESHOLDS = [0.03, 0.05, 0.08, 0.12]
VOL_WINDOW_S = 30 * 60   # 30-min trailing vol window (in seconds)
VOL_MIN_BARS = 10        # require ≥10 bars for a valid vol estimate


# ---------------------------------------------------------------------------
# vol computation helper — vectorized over an array of fire_us timestamps
# ---------------------------------------------------------------------------
def compute_vol_series(end_us: np.ndarray, price_close: np.ndarray,
                       fire_us_arr: np.ndarray,
                       vol_window_us: int) -> np.ndarray:
    """Causal trailing realized vol (annualized, 1m bars) for each fire timestamp."""
    sigmas = np.full(len(fire_us_arr), np.nan)
    for i, fire_us in enumerate(fire_us_arr):
        t_start_us = int(fire_us) - vol_window_us
        t_end_us = int(fire_us)
        mask = (end_us >= t_start_us) & (end_us <= t_end_us)
        seg = price_close[mask]
        if len(seg) < VOL_MIN_BARS:
            continue
        log_rets = np.diff(np.log(seg.astype(float)))
        if len(log_rets) < VOL_MIN_BARS - 1:
            continue
        # annualize from 1-minute bars
        sigmas[i] = float(np.std(log_rets, ddof=1) * np.sqrt(SECS_PER_YEAR / 60))
    return sigmas


# ---------------------------------------------------------------------------
# BSM N(d2) computation (vectorized)
# ---------------------------------------------------------------------------
def bsm_fair_prob_up(S: np.ndarray, K: np.ndarray,
                     tau_yr: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """N(d2) for binary call, drift=0.
    Returns NaN for invalid inputs.
    """
    valid = (S > 0) & (K > 0) & (tau_yr > 0) & (sigma > 0) & \
            np.isfinite(S) & np.isfinite(K) & np.isfinite(tau_yr) & np.isfinite(sigma)
    d2 = np.full(len(S), np.nan)
    d2[valid] = (np.log(S[valid] / K[valid]) - 0.5 * sigma[valid]**2 * tau_yr[valid]) / \
                (sigma[valid] * np.sqrt(tau_yr[valid]))
    return norm.cdf(d2)


# ---------------------------------------------------------------------------
# Core: compute BSM features for one dirscan parquet
# ---------------------------------------------------------------------------
def compute_bsm_features(df: pd.DataFrame, asset: str, tf: str) -> pd.DataFrame:
    """Add fair_prob_up, implied_up, edge, sigma, tau_yr columns to df."""
    k = load_klines(asset, period_id="1MIN")
    end_us = k["time_period_end_us"].values
    price_close = k["price_close"].values

    vol_window_us = int(VOL_WINDOW_S * 1_000_000)

    print(f"  Computing vol for {len(df)} rows ({asset} {tf})…", flush=True)
    sigmas = compute_vol_series(end_us, price_close, df["fire_us"].values, vol_window_us)

    # Spot price: prefer bin_px, fall back to cl_px
    S = np.where(np.isfinite(df["bin_px"].values), df["bin_px"].values, df["cl_px"].values)
    K = df["strike"].values

    window_s = WINDOW_S[tf]
    tau_s = window_s - df["offset_s"].values
    tau_yr = tau_s.astype(float) / SECS_PER_YEAR

    fair_prob_up = bsm_fair_prob_up(S, K, tau_yr, sigmas)
    implied_up = df["u_vwap"].values / (df["u_vwap"].values + df["d_vwap"].values)
    edge = fair_prob_up - implied_up

    out = df.copy()
    out["S"] = S
    out["sigma"] = sigmas
    out["tau_yr"] = tau_yr
    out["fair_prob_up"] = fair_prob_up
    out["implied_up"] = implied_up
    out["edge"] = edge
    return out


# ---------------------------------------------------------------------------
# Build fired frame for BSM signal
# ---------------------------------------------------------------------------
def build_fired_bsm(d: pd.DataFrame, thr: float, asset: str,
                    px_lo: float = PX_LO, px_hi: float = PX_HI) -> pd.DataFrame:
    """Filter rows where |edge| > thr and both-side fills OK.

    Direction: edge > +thr → buy Up; edge < -thr → buy Down.
    """
    spread = SPREAD[asset]

    # Only rows with valid BSM signal
    valid = d["edge"].notna() & d["fair_prob_up"].notna()
    d = d[valid].copy()

    # Signal
    buy_up = d["edge"] > thr
    buy_down = d["edge"] < -thr
    has_signal = buy_up | buy_down
    d = d[has_signal].copy()
    buy_up = d["edge"] > thr
    buy_down = d["edge"] < -thr

    d["side"] = np.where(buy_up, "Up", "Down")
    is_up = d["side"] == "Up"

    # Fill OK gate
    d["ok"] = np.where(is_up, d["u_ok"], d["d_ok"])
    d = d[d["ok"].fillna(False)].copy()
    if d.empty:
        return d

    is_up = d["side"] == "Up"
    d["vwap"] = np.where(is_up, d["u_vwap"], d["d_vwap"])
    d["shares"] = np.where(is_up, d["u_shares"], d["d_shares"])
    d["stake_usd"] = np.where(is_up, d["u_usd"], d["d_usd"])
    d["ask0"] = np.where(is_up, d["u_ask0"], d["d_ask0"])
    d["bid0"] = np.where(is_up, d["u_bid0"], d["d_bid0"])

    # Price + spread gates
    d = d[(d["vwap"] >= px_lo) & (d["vwap"] <= px_hi)]
    d = d[(d["ask0"] - d["bid0"]) <= spread]
    if d.empty:
        return d

    d["direction"] = d["side"]
    d["won"] = d["direction"] == d["outcome_truth"]
    d["pnl_usd"] = settle_legacy(d["won"].values, d["shares"].values, d["stake_usd"].values)
    d["pnl_realistic"] = settle_realistic(
        d["won"].values, d["shares"].values, d["vwap"].values, d["stake_usd"].values)
    d["ws_s"] = d["slot_start_s"]
    return d


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------
def run_gates(fired: pd.DataFrame) -> dict:
    if len(fired) < 10:
        return {"n": len(fired), "note": "n<10 (G0 fail)"}
    perm = permutation_test(fired, n_permutations=2000, seed=42)
    boot = bootstrap_mean_ci(fired, n_boot=10000, seed=42)
    wf = walkforward_test(fired, train_days=5, test_days=2)
    G1 = fired["pnl_usd"].mean() > 0
    G3 = perm.get("p_value", 1.0) < 0.05
    G4 = boot.get("ci_lower", -1) > 0
    G2 = wf.get("verdict") == "PASS"
    gates_pass = sum([G1, G2, G3, G4])
    return {
        "n": len(fired),
        "wr": round(float(fired["won"].mean()), 4),
        "mean_pnl_legacy": round(float(fired["pnl_usd"].mean()), 4),
        "total_pnl_legacy": round(float(fired["pnl_usd"].sum()), 2),
        "mean_pnl_realistic": round(float(fired["pnl_realistic"].mean()), 4)
            if "pnl_realistic" in fired.columns else None,
        "G1_mean_pos": G1,
        "G2_walkforward": G2,
        "G3_perm_p": round(perm.get("p_value", float("nan")), 4),
        "G3_pass": G3,
        "G4_ci_lo": round(boot.get("ci_lower", float("nan")), 4),
        "G4_pass": G4,
        "wf_n_windows": wf.get("n_windows"),
        "wf_frac_pos": round(wf.get("frac_positive", float("nan")), 3),
        "gates_pass": gates_pass,
        "verdict": "PASS" if gates_pass >= 3 else ("BORDERLINE" if gates_pass == 2 else "FAIL"),
    }


# ---------------------------------------------------------------------------
# Control analysis: correlation of BSM direction with favorite / px_vs_strike
# ---------------------------------------------------------------------------
def control_correlation(d: pd.DataFrame, thr: float) -> dict:
    """Compare BSM signal direction to favorite / px_vs_strike signal."""
    valid = d["edge"].notna()
    d = d[valid].copy()

    bsm_up = (d["edge"] > thr).astype(int)  # 1=Up, 0=Down or no-signal
    bsm_fire = (d["edge"].abs() > thr)
    bsm_dir = np.where(d["edge"] > thr, "Up", np.where(d["edge"] < -thr, "Down", "None"))

    # Favorite: buy the side with higher CLOB price (> 0.5)
    fav_dir = np.where(d["implied_up"] > 0.5, "Up", "Down")

    # px_vs_strike (momentum): buy Up if spot > strike
    mom_dir = np.where(d["px_vs_strike_bps"].fillna(0) > 0, "Up", "Down")

    fired_mask = bsm_fire.values
    bsm_d = bsm_dir[fired_mask]
    fav_d = fav_dir[fired_mask]
    mom_d = mom_dir[fired_mask]

    n = fired_mask.sum()
    if n == 0:
        return {"n_fired": 0, "agree_favorite": float("nan"), "agree_px_vs_strike": float("nan")}

    agree_fav = float((bsm_d == fav_d).mean())
    agree_mom = float((bsm_d == mom_d).mean())

    # When BSM disagrees with both
    disagrees_both = (bsm_d != fav_d) & (bsm_d != mom_d)
    n_disagree = disagrees_both.sum()

    return {
        "n_fired": int(n),
        "agree_favorite": round(agree_fav, 3),
        "agree_px_vs_strike": round(agree_mom, 3),
        "n_disagree_both": int(n_disagree),
        "frac_disagree_both": round(float(n_disagree / n), 3),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    RES.mkdir(parents=True, exist_ok=True)
    MARKETS = [
        ("btc", "5m"), ("eth", "5m"), ("eth", "15m"),
        ("sol", "5m"), ("sol", "15m"),
    ]

    all_rows = []
    plateau_rows = []
    all_fires = []

    for asset, tf in MARKETS:
        mk = f"{asset}_{tf}"
        fn = RES / f"dirscan_{mk}.parquet"
        if not fn.exists():
            print(f"[SKIP] {mk}: dirscan not found")
            continue

        print(f"\n=== {mk} ===")
        raw = pd.read_parquet(fn)

        print(f"  Adding BSM features ({len(raw)} rows)…")
        d = compute_bsm_features(raw, asset, tf)

        # Sanity: BSM close to 0.5 when S≈K
        near_atm = d[d["px_vs_strike_bps"].abs() < 20]
        if len(near_atm) > 0:
            print(f"  Sanity (|px_vs_strike|<20bps): mean fair_prob_up="
                  f"{near_atm['fair_prob_up'].mean():.4f} (expect ~0.5)")

        primary_off = PRIMARY_OFFSET[tf]
        offsets = sorted(d["offset_s"].unique())

        # ---------------------------------------------------------------
        # Threshold x offset sweep
        # ---------------------------------------------------------------
        for off in offsets:
            do = d[d["offset_s"] == off].copy()
            tau_s_left = WINDOW_S[tf] - off

            # BSM–CLOB price closeness stats (before any signal threshold)
            bsm_valid = do["edge"].notna()
            if bsm_valid.sum() > 0:
                abs_edge = do.loc[bsm_valid, "edge"].abs()
                median_abs_edge = float(abs_edge.median())
                mean_abs_edge = float(abs_edge.mean())
                frac_lt5pct = float((abs_edge < 0.05).mean())
                frac_lt10pct = float((abs_edge < 0.10).mean())
            else:
                median_abs_edge = mean_abs_edge = frac_lt5pct = frac_lt10pct = float("nan")

            # Controls for primary offset
            ctrl = control_correlation(do, thr=0.05) if off == primary_off else {}

            for thr in THRESHOLDS:
                fired = build_fired_bsm(do, thr, asset)

                # Plateau row
                plateau_row = {
                    "market": mk, "asset": asset, "tf": tf,
                    "offset_s": off, "thr": thr, "tau_s_remaining": tau_s_left,
                    "n_bsm_valid": int(bsm_valid.sum()),
                    "median_abs_edge": round(median_abs_edge, 4),
                    "mean_abs_edge": round(mean_abs_edge, 4),
                    "frac_abs_edge_lt5pct": round(frac_lt5pct, 3),
                    "frac_abs_edge_lt10pct": round(frac_lt10pct, 3),
                }
                plateau_row.update(ctrl if ctrl else {})

                if len(fired) >= 10:
                    g = run_gates(fired)
                    plateau_row.update({
                        "n": g["n"], "wr": g["wr"],
                        "mean_pnl_legacy": g["mean_pnl_legacy"],
                        "mean_pnl_realistic": g["mean_pnl_realistic"],
                        "G1": g["G1_mean_pos"], "G2": g["G2_walkforward"],
                        "G3_p": g["G3_perm_p"], "G3": g["G3_pass"],
                        "G4_ci_lo": g["G4_ci_lo"], "G4": g["G4_pass"],
                        "gates_pass": g["gates_pass"], "verdict": g["verdict"],
                    })
                    if off == primary_off:
                        all_rows.append({**plateau_row, "market": mk, "thr": thr})
                        # Save fires for per-trade detail
                        fired_save = fired[["slug", "offset_s", "fire_us", "outcome_truth",
                                            "direction", "won", "vwap", "shares", "stake_usd",
                                            "pnl_usd", "pnl_realistic", "ws_s",
                                            "edge", "fair_prob_up", "implied_up", "sigma",
                                            "tau_yr", "S", "strike",
                                            "px_vs_strike_bps"]].copy()
                        fired_save["market"] = mk
                        fired_save["thr"] = thr
                        all_fires.append(fired_save)
                else:
                    plateau_row.update({"n": len(fired), "verdict": "INSUFFICIENT"})

                plateau_rows.append(plateau_row)

        # Per-offset BSM closeness summary (primary only)
        do_p = d[d["offset_s"] == primary_off]
        bsm_valid = do_p["edge"].notna()
        if bsm_valid.sum() > 50:
            abs_e = do_p.loc[bsm_valid, "edge"].abs()
            corr_price = do_p.loc[bsm_valid, ["implied_up", "fair_prob_up"]].corr().iloc[0, 1]
            print(f"  Primary offset={primary_off}s: n_valid={bsm_valid.sum()}, "
                  f"median|edge|={abs_e.median():.4f}, mean|edge|={abs_e.mean():.4f}, "
                  f"corr(implied,fair)={corr_price:.4f}")

    # ---------------------------------------------------------------
    # Save outputs
    # ---------------------------------------------------------------
    results_df = pd.DataFrame(all_rows)
    plateau_df = pd.DataFrame(plateau_rows)

    out_csv = RES / "bsm_fairvalue_results.csv"
    out_plateau = RES / "bsm_fairvalue_plateau.csv"
    out_fires = RES / "bsm_fairvalue_fires.parquet"

    results_df.to_csv(out_csv, index=False)
    plateau_df.to_csv(out_plateau, index=False)

    if all_fires:
        fires_df = pd.concat(all_fires, ignore_index=True)
        fires_df.to_parquet(out_fires, index=False)
    else:
        fires_df = pd.DataFrame()

    print(f"\n=== RESULTS SAVED ===")
    print(f"  {out_csv}")
    print(f"  {out_plateau}")
    print(f"  {out_fires}")

    # ---------------------------------------------------------------
    # Print summary table
    # ---------------------------------------------------------------
    print("\n\n=== BSM FAIRVALUE BACKTEST SUMMARY (primary offsets, thr sweep) ===")
    if not results_df.empty:
        cols_show = ["market", "thr", "n", "wr", "mean_pnl_legacy",
                     "mean_pnl_realistic", "G1", "G2", "G3_p", "G4_ci_lo",
                     "gates_pass", "verdict", "median_abs_edge", "frac_abs_edge_lt5pct",
                     "agree_favorite", "agree_px_vs_strike"]
        cols_show = [c for c in cols_show if c in results_df.columns]
        print(results_df[cols_show].to_string(index=False))

    # ---------------------------------------------------------------
    # Control: how close is CLOB price to N(d2)?
    # ---------------------------------------------------------------
    print("\n\n=== BSM–CLOB CLOSENESS (primary offsets) ===")
    closeness_rows = plateau_df[
        plateau_df["offset_s"].isin(PRIMARY_OFFSET.values())
    ][["market", "offset_s", "n_bsm_valid", "median_abs_edge",
       "mean_abs_edge", "frac_abs_edge_lt5pct", "frac_abs_edge_lt10pct"]].drop_duplicates(
        subset=["market", "offset_s"])
    if not closeness_rows.empty:
        print(closeness_rows.to_string(index=False))

    # ---------------------------------------------------------------
    # Control: BSM direction vs favorite / px_vs_strike
    # ---------------------------------------------------------------
    print("\n\n=== CONTROL: BSM DIRECTION OVERLAP WITH FAVORITE / PX_VS_STRIKE (thr=0.05) ===")
    ctrl_rows = plateau_df[
        (plateau_df["thr"] == 0.05) &
        plateau_df["offset_s"].isin(PRIMARY_OFFSET.values()) &
        plateau_df["n_fired"].notna()
    ][["market", "n_fired", "agree_favorite", "agree_px_vs_strike",
       "n_disagree_both", "frac_disagree_both"]].drop_duplicates("market")
    if not ctrl_rows.empty:
        print(ctrl_rows.to_string(index=False))

    # ---------------------------------------------------------------
    # Deviation-only subset (BSM disagrees with CLOB by >thr but fires OPPOSITE favorite)
    # ---------------------------------------------------------------
    if all_fires and len(fires_df) > 0:
        print("\n\n=== DEVIATION TRADES (BSM disagrees with favorite, thr=0.05, primary offset) ===")
        for mk in fires_df["market"].unique():
            sub = fires_df[(fires_df["market"] == mk) & (fires_df["thr"] == 0.05)].copy()
            if sub.empty:
                continue
            # favorite direction = implied_up > 0.5 → Up
            sub["fav_dir"] = np.where(sub["implied_up"] > 0.5, "Up", "Down")
            sub_dev = sub[sub["direction"] != sub["fav_dir"]]
            if len(sub_dev) < 5:
                continue
            wr = sub_dev["won"].mean()
            mpnl = sub_dev["pnl_usd"].mean()
            print(f"  {mk}: n_deviation={len(sub_dev)}, wr={wr:.3f}, mean_pnl={mpnl:.4f}")

    print("\n=== DONE ===")
    return results_df, fires_df, plateau_df


if __name__ == "__main__":
    main()
