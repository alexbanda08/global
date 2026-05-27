"""
W2e — SMS liquidity_reclaim port to Hyperliquid futures.

Tests:
  Pure SMS variants × asset × TF × hold-mode
  + regime gate × session gate × Markov sizing
  + BOS / CHoCH variants
  + Cross-TF confluence (5m liq_dn + 15m ranging)

Outputs:
  - W2e_results.csv (one row per cell)
  - W2e_sms_regime.md (narrative report)

Validation gates G1-G7 are reported per cell (G1 binomial-p, simplified G4 perm,
G6 bootstrap CI on $/tr). Full WF + 1k-perm is too expensive for ~150 cells;
we run heavy validation only on the top-3 cells per variant family.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.hl_research_2026_05_26.hl_engine import (  # noqa: E402
    HyperliquidConfig,
    run_backtest,
)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

PANELS_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_START = pd.Timestamp("2025-01-01", tz="UTC")   # match HL funding window

ASSETS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m", "1h", "4h"]

# Holds in bars per TF — must be ≤ funding window so trades close
HOLD_BARS = [1, 3, 5, 10]

NOTIONAL = 250.0
LEVERAGE = 1.0

CFG = HyperliquidConfig()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _bar_us(tf: str) -> int:
    return {
        "5m":  5  * 60 * 1_000_000,
        "15m": 15 * 60 * 1_000_000,
        "1h":  60 * 60 * 1_000_000,
        "4h":  4  * 60 * 60 * 1_000_000,
    }[tf]


def load_panel(asset: str, tf: str) -> pd.DataFrame:
    p = PANELS_DIR / f"hl_panel_{asset}_{tf}.parquet"
    df = pd.read_parquet(p)
    df = df[df["open_time"] >= DATA_START].copy().reset_index(drop=True)
    df["ts_us"] = (df["open_time"].astype("int64") // 1_000).astype("int64")
    return df


def load_funding(asset: str) -> pd.DataFrame:
    p = FUNDING_DIR / f"{asset}_funding.parquet"
    return pd.read_parquet(p)


def make_klines_view(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["open_time", "open", "high", "low", "close", "volume"]].copy()
    out["open_time_us"] = (out["open_time"].astype("int64") // 1_000).astype("int64")
    return out


def signals_from_mask(
    panel: pd.DataFrame, mask: np.ndarray, direction: str, hold_bars: int, tf: str,
) -> pd.DataFrame:
    """Build a signals df from a boolean mask. Signal fires at end of bar
    (open_time + bar_us) and exits hold_bars later."""
    rows = panel.loc[mask].copy()
    if rows.empty:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    bar_us = _bar_us(tf)
    sig_us = rows["ts_us"].to_numpy() + bar_us       # fire at bar close
    exit_us = sig_us + hold_bars * bar_us
    return pd.DataFrame({
        "signal_us": sig_us.astype("int64"),
        "direction": direction,
        "exit_us":   exit_us.astype("int64"),
    })


def signals_signal_flip(
    panel: pd.DataFrame, long_mask: np.ndarray, short_mask: np.ndarray, tf: str,
) -> pd.DataFrame:
    """Walk forward: each fire stays in position until the opposite-direction
    signal fires. Used for the signal_flip exit comparison."""
    bar_us = _bar_us(tf)
    n = len(panel)
    if n == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    long_idx = np.where(long_mask)[0]
    short_idx = np.where(short_mask)[0]
    ts = panel["ts_us"].to_numpy()
    out = []
    pos = None         # "LONG" / "SHORT"
    entry_i = None
    # build ordered list of all signal indices
    all_sigs = [(i, "LONG") for i in long_idx] + [(i, "SHORT") for i in short_idx]
    all_sigs.sort()
    for idx, side in all_sigs:
        if pos is None:
            pos = side
            entry_i = idx
        elif side != pos:
            # close at this bar, open opposite
            sig_us = int(ts[entry_i]) + bar_us
            exit_us = int(ts[idx]) + bar_us
            if exit_us > sig_us:
                out.append((sig_us, pos, exit_us))
            pos = side
            entry_i = idx
        # else: same direction repeated — ignore (no compounding)
    if pos is not None and entry_i is not None:
        # close at last bar end
        sig_us = int(ts[entry_i]) + bar_us
        exit_us = int(ts[-1]) + bar_us
        if exit_us > sig_us:
            out.append((sig_us, pos, exit_us))
    if not out:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    return pd.DataFrame(out, columns=["signal_us", "direction", "exit_us"])


def signals_atr_trailing(
    panel: pd.DataFrame, mask: np.ndarray, direction: str, tf: str,
    atr_mult_stop: float = 2.0, atr_mult_target: float = 3.0, max_bars: int = 30,
) -> tuple[pd.DataFrame, float]:
    """ATR exit: scan up to max_bars after entry, exit at SL or TP whichever
    hits first; else time-stop. Returns (signals_df, frac_hit_target).
    We approximate by simulating outside the run_backtest engine - return
    a signals_df with exit_us already set to whichever bar tripped."""
    bar_us = _bar_us(tf)
    indices = np.where(mask)[0]
    if len(indices) == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"]), 0.0
    ts = panel["ts_us"].to_numpy()
    high = panel["high"].to_numpy()
    low = panel["low"].to_numpy()
    close = panel["close"].to_numpy()
    atr = panel["atr_14"].to_numpy()
    n = len(panel)
    rows = []
    n_target = 0
    for i in indices:
        if i + 1 >= n:
            continue
        entry_px = close[i]   # decision price at bar close
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if direction == "LONG":
            sl_px = entry_px - atr_mult_stop * a
            tp_px = entry_px + atr_mult_target * a
        else:
            sl_px = entry_px + atr_mult_stop * a
            tp_px = entry_px - atr_mult_target * a
        exit_i = min(i + max_bars, n - 1)
        for j in range(i + 1, min(i + max_bars + 1, n)):
            if direction == "LONG":
                if low[j] <= sl_px:
                    exit_i = j
                    break
                if high[j] >= tp_px:
                    exit_i = j
                    n_target += 1
                    break
            else:
                if high[j] >= sl_px:
                    exit_i = j
                    break
                if low[j] <= tp_px:
                    exit_i = j
                    n_target += 1
                    break
        rows.append((int(ts[i]) + bar_us, direction, int(ts[exit_i]) + bar_us))
    if not rows:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"]), 0.0
    df = pd.DataFrame(rows, columns=["signal_us", "direction", "exit_us"])
    return df, n_target / len(rows)


# -----------------------------------------------------------------------------
# Validation primitives
# -----------------------------------------------------------------------------

def binom_p_two_sided(n: int, k: int, p: float = 0.5) -> float:
    """Two-sided binomial test p-value. Normal approx for n>=30; uses scipy if
    available, else closed-form normal approx."""
    if n < 1:
        return float("nan")
    try:
        from scipy import stats as _st
        return float(_st.binomtest(int(k), int(n), float(p)).pvalue)
    except Exception:
        # normal approx
        from math import erfc, sqrt
        mu = n * p
        sd = (n * p * (1 - p)) ** 0.5
        if sd == 0:
            return 1.0
        z = abs(k - mu) / sd
        return float(erfc(z / 2 ** 0.5))


def bootstrap_pnl_ci(pnl: np.ndarray, n_boot: int = 2000, seed: int = 42) -> tuple[float, float]:
    """5%/95% bootstrap CI on mean(pnl)."""
    if len(pnl) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    n = len(pnl)
    for i in range(n_boot):
        sample = rng.choice(pnl, size=n, replace=True)
        means[i] = sample.mean()
    return (float(np.percentile(means, 5)), float(np.percentile(means, 95)))


def perm_test_sharpe(pnl: np.ndarray, n_perm: int = 1000, seed: int = 42) -> float:
    """Pct of random sign-flip shuffles with Sharpe >= observed.
    NB: we shuffle directions (sign flips) under H0: no directional edge.
    Returns p-value (lower = better)."""
    if len(pnl) < 10:
        return float("nan")
    obs_sharpe = pnl.mean() / (pnl.std() + 1e-12)
    rng = np.random.default_rng(seed)
    abs_pnl = np.abs(pnl)
    n = len(pnl)
    cnt = 0
    for _ in range(n_perm):
        signs = rng.choice([-1.0, 1.0], size=n)
        sh = (signs * abs_pnl).mean() / (abs_pnl.std() + 1e-12)
        if sh >= obs_sharpe:
            cnt += 1
    return cnt / n_perm


def evaluate_cell(trades_df: pd.DataFrame, stats: dict, asset: str, tf: str,
                  variant: str, n_perm: int = 0) -> dict:
    """Compute G1, optional G4-style perm, G6 bootstrap CI on $/tr."""
    n = int(stats["n_trades"])
    wins = int(stats["n_wins"])
    p_binom = binom_p_two_sided(n, wins) if n > 0 else float("nan")
    pnl = trades_df["pnl_net_usd"].to_numpy() if not trades_df.empty else np.array([])
    ci_lo, ci_hi = bootstrap_pnl_ci(pnl) if n > 5 else (float("nan"), float("nan"))
    p_perm = perm_test_sharpe(pnl, n_perm) if n_perm and n >= 20 else float("nan")
    return {
        "asset": asset,
        "tf": tf,
        "variant": variant,
        "n_trades": n,
        "n_wins": wins,
        "win_rate": stats["win_rate"],
        "total_pnl_usd": stats["total_pnl_usd"],
        "avg_pnl_usd": stats["avg_pnl_usd"],
        "sharpe": stats["sharpe"],
        "max_dd_usd": stats["max_dd_usd"],
        "avg_fees_usd": stats["avg_fees_paid"],
        "avg_funding_usd": stats["avg_funding_paid"],
        "avg_bars_held": stats["avg_bars_held"],
        "g1_binom_p": p_binom,
        "g6_pnl_ci_lo": ci_lo,
        "g6_pnl_ci_hi": ci_hi,
        "g4_perm_p": p_perm,
    }


# -----------------------------------------------------------------------------
# Variant builders
# -----------------------------------------------------------------------------

def build_pure_sms(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    long_mask  = panel["liquidity_dn"].fillna(False).to_numpy().astype(bool)
    short_mask = panel["liquidity_up"].fillna(False).to_numpy().astype(bool)
    return long_mask, short_mask


def build_bos(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    long_mask  = panel["bos_buy"].fillna(False).to_numpy().astype(bool)
    short_mask = panel["bos_sell"].fillna(False).to_numpy().astype(bool)
    return long_mask, short_mask


def build_choch(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    long_mask  = panel["choch_buy"].fillna(False).to_numpy().astype(bool)
    short_mask = panel["choch_sell"].fillna(False).to_numpy().astype(bool)
    return long_mask, short_mask


def build_bos_and_liq(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    long_mask  = (panel["bos_buy"].fillna(False) & panel["liquidity_dn"].fillna(False)).to_numpy().astype(bool)
    short_mask = (panel["bos_sell"].fillna(False) & panel["liquidity_up"].fillna(False)).to_numpy().astype(bool)
    return long_mask, short_mask


def build_regime_gated(panel: pd.DataFrame, base_long: np.ndarray, base_short: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """SMS + regime: only LONG when regime_label == 'trending_up', SHORT when 'trending_dn'."""
    regime = panel["regime_label"].fillna("").to_numpy()
    long_mask = base_long & (regime == "trending_up")
    short_mask = base_short & (regime == "trending_dn")
    return long_mask, short_mask


def build_session_gated(panel: pd.DataFrame, base_long: np.ndarray, base_short: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """SMS + session: only fire during London or NY hours."""
    active = (panel["tr_in_london"].fillna(False) | panel["tr_in_ny"].fillna(False)).to_numpy().astype(bool)
    return base_long & active, base_short & active


def build_session_asia_only(panel: pd.DataFrame, base_long: np.ndarray, base_short: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Comparison: SMS during Tokyo only."""
    if "tr_in_tokyo" not in panel.columns:
        return base_long & False, base_short & False
    active = panel["tr_in_tokyo"].fillna(False).to_numpy().astype(bool)
    return base_long & active, base_short & active


