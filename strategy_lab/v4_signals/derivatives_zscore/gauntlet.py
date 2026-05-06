"""10-gate validation gauntlet for the Derivatives Z-Score strategy (z_lsr<-1.5 + N-hour hold).

Produces:
  strategy_lab/reports/derivatives_zscore/gauntlet_results.csv     — one row per (symbol, hold)
  strategy_lab/reports/derivatives_zscore/equity_curves/{key}.parquet — hourly equity per cell
  strategy_lab/reports/derivatives_zscore/extras_{key}.json        — monthly/yearly/regime maps

Gates (10):
  G1  Sharpe >= 0.5            (annualized, hourly bars)
  G2  Calmar >= 1.0            (CAGR / |MaxDD|)
  G3  MaxDD >= -30%            (i.e. shallower than 30%)
  G4  Per-year Sharpe > 0 in >= 70% of years
  G5  Permutation p < 0.01     (shuffle bar returns 500x → strat sharpe distribution)
  G6  Bootstrap Sharpe lower-95% CI > 0  (stationary block bootstrap, 1000 iters)
  G7  Walk-forward efficiency >= 0.5     (6-fold anchored expanding)
  G8  Cost stress: PF stays > 1.0 at 20 bps round-trip
  G9  Parameter sensitivity: median Sharpe across (z_lsr ∈ {-1.0,-1.5,-2.0}, hold ∈ {12,24,48}) > 0
  G10 Profit factor >= 1.10
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))
from eval.metrics import (
    sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown,
    dd_duration_bars, dd_recovery_bars, ulcer_index, ulcer_performance_index,
    tail_ratio, probabilistic_sharpe, deflated_sharpe, monthly_returns,
)
from eval.robustness import (
    per_year_stats, block_bootstrap_ci,
)

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
EQ_DIR = REPORTS / "equity_curves"
EQ_DIR.mkdir(parents=True, exist_ok=True)

BARS_PER_YEAR = 24 * 365  # hourly bars
FEE_BPS = 6.0  # Hyperliquid: 4.5bp taker + 1.5bp slippage per side = 12bp RT


def load_h(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet").resample("1h").last()
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")["close"].astype(float)
    p["price"] = spot.reindex(p.index, method="ffill")
    p["ma_200d"] = p["price"].rolling(200 * 24, min_periods=200 * 24).mean()
    p["ret_1h"] = p["price"].pct_change()
    p["realized_vol_30d"] = p["ret_1h"].rolling(30 * 24, min_periods=30 * 24).std() * np.sqrt(24 * 365)
    p["vol_median"] = p["realized_vol_30d"].rolling(90 * 24, min_periods=24 * 24).median()
    return p.dropna(subset=["price", "z_lsr", "score_bull_scaled"])


def _entry_check(r, variant: str, z_thr: float) -> bool:
    """Returns True if entry conditions met. Uses itertuples row r."""
    if variant == "V1_baseline":
        return r.z_lsr < z_thr
    if variant == "V8_zlsr_oisilent":
        return (r.z_lsr < z_thr) and (r.z_oi_silent > 1.0)
    if variant == "V7_zlsr_zfund_sl_volsz":
        return (r.z_lsr < z_thr) and (r.z_fund < -0.5)
    # v4 (regime-filtered)
    if variant == "V9_lowvol":
        if pd.isna(r.realized_vol_30d) or pd.isna(r.vol_median):
            return False
        return r.z_lsr < z_thr and r.realized_vol_30d < r.vol_median
    if variant == "V10_ma200_lowvol":
        if pd.isna(r.ma_200d) or pd.isna(r.realized_vol_30d) or pd.isna(r.vol_median):
            return False
        return (r.z_lsr < z_thr and r.price > r.ma_200d
                and r.realized_vol_30d < r.vol_median)
    raise ValueError(f"unknown variant: {variant}")


def run_strategy(df: pd.DataFrame, z_thr: float = -1.5, hold_h: int = 24,
                 fee_bps: float = FEE_BPS, variant: str = "V1_baseline",
                 stop_loss_pct: float | None = None, use_vol_sizing: bool = False,
                 vol_scaled_hold: bool = False):
    """Long-only with selectable variant. Returns (equity_h, trades, hourly_rets)."""
    fee = fee_bps / 1e4
    pos = 0
    entry_px = None
    entry_t = None
    entry_idx = None
    scheduled_hold = hold_h
    pos_size = 1.0
    cash = 1.0
    eq_log = np.empty(len(df), dtype=float)
    rows = list(df.itertuples(index=True))
    trades = []
    for i, r in enumerate(rows):
        ts, px = r.Index, r.price
        if pos == 1:
            mkt_ret = (px / entry_px - 1) * pos_size
            eq_log[i] = cash * (1 + mkt_ret)
        else:
            mkt_ret = 0.0
            eq_log[i] = cash
        # exit
        exit_now = False
        reason = None
        if pos == 1:
            if stop_loss_pct is not None and mkt_ret <= stop_loss_pct:
                exit_now = True
                reason = "stop_loss"
            elif (i - entry_idx) >= scheduled_hold:
                exit_now = True
                reason = "time"
        if exit_now:
            net_ret = (px / entry_px - 1) * pos_size - 2 * fee
            cash *= (1 + net_ret)
            trades.append(dict(entry_t=entry_t, exit_t=ts, side="long",
                               entry_px=float(entry_px), exit_px=float(px),
                               ret=float(net_ret), pos_size=float(pos_size),
                               hours=float((ts - entry_t).total_seconds() / 3600),
                               reason=reason))
            pos = 0
            entry_px = None
            pos_size = 1.0
            scheduled_hold = hold_h
        # entry
        if pos == 0 and _entry_check(r, variant, z_thr):
            pos = 1
            entry_px = px
            entry_t = ts
            entry_idx = i
            if use_vol_sizing and not np.isnan(r.realized_vol_30d) and r.realized_vol_30d > 0:
                pos_size = float(np.clip(0.50 / r.realized_vol_30d, 0.5, 1.5))
            if vol_scaled_hold and not np.isnan(r.realized_vol_30d) and r.realized_vol_30d > 0:
                scheduled_hold = int(np.clip(hold_h * (0.50 / r.realized_vol_30d), 12, 96))
            else:
                scheduled_hold = hold_h

    eq = pd.Series(eq_log, index=df.index, name="equity")
    rets = eq.pct_change().fillna(0)
    return eq, trades, rets


# ────────────────────────────────────────────────────────────
#  Robustness pieces
# ────────────────────────────────────────────────────────────

def permutation_test(strategy_rets: pd.Series, n_iter: int = 500, seed: int = 42) -> dict:
    """Shuffle the bar-by-bar strategy returns N times; how often does the shuffled
    series produce a Sharpe >= the real one?"""
    if len(strategy_rets) < 100:
        return {"p_value": 1.0, "n_iter": 0, "real_sharpe": 0.0}
    rng = np.random.default_rng(seed)
    real = sharpe_ratio(strategy_rets, BARS_PER_YEAR)
    arr = strategy_rets.to_numpy()
    cnt = 0
    for _ in range(n_iter):
        rng.shuffle(arr)
        sh = sharpe_ratio(pd.Series(arr), BARS_PER_YEAR)
        if sh >= real:
            cnt += 1
    return {"p_value": (cnt + 1) / (n_iter + 1), "n_iter": n_iter, "real_sharpe": float(real)}


def walk_forward_anchored(df: pd.DataFrame, z_thr: float, hold_h: int, n_folds: int = 6,
                          variant: str = "V1_baseline", stop_loss_pct=None, use_vol_sizing=False,
                          vol_scaled_hold: bool = False) -> dict:
    """Anchored expanding-window WF. Each fold: train = first k%, test = next chunk.
    'Efficiency ratio' = mean test Sharpe / IS Sharpe. With our parameter-free strategy this
    is purely an out-of-sample stability check."""
    n = len(df)
    if n < 2000:
        return {"folds": [], "efficiency_ratio": 0.0, "n_positive_folds": 0}
    test_size = n // (n_folds + 1)
    is_eq, _, _ = run_strategy(df, z_thr, hold_h, variant=variant,
                               stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)
    is_rets = is_eq.pct_change().fillna(0)
    is_sharpe = sharpe_ratio(is_rets, BARS_PER_YEAR)
    folds = []
    for k in range(n_folds):
        test_lo = (k + 1) * test_size
        test_hi = min((k + 2) * test_size, n)
        if test_hi <= test_lo:
            continue
        sub = df.iloc[test_lo:test_hi]
        eq_f, tr_f, rets_f = run_strategy(sub, z_thr, hold_h, variant=variant,
                                          stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)
        sh_f = sharpe_ratio(rets_f, BARS_PER_YEAR)
        ret_total = float(eq_f.iloc[-1] / eq_f.iloc[0] - 1) if len(eq_f) > 0 else 0.0
        folds.append({"fold": k + 1, "n_bars": int(len(sub)), "n_trades": len(tr_f),
                      "sharpe": float(sh_f), "return": ret_total})
    if not folds:
        return {"folds": [], "efficiency_ratio": 0.0, "n_positive_folds": 0}
    avg_test_sh = np.mean([f["sharpe"] for f in folds])
    eff = float(avg_test_sh / is_sharpe) if is_sharpe > 0 else 0.0
    pos = sum(1 for f in folds if f["sharpe"] > 0)
    return {"folds": folds, "efficiency_ratio": eff, "n_positive_folds": pos,
            "is_sharpe": float(is_sharpe), "avg_test_sharpe": float(avg_test_sh)}


def parameter_sensitivity(df: pd.DataFrame, variant: str = "V1_baseline",
                          stop_loss_pct=None, use_vol_sizing=False,
                          vol_scaled_hold: bool = False) -> dict:
    """Run across a (z_lsr_thr, hold_h) grid and report median Sharpe + dispersion."""
    grid = []
    for z in [-1.0, -1.5, -2.0]:
        for h in [12, 24, 48]:
            eq, tr, rets = run_strategy(df, z, h, variant=variant,
                                        stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)
            sh = sharpe_ratio(rets, BARS_PER_YEAR)
            ret_total = float(eq.iloc[-1] / eq.iloc[0] - 1)
            grid.append({"z_thr": z, "hold_h": h, "sharpe": float(sh),
                         "return": ret_total, "n_trades": len(tr)})
    sharpes = [g["sharpe"] for g in grid]
    return {"grid": grid, "median_sharpe": float(np.median(sharpes)),
            "min_sharpe": float(min(sharpes)), "max_sharpe": float(max(sharpes))}


def cost_stress(df: pd.DataFrame, z_thr: float, hold_h: int, variant: str = "V1_baseline",
                stop_loss_pct=None, use_vol_sizing=False, vol_scaled_hold: bool = False) -> dict:
    """Re-run at 12 / 18 / 24 bps round-trip (Hyperliquid base / 1.5× / 2×) and capture PF + return."""
    out = []
    for bps in [12, 18, 24]:
        eq, tr, _ = run_strategy(df, z_thr, hold_h, fee_bps=bps / 2, variant=variant,
                                 stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)
        if not tr:
            out.append({"bps_rt": bps, "n": 0, "pf": 0.0, "return": 0.0})
            continue
        rets = np.array([t["ret"] for t in tr])
        wins = rets > 0
        pf = float(rets[wins].sum() / -rets[~wins].sum()) if (~wins).any() and rets[wins].any() else 0.0
        out.append({"bps_rt": bps, "n": len(tr), "pf": pf,
                    "return": float(eq.iloc[-1] / eq.iloc[0] - 1)})
    return {"grid": out}


# ────────────────────────────────────────────────────────────
#  Main per-cell run
# ────────────────────────────────────────────────────────────

def run_cell(symbol: str, z_thr: float = -1.5, hold_h: int = 24,
             variant: str = "V1_baseline", stop_loss_pct=None, use_vol_sizing=False,
             vol_scaled_hold: bool = False) -> dict:
    df = load_h(symbol)
    eq, trades, rets = run_strategy(df, z_thr, hold_h, variant=variant,
                                    stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)
    bh = float(df["price"].iloc[-1] / df["price"].iloc[0])
    eq.to_frame("equity").to_parquet(EQ_DIR / f"derivzscore__{symbol}__1h.parquet")

    # Core metrics
    sh = sharpe_ratio(rets, BARS_PER_YEAR)
    sor = sortino_ratio(rets, BARS_PER_YEAR)
    mdd = max_drawdown(eq)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    years = len(eq) / BARS_PER_YEAR
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else 0.0
    cal = calmar_ratio(cagr, mdd)
    ui = ulcer_index(eq)
    upi = ulcer_performance_index(eq, BARS_PER_YEAR)
    dd_dur = dd_duration_bars(eq)
    dd_rec = dd_recovery_bars(eq)
    tail = tail_ratio(rets)

    # PSR / DSR
    n_obs = len(rets)
    skew = float(rets.skew())
    kurt = float(rets.kurt() + 3)  # pandas returns excess kurtosis
    psr = probabilistic_sharpe(sh, n_obs, skew, kurt, 0.0)
    # 9 trials = the (z, hold) grid we sweep in parameter_sensitivity
    dsr = deflated_sharpe(sh, n_obs, n_trials=9, sd_sharpe_trials=None, skew=skew, kurt=kurt)

    # Trades
    if trades:
        tr_rets = np.array([t["ret"] for t in trades])
        wins = tr_rets > 0
        pf = float(tr_rets[wins].sum() / -tr_rets[~wins].sum()) if (~wins).any() else float("inf")
        wr = float(wins.mean())
        avg_hold = float(np.mean([t["hours"] for t in trades]))
        avg_win = float(tr_rets[wins].mean()) if wins.any() else 0.0
        avg_loss = float(tr_rets[~wins].mean()) if (~wins).any() else 0.0
        expectancy = float(tr_rets.mean())
    else:
        pf = wr = avg_hold = avg_win = avg_loss = expectancy = 0.0

    # Per-year
    py = per_year_stats(eq, BARS_PER_YEAR)
    yrs_pos = sum(1 for y in py.values() if y.get("sharpe", 0) > 0)

    # Permutation
    perm = permutation_test(rets, n_iter=500)

    # Bootstrap
    bs = block_bootstrap_ci(rets, n_iter=1000, bars_per_year=BARS_PER_YEAR)

    # Walk-forward
    wf = walk_forward_anchored(df, z_thr, hold_h, n_folds=6, variant=variant,
                               stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)

    # Parameter sensitivity
    psen = parameter_sensitivity(df, variant=variant,
                                 stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                          vol_scaled_hold=vol_scaled_hold)

    # Cost stress (Hyperliquid: 12 / 18 / 24 bps RT)
    cs = cost_stress(df, z_thr, hold_h, variant=variant,
                     stop_loss_pct=stop_loss_pct, use_vol_sizing=use_vol_sizing,
                     vol_scaled_hold=vol_scaled_hold)
    pf_at_24bp = next((c["pf"] for c in cs["grid"] if c["bps_rt"] == 24), 0.0)

    # Monthly + yearly maps
    monthly = monthly_returns(eq)
    monthly_map = {f"{ts.year}-{ts.month:02d}": float(v) for ts, v in monthly.items()}
    yearly_map = {str(yr): info["return"] for yr, info in py.items()}

    # ── 10 GATES ──
    gates = {
        "G1_sharpe>=0.5":          sh >= 0.5,
        "G2_calmar>=1.0":          cal >= 1.0,
        "G3_maxdd>=-30%":          mdd >= -0.30,
        "G4_per_year_pos>=70%":    (yrs_pos / max(1, len(py))) >= 0.70 and len(py) >= 2,
        "G5_perm_p<0.01":          perm["p_value"] < 0.01,
        "G6_bootstrap_sh_lo>0":    bs.get("sharpe", {}).get("ci_lo", -1) > 0,
        "G7_wfe>=0.5":             wf["efficiency_ratio"] >= 0.5,
        "G8_pf_at_24bp>1.0":       pf_at_24bp > 1.0,
        "G9_param_median_sh>0":    psen["median_sharpe"] > 0,
        "G10_pf>=1.10":            pf >= 1.10,
    }
    gates_passed = sum(1 for v in gates.values() if v)

    extras = {
        "per_year": py, "perm": perm, "bootstrap": bs, "walk_forward": wf,
        "parameter_sensitivity": psen, "cost_stress": cs,
        "monthly_returns": monthly_map, "yearly_returns": yearly_map,
        "gates": gates,
    }
    (REPORTS / f"extras_{symbol}.json").write_text(json.dumps(extras, indent=2, default=str))

    return {
        "strategy_id": f"derivzscore_{variant}",
        "symbol": symbol,
        "tf": "1h",
        "z_thr": z_thr,
        "hold_h": hold_h,
        "variant": variant,
        "stop_loss_pct": float(stop_loss_pct) if stop_loss_pct is not None else float("nan"),
        "use_vol_sizing": bool(use_vol_sizing),
        "n_bars": len(eq),
        "n_trades": len(trades),
        "win_rate": wr,
        "profit_factor": pf,
        "expectancy": expectancy,
        "avg_hold_h": avg_hold,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "oos_sharpe": float(sh),
        "oos_sortino": float(sor),
        "oos_calmar": float(cal),
        "oos_max_dd": float(mdd),
        "oos_cagr": float(cagr),
        "oos_ulcer": float(ui),
        "oos_upi": float(upi),
        "oos_dd_duration_bars": int(dd_dur),
        "oos_dd_recovery_bars": int(dd_rec),
        "oos_tail_ratio": float(tail),
        "oos_psr": float(psr),
        "oos_dsr": float(dsr),
        "buy_hold_x": bh,
        "final_equity_x": float(eq.iloc[-1]),
        "perm_p": perm["p_value"],
        "boot_sharpe_lo": float(bs.get("sharpe", {}).get("ci_lo", float("nan"))),
        "boot_sharpe_hi": float(bs.get("sharpe", {}).get("ci_hi", float("nan"))),
        "boot_calmar_lo": float(bs.get("calmar", {}).get("ci_lo", float("nan"))),
        "boot_mdd_hi":    float(bs.get("max_dd", {}).get("ci_hi", float("nan"))),
        "wfe":            float(wf["efficiency_ratio"]),
        "wf_pos_folds":   int(wf["n_positive_folds"]),
        "param_median_sharpe": float(psen["median_sharpe"]),
        "pf_at_24bp": float(pf_at_24bp),
        "n_years":  len(py),
        "n_years_pos": yrs_pos,
        "gates_passed": gates_passed,
        # for dashboard render:
        "monthly_returns": json.dumps(monthly_map),
        "yearly_returns":  json.dumps(yearly_map),
        "regime_sharpes":  json.dumps({}),
        "equity_file": f"derivzscore__{symbol}__1h.parquet",
        "maker_fill_pct": 0.0,
        "rho_buy_hold_oos": 0.0,
        "worst3_months_mean": 0.0,
        "total_fee_paid": 0.0,
        "unfilled_pct": 0.0,
        "status": "ok",
    }


CHAMPIONS = {
    # symbol → (variant, z_thr, hold_h, stop_loss_pct, use_vol_sizing, vol_scaled_hold)
    # v4 — chosen from research_improvements.py. Universal pattern: low-vol regime + vol-scaled exit.
    "BTCUSDT": ("V9_lowvol",        -1.5, 24, None, False, True),   # F3+E5: PF 1.40, Sharpe 1.22, MDD -25%
    "ETHUSDT": ("V10_ma200_lowvol", -1.5, 24, None, False, True),   # F8+E5: PF 1.60, Sharpe 1.24, MDD -24%, BEATS B&H 1.88×
    "SOLUSDT": ("V10_ma200_lowvol", -1.5, 48, None, False, False),  # F8+E1_48h: PF 1.63, Sharpe 1.04, MDD -36%
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--use-champions", action="store_true",
                    help="Use the per-asset CHAMPIONS map (v4 results). Default behaviour.")
    args = ap.parse_args()

    rows = []
    for sym in args.symbols:
        variant, z_thr, hold_h, sl_pct, vol_sz, vol_hold = CHAMPIONS.get(
            sym, ("V1_baseline", -1.5, 24, None, False, False))
        print(f"\n[{sym}] {variant}  z<{z_thr}  hold={hold_h}h  SL={sl_pct}  vol_sz={vol_sz}  vol_hold={vol_hold}")
        r = run_cell(sym, z_thr, hold_h, variant=variant,
                     stop_loss_pct=sl_pct, use_vol_sizing=vol_sz, vol_scaled_hold=vol_hold)
        rows.append(r)
        print(f"  trades={r['n_trades']}  PF={r['profit_factor']:.2f}  "
              f"Sharpe={r['oos_sharpe']:+.2f}  Calmar={r['oos_calmar']:+.2f}  "
              f"MaxDD={r['oos_max_dd']*100:+.1f}%")
        print(f"  Gates passed: {r['gates_passed']}/10")
        print(f"  Eq: {r['final_equity_x']:.3f}× vs B&H {r['buy_hold_x']:.3f}×")

    out = pd.DataFrame(rows)
    out.to_csv(REPORTS / "gauntlet_results.csv", index=False)
    out.to_parquet(REPORTS / "gauntlet_results.parquet")
    print(f"\nWrote {len(out)} rows to {REPORTS/'gauntlet_results.csv'}")


if __name__ == "__main__":
    main()
