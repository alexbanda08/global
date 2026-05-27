"""W2d — Cyclops 3-Axis (N9) + Markov sized leverage (N4) on Hyperliquid.

Ports the Polymarket Cyclops S7 X1 composite (trend / levels / momentum
coherence) to HL perpetuals across (BTC, ETH, SOL) × (5m, 15m, 1h, 4h)
with optional Markov-state leverage sizing.

Axes (futures-adapted)
----------------------
TREND
    20-bar linear-regression slope of close (vol-adaptive sign) AND
    ema_stack_score sign alignment.
    vote = +1 if slope>0 AND ema_stack_score>=1, -1 if slope<0 AND stack<=-1,
    else 0.

LEVELS
    Distance to most-recent `pivot_high` (resistance) and `pivot_low`
    (support) measured in ATR units; require proximity within 0.5 × atr_14
    and a "tested-not-broken" check (bos_buy / bos_sell == 0 in last 3 bars).
    vote = +1 if near support AND not broken down, -1 mirror, else 0.

MOMENTUM
    rsi_14 > 55 → +1; rsi_14 < 45 → -1; else 0. Conflict check on
    `markov_state_fixed` (anti-mean-revert: skip if rsi>55 but markov=-1).

A signal fires when ALL THREE axes agree (and at most ABSTAIN_LIMIT abstain).
Fire DIRECTION = axis consensus sign.

Markov sizing (N4)
------------------
Layered on top of fires:
    LONG  + markov_state ==  1 (BULL)    → 2.0× leverage
    LONG  + markov_state ==  0 (SIDEWAYS)→ 1.0× leverage
    LONG  + markov_state == -1 (BEAR)    → 0.0× → SKIP

    SHORT mirrors with +1 ↔ -1 swap.

Two sub-variants tested per (asset, tf):
    (a) NO_MARKOV — fixed 2× leverage (Cyclops baseline)
    (b) MARKOV_SIZED — 0/1/2× per state above

Hold model:
    fixed N=5 bars (time stop). signal_flip not implemented (would require
    bar-by-bar axis recompute which doesn't materially change the punchline
    at this validation depth).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from strategy_lab.hl_research_2026_05_26.hl_engine import (  # noqa: E402
    HyperliquidConfig,
    run_backtest,
)

PANEL_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Axis primitives                                                              #
# --------------------------------------------------------------------------- #

def _lr_slope_sign(close: np.ndarray, k: int = 20, eps_frac: float = 5e-4) -> np.ndarray:
    """Rolling 20-bar linear-reg slope sign as fraction of mean price.

    Returns int8 in {-1, 0, +1}; first k-1 bars are 0 (warm-up).
    """
    n = close.size
    out = np.zeros(n, dtype=np.int8)
    if n < k:
        return out
    x = np.arange(k, dtype=np.float64)
    xm = x.mean()
    denom = ((x - xm) ** 2).sum()
    if denom <= 0:
        return out
    # Strided window. Avoid the O(n*k) python loop by using sliding_window_view.
    win = np.lib.stride_tricks.sliding_window_view(close, k)        # (n-k+1, k)
    ym = win.mean(axis=1)
    numer = ((x - xm)[None, :] * (win - ym[:, None])).sum(axis=1)
    slope = numer / denom
    frac = slope * k / np.where(ym > 0, ym, np.nan)
    sign = np.where(frac > eps_frac, 1, np.where(frac < -eps_frac, -1, 0))
    out[k - 1:] = sign.astype(np.int8)
    return out


def _trend_vote(panel: pd.DataFrame) -> np.ndarray:
    """Trend axis: slope sign × ema_stack_score sign (must align)."""
    close = panel["close"].to_numpy(dtype=float)
    slope_sign = _lr_slope_sign(close, k=20)
    stack = panel["tr_ema_stack_score"].fillna(0).to_numpy()
    stack_sign = np.where(stack >= 1, 1, np.where(stack <= -1, -1, 0))
    vote = np.where((slope_sign == 1) & (stack_sign == 1), 1,
                    np.where((slope_sign == -1) & (stack_sign == -1), -1, 0))
    return vote.astype(np.int8)


def _levels_vote(panel: pd.DataFrame, atr_mult: float = 0.5) -> np.ndarray:
    """Levels axis: proximity to swing low (long) / high (short).

    pivot_high / pivot_low are sparse (NaN except at the bar that printed
    the pivot). Forward-fill the most-recent pivot price to evaluate
    distance at the current bar. Tested-not-broken via bos_* in last 3 bars.
    """
    close = panel["close"].to_numpy(dtype=float)
    atr = panel["atr_14"].fillna(0).to_numpy()
    # Forward-fill last pivot price (pandas ffill on the raw col).
    p_hi = panel["pivot_high"].ffill().to_numpy()
    p_lo = panel["pivot_low"].ffill().to_numpy()
    # bos_buy / bos_sell are 0/1 flags per bar. Rolling-3 sum gives "broken in last 3".
    bos_buy_3 = panel["bos_buy"].fillna(0).rolling(3, min_periods=1).sum().to_numpy()
    bos_sell_3 = panel["bos_sell"].fillna(0).rolling(3, min_periods=1).sum().to_numpy()
    # Distance in ATR units.
    safe_atr = np.where(atr > 0, atr, np.nan)
    dist_to_lo = np.where(p_lo > 0, (close - p_lo) / safe_atr, np.nan)
    dist_to_hi = np.where(p_hi > 0, (p_hi - close) / safe_atr, np.nan)
    near_support = (dist_to_lo >= 0) & (dist_to_lo <= atr_mult) & (bos_sell_3 == 0)
    near_resist = (dist_to_hi >= 0) & (dist_to_hi <= atr_mult) & (bos_buy_3 == 0)
    vote = np.where(near_support, 1, np.where(near_resist, -1, 0))
    return vote.astype(np.int8)


def _momentum_vote(panel: pd.DataFrame) -> np.ndarray:
    """RSI(14)-based momentum + Markov non-conflict check."""
    rsi = panel["rsi_14"].fillna(50).to_numpy()
    mks = panel["markov_state_fixed"].fillna(0).to_numpy() if "markov_state_fixed" in panel.columns \
          else panel["markov_state"].fillna(0).to_numpy()
    vote = np.where((rsi > 55) & (mks >= 0), 1,
                    np.where((rsi < 45) & (mks <= 0), -1, 0))
    return vote.astype(np.int8)


def _cyclops_signal(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (fire_dir_arr, fire_mask) where fire_dir_arr is +1/-1/0.

    Fires only when all three axes vote the same direction (no abstains).
    """
    t = _trend_vote(panel)
    l = _levels_vote(panel)
    m = _momentum_vote(panel)
    # Coherent: all three are +1 OR all three are -1.
    all_up = (t == 1) & (l == 1) & (m == 1)
    all_dn = (t == -1) & (l == -1) & (m == -1)
    fire_dir = np.where(all_up, 1, np.where(all_dn, -1, 0)).astype(np.int8)
    fire_mask = fire_dir != 0
    return fire_dir, fire_mask