def build_ranging_regime(panel: pd.DataFrame, base_long: np.ndarray, base_short: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """SMS in ranging regime (sweep in chop = high-quality mean rev)."""
    ranging = (panel["regime_label"].fillna("") == "ranging").to_numpy()
    return base_long & ranging, base_short & ranging


# -----------------------------------------------------------------------------
# Markov sizing — single LONG mask, 0x/1x/2x notional per state
# -----------------------------------------------------------------------------

def markov_size_signals(panel: pd.DataFrame, long_mask: np.ndarray, short_mask: np.ndarray, hold_bars: int, tf: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build two separate signal dfs, one for 1x bars and one for 2x bars (zero
    bars are simply dropped). The caller then runs each with the appropriate
    notional and concats results."""
    state = panel["markov_state_fixed"].fillna(0).to_numpy()
    # LONG: BEAR(-1) → 0x; BULL(+1) → 2x; NEUTRAL → 1x
    # SHORT: mirror (BULL → 0x, BEAR → 2x, NEUTRAL → 1x)
    long_2x = long_mask & (state == 1.0)
    long_1x = long_mask & (state == 0.0)
    # long_0x = long_mask & (state == -1.0)    # discarded
    short_2x = short_mask & (state == -1.0)
    short_1x = short_mask & (state == 0.0)
    sig_1x = pd.concat([
        signals_from_mask(panel, long_1x, "LONG", hold_bars, tf),
        signals_from_mask(panel, short_1x, "SHORT", hold_bars, tf),
    ], ignore_index=True)
    sig_2x = pd.concat([
        signals_from_mask(panel, long_2x, "LONG", hold_bars, tf),
        signals_from_mask(panel, short_2x, "SHORT", hold_bars, tf),
    ], ignore_index=True)
    return sig_1x, sig_2x


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------

def run_signals(klines: pd.DataFrame, funding: pd.DataFrame, sig: pd.DataFrame,
                asset: str, notional: float = NOTIONAL, leverage: float = LEVERAGE):
    if sig.empty:
        return pd.DataFrame(), {
            "asset": asset, "n_trades": 0, "n_wins": 0,
            "win_rate": float("nan"), "total_pnl_usd": 0.0,
            "avg_pnl_usd": float("nan"), "sharpe": float("nan"),
            "max_dd_usd": 0.0, "avg_funding_paid": 0.0, "avg_fees_paid": 0.0,
            "avg_bars_held": float("nan"), "n_end_of_data": 0,
        }
    return run_backtest(klines, funding, sig, asset, notional_usd=notional, leverage=leverage, cfg=CFG)


def run_pure_sms_cell(panel: pd.DataFrame, klines: pd.DataFrame, funding: pd.DataFrame,
                      asset: str, tf: str, results: list, n_perm: int = 0) -> None:
    long_mask, short_mask = build_pure_sms(panel)
    # Fixed-bar holds
    for hold in HOLD_BARS:
        sig_long = signals_from_mask(panel, long_mask, "LONG", hold, tf)
        sig_short = signals_from_mask(panel, short_mask, "SHORT", hold, tf)
        sig = pd.concat([sig_long, sig_short], ignore_index=True)
        t, s = run_signals(klines, funding, sig, asset)
        results.append(evaluate_cell(t, s, asset, tf, f"pure_sms_hold{hold}", n_perm))
    # Signal flip
    sig_flip = signals_signal_flip(panel, long_mask, short_mask, tf)
    t, s = run_signals(klines, funding, sig_flip, asset)
    results.append(evaluate_cell(t, s, asset, tf, "pure_sms_signal_flip", n_perm))
    # ATR trailing (LONG)
    sig_long_atr, _ = signals_atr_trailing(panel, long_mask, "LONG", tf)
    sig_short_atr, _ = signals_atr_trailing(panel, short_mask, "SHORT", tf)
    sig = pd.concat([sig_long_atr, sig_short_atr], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, "pure_sms_atr_trail", n_perm))


def run_gated_variants(panel: pd.DataFrame, klines: pd.DataFrame, funding: pd.DataFrame,
                       asset: str, tf: str, results: list) -> None:
    base_long, base_short = build_pure_sms(panel)
    # use hold=3 as default for gated tests (compromise across TFs)
    hold = 3

    # Regime trending gate
    l, sh = build_regime_gated(panel, base_long, base_short)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"sms_regime_trending_hold{hold}"))

    # Session: London+NY
    l, sh = build_session_gated(panel, base_long, base_short)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"sms_session_londNy_hold{hold}"))

    # Session: Asia only (test for symmetry)
    l, sh = build_session_asia_only(panel, base_long, base_short)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"sms_session_asia_hold{hold}"))

    # Ranging regime
    l, sh = build_ranging_regime(panel, base_long, base_short)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"sms_ranging_hold{hold}"))

    # Markov-sized
    sig_1x, sig_2x = markov_size_signals(panel, base_long, base_short, hold, tf)
    t1, s1 = run_signals(klines, funding, sig_1x, asset, notional=NOTIONAL, leverage=1.0)
    t2, s2 = run_signals(klines, funding, sig_2x, asset, notional=NOTIONAL, leverage=2.0)
    # Combined
    t_all = pd.concat([t1, t2], ignore_index=True)
    if not t_all.empty:
        merged_stats = {
            "n_trades": len(t_all),
            "n_wins": int((t_all["pnl_net_usd"] > 0).sum()),
            "win_rate": float((t_all["pnl_net_usd"] > 0).mean()),
            "total_pnl_usd": float(t_all["pnl_net_usd"].sum()),
            "avg_pnl_usd": float(t_all["pnl_net_usd"].mean()),
            "sharpe": float(t_all["pnl_net_usd"].mean() / (t_all["pnl_net_usd"].std() + 1e-12) * np.sqrt(252)),
            "max_dd_usd": float((t_all["pnl_net_usd"].cumsum() - t_all["pnl_net_usd"].cumsum().cummax()).min()),
            "avg_fees_paid": float((t_all["fee_in_usd"] + t_all["fee_out_usd"]).mean()),
            "avg_funding_paid": float(t_all["funding_paid_usd"].mean()),
            "avg_bars_held": float(t_all["bars_held"].mean()),
        }
    else:
        merged_stats = {
            "n_trades": 0, "n_wins": 0, "win_rate": float("nan"),
            "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"), "sharpe": float("nan"),
            "max_dd_usd": 0.0, "avg_fees_paid": 0.0, "avg_funding_paid": 0.0,
            "avg_bars_held": float("nan"),
        }
    results.append(evaluate_cell(t_all, merged_stats, asset, tf, f"sms_markov_sized_hold{hold}"))


def run_struct_variants(panel: pd.DataFrame, klines: pd.DataFrame, funding: pd.DataFrame,
                        asset: str, tf: str, results: list) -> None:
    hold = 5  # structure breaks expect bigger moves
    # BOS standalone
    l, sh = build_bos(panel)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"bos_pure_hold{hold}"))

    # CHoCH standalone
    l, sh = build_choch(panel)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"choch_pure_hold{hold}"))

    # BOS + liquidity_reclaim AND combined
    l, sh = build_bos_and_liq(panel)
    sig = pd.concat([
        signals_from_mask(panel, l, "LONG", hold, tf),
        signals_from_mask(panel, sh, "SHORT", hold, tf),
    ], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, tf, f"bos_AND_liq_hold{hold}"))


def run_cross_tf(panel_low: pd.DataFrame, panel_high: pd.DataFrame,
                 klines: pd.DataFrame, funding: pd.DataFrame,
                 asset: str, low_tf: str, high_tf: str, results: list,
                 variant_name: str) -> None:
    """Confluence: low-tf liquidity event + high-tf condition (asof join).

    `variant_name`:  "5m_liq_AND_15m_ranging" / "15m_liq_AND_1h_liq".
    """
    low = panel_low[["open_time", "liquidity_dn", "liquidity_up", "ts_us"]].copy()
    if variant_name.endswith("ranging"):
        # join on high-TF regime_label
        high = panel_high[["open_time", "regime_label"]].copy()
        # back-fill high TF state to each low-TF bar
        merged = pd.merge_asof(
            low.sort_values("open_time"),
            high.sort_values("open_time"),
            on="open_time", direction="backward",
        )
        is_ranging = (merged["regime_label"] == "ranging").to_numpy()
        long_mask = (merged["liquidity_dn"].fillna(False).astype(bool).to_numpy()) & is_ranging
        short_mask = (merged["liquidity_up"].fillna(False).astype(bool).to_numpy()) & is_ranging
    else:
        # both-TF liquidity confluence
        high = panel_high[["open_time", "liquidity_dn", "liquidity_up"]].copy()
        merged = pd.merge_asof(
            low.sort_values("open_time"),
            high.sort_values("open_time").rename(columns={
                "liquidity_dn": "hi_liq_dn", "liquidity_up": "hi_liq_up",
            }),
            on="open_time", direction="backward",
        )
        long_mask  = (merged["liquidity_dn"].fillna(False).astype(bool) & merged["hi_liq_dn"].fillna(False).astype(bool)).to_numpy()
        short_mask = (merged["liquidity_up"].fillna(False).astype(bool) & merged["hi_liq_up"].fillna(False).astype(bool)).to_numpy()
    hold = 5
    # Build signals using low_tf bar period
    sig_long = signals_from_mask(panel_low, long_mask, "LONG", hold, low_tf)
    sig_short = signals_from_mask(panel_low, short_mask, "SHORT", hold, low_tf)
    sig = pd.concat([sig_long, sig_short], ignore_index=True)
    t, s = run_signals(klines, funding, sig, asset)
    results.append(evaluate_cell(t, s, asset, low_tf, variant_name))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    results: list[dict] = []
    panels_cache: dict[tuple[str, str], pd.DataFrame] = {}
    funding_cache: dict[str, pd.DataFrame] = {}

    for asset in ASSETS:
        try:
            funding_cache[asset] = load_funding(asset)
        except Exception as e:
            print(f"WARN: skip {asset} no funding: {e}")
            continue

        for tf in TFS:
            try:
                panel = load_panel(asset, tf)
            except Exception as e:
                print(f"  skip {asset} {tf}: {e}")
                continue
            panels_cache[(asset, tf)] = panel
            klines = make_klines_view(panel)
            funding = funding_cache[asset]
            print(f"\n=== {asset} {tf} (n_bars={len(panel)}, "
                  f"liq_dn={int(panel['liquidity_dn'].sum())}, "
                  f"liq_up={int(panel['liquidity_up'].sum())}) ===")

            run_pure_sms_cell(panel, klines, funding, asset, tf, results, n_perm=0)
            run_gated_variants(panel, klines, funding, asset, tf, results)
            run_struct_variants(panel, klines, funding, asset, tf, results)

    # Cross-TF confluence: 5m sms + 15m ranging; 15m + 1h liq confluence
    print("\n=== Cross-TF confluence ===")
    for asset in ASSETS:
        if (asset, "5m") in panels_cache and (asset, "15m") in panels_cache:
            panel_low = panels_cache[(asset, "5m")]
            panel_high = panels_cache[(asset, "15m")]
            klines = make_klines_view(panel_low)
            run_cross_tf(panel_low, panel_high, klines, funding_cache[asset],
                         asset, "5m", "15m", results, "5m_liq_AND_15m_ranging")
        if (asset, "15m") in panels_cache and (asset, "1h") in panels_cache:
            panel_low = panels_cache[(asset, "15m")]
            panel_high = panels_cache[(asset, "1h")]
            klines = make_klines_view(panel_low)
            run_cross_tf(panel_low, panel_high, klines, funding_cache[asset],
                         asset, "15m", "1h", results, "15m_liq_AND_1h_liq")

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "W2e_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}  ({len(df)} rows)")
    return df


if __name__ == "__main__":
    df = main()
    # Quick on-screen leaderboard
    if df is not None and not df.empty:
        df_n = df[df["n_trades"] >= 30].copy()
        df_n = df_n.sort_values("avg_pnl_usd", ascending=False)
        print("\nTop-15 cells by avg_pnl_usd (n>=30):")
        cols = ["asset", "tf", "variant", "n_trades", "win_rate",
                "avg_pnl_usd", "sharpe", "total_pnl_usd", "g1_binom_p",
                "g6_pnl_ci_lo", "g6_pnl_ci_hi"]
        print(df_n[cols].head(15).to_string(index=False))
