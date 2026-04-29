"""
polymarket_cross_asset_leader.py — E6: BTC as leading indicator for ETH/SOL.

Hypothesis (from experiments queue):
  BTC moves are leading indicators for ETH/SOL on short timeframes (~10-60s lag).
  Test whether BTC ret_5m at (ETH_window_start - K) predicts ETH outcome better than
  ETH's own ret_5m, OR as a confirming co-signal.

Signal variants (all on ETH and SOL markets only — BTC excluded since BTC predicts itself):
  S0: own_q10                    — ETH/SOL own ret_5m_q10 (baseline)
  S1: btc_lag_K                  — sign(BTC ret_5m at lag K) as PRIMARY signal
  S2: btc_lag_K + own_agree      — bet only when btc_lag_K agrees with own_q10 direction
  S3: btc_lag_K + own_disagree   — divergence signal: when BTC and own disagree,
                                    bet on the LAGGING asset (ETH/SOL) to catch up to BTC

Lag K tested: 0s (synchronous), 30s, 60s, 90s, 120s
  Lag K means BTC ret computed over [ws-K-300, ws-K], i.e. 5min window ending K seconds before ETH ws.

Outputs:
  results/polymarket/cross_asset_leader.csv
  reports/POLYMARKET_CROSS_ASSET_LEADER.md
"""
from __future__ import annotations
from pathlib import Path
import sys
import math
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import load_features, load_trajectories, load_klines_1m, simulate_market

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
TARGET_ASSETS = ["eth", "sol"]  # we don't predict BTC from BTC
REV_BP = 5
LAGS = [0, 30, 60, 90, 120]

OUT_CSV = HERE / "results" / "polymarket" / "cross_asset_leader.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_CROSS_ASSET_LEADER.md"