# --------------------------------------------------------------------------- #
# Markov sizing                                                                #
# --------------------------------------------------------------------------- #

def _markov_leverage(markov_state: np.ndarray, direction_arr: np.ndarray) -> np.ndarray:
    """Per-fire leverage given Markov state (−1/0/+1) and trade direction.

    LONG (+1) trades:
        BULL  (+1) → 2.0
        SIDE  ( 0) → 1.0
        BEAR  (−1) → 0.0  (skip)

    SHORT (−1) trades mirror with +1↔−1.
    """
    long_lev = np.where(direction_arr == 1,
                        np.where(markov_state == 1, 2.0,
                                 np.where(markov_state == 0, 1.0, 0.0)),
                        0.0)
    short_lev = np.where(direction_arr == -1,
                         np.where(markov_state == -1, 2.0,
                                  np.where(markov_state == 0, 1.0, 0.0)),
                         0.0)
    return long_lev + short_lev


# --------------------------------------------------------------------------- #
# Backtest runner per (asset, tf, variant)                                     #
# --------------------------------------------------------------------------- #

def _bar_us(tf: str) -> int:
    return {"5m": 5 * 60_000_000, "15m": 15 * 60_000_000,
            "1h": 60 * 60_000_000, "4h": 4 * 60 * 60_000_000}[tf]


