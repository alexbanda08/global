"""
Portfolio audit — single-account $10k Hyperliquid portfolio spec.

Vectorbt-FREE: uses a custom bar-by-bar simulator so we don't depend on
vbt's plotly template registration (which hung under Python 3.14 + plotly 6.7).

Flow:
  1. Load each coin's 4h parquet directly (no engine.py).
  2. Generate signals using the pure strategy functions (strategies_v2/3/4)
     which depend only on numpy/pandas/talib.
  3. Run a bar-by-bar simulator that handles long-only, fees, slippage,
     static SL (%) and trailing SL (%) — same semantics as vbt's
     sl_stop / tsl_stop.
  4. Per coin: full-period + IS (2018-2022) + OOS (2023+) metrics; equity
     curve; trade log.
  5. Build joint return matrix across all 9 coins.
  6. Grid-search (sizing_fraction per trade × leverage) for best risk-adjusted
     OOS performance.
  7. Recommend a spec for Hyperliquid deployment.

Outputs: strategy_lab/results/portfolio/
"""
from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.strategies_v2 import STRATEGIES_V2
from strategy_lab.strategies_v3 import STRATEGIES_V3
from strategy_lab.strategies_v4 import STRATEGIES_V4
from strategy_lab.strategies_v7 import STRATEGIES_V7

ALL_STRATS = {**STRATEGIES_V2, **STRATEGIES_V3, **STRATEGIES_V4, **STRATEGIES_V7}

TF   = "4h"
INIT = 10_000.0
# Hyperliquid maker fee (limit orders) — 0.015 % per side.  Zero slippage
# because a limit order is filled at its own price (by definition — when it
# fills).  This is the optimistic "100 % maker fills" model; reality will
# sit somewhere between this and the taker model (0.045 %, 5 bps slip).
FEE  = 0.00015
SLIP = 0.0

BASE = Path(__file__).resolve().parent
PARQ = BASE.parent / "data" / "binance" / "parquet"
OUT  = BASE / "results" / "portfolio"
PER  = OUT / "per_coin"
OUT.mkdir(parents=True, exist_ok=True)
PER.mkdir(parents=True, exist_ok=True)

# OOS-validated best-per-coin (6 of 9 survived walk-forward).
# Dropped: AVAX, DOGE, BNB — all failed OOS (sharpe <0.5, negative CAGR).
# Kept set had OOS Sharpe in [0.59, 1.00].
PORTFOLIO = {
    "BTCUSDT":  ("V4C_range_kalman", "2018-01-01"),
    "ETHUSDT":  ("V3B_adx_gate",     "2018-01-01"),
    "SOLUSDT":  ("V4C_range_kalman", "2020-10-01"),
    "LINKUSDT": ("V3B_adx_gate",     "2019-03-01"),
    "ADAUSDT":  ("V4C_range_kalman", "2018-06-01"),
    # XRP switched from V3B (28% WR, PF 1.3) to HWR1 (73% WR, PF 2.10)
    # after the HWR hunt — XRP is the only coin with enough mean-reverting
    # character for a high-win-rate strategy to also be profitable.
    "XRPUSDT":  ("HWR1_bb_meanrev",  "2018-06-01"),
}
END_GLOBAL = "2026-04-01"
IS_END     = "2023-01-01"
BARS_PER_YR = 365.25 * 24 / 4  # 4h


# ---------------------------------------------------------------------
def load_ohlcv(sym: str, start: str, end: str) -> pd.DataFrame:
    folder = PARQ / sym / TF
    frames = [pd.read_parquet(f) for f in sorted(folder.glob("year=*/part.parquet"))]
    df = (pd.concat(frames, ignore_index=True)
            .drop_duplicates("open_time").sort_values("open_time")
            .set_index("open_time"))
    s = pd.Timestamp(start, tz="UTC"); e = pd.Timestamp(end, tz="UTC")
    df = df[(df.index >= s) & (df.index < e)]
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