def add_q10_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Standard own-asset q10 signal."""
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r_abs = df.loc[m, "ret_5m"].abs()
            thr = r_abs.quantile(0.90)
            sel = m & (df.ret_5m.abs() >= thr) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df


def compute_btc_ret_at_lag(btc_k1m: pd.DataFrame, ws: int, lag_s: int) -> float:
    """BTC ret_5m at window ending (ws - lag_s)."""
    end_ts = ws - lag_s
    start_ts = end_ts - 300
    end_idx = btc_k1m.ts_s.searchsorted(end_ts, side="right") - 1
    start_idx = btc_k1m.ts_s.searchsorted(start_ts, side="right") - 1
    if end_idx < 0 or start_idx < 0:
        return float("nan")
    p_end = float(btc_k1m.price_close.iloc[end_idx])
    p_start = float(btc_k1m.price_close.iloc[start_idx])
    if p_start <= 0:
        return float("nan")
    return math.log(p_end / p_start)


def sim_signal(df_signal, traj, k1m, rev_bp=REV_BP, hedge_hold=True):
    """Run hedge-hold simulator on rows with df_signal['signal'] populated."""
    sub = df_signal[df_signal.signal != -1]
    pnls = []
    for _, row in sub.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        p = simulate_market(row, traj_g, k1m[row.asset],
                            target=None, stop=None, rev_bp=rev_bp,
                            merge_aware=False, hedge_hold=hedge_hold)
        if p is not None and np.isfinite(p):
            pnls.append(p)
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"),
                "ci_lo": 0, "ci_hi": 0, "pnl_total": 0, "pnl_mean": 0}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "pnl_total": float(pnls.sum()),
        "pnl_mean": float(pnls.mean()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
    }


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    btc_k = k1m["btc"]

    # Compute BTC ret at all lags for every market (we'll need it for ETH/SOL)
    print("Computing BTC ret at lags for all markets...")
    for L in LAGS:
        col = f"btc_ret_lag{L}"
        feats[col] = feats["window_start_unix"].apply(lambda ws: compute_btc_ret_at_lag(btc_k, int(ws), L))
    own_q10 = add_q10_signal(feats)
    print(f"  rows with own q10 signal: {(own_q10.signal != -1).sum()}")

    # Restrict to ETH and SOL markets (BTC predicts BTC tautologically — exclude)
    target_df = own_q10[own_q10.asset.isin(TARGET_ASSETS)].copy()
    print(f"  ETH+SOL universe: {len(target_df)} markets")

    rows_csv = []

    # ===== S0 baseline: own q10 =====
    s0 = sim_signal(target_df, traj, k1m)
    s0_label = "S0_own_q10"
    rows_csv.append({"variant": s0_label, "lag_s": None, **s0,
                     "trade_rate": float((target_df.signal != -1).mean())})
    print(f"  {s0_label:30s}: n={s0['n']:>4d} hit={s0['hit']*100:5.1f}% ROI={s0['roi']:+6.2f}%")

    # ===== S1: BTC at lag K as PRIMARY signal =====
    # Build q10 threshold on BTC_ret_lag_K within each (asset, tf) cell
    for L in LAGS:
        col = f"btc_ret_lag{L}"
        df_s1 = target_df.copy()
        df_s1["signal"] = -1
        for asset in df_s1.asset.unique():
            for tf in df_s1.timeframe.unique():
                m = (df_s1.asset == asset) & (df_s1.timeframe == tf)
                r_abs = df_s1.loc[m, col].abs()
                if r_abs.dropna().empty:
                    continue
                thr = r_abs.quantile(0.90)
                sel = m & (df_s1[col].abs() >= thr) & df_s1[col].notna()
                df_s1.loc[sel, "signal"] = (df_s1.loc[sel, col] > 0).astype(int)
        s1 = sim_signal(df_s1, traj, k1m)
        label = f"S1_btc_lag{L}_q10"
        rows_csv.append({"variant": label, "lag_s": L, **s1,
                         "trade_rate": float((df_s1.signal != -1).mean())})
        print(f"  {label:30s}: n={s1['n']:>4d} hit={s1['hit']*100:5.1f}% ROI={s1['roi']:+6.2f}%")

    # ===== S2: BTC lag K AND own_q10 agree direction =====
    for L in LAGS:
        col = f"btc_ret_lag{L}"
        df_s2 = target_df.copy()
        # Compute btc q10 signal on lag K within each cell
        df_s2["btc_sig"] = -1
        for asset in df_s2.asset.unique():
            for tf in df_s2.timeframe.unique():
                m = (df_s2.asset == asset) & (df_s2.timeframe == tf)
                r_abs = df_s2.loc[m, col].abs()
                if r_abs.dropna().empty:
                    continue
                thr = r_abs.quantile(0.90)
                sel = m & (df_s2[col].abs() >= thr) & df_s2[col].notna()
                df_s2.loc[sel, "btc_sig"] = (df_s2.loc[sel, col] > 0).astype(int)
        # Take where own_q10 fires AND btc_sig agrees
        df_s2["signal"] = -1
        agree = (df_s2.signal_x_compat() if False else
                 ((df_s2["signal"] == -1) & False))  # placeholder
        # Actually compute agree:
        own_signal = df_s2["signal"].copy()  # original own signal stays in 'signal' from add_q10_signal
        # Use the own signal we built earlier (target_df.signal)
        # Need to reconstruct since we copied
        own_signal_recomputed = target_df.set_index(["asset", "tf" if "tf" in target_df.columns else "timeframe", "slug"])
        # Easier: just use target_df's signal directly (same index alignment)
        df_s2 = df_s2.reset_index(drop=True)
        df_s2["own_sig"] = target_df.reset_index(drop=True)["signal"].values
        agree_up = (df_s2.own_sig == 1) & (df_s2.btc_sig == 1)
        agree_dn = (df_s2.own_sig == 0) & (df_s2.btc_sig == 0)
        df_s2.loc[agree_up | agree_dn, "signal"] = df_s2.loc[agree_up | agree_dn, "own_sig"]

        s2 = sim_signal(df_s2, traj, k1m)
        label = f"S2_own_AND_btc_lag{L}_agree"
        rows_csv.append({"variant": label, "lag_s": L, **s2,
                         "trade_rate": float((df_s2.signal != -1).mean())})
        print(f"  {label:30s}: n={s2['n']:>4d} hit={s2['hit']*100:5.1f}% ROI={s2['roi']:+6.2f}%")

    # ===== S3: divergence — BTC and own DISAGREE → bet on BTC direction (lagging asset catches up) =====
    for L in LAGS:
        col = f"btc_ret_lag{L}"
        df_s3 = target_df.copy().reset_index(drop=True)
        df_s3["btc_sig"] = -1
        for asset in df_s3.asset.unique():
            for tf in df_s3.timeframe.unique():
                m = (df_s3.asset == asset) & (df_s3.timeframe == tf)
                r_abs = df_s3.loc[m, col].abs()
                if r_abs.dropna().empty:
                    continue
                thr = r_abs.quantile(0.90)
                sel = m & (df_s3[col].abs() >= thr) & df_s3[col].notna()
                df_s3.loc[sel, "btc_sig"] = (df_s3.loc[sel, col] > 0).astype(int)
        # When own disagrees with BTC, bet ON BTC's direction (lagging asset reverts to leader)
        df_s3["own_sig"] = target_df.reset_index(drop=True)["signal"].values
        df_s3["signal"] = -1
        # disagree: both signals fire but in different directions
        disagree_btc_up = (df_s3.own_sig == 0) & (df_s3.btc_sig == 1)
        disagree_btc_dn = (df_s3.own_sig == 1) & (df_s3.btc_sig == 0)
        df_s3.loc[disagree_btc_up, "signal"] = 1  # bet UP (follow BTC)
        df_s3.loc[disagree_btc_dn, "signal"] = 0  # bet DOWN (follow BTC)

        s3 = sim_signal(df_s3, traj, k1m)
        label = f"S3_divergence_btc_lag{L}"
        rows_csv.append({"variant": label, "lag_s": L, **s3,
                         "trade_rate": float((df_s3.signal != -1).mean())})
        print(f"  {label:30s}: n={s3['n']:>4d} hit={s3['hit']*100:5.1f}% ROI={s3['roi']:+6.2f}%")

    # ===== Per-asset breakdown for best variant =====
    df_csv = pd.DataFrame(rows_csv)
    s0_row = df_csv[df_csv.variant == "S0_own_q10"].iloc[0]
    challengers = df_csv[df_csv.variant != "S0_own_q10"].copy()
    challengers["lift_vs_s0"] = challengers["roi"] - s0_row["roi"]
    challengers = challengers.sort_values("roi", ascending=False)
    best = challengers.iloc[0]
    print(f"\nBaseline S0 (own q10): n={int(s0_row['n'])} hit={s0_row['hit']*100:.1f}% ROI={s0_row['roi']:+.2f}%")
    print(f"Best variant: {best['variant']}: n={int(best['n'])} hit={best['hit']*100:.1f}% ROI={best['roi']:+.2f}% "
          f"(lift {best['lift_vs_s0']:+.2f}pp)")

    # MD report
    md = ["# Cross-Asset Leader Test (E6) — BTC predicts ETH/SOL\n",
          f"Hypothesis: BTC ret_5m at lag K predicts ETH/SOL outcomes better than (or as confirming filter to) "
          f"ETH/SOL's own ret_5m. Lag K ∈ {LAGS} seconds. Universe: ETH+SOL × q10. "
          f"Exit: hedge-hold rev_bp={REV_BP} (locked baseline).\n",
          "\n## Variant grid (sorted by ROI)\n",
          "| Variant | Lag (s) | n | Trade rate | Hit% | ROI | 95% CI total | vs S0 baseline |",
          "|---|---|---|---|---|---|---|---|"]
    df_sorted = df_csv.sort_values("roi", ascending=False)
    for _, r in df_sorted.iterrows():
        is_baseline = r["variant"] == "S0_own_q10"
        marker = " (baseline)" if is_baseline else (" ★" if r["variant"] == best["variant"] else "")
        lift = (r["roi"] - s0_row["roi"]) if not is_baseline else 0.0
        md.append(f"| {r['variant']}{marker} | "
                  f"{r['lag_s'] if pd.notna(r['lag_s']) else '—'} | "
                  f"{int(r['n'])} | {r['trade_rate']*100:.1f}% | "
                  f"{r['hit']*100 if not np.isnan(r['hit']) else 0:.1f}% | "
                  f"{r['roi']:+.2f}% | "
                  f"[{r['ci_lo']:+.0f}, {r['ci_hi']:+.0f}] | "
                  f"{lift:+.2f}pp |")

    md.append("\n## Verdict\n")
    if best["lift_vs_s0"] > 0:
        md.append(f"Best variant `{best['variant']}` lifts +{best['lift_vs_s0']:.2f}pp over S0 baseline.")
        if best["lift_vs_s0"] >= 2 and best["n"] >= 100:
            md.append("\n✅ **Worth forward-walk validation.** Cross-asset leader signal candidate.")
        else:
            md.append("\n⚠️ Lift exists but small or thin sample. Forward-walk recommended.")
    else:
        md.append(f"All variants UNDERPERFORM S0 baseline. Best is `{best['variant']}` at {best['lift_vs_s0']:+.2f}pp.")
        md.append("\n❌ **No edge from cross-asset leader signal.** "
                  "ETH/SOL's own ret_5m already captures the BTC information that arrives via spot price linkage.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_csv.to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