def _build_signals(panel: pd.DataFrame, tf: str, hold_bars: int) -> pd.DataFrame:
    """Compute fire times + directions per (asset, tf)."""
    fire_dir, fire_mask = _cyclops_signal(panel)
    if not fire_mask.any():
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us",
                                     "fire_dir", "markov_state"])
    idx = np.where(fire_mask)[0]
    # signal_us = bar close. The engine adds latency and fills at next bar open.
    bar_us = _bar_us(tf)
    open_time_us = panel["ts_us"].to_numpy(dtype=np.int64)
    sig_us = open_time_us[idx] + bar_us            # close of fire bar
    dir_arr = fire_dir[idx]
    mks_col = "markov_state_fixed" if "markov_state_fixed" in panel.columns else "markov_state"
    mks = panel[mks_col].fillna(0).to_numpy()[idx]
    exit_us = sig_us + hold_bars * bar_us
    direction = np.where(dir_arr == 1, "LONG", "SHORT")
    return pd.DataFrame({
        "signal_us": sig_us,
        "direction": direction,
        "exit_us": exit_us,
        "fire_dir": dir_arr,
        "markov_state": mks,
    })


def _run_variant(panel: pd.DataFrame, funding: pd.DataFrame, asset: str,
                 tf: str, variant: str, hold_bars: int = 5,
                 notional_usd: float = 250.0,
                 cfg: HyperliquidConfig | None = None) -> dict:
    """Run one (asset, tf, variant) cell.

    variant ∈ {"baseline_lev2", "markov_sized", "markov_gate"}:
      - baseline_lev2 : fixed 2× leverage on every fire
      - markov_sized  : 0/1/2× per Markov state (per-direction)
      - markov_gate   : 2× when allowed by Markov, 0× (skip) otherwise
    """
    if cfg is None:
        cfg = HyperliquidConfig()
    signals = _build_signals(panel, tf, hold_bars)
    if len(signals) == 0:
        return {
            "asset": asset, "tf": tf, "variant": variant,
            "n_fires": 0, "n_trades": 0, "win_rate": float("nan"),
            "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"),
            "sharpe": float("nan"), "max_dd_usd": 0.0,
            "avg_lev": float("nan"),
        }
    n_fires = len(signals)
    if variant == "baseline_lev2":
        lev_per_trade = np.full(n_fires, 2.0)
    else:
        lev_per_trade = _markov_leverage(
            signals["markov_state"].to_numpy(),
            signals["fire_dir"].to_numpy(),
        )
        if variant == "markov_gate":
            # Binary gate: 2× when state allows, 0× when not.
            lev_per_trade = np.where(lev_per_trade > 0, 2.0, 0.0)

    # Drop zero-leverage signals (skipped trades).
    keep = lev_per_trade > 0
    signals_kept = signals.loc[keep].reset_index(drop=True)
    lev_kept = lev_per_trade[keep]
    n_taken = len(signals_kept)
    if n_taken == 0:
        return {
            "asset": asset, "tf": tf, "variant": variant,
            "n_fires": n_fires, "n_trades": 0, "win_rate": float("nan"),
            "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"),
            "sharpe": float("nan"), "max_dd_usd": 0.0,
            "avg_lev": 0.0,
        }

    # Per-trade leverage requires looping over unique leverages (run_backtest
    # accepts a single leverage scalar). To keep one backtest call, split by lev.
    all_trades = []
    klines = panel[["ts_us", "open", "high", "low", "close"]].rename(
        columns={"ts_us": "open_time_us"})
    for lev_val in np.unique(lev_kept):
        sub_mask = lev_kept == lev_val
        sig_sub = signals_kept.loc[sub_mask, ["signal_us", "direction", "exit_us"]].copy()
        tdf, _stats = run_backtest(
            klines, funding, sig_sub, asset,
            notional_usd=notional_usd, leverage=float(lev_val), cfg=cfg,
        )
        all_trades.append(tdf)
    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    if len(trades_df) == 0:
        return {
            "asset": asset, "tf": tf, "variant": variant,
            "n_fires": n_fires, "n_trades": 0, "win_rate": float("nan"),
            "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"),
            "sharpe": float("nan"), "max_dd_usd": 0.0,
            "avg_lev": float(lev_kept.mean()),
        }
    pnl = trades_df["pnl_net_usd"].to_numpy()
    wins = int((pnl > 0).sum())
    sharpe = float("nan")
    if pnl.std() > 0:
        sharpe = float((pnl.mean() / pnl.std()) * np.sqrt(252))
    cum = np.cumsum(pnl)
    peaks = np.maximum.accumulate(cum)
    max_dd = float((cum - peaks).min()) if len(cum) else 0.0

    return {
        "asset": asset, "tf": tf, "variant": variant,
        "n_fires": int(n_fires),
        "n_trades": int(len(trades_df)),
        "win_rate": float(wins) / len(trades_df),
        "total_pnl_usd": float(pnl.sum()),
        "avg_pnl_usd": float(pnl.mean()),
        "sharpe": sharpe,
        "max_dd_usd": max_dd,
        "avg_lev": float(lev_kept.mean()),
    }