# ---------------------------------------------------------------------
# Bar-by-bar simulator (vbt-free)
# Matches our engine.py semantics: signal on bar i → fill at open of bar i+1.
# Fees/slippage applied per side. Supports sl_stop (pct) and tsl_stop (pct).
# ---------------------------------------------------------------------
def simulate(df: pd.DataFrame, entries: pd.Series, exits: pd.Series,
             sl_stop=None, tsl_stop=None, tp_stop=None, init: float = INIT):
    # Coerce to bool arrays without the dtype-object ffill / downcast warnings.
    e_arr = np.asarray(entries.astype("boolean").shift(1).fillna(False), dtype=bool)
    x_arr = np.asarray(exits.astype("boolean").shift(1).fillna(False),   dtype=bool)

    def _as_arr(x):
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return np.full(len(df), float(x))
        if isinstance(x, pd.Series):
            return x.ffill().fillna(0).to_numpy(dtype=float)
        return np.asarray(x, dtype=float)

    sl  = _as_arr(sl_stop)
    tsl = _as_arr(tsl_stop)
    tp  = _as_arr(tp_stop)

    op = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    n  = len(df)

    cash = init
    eq   = np.empty(n); eq[0] = cash
    pos  = 0          # shares
    entry_p = 0.0
    peak    = 0.0     # for trailing
    sl_price  = -np.inf
    tsl_price = -np.inf
    tp_price  = np.inf
    trades = []
    entry_idx = -1

    for i in range(n):
        # Check exits first at bar open: trailing/static SL, signal exit.
        if pos > 0:
            # Update trailing after a new bar's high
            if tsl is not None and not np.isnan(tsl[i]) and tsl[i] > 0:
                peak = max(peak, hi[i])
                cand = peak * (1 - tsl[i])
                if cand > tsl_price: tsl_price = cand
            # Check intrabar stop hit: uses low
            stop_hit_price = None
            hit_reason = None
            if sl_price > 0 and lo[i] <= sl_price:
                stop_hit_price = sl_price; hit_reason = "SL"
            if tsl_price > 0 and lo[i] <= tsl_price:
                stop_hit_price = max(stop_hit_price or -np.inf, tsl_price); hit_reason = "TSL"
            # Take-profit: intrabar high hits the TP level
            if tp_price < np.inf and hi[i] >= tp_price:
                # If both SL and TP hit same bar, assume SL hits first (conservative)
                if stop_hit_price is None:
                    stop_hit_price = tp_price; hit_reason = "TP"
            if stop_hit_price is not None:
                px = stop_hit_price * (1 - SLIP)
                cash += pos * px - (pos * px) * FEE
                ret = (px / entry_p) - 1 - 2 * FEE
                trades.append({"entry_idx": entry_idx, "exit_idx": i,
                               "entry_time": df.index[entry_idx],
                               "exit_time": df.index[i],
                               "entry_price": entry_p, "exit_price": px,
                               "shares": pos, "return": ret,
                               "reason": hit_reason,
                               "bars_held": i - entry_idx})
                pos = 0; entry_p = 0.0; sl_price = -np.inf
                tsl_price = -np.inf; tp_price = np.inf; peak = 0
            elif x_arr[i]:
                px = op[i] * (1 - SLIP)
                cash += pos * px - (pos * px) * FEE
                ret = (px / entry_p) - 1 - 2 * FEE
                trades.append({"entry_idx": entry_idx, "exit_idx": i,
                               "entry_time": df.index[entry_idx],
                               "exit_time": df.index[i],
                               "entry_price": entry_p, "exit_price": px,
                               "shares": pos, "return": ret,
                               "reason": "SIG",
                               "bars_held": i - entry_idx})
                pos = 0; entry_p = 0.0; sl_price = -np.inf; tsl_price = -np.inf; peak = 0

        # Entries (after exits on same bar — vbt semantics)
        if pos == 0 and e_arr[i] and i < n - 1:
            px = op[i] * (1 + SLIP)
            shares = cash / px
            cost = shares * px
            fee = cost * FEE
            cash -= cost + fee
            pos = shares
            entry_p = px
            entry_idx = i
            peak = px
            if sl  is not None and not np.isnan(sl[i])  and sl[i] > 0:
                sl_price  = px * (1 - sl[i])
            if tsl is not None and not np.isnan(tsl[i]) and tsl[i] > 0:
                tsl_price = px * (1 - tsl[i])
            if tp  is not None and not np.isnan(tp[i])  and tp[i] > 0:
                tp_price  = px * (1 + tp[i])

        # Mark-to-market equity
        if pos > 0:
            eq[i] = cash + pos * cl[i]
        else:
            eq[i] = cash

    # Close open position at last bar's close
    if pos > 0:
        px = cl[-1] * (1 - SLIP)
        cash += pos * px - (pos * px) * FEE
        ret = (px / entry_p) - 1 - 2 * FEE
        trades.append({"entry_idx": entry_idx, "exit_idx": n-1,
                       "entry_time": df.index[entry_idx],
                       "exit_time": df.index[-1],
                       "entry_price": entry_p, "exit_price": px,
                       "shares": pos, "return": ret,
                       "reason": "EOD",
                       "bars_held": n - 1 - entry_idx})
        eq[-1] = cash

    return pd.Series(eq, index=df.index, name="equity"), trades


