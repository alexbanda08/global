"""Fair-value + CVD + spike feature overlay on momo fires.

Builds three new features per fire (Baseline_v1+v2 production-equivalent
variants) using 1s binance klines from VPS3:

  1. fair_up = Φ(z) where z = ln(S_now/ref_px) / (sigma_15m·√τ)  — closed-form
     UP-probability for the active slot (mlmodelpoly fair_model.py port).
  2. cvd_30s_slope = (CVD_at_fire − CVD_at_fire−30s) / 30  — order-flow imbalance.
     CVD = cumsum(2·taker_buy_base − volume_traded) on 1s bars.
  3. spike_5s_bps = 10000 · log(close_at_fire / close_at_fire−5s)  — micro-spike flag.

Then buckets fires three ways:

  A. WR vs edge = fair_up − entry_vwap (or (1−fair_up) − entry_vwap_no for DOWN)
  B. WR vs (edge_tier × cvd_agree)
  C. WR vs (edge_tier × spike_direction)

OUTPUT:
  data/v4/canonical/_results/fv_cvd_spike_overlay.csv  — per-fire features
  data/v4/canonical/_results/fv_cvd_spike_summary.csv  — bucketed WR table
  strategy_lab/reports/FV_CVD_SPIKE_BACKTEST_<run_date>.md

Source 1s data: data/v4/canonical/klines_1s/binance_1s_28d.parquet (pulled
2026-05-23 from VPS3 binance_klines_v2; covers 2026-04-30 → 2026-05-22).
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions  # noqa: E402

PT = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_PT = ROOT / "data" / "v4" / "canonical" / "_results" / "fv_cvd_spike_overlay.parquet"
OUT_SUM = ROOT / "data" / "v4" / "canonical" / "_results" / "fv_cvd_spike_summary.csv"

# Slot window per timeframe (seconds).
WINDOW_S = {"5m": 300, "15m": 900}
# σ lookback (seconds). 15m of 1s bars = 900 samples.
SIGMA_LOOKBACK_S = 900
CVD_LAG_S = 30
SPIKE_LAG_S = 5


# ---------------------------------------------------------------------------
# Fair value model (port of mlmodelpoly src/collector/fair_model.py).
# ---------------------------------------------------------------------------

def standard_normal_cdf(x: float) -> float:
    if not math.isfinite(x):
        return 0.5
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_fair_up(
    s_now: float, ref_px: float, sigma_per_sqrt_sec: float, tau_sec: float,
) -> float:
    """Probability S_end > ref_px under log-normal price dynamics.

    sigma_per_sqrt_sec is the per-√second realized vol (so total σ for τ
    seconds = sigma_per_sqrt_sec · √τ).
    """
    if (
        not math.isfinite(s_now) or not math.isfinite(ref_px)
        or s_now <= 0 or ref_px <= 0
        or not math.isfinite(sigma_per_sqrt_sec) or sigma_per_sqrt_sec <= 1e-8
        or not math.isfinite(tau_sec) or tau_sec <= 0
    ):
        return 0.5
    z = math.log(s_now / ref_px) / (sigma_per_sqrt_sec * math.sqrt(tau_sec))
    return standard_normal_cdf(z)


# ---------------------------------------------------------------------------
# 1s feature engine — vectorised per asset.
# ---------------------------------------------------------------------------

def build_1s_features(df_1s: pd.DataFrame) -> pd.DataFrame:
    """Add CVD, log_close, σ_15m to 1s table. Per (symbol_id, source) merged."""
    # Prefer binance-spot-ws when both sources are present at the same ts.
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us", "source"])
    df_1s = df_1s.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us"]).reset_index(drop=True)

    out = []
    for sym, sub in df_1s.groupby("symbol_id", sort=False):
        sub = sub.copy().reset_index(drop=True)
        # CVD delta = 2·taker_buy − total_vol  (signed flow)
        sub["delta_vol"] = 2.0 * sub["taker_buy_base"].fillna(0) - sub["volume_traded"].fillna(0)
        sub["cvd"] = sub["delta_vol"].cumsum()
        sub["log_close"] = np.log(sub["price_close"].replace(0, np.nan))
        # σ_15m: rolling std of log returns over 900 bars, expressed per-√sec.
        # log_ret_1s = log_close[t] − log_close[t−1]; std over 900 samples = σ for 1s.
        # Total σ over τ sec = σ_1s · √τ_sec.
        ret_1s = sub["log_close"].diff()
        sub["sigma_per_sqrt_sec"] = ret_1s.rolling(SIGMA_LOOKBACK_S, min_periods=300).std()
        out.append(sub)
    return pd.concat(out, ignore_index=True)


def asof_indexer(end_us: np.ndarray, target_us: int) -> int:
    i = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if i < 0 or i >= len(end_us):
        return -1
    return i


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"[1] loading 1s klines from {KL1S.name}...")
    df_1s = pd.read_parquet(KL1S)
    print(f"    {len(df_1s):,} rows")

    print(f"[2] building per-symbol feature arrays...")
    df_1s = build_1s_features(df_1s)
    # Map symbol_id → asset code
    sym_map = {
        "BINANCE_SPOT_BTC_USDT": "BTC",
        "BINANCE_SPOT_ETH_USDT": "ETH",
        "BINANCE_SPOT_SOL_USDT": "SOL",
    }
    df_1s["asset"] = df_1s["symbol_id"].map(sym_map)
    # Per-asset numpy arrays for fast asof.
    arrs: dict[str, dict] = {}
    for a in ("BTC", "ETH", "SOL"):
        sub = df_1s[df_1s["asset"] == a].sort_values("time_period_start_us").reset_index(drop=True)
        arrs[a] = {
            "ts": sub["time_period_start_us"].values.astype("int64"),
            "close": sub["price_close"].values.astype("float64"),
            "log_close": sub["log_close"].values.astype("float64"),
            "cvd": sub["cvd"].values.astype("float64"),
            "sigma": sub["sigma_per_sqrt_sec"].values.astype("float64"),
        }
        print(f"    {a}: {len(sub):,} 1s rows; sigma valid={int(np.isfinite(sub.sigma_per_sqrt_sec).sum()):,}")

    print(f"[3] loading per-trade rows + chainlink strikes...")
    pt = pd.read_parquet(PT)
    pt = pt[pt.variant.isin(["Baseline_v1", "Baseline_v2"])].copy().reset_index(drop=True)
    res = load_resolutions()
    res = res.rename(columns={"ticker": "asset", "timeframe": "tf"})
    strike_map = {row.slug: float(row.strike_price) for _, row in res.iterrows()}
    pt["strike"] = pt.slug.map(strike_map)
    miss = int(pt.strike.isna().sum())
    print(f"    {len(pt):,} per-trade rows, {miss:,} missing strike")
    pt = pt[pt.strike.notna()].copy().reset_index(drop=True)

    # slot_end_s = slug-suffix seconds + window_s; tau = slot_end_s − fire_s.
    pt["window_s"] = pt.tf.map(WINDOW_S).astype("int64")
    pt["slot_start_s"] = pt.slug.str.rsplit("-", n=1).str[1].astype("int64")
    pt["slot_end_s"] = pt.slot_start_s + pt.window_s
    pt["tau_sec"] = pt.slot_end_s - pt.fire_s
    pt["fire_us"] = pt.fire_s.astype("int64") * 1_000_000

    print(f"[4] computing fair_up + CVD + spike per fire...")
    fair_up = np.full(len(pt), np.nan)
    cvd_30s_slope = np.full(len(pt), np.nan)
    spike_5s_bps = np.full(len(pt), np.nan)
    s_now_arr = np.full(len(pt), np.nan)
    sigma_arr = np.full(len(pt), np.nan)

    for asset in ("BTC", "ETH", "SOL"):
        m = pt.asset.values == asset
        if not m.any():
            continue
        ts_arr = arrs[asset]["ts"]
        close = arrs[asset]["close"]
        cvd = arrs[asset]["cvd"]
        sigma = arrs[asset]["sigma"]
        log_close = arrs[asset]["log_close"]
        rows = pt[m].reset_index(drop=False)
        for _, r in rows.iterrows():
            t_us = int(r.fire_us)
            idx = asof_indexer(ts_arr, t_us)
            if idx < 0:
                continue
            s_now = float(close[idx])
            sig = float(sigma[idx])
            if not (math.isfinite(s_now) and math.isfinite(sig) and sig > 0):
                continue
            fu = compute_fair_up(s_now, float(r.strike), sig, float(r.tau_sec))
            i_minus_30 = asof_indexer(ts_arr, t_us - 30 * 1_000_000)
            i_minus_5 = asof_indexer(ts_arr, t_us - 5 * 1_000_000)
            slope = float("nan")
            if i_minus_30 >= 0:
                slope = (cvd[idx] - cvd[i_minus_30]) / 30.0
            spk = float("nan")
            if i_minus_5 >= 0 and math.isfinite(log_close[idx]) and math.isfinite(log_close[i_minus_5]):
                spk = (log_close[idx] - log_close[i_minus_5]) * 10000.0
            orig_idx = int(r["index"])
            fair_up[orig_idx] = fu
            cvd_30s_slope[orig_idx] = slope
            spike_5s_bps[orig_idx] = spk
            s_now_arr[orig_idx] = s_now
            sigma_arr[orig_idx] = sig

    pt["fair_up"] = fair_up
    pt["cvd_30s_slope"] = cvd_30s_slope
    pt["spike_5s_bps"] = spike_5s_bps
    pt["s_now"] = s_now_arr
    pt["sigma_per_sqrt_sec"] = sigma_arr

    # Edge per signal direction:
    #   UP fires bet on UP token at entry_vwap → edge_up = fair_up − entry_vwap
    #   DOWN fires bet on DOWN token at entry_vwap → edge_dn = (1−fair_up) − entry_vwap
    # entry_vwap in per_trade_markov is the price PAID for the bet token.
    pt["edge"] = np.where(
        pt.signal == "UP",
        pt.fair_up - pt.entry_vwap,
        (1.0 - pt.fair_up) - pt.entry_vwap,
    )

    # CVD agree: UP fires want positive slope, DOWN fires want negative slope.
    pt["cvd_agree"] = np.where(
        pt.signal == "UP", pt.cvd_30s_slope > 0,
        np.where(pt.signal == "DOWN", pt.cvd_30s_slope < 0, False),
    )

    # Spike agree: UP fires want positive spike, DOWN want negative.
    pt["spike_agree"] = np.where(
        pt.signal == "UP", pt.spike_5s_bps > 5.0,
        np.where(pt.signal == "DOWN", pt.spike_5s_bps < -5.0, False),
    )

    print(f"[5] writing per-fire parquet...")
    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    keep_cols = [
        "variant", "slug", "asset", "tf", "ws", "fire_s", "signal", "won",
        "entry_vwap", "pnl_legacy_usd", "ret_2m", "threshold", "rsi_14", "f7",
        "strike", "tau_sec", "s_now", "sigma_per_sqrt_sec", "fair_up", "edge",
        "cvd_30s_slope", "cvd_agree", "spike_5s_bps", "spike_agree",
    ]
    pt[keep_cols].to_parquet(OUT_PT, index=False, compression="zstd")
    print(f"    wrote {OUT_PT}")

    # ----- bucketing summaries -----
    pt_finite = pt[pt.fair_up.notna() & pt.edge.notna()].copy()
    print(f"\n[6] {len(pt_finite):,} fires with valid features (of {len(pt):,})")

    # A. WR vs edge bucket
    bins = [-1, -0.05, -0.02, 0, 0.02, 0.05, 0.10, 1.0]
    labels = ["<-5pp", "-5..-2pp", "-2..0pp", "0..2pp", "2..5pp", "5..10pp", ">10pp"]
    pt_finite["edge_tier"] = pd.cut(pt_finite.edge, bins=bins, labels=labels)
    sumA = pt_finite.groupby("edge_tier", observed=True).agg(
        n=("won", "count"), wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
    ).round(3)
    print("\n--- A. WR by edge bucket (fair_up − entry_vwap, signed for bet side) ---")
    print(sumA.to_string())

    # B. WR by edge × cvd_agree
    sumB = pt_finite.groupby(["edge_tier", "cvd_agree"], observed=True).agg(
        n=("won", "count"), wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
    ).round(3)
    print("\n--- B. WR by edge × cvd_agree (30s slope same sign as signal) ---")
    print(sumB.to_string())

    # C. WR by edge × spike_agree
    sumC = pt_finite.groupby(["edge_tier", "spike_agree"], observed=True).agg(
        n=("won", "count"), wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
    ).round(3)
    print("\n--- C. WR by edge × spike_agree (5s |ret| > 5bps, same sign) ---")
    print(sumC.to_string())

    # D. Per-cell WR at edge>=2pp (the deployable subset)
    high_edge = pt_finite[pt_finite.edge >= 0.02].copy()
    sumD = high_edge.groupby(["asset", "tf"], observed=True).agg(
        n=("won", "count"), wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
    ).round(3)
    print(f"\n--- D. Per-(asset,tf) WR at edge >= 2pp ({len(high_edge):,} fires) ---")
    print(sumD.to_string())

    # E. Triple stack: edge >= 2pp AND cvd_agree AND |spike_5s_bps| not against signal
    triple = pt_finite[
        (pt_finite.edge >= 0.02) & pt_finite.cvd_agree & (~(
            ((pt_finite.signal == "UP") & (pt_finite.spike_5s_bps < -5.0))
            | ((pt_finite.signal == "DOWN") & (pt_finite.spike_5s_bps > 5.0))
        ))
    ].copy()
    sumE_overall = pd.DataFrame({
        "n": [len(triple)],
        "wr": [float(triple.won.mean()) if len(triple) else float("nan")],
        "avg_pnl": [float(triple.pnl_legacy_usd.mean()) if len(triple) else float("nan")],
        "sum_pnl": [float(triple.pnl_legacy_usd.sum()) if len(triple) else float("nan")],
    }).round(3)
    print(f"\n--- E. TRIPLE STACK: edge >= 2pp & cvd_agree & no-anti-spike ---")
    print(sumE_overall.to_string(index=False))
    sumE_per_cell = triple.groupby(["asset", "tf"], observed=True).agg(
        n=("won", "count"), wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
    ).round(3)
    print("\n  per cell:")
    print(sumE_per_cell.to_string())

    # Save the summary CSV
    sumA["bucket_type"] = "A_edge"
    sumA.to_csv(OUT_SUM)
    print(f"\nSaved: {OUT_SUM}")

    # Markdown report
    md_path = ROOT / "strategy_lab" / "reports" / f"FV_CVD_SPIKE_BACKTEST_{datetime.now(timezone.utc).strftime('%Y_%m_%d')}.md"
    md = []
    md.append(f"# Fair-value + CVD + spike backtest — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    md.append("")
    md.append("Adds three features per momo fire from 1s binance klines (pulled "
              "from VPS3 `binance_klines_v2.period_id='1SEC'`, 28d window):")
    md.append("")
    md.append("- **fair_up** = Φ(z) Black-Scholes UP-probability (mlmodelpoly port)")
    md.append("- **cvd_30s_slope** = (CVD@fire − CVD@fire−30s) / 30; CVD = cumsum(2·taker_buy − total_vol)")
    md.append("- **spike_5s_bps** = 10000·log(close@fire / close@fire−5s)")
    md.append("")
    md.append("**Edge** = `fair_up − entry_vwap` for UP fires, `(1−fair_up) − entry_vwap` for DOWN.")
    md.append("")
    md.append(f"Universe: {len(pt_finite):,} Baseline_v1+v2 fires with valid features.")
    md.append("")
    md.append("## A. WR by edge bucket")
    md.append("")
    md.append(sumA.to_markdown())
    md.append("")
    md.append("## B. WR by edge × CVD agreement")
    md.append("")
    md.append(sumB.to_markdown())
    md.append("")
    md.append("## C. WR by edge × spike agreement")
    md.append("")
    md.append(sumC.to_markdown())
    md.append("")
    md.append("## D. Per-cell WR at edge >= 2pp")
    md.append("")
    md.append(sumD.to_markdown())
    md.append("")
    md.append("## E. Triple stack: edge >= 2pp & cvd_agree & no-anti-spike")
    md.append("")
    md.append("Overall:")
    md.append("")
    md.append(sumE_overall.to_markdown(index=False))
    md.append("")
    md.append("Per cell:")
    md.append("")
    md.append(sumE_per_cell.to_markdown())
    md.append("")
    md.append(f"_per-fire parquet: `{OUT_PT.relative_to(ROOT)}`_")
    md.append(f"_script: `strategy_lab/meta_classifier/fv_cvd_spike_backtest.py`_")
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {md_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