# --------------------------------------------------------------------------- #
# G6 — Monte Carlo bootstrap on PnL                                            #
# --------------------------------------------------------------------------- #

def _bootstrap_sharpe_ci(pnl: np.ndarray, n_boot: int = 10_000,
                         seed: int = 42) -> tuple[float, float]:
    """Return (sharpe_lo, sharpe_hi) at 95% via stationary bootstrap (simple
    resample of trades; trade PnLs are iid in this back-of-envelope)."""
    rng = np.random.default_rng(seed)
    n = pnl.size
    if n < 30:
        return float("nan"), float("nan")
    boots = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        sample = pnl[rng.integers(0, n, size=n)]
        if sample.std() > 0:
            boots[b] = sample.mean() / sample.std() * np.sqrt(252)
        else:
            boots[b] = 0.0
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


# --------------------------------------------------------------------------- #
# Main sweep                                                                   #
# --------------------------------------------------------------------------- #

def main() -> None:
    rows: list[dict] = []
    funding_cache: dict[str, pd.DataFrame] = {}
    for asset in ("BTC", "ETH", "SOL"):
        fpath = FUNDING_DIR / f"{asset}_funding.parquet"
        funding_cache[asset] = pd.read_parquet(fpath)

    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m", "1h", "4h"):
            ppath = PANEL_DIR / f"hl_panel_{asset}_{tf}.parquet"
            if not ppath.exists():
                continue
            panel = pd.read_parquet(ppath)
            # Drop bars without enough history for trend/atr.
            panel = panel.dropna(subset=["atr_14", "rsi_14", "ema_50"]).reset_index(drop=True)
            funding = funding_cache[asset]
            for variant in ("baseline_lev2", "markov_sized", "markov_gate"):
                stats = _run_variant(panel, funding, asset, tf, variant,
                                     hold_bars=5, notional_usd=250.0)
                rows.append(stats)
                print(f"{asset} {tf:>3s} {variant:>14s}  "
                      f"n_fires={stats['n_fires']:>5d}  n={stats['n_trades']:>5d}  "
                      f"wr={stats['win_rate']:.3f}  pnl=${stats['total_pnl_usd']:>+9.0f}  "
                      f"avg=${stats['avg_pnl_usd']:>+7.3f}  sharpe={stats['sharpe']:>5.2f}  "
                      f"dd=${stats['max_dd_usd']:>+8.0f}  lev={stats['avg_lev']:.2f}")

    results = pd.DataFrame(rows)
    results.to_csv(OUT_DIR / "W2d_results.csv", index=False)
    print(f"\nWrote {OUT_DIR / 'W2d_results.csv'} ({len(results)} rows)")

    # ---------------------------------------------------------------------- #
    # G6 bootstrap + G7 regime hold-out on the SINGLE BEST cell.             #
    # ---------------------------------------------------------------------- #
    # Best = highest sharpe with n_trades >= 50 (so bootstrap is meaningful).
    valid = results[(results["n_trades"] >= 50) & (results["sharpe"].notna())].copy()
    if len(valid) == 0:
        print("WARN: no cell with n_trades>=50; skipping G6/G7")
        return
    best = valid.sort_values("sharpe", ascending=False).iloc[0]
    print(f"\n=== BEST CELL ===\n{best.to_dict()}")

    # Re-run best cell to get trades_df (for G6 bootstrap + G7 regime split).
    ppath = PANEL_DIR / f"hl_panel_{best['asset']}_{best['tf']}.parquet"
    panel = pd.read_parquet(ppath).dropna(
        subset=["atr_14", "rsi_14", "ema_50"]).reset_index(drop=True)
    funding = funding_cache[best["asset"]]
    signals = _build_signals(panel, best["tf"], 5)
    lev_arr = _markov_leverage(signals["markov_state"].to_numpy(),
                               signals["fire_dir"].to_numpy()) \
              if best["variant"] != "baseline_lev2" \
              else np.full(len(signals), 2.0)
    if best["variant"] == "markov_gate":
        lev_arr = np.where(lev_arr > 0, 2.0, 0.0)
    keep = lev_arr > 0
    signals_kept = signals.loc[keep].reset_index(drop=True)
    lev_kept = lev_arr[keep]

    klines = panel[["ts_us", "open", "high", "low", "close"]].rename(
        columns={"ts_us": "open_time_us"})
    all_trades = []
    for lev_val in np.unique(lev_kept):
        m2 = lev_kept == lev_val
        s2 = signals_kept.loc[m2, ["signal_us", "direction", "exit_us"]].copy()
        tdf, _ = run_backtest(klines, funding, s2, best["asset"],
                              notional_usd=250.0, leverage=float(lev_val))
        # Re-attach markov_state for regime split.
        tdf["markov_state"] = signals_kept.loc[m2, "markov_state"].to_numpy()
        all_trades.append(tdf)
    trades_df = pd.concat(all_trades, ignore_index=True)
    pnl = trades_df["pnl_net_usd"].to_numpy()

    # G6 bootstrap
    lo, hi = _bootstrap_sharpe_ci(pnl, n_boot=10_000, seed=42)
    print(f"G6 Sharpe 95% CI: [{lo:.3f}, {hi:.3f}]  (lower>0 => pass)")

    # G7 regime hold-out
    g7_rows = []
    for state, label in [(1, "BULL"), (0, "SIDEWAYS"), (-1, "BEAR")]:
        sub = trades_df[trades_df["markov_state"] == state]
        if len(sub) == 0:
            g7_rows.append({"regime": label, "n": 0, "sharpe": float("nan"),
                            "pnl": 0.0, "wr": float("nan")})
            continue
        s_pnl = sub["pnl_net_usd"].to_numpy()
        s_sharpe = float("nan")
        if s_pnl.std() > 0:
            s_sharpe = float((s_pnl.mean() / s_pnl.std()) * np.sqrt(252))
        g7_rows.append({
            "regime": label, "n": int(len(sub)),
            "sharpe": s_sharpe, "pnl": float(s_pnl.sum()),
            "wr": float((s_pnl > 0).mean()),
        })
    print("\nG7 regime hold-out (best cell):")
    for r in g7_rows:
        print(f"  {r['regime']:>8s}  n={r['n']:>4d}  sharpe={r['sharpe']:>5.2f}  "
              f"pnl=${r['pnl']:>+8.0f}  wr={r['wr']:.3f}")

    # Persist a JSON summary for the markdown report.
    summary = {
        "best_cell": {k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
                      for k, v in best.to_dict().items()},
        "g6_sharpe_lo": lo, "g6_sharpe_hi": hi,
        "g7_regimes": g7_rows,
    }
    (OUT_DIR / "W2d_best_cell.json").write_text(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_DIR / 'W2d_best_cell.json'}")


if __name__ == "__main__":
    main()