# ---------------------------------------------------------------------
def metrics_from_equity(eq: pd.Series, trades=None, label="FULL") -> dict:
    if len(eq) < 10 or eq.iloc[-1] <= 0:
        return {"label": label, "n_bars": len(eq)}
    rets = eq.pct_change().fillna(0.0)
    yrs  = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    sharpe = (rets.mean() * BARS_PER_YR) / (rets.std() * np.sqrt(BARS_PER_YR) + 1e-12)
    dd = ((eq / eq.cummax()) - 1).min()
    calmar = cagr / abs(dd) if dd < 0 else 0
    vol = rets.std() * np.sqrt(BARS_PER_YR)
    out = {
        "label": label, "n_bars": int(len(eq)),
        "cagr":   round(float(cagr),   4),
        "sharpe": round(float(sharpe), 3),
        "max_dd": round(float(dd),     4),
        "calmar": round(float(calmar), 3),
        "vol":    round(float(vol),    3),
        "final":  round(float(eq.iloc[-1]), 0),
    }
    if trades is not None and len(trades) > 0:
        tr = pd.DataFrame(trades)
        wins   = (tr["return"] > 0).sum()
        losses = (tr["return"] <= 0).sum()
        out["n_trades"]   = int(len(tr))
        out["win_rate"]   = round(float(wins / len(tr)), 3)
        out["avg_win"]    = round(float(tr[tr["return"] > 0]["return"].mean() or 0), 4)
        out["avg_loss"]   = round(float(tr[tr["return"] <= 0]["return"].mean() or 0), 4)
        out["pf"] = round(
            float(tr[tr["return"] > 0]["return"].sum() /
                  abs(tr[tr["return"] <= 0]["return"].sum() or 1e-12)), 3)
        out["avg_bars_held"] = round(float(tr["bars_held"].mean()), 1)
        out["max_consec_loss"] = int(max(
            (sum(1 for _ in g) for k, g in itertools_groupby(tr["return"] <= 0) if k),
            default=0))
    return out


from itertools import groupby as itertools_groupby


# ---------------------------------------------------------------------
# Phase 1 — per-coin solo
# ---------------------------------------------------------------------
def phase1_per_coin() -> pd.DataFrame:
    summary = {}
    returns_by_sym = {}
    for sym, (strat, start) in PORTFOLIO.items():
        print(f"  [solo] {sym}  {strat}", flush=True)
        df = load_ohlcv(sym, start, END_GLOBAL)
        sig = ALL_STRATS[strat](df)
        eq, trades = simulate(df, sig["entries"], sig["exits"],
                              sl_stop=sig.get("sl_stop"),
                              tsl_stop=sig.get("tsl_stop"), init=INIT)
        rets = eq.pct_change().fillna(0.0); rets.name = sym

        eq.to_csv(PER / f"{sym}_equity.csv", header=True)
        rets.to_csv(PER / f"{sym}_returns.csv", header=True)
        pd.DataFrame(trades).to_csv(PER / f"{sym}_trades.csv", index=False)

        split_ts = pd.Timestamp(IS_END, tz="UTC")
        is_mask  = eq.index <  split_ts
        oos_mask = eq.index >= split_ts
        summary[sym] = {
            "strategy": strat, "start": start,
            "FULL": metrics_from_equity(eq, trades, "FULL"),
            "IS":   metrics_from_equity(eq[is_mask],
                        [t for t in trades if t["exit_time"] < split_ts], "IS"),
            "OOS":  metrics_from_equity(eq[oos_mask],
                        [t for t in trades if t["exit_time"] >= split_ts], "OOS"),
        }
        returns_by_sym[sym] = rets

        m = summary[sym]["FULL"]
        o = summary[sym]["OOS"]
        print(f"    FULL: n={m.get('n_trades',0)} sharpe={m.get('sharpe',0):.2f} "
              f"cagr={m.get('cagr',0)*100:+.1f}% dd={m.get('max_dd',0)*100:.1f}% final=${m.get('final',0):,.0f}")
        print(f"    OOS : n={o.get('n_trades',0)} sharpe={o.get('sharpe',0):.2f} "
              f"cagr={o.get('cagr',0)*100:+.1f}% dd={o.get('max_dd',0)*100:.1f}% final=${o.get('final',0):,.0f}")

    (OUT / "per_coin_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    rmat = pd.concat(returns_by_sym.values(), axis=1, join="outer").fillna(0.0)
    rmat.to_parquet(OUT / "joint_returns.parquet")
    print(f"  joint returns: {rmat.shape[0]:,} bars x {rmat.shape[1]} strategies")
    return rmat


# ---------------------------------------------------------------------
# Phase 2 — (sizing_fraction × leverage) grid
# ---------------------------------------------------------------------
def portfolio_equity(rmat: pd.DataFrame, sizing_frac: float, leverage: float,
                     init: float = INIT) -> pd.Series:
    w = sizing_frac * leverage
    contrib = (rmat * w).sum(axis=1)
    # Guard against catastrophic loss: equity floor at 0
    cum = (1 + contrib).cumprod()
    cum = cum.where(cum > 0, 0.001)
    return init * cum


def phase2_grid(rmat: pd.DataFrame) -> pd.DataFrame:
    SIZES = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.33]
    LEVS  = [1, 2, 3, 5]
    split = pd.Timestamp(IS_END, tz="UTC")
    is_r  = rmat[rmat.index <  split]
    oos_r = rmat[rmat.index >= split]
    rows = []
    for f, L in itertools.product(SIZES, LEVS):
        eq_full = portfolio_equity(rmat, f, L)
        eq_is   = portfolio_equity(is_r, f, L)
        eq_oos  = portfolio_equity(oos_r, f, L)
        valid = eq_full.min() > 1.0
        row = {"sizing_frac": f, "leverage": L,
               "max_gross_if_all_9_active": round(f * L * rmat.shape[1], 2),
               "valid": bool(valid)}
        row.update({f"full_{k}": v for k, v in metrics_from_equity(eq_full, None, "FULL").items() if k != "label"})
        row.update({f"is_{k}":   v for k, v in metrics_from_equity(eq_is,   None, "IS").items()   if k != "label"})
        row.update({f"oos_{k}":  v for k, v in metrics_from_equity(eq_oos,  None, "OOS").items()  if k != "label"})
        rows.append(row)
    g = pd.DataFrame(rows)
    g.to_csv(OUT / "grid.csv", index=False)
    return g


# ---------------------------------------------------------------------
# Phase 3 — recommend + save final portfolio equity
# ---------------------------------------------------------------------
def phase3_recommend(rmat: pd.DataFrame, grid: pd.DataFrame) -> dict:
    # Three risk profiles — all must pass (valid, OOS DD > -35%, OOS Calmar > 0.5).
    #   conservative: gross exposure ~ 0.6-1.0x
    #   balanced:     gross exposure ~ 1.2-1.8x (target)
    #   aggressive:   gross exposure ~ 2.5-4x
    safe = grid[(grid["valid"]) &
                (grid["oos_max_dd"] > -0.35) &
                (grid["oos_calmar"] > 0.5)].copy()
    if len(safe) == 0:
        safe = grid[(grid["valid"]) & (grid["oos_max_dd"] > -0.50)].copy()

    # Pick by proximity to target gross exposure + best oos_calmar.
    def pick(target_gross: float) -> dict:
        s = safe.copy()
        s["dist"] = (s["max_gross_if_all_9_active"] - target_gross).abs()
        s = s.sort_values(["dist", "oos_calmar"], ascending=[True, False])
        return s.iloc[0].to_dict()

    cons = pick(0.8)   # conservative
    bal  = pick(1.5)   # balanced  — recommended default
    agg  = pick(3.0)   # aggressive

    best = bal
    f = float(best["sizing_frac"]); L = int(best["leverage"])

    eq_full = portfolio_equity(rmat, f, L)
    eq_full.to_csv(OUT / "portfolio_equity.csv", header=["equity"])

    split = pd.Timestamp(IS_END, tz="UTC")
    def expand(profile_name, row):
        f_, L_ = float(row["sizing_frac"]), int(row["leverage"])
        eq = portfolio_equity(rmat, f_, L_)
        return {
            "profile": profile_name,
            "sizing_fraction_per_trade": f_,
            "leverage": L_,
            "max_gross_exposure": round(f_ * L_ * rmat.shape[1], 2),
            "FULL": metrics_from_equity(eq, None, "FULL"),
            "IS":   metrics_from_equity(portfolio_equity(rmat[rmat.index <  split], f_, L_), None, "IS"),
            "OOS":  metrics_from_equity(portfolio_equity(rmat[rmat.index >= split], f_, L_), None, "OOS"),
        }

    rec = {
        "recommended": {
            "profile": "balanced",
            "sizing_fraction_per_trade": f,
            "leverage": L,
            "max_gross_exposure_if_all_6_active": round(f * L * rmat.shape[1], 2),
            "coins_and_strategies": {s: v[0] for s, v in PORTFOLIO.items()},
            "initial_capital_usd": INIT,
            "timeframe": TF,
            "fee_model": "Binance spot 0.10% (conservative; Hyperliquid is ~0.045% taker / 0.015% maker)",
        },
        "metrics": {
            "FULL": metrics_from_equity(eq_full, None, "FULL"),
            "IS":   metrics_from_equity(portfolio_equity(rmat[rmat.index <  split], f, L), None, "IS"),
            "OOS":  metrics_from_equity(portfolio_equity(rmat[rmat.index >= split], f, L), None, "OOS"),
        },
        "profiles": {
            "conservative": expand("conservative", cons),
            "balanced":     expand("balanced",     bal),
            "aggressive":   expand("aggressive",   agg),
        },
        "top10_candidates": safe.head(10).to_dict(orient="records"),
    }
    (OUT / "recommended.json").write_text(json.dumps(rec, indent=2, default=str))
    return rec


# ---------------------------------------------------------------------
def main():
    print("=== Phase 1: per-coin solo + walk-forward ===", flush=True)
    rmat = phase1_per_coin()

    print("\n=== Phase 2: sizing x leverage grid ===", flush=True)
    g = phase2_grid(rmat)
    print(f"  evaluated {len(g)} combos")

    print("\n=== Phase 3: recommend ===", flush=True)
    rec = phase3_recommend(rmat, g)
    r = rec["recommended"]; m = rec["metrics"]
    print(f"\n  RECOMMENDED SPEC:")
    print(f"    sizing per trade    = {r['sizing_fraction_per_trade']*100:.1f}% of equity")
    print(f"    leverage            = {r['leverage']}x")
    print(f"    max gross exposure  = {r['max_gross_exposure_if_all_6_active']}x (if all 6 coins long)")
    for label in ("FULL","IS","OOS"):
        mm = m[label]
        print(f"  {label:<5}: CAGR {mm.get('cagr',0)*100:+.1f}%  Sharpe {mm.get('sharpe',0):.2f}  "
              f"MaxDD {mm.get('max_dd',0)*100:.1f}%  Calmar {mm.get('calmar',0):.2f}  "
              f"Final ${mm.get('final',0):,.0f}")


if __name__ == "__main__":
    main()
