"""
Wave 2 PERP — Family B: Mean-Reversion on Hyperliquid Perpetuals
=================================================================

5 perp-native mean-reversion templates with futures-style exits (ATR SL+TP,
signal-flip, NOT fixed-time holds). Indicators are INPUTS, not Polymarket
binary triggers.

Strategies:
  B1 — RSI extreme reversion         (rsi_14 < 25 LONG / > 75 SHORT)
  B2 — Bollinger Band reversal       (close vs 2-sigma bands)
  B3 — Z-score deviation reversion   (z = (close - ema_50) / atr_14 > |2|)
  B4 — SMS liquidity_reclaim + RSI   (sweep at oversold/overbought, MR)
  B5 — VWAP deviation reversion      (close vs session VWAP +/- 2*ATR)

Exits:
  ATR SL/TP brackets (default), signal-flip-back-to-mean fallback,
  or ATR trail. NO fixed-time holds.

Universe:
  BTC ETH SOL AVAX LINK BNB ADA DOGE XRP SUI TON (subject to data avail)

Outputs:
  B_results.csv  — per-cell metrics
  B_mean_reversion.md — narrative report

Schema (matches W2 A spec):
  strategy_id, family, variant, asset, tf, n_trades, win_rate, avg_pnl_usd,
  total_pnl_usd, sharpe_ann, calmar, max_dd_usd, profit_factor, avg_bars_held,
  avg_fees, avg_funding, oos_sharpe, oos_pf
"""
from __future__ import annotations

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import talib

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
PANEL_DIR = HERE.parent / "panels"
BINANCE_DIR = REPO / "data" / "binance" / "parquet"
HL_FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"

sys.path.insert(0, str(HERE.parent))
from hl_engine import HyperliquidConfig, run_backtest  # noqa: E402

OUT_CSV = HERE / "B_results.csv"
OUT_MD = HERE / "B_mean_reversion.md"

# ---------------------------------------------------------------------------
# Universe definition
# ---------------------------------------------------------------------------
COINS_ALL = ["BTC", "ETH", "SOL", "AVAX", "LINK", "BNB", "ADA", "DOGE", "XRP", "SUI", "TON"]

# Map asset -> binance symbol
BSYM = {c: f"{c}USDT" for c in COINS_ALL}

# Coins with HL funding parquets
HL_FUNDING_COINS = {"BTC", "ETH", "SOL", "AVAX", "LINK"}

# Coins with binance 1d klines
HAS_1D = {"BTC", "ETH", "SOL", "SUI", "TON"}

# Notional/leverage convention (matches Wave 1/V52)
NOTIONAL = 250.0
LEVERAGE = 1.0

# Annualization bars/yr (used for sharpe + calmar)
BARS_PER_YEAR = {
    "1h": 24 * 365,
    "4h": 6 * 365,
    "1d": 365,
}

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_binance_klines(sym: str, tf: str, start_year: int = 2020, end_year: int = 2026) -> pd.DataFrame:
    """Load + concat binance parquet klines for symbol/tf."""
    base = BINANCE_DIR / sym / tf
    if not base.exists():
        return pd.DataFrame()
    parts = []
    for y in range(start_year, end_year + 1):
        p = base / f"year={y}" / "part.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.sort_values("open_time").drop_duplicates(subset=["open_time"]).reset_index(drop=True)
    df["open_time_us"] = (df["open_time"].astype("int64") // 1_000).astype("int64")
    return df


def load_panel(asset: str, tf: str) -> pd.DataFrame:
    """Load pre-built panel for BTC/ETH/SOL @ 1h/4h. RangeIndex."""
    p = PANEL_DIR / f"hl_panel_{asset}_{tf}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    if "open_time_us" not in df.columns:
        df["open_time_us"] = (df["open_time"].astype("int64") // 1_000).astype("int64")
    return df


def load_funding(asset: str) -> pd.DataFrame:
    p = HL_FUNDING_DIR / f"{asset}_funding.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    # Ensure expected schema for engine
    if "funding_rate" not in df.columns and "fundingRate" in df.columns:
        df = df.rename(columns={"fundingRate": "funding_rate"})
    return df


# ---------------------------------------------------------------------------
# Indicator builders (inline for coins without panels, OR 1d for any coin)
# ---------------------------------------------------------------------------

def add_inline_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute minimum indicators needed for B-family.

    rsi_14, atr_14, ema_50, bb_pos_20 (0=lower 0.5=mid 1=upper), bb_upper, bb_lower, bb_mid.
    """
    out = df.copy()
    c = out["close"].values.astype(float)
    h = out["high"].values.astype(float)
    l = out["low"].values.astype(float)

    out["rsi_14"] = talib.RSI(c, timeperiod=14)
    out["atr_14"] = talib.ATR(h, l, c, timeperiod=14)
    out["ema_50"] = talib.EMA(c, timeperiod=50)

    upper, mid, lower = talib.BBANDS(c, timeperiod=20, nbdevup=2, nbdevdn=2)
    out["bb_upper"] = upper
    out["bb_mid"] = mid
    out["bb_lower"] = lower
    rng = (upper - lower)
    out["bb_pos_20"] = np.where(rng > 0, (c - lower) / rng, np.nan)
    return out


def ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """If a panel df is missing any required col, recompute inline."""
    need = {"rsi_14", "atr_14", "ema_50", "bb_pos_20"}
    have = set(df.columns)
    if need.issubset(have):
        # bb_pos exists but may need raw bands for B2 logic. Reconstruct bands from bb_pos if not present.
        if "bb_upper" not in have:
            # Reconstruct via BBANDS (idempotent vs panel)
            c = df["close"].values.astype(float)
            upper, mid, lower = talib.BBANDS(c, timeperiod=20, nbdevup=2, nbdevdn=2)
            df = df.copy()
            df["bb_upper"] = upper
            df["bb_mid"] = mid
            df["bb_lower"] = lower
        return df
    return add_inline_indicators(df)


def session_vwap_1h(df: pd.DataFrame) -> pd.Series:
    """Compute UTC daily-session VWAP on 1h bars.

    Resets each calendar day at 00:00 UTC. cumulative (price*vol)/cumulative vol.
    """
    out = df.copy()
    out["typ"] = (out["high"] + out["low"] + out["close"]) / 3.0
    out["pv"] = out["typ"] * out["volume"]
    out["day"] = out["open_time"].dt.floor("D")
    cum_pv = out.groupby("day")["pv"].cumsum()
    cum_v = out.groupby("day")["volume"].cumsum()
    vwap = cum_pv / cum_v.replace(0, np.nan)
    return vwap.values


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------

def b1_rsi_extreme(df: pd.DataFrame, low: float = 25.0, high: float = 75.0) -> pd.Series:
    """LONG when rsi<low, SHORT when rsi>high. Returns +1/-1/0 series."""
    rsi = df["rsi_14"].values
    sig = np.zeros(len(df), dtype=int)
    sig[(rsi < low) & ~np.isnan(rsi)] = +1
    sig[(rsi > high) & ~np.isnan(rsi)] = -1
    # Only fire on TRANSITION (not every consecutive bar in regime) -> require prev bar OUT of zone
    prev = np.concatenate([[0], sig[:-1]])
    fire = np.where((sig != 0) & (prev != sig), sig, 0)
    return pd.Series(fire, index=df.index)


def b2_bb_reversal(df: pd.DataFrame) -> pd.Series:
    """LONG close<lower, SHORT close>upper."""
    c = df["close"].values
    up = df["bb_upper"].values
    lo = df["bb_lower"].values
    sig = np.zeros(len(df), dtype=int)
    sig[(c < lo) & ~np.isnan(lo)] = +1
    sig[(c > up) & ~np.isnan(up)] = -1
    prev = np.concatenate([[0], sig[:-1]])
    fire = np.where((sig != 0) & (prev != sig), sig, 0)
    return pd.Series(fire, index=df.index)


def b3_zscore(df: pd.DataFrame, thresh: float = 2.0) -> pd.Series:
    """LONG z<-thresh, SHORT z>+thresh."""
    c = df["close"].values
    ema = df["ema_50"].values
    atr = df["atr_14"].values
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (c - ema) / atr
    sig = np.zeros(len(df), dtype=int)
    sig[(z < -thresh) & ~np.isnan(z)] = +1
    sig[(z > +thresh) & ~np.isnan(z)] = -1
    prev = np.concatenate([[0], sig[:-1]])
    fire = np.where((sig != 0) & (prev != sig), sig, 0)
    return pd.Series(fire, index=df.index)


def b4_sms_reclaim(df: pd.DataFrame) -> pd.Series:
    """B4 — liquidity_reclaim as mean-reversion. Requires panel columns
    liquidity_up/dn + regime_label. If missing, returns zeros (skip cell).
    """
    if "liquidity_up" not in df.columns or "liquidity_dn" not in df.columns:
        return pd.Series(np.zeros(len(df), dtype=int), index=df.index)
    if "regime_label" not in df.columns:
        # fall back: no regime gate
        regime = pd.Series(["unknown"] * len(df), index=df.index)
    else:
        regime = df["regime_label"].astype(str)
    rsi = df["rsi_14"].values
    liq_up = df["liquidity_up"].astype(bool).values
    liq_dn = df["liquidity_dn"].astype(bool).values
    sig = np.zeros(len(df), dtype=int)
    # LONG: sweep DOWN reclaim + oversold + NOT in down-trend regime
    long_mask = liq_dn & (rsi < 40) & (regime != "trending_dn").values & ~np.isnan(rsi)
    short_mask = liq_up & (rsi > 60) & (regime != "trending_up").values & ~np.isnan(rsi)
    sig[long_mask] = +1
    sig[short_mask] = -1
    # No need for transition filter — liquidity events are sparse already
    return pd.Series(sig, index=df.index)


def b5_vwap_dev(df: pd.DataFrame, k: float = 2.0) -> pd.Series:
    """LONG close < VWAP - k*ATR, SHORT close > VWAP + k*ATR (1h only)."""
    vwap = session_vwap_1h(df)
    c = df["close"].values
    atr = df["atr_14"].values
    sig = np.zeros(len(df), dtype=int)
    long_mask = (c < (vwap - k * atr)) & ~np.isnan(vwap) & ~np.isnan(atr)
    short_mask = (c > (vwap + k * atr)) & ~np.isnan(vwap) & ~np.isnan(atr)
    sig[long_mask] = +1
    sig[short_mask] = -1
    prev = np.concatenate([[0], sig[:-1]])
    fire = np.where((sig != 0) & (prev != sig), sig, 0)
    return pd.Series(fire, index=df.index)


# ---------------------------------------------------------------------------
# Exit logic — ATR SL/TP bracket OR mean-cross
# ---------------------------------------------------------------------------

def find_atr_sl_tp_exits(
    kl: pd.DataFrame,
    entry_idxs: np.ndarray,
    directions: np.ndarray,
    atr_series: np.ndarray,
    sl_mult: float,
    tp_mult: float,
    mean_cross_series: np.ndarray | None = None,
    max_bars: int = 500,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized over trades. For each entry, scan forward up to max_bars.

    Exit triggers (whichever first):
      - low <= entry - sl_mult*ATR (LONG SL) / high >= entry + sl_mult*ATR (SHORT SL)
      - high >= entry + tp_mult*ATR (LONG TP) / low <= entry - tp_mult*ATR (SHORT TP)
      - mean_cross trigger: optional precomputed boolean series — exit when this flips

    Returns (exit_idx, exit_us, exit_reason_code) where reason in {sl=0, tp=1, mean=2, max_bars=3, eod=4}.
    """
    n_bars = len(kl)
    opens = kl["open"].values.astype(float)
    highs = kl["high"].values.astype(float)
    lows = kl["low"].values.astype(float)
    times = kl["open_time_us"].values.astype("int64")
    bar_us = int(np.median(np.diff(times)))

    n_t = len(entry_idxs)
    exit_idx = np.full(n_t, -1, dtype=np.int64)
    exit_us = np.full(n_t, -1, dtype=np.int64)
    reason = np.full(n_t, 4, dtype=np.int8)  # default eod

    for i in range(n_t):
        ei = int(entry_idxs[i])
        if ei < 0 or ei >= n_bars - 1:
            continue
        d = int(directions[i])
        atr_e = atr_series[ei]
        if np.isnan(atr_e) or atr_e <= 0:
            continue
        entry_px = opens[ei + 1] if ei + 1 < n_bars else opens[ei]
        if d > 0:  # LONG
            sl_px = entry_px - sl_mult * atr_e
            tp_px = entry_px + tp_mult * atr_e
        else:
            sl_px = entry_px + sl_mult * atr_e
            tp_px = entry_px - tp_mult * atr_e

        end_pos = min(ei + 1 + max_bars, n_bars)
        for j in range(ei + 1, end_pos):
            sl_hit = (lows[j] <= sl_px) if d > 0 else (highs[j] >= sl_px)
            tp_hit = (highs[j] >= tp_px) if d > 0 else (lows[j] <= tp_px)
            mean_hit = False
            if mean_cross_series is not None and mean_cross_series[j]:
                mean_hit = True
            if sl_hit and tp_hit:
                # pessimistic: SL first
                exit_idx[i] = j
                exit_us[i] = times[j]
                reason[i] = 0
                break
            if sl_hit:
                exit_idx[i] = j; exit_us[i] = times[j]; reason[i] = 0; break
            if tp_hit:
                exit_idx[i] = j; exit_us[i] = times[j]; reason[i] = 1; break
            if mean_hit:
                exit_idx[i] = j; exit_us[i] = times[j]; reason[i] = 2; break
        else:
            # no break → ran out of max_bars or data end
            last_j = end_pos - 1 if end_pos > 0 else ei
            exit_idx[i] = last_j
            exit_us[i] = times[last_j]
            reason[i] = 3 if end_pos < n_bars else 4

    return exit_idx, exit_us, reason


# ---------------------------------------------------------------------------
# Backtest one strategy on one (asset, tf) cell
# ---------------------------------------------------------------------------

def _mean_cross_series_for(strat_id: str, df: pd.DataFrame) -> np.ndarray | None:
    """Optional mean-cross exit indicator (paired with ATR SL/TP).

    B1: RSI crosses 50
    B2: close crosses bb_mid
    B3: z crosses 0
    B5: close crosses VWAP
    B4: no mean cross (rely on SL/TP)
    """
    n = len(df)
    if strat_id == "B1":
        rsi = df["rsi_14"].values
        # Series of bool: True when rsi just crossed 50 (either direction)
        prev = np.concatenate([[np.nan], rsi[:-1]])
        cross = ((prev < 50) & (rsi >= 50)) | ((prev > 50) & (rsi <= 50))
        return cross
    if strat_id == "B2":
        c = df["close"].values
        m = df["bb_mid"].values
        prev_c = np.concatenate([[np.nan], c[:-1]])
        prev_m = np.concatenate([[np.nan], m[:-1]])
        cross = ((prev_c < prev_m) & (c >= m)) | ((prev_c > prev_m) & (c <= m))
        return cross
    if strat_id == "B3":
        c = df["close"].values
        ema = df["ema_50"].values
        atr = df["atr_14"].values
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (c - ema) / atr
        prev = np.concatenate([[np.nan], z[:-1]])
        cross = ((prev < 0) & (z >= 0)) | ((prev > 0) & (z <= 0))
        return cross
    if strat_id == "B5":
        # Reconstruct VWAP
        vwap = session_vwap_1h(df)
        c = df["close"].values
        prev_c = np.concatenate([[np.nan], c[:-1]])
        prev_v = np.concatenate([[np.nan], vwap[:-1]])
        cross = ((prev_c < prev_v) & (c >= vwap)) | ((prev_c > prev_v) & (c <= vwap))
        return cross
    return None


STRAT_EXIT_PARAMS = {
    "B1": dict(sl_mult=1.5, tp_mult=2.0),
    "B2": dict(sl_mult=1.5, tp_mult=2.0),
    "B3": dict(sl_mult=1.5, tp_mult=2.0),  # default
    "B4": dict(sl_mult=1.0, tp_mult=2.5),
    "B5": dict(sl_mult=1.5, tp_mult=2.0),  # default; ATR trail mult=1.5 baked into TP/SL
}


def run_cell(strat_id: str, asset: str, tf: str) -> dict | None:
    """Run one (strategy, asset, tf) cell. Returns row dict or None on skip."""
    # 1) Load price/indicator panel
    df = pd.DataFrame()
    have_panel = False
    if asset in ("BTC", "ETH", "SOL") and tf in ("1h", "4h"):
        df = load_panel(asset, tf)
        have_panel = len(df) > 0
    if not have_panel:
        sym = BSYM.get(asset)
        if sym is None:
            return None
        df = load_binance_klines(sym, tf)
        if len(df) == 0:
            return None
        df = add_inline_indicators(df)
    else:
        df = ensure_indicators(df)

    # B4 requires SMS panel cols; if asset has no panel, skip B4
    if strat_id == "B4" and ("liquidity_up" not in df.columns or "liquidity_dn" not in df.columns):
        return None

    # B5 is 1h only
    if strat_id == "B5" and tf != "1h":
        return None

    # 2) Signals
    if strat_id == "B1":
        signals = b1_rsi_extreme(df)
    elif strat_id == "B2":
        signals = b2_bb_reversal(df)
    elif strat_id == "B3":
        signals = b3_zscore(df, thresh=2.0)
    elif strat_id == "B4":
        signals = b4_sms_reclaim(df)
    elif strat_id == "B5":
        signals = b5_vwap_dev(df, k=2.0)
    else:
        return None

    fire_idx = np.where(signals.values != 0)[0]
    if len(fire_idx) == 0:
        return {
            "strategy_id": strat_id, "family": "B_mean_reversion", "variant": strat_id,
            "asset": asset, "tf": tf,
            "n_trades": 0, "win_rate": np.nan, "avg_pnl_usd": np.nan,
            "total_pnl_usd": 0.0, "sharpe_ann": np.nan, "calmar": np.nan,
            "max_dd_usd": 0.0, "profit_factor": np.nan, "avg_bars_held": np.nan,
            "avg_fees": np.nan, "avg_funding": np.nan,
            "oos_sharpe": np.nan, "oos_pf": np.nan,
        }
    fire_dirs = signals.values[fire_idx]  # +1 / -1

    # 3) Compute exits (ATR SL+TP + optional mean cross)
    mean_series = _mean_cross_series_for(strat_id, df)
    atr_arr = df["atr_14"].values.astype(float)
    exit_idx, exit_us, exit_reason = find_atr_sl_tp_exits(
        df, fire_idx, fire_dirs, atr_arr,
        sl_mult=STRAT_EXIT_PARAMS[strat_id]["sl_mult"],
        tp_mult=STRAT_EXIT_PARAMS[strat_id]["tp_mult"],
        mean_cross_series=mean_series,
        max_bars=500,
    )

    # 4) Build signals_df for engine run_backtest
    sig_us = df["open_time_us"].values[fire_idx].astype("int64")
    valid = exit_idx >= 0
    if valid.sum() == 0:
        return None
    sig_df = pd.DataFrame({
        "signal_us": sig_us[valid],
        "direction": np.where(fire_dirs[valid] == 1, "LONG", "SHORT"),
        "exit_us": exit_us[valid],
    })

    # 5) Load funding (or zero)
    if asset in HL_FUNDING_COINS:
        fnd = load_funding(asset)
        funding_method = "hourly_accrual"
    else:
        fnd = pd.DataFrame({
            "funding_rate": [0.0, 0.0],
            "funding_time_us": [int(df["open_time_us"].iloc[0]) - 1, int(df["open_time_us"].iloc[-1]) + 1],
        })
        funding_method = "ignore"

    cfg = HyperliquidConfig(funding_method=funding_method)
    try:
        trades_df, _stats = run_backtest(df, fnd, sig_df, asset, notional_usd=NOTIONAL, leverage=LEVERAGE, cfg=cfg)
    except Exception as e:
        return {
            "strategy_id": strat_id, "family": "B_mean_reversion", "variant": strat_id,
            "asset": asset, "tf": tf,
            "n_trades": 0, "win_rate": np.nan, "avg_pnl_usd": np.nan,
            "total_pnl_usd": 0.0, "sharpe_ann": np.nan, "calmar": np.nan,
            "max_dd_usd": 0.0, "profit_factor": np.nan, "avg_bars_held": np.nan,
            "avg_fees": np.nan, "avg_funding": np.nan,
            "oos_sharpe": np.nan, "oos_pf": np.nan,
            "note": f"engine error: {e}",
        }

    if len(trades_df) == 0:
        return {
            "strategy_id": strat_id, "family": "B_mean_reversion", "variant": strat_id,
            "asset": asset, "tf": tf,
            "n_trades": 0, "win_rate": np.nan, "avg_pnl_usd": np.nan,
            "total_pnl_usd": 0.0, "sharpe_ann": np.nan, "calmar": np.nan,
            "max_dd_usd": 0.0, "profit_factor": np.nan, "avg_bars_held": np.nan,
            "avg_fees": np.nan, "avg_funding": np.nan,
            "oos_sharpe": np.nan, "oos_pf": np.nan,
        }

    # 6) Compute metrics
    return _compute_metrics(strat_id, asset, tf, trades_df)


# ---------------------------------------------------------------------------
# Metrics + walk-forward
# ---------------------------------------------------------------------------

def _metrics_block(trades: pd.DataFrame, tf: str) -> dict:
    pnl = trades["pnl_net_usd"].values.astype(float)
    if len(pnl) == 0:
        return dict(n_trades=0, win_rate=np.nan, avg_pnl_usd=np.nan, total_pnl_usd=0.0,
                    sharpe_ann=np.nan, calmar=np.nan, max_dd_usd=0.0,
                    profit_factor=np.nan, avg_bars_held=np.nan, avg_fees=np.nan, avg_funding=np.nan)
    wins = (pnl > 0).sum()
    losses = (pnl < 0).sum()
    pos = pnl[pnl > 0].sum() if wins else 0.0
    neg = pnl[pnl < 0].sum() if losses else 0.0
    pf = float(abs(pos / neg)) if neg < 0 else float("inf")
    avg_bars = float(trades["bars_held"].mean())
    fees_avg = float((trades["fee_in_usd"] + trades["fee_out_usd"]).mean())
    fund_avg = float(trades["funding_paid_usd"].mean())

    # Annualized Sharpe: scale per-trade pnl by frequency. trades / year = (bars_per_year / avg_bars)
    bpy = BARS_PER_YEAR.get(tf, 24 * 365)
    trades_per_year = bpy / max(1.0, avg_bars)
    if pnl.std() > 0:
        sharpe_ann = float(pnl.mean() / pnl.std() * np.sqrt(trades_per_year))
    else:
        sharpe_ann = 0.0

    cum = np.cumsum(pnl)
    peaks = np.maximum.accumulate(cum)
    dd = cum - peaks
    max_dd = float(dd.min()) if len(dd) else 0.0
    total = float(pnl.sum())
    calmar = float(total / abs(max_dd)) if max_dd < 0 else (float("inf") if total > 0 else 0.0)

    return dict(
        n_trades=int(len(pnl)),
        win_rate=float(wins / len(pnl)),
        avg_pnl_usd=float(pnl.mean()),
        total_pnl_usd=total,
        sharpe_ann=sharpe_ann,
        calmar=calmar,
        max_dd_usd=max_dd,
        profit_factor=pf,
        avg_bars_held=avg_bars,
        avg_fees=fees_avg,
        avg_funding=fund_avg,
    )


def _compute_metrics(strat_id: str, asset: str, tf: str, trades: pd.DataFrame) -> dict:
    base = _metrics_block(trades, tf)
    # Walk-forward 70/30 by trade order
    n = len(trades)
    if n >= 10:
        split = int(0.7 * n)
        oos = trades.iloc[split:].copy()
        oos_m = _metrics_block(oos, tf)
        oos_sharpe = oos_m["sharpe_ann"]
        oos_pf = oos_m["profit_factor"]
    else:
        oos_sharpe = np.nan
        oos_pf = np.nan
    row = {
        "strategy_id": f"{strat_id}_{asset}_{tf}",
        "family": "B_mean_reversion",
        "variant": strat_id,
        "asset": asset,
        "tf": tf,
        **base,
        "oos_sharpe": oos_sharpe,
        "oos_pf": oos_pf,
    }
    return row


# ---------------------------------------------------------------------------
# Buy-and-hold benchmark
# ---------------------------------------------------------------------------

def buy_hold_benchmark(asset: str, tf: str = "1d") -> dict:
    sym = BSYM[asset]
    df = load_binance_klines(sym, tf if tf in ("1d","4h","1h") else "1d")
    if len(df) == 0:
        return {"asset": asset, "n/a": True}
    px0 = float(df["close"].iloc[0])
    pxN = float(df["close"].iloc[-1])
    ret = pxN / px0 - 1.0
    days = (df["open_time"].iloc[-1] - df["open_time"].iloc[0]).days or 1
    return {"asset": asset, "first": str(df["open_time"].iloc[0].date()),
            "last": str(df["open_time"].iloc[-1].date()),
            "ret_total": float(ret), "ret_ann": float(ret * 365.0 / days)}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

CELL_PLAN = []

def _build_plan():
    """Cells to run per strategy."""
    plan = []
    # B1 RSI: 1h 4h 1d, all coins
    for asset in COINS_ALL:
        for tf in ("1h", "4h", "1d"):
            if tf == "1d" and asset not in HAS_1D:
                continue
            plan.append(("B1", asset, tf))
    # B2 BB: 1h 4h, all coins
    for asset in COINS_ALL:
        for tf in ("1h", "4h"):
            plan.append(("B2", asset, tf))
    # B3 Z-score: 1h 4h 1d, all coins
    for asset in COINS_ALL:
        for tf in ("1h", "4h", "1d"):
            if tf == "1d" and asset not in HAS_1D:
                continue
            plan.append(("B3", asset, tf))
    # B4 SMS reclaim: 4h 1d, BTC/ETH/SOL only (panel-only) — 1d also skipped as no panel
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("4h",):
            plan.append(("B4", asset, tf))
    # B5 VWAP: 1h, all coins
    for asset in COINS_ALL:
        plan.append(("B5", asset, "1h"))
    return plan


def main():
    plan = _build_plan()
    print(f"[B] Running {len(plan)} cells")
    rows = []
    for i, (strat, asset, tf) in enumerate(plan):
        print(f"  [{i+1:>3}/{len(plan)}] {strat} {asset} {tf} ...", end="", flush=True)
        try:
            row = run_cell(strat, asset, tf)
        except Exception as e:
            print(f" ERROR {type(e).__name__}: {e}")
            continue
        if row is None:
            print(" skip")
            continue
        n = row.get("n_trades", 0)
        sh = row.get("sharpe_ann", float("nan"))
        tot = row.get("total_pnl_usd", 0.0)
        print(f" n={n:5d} sharpe={sh:+.2f} pnl=${tot:+.0f}")
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)
    print(f"\n[B] Wrote {OUT_CSV} ({len(df)} cells)")

    # Buy-hold benchmark for each asset
    bh = []
    for a in COINS_ALL:
        bh.append(buy_hold_benchmark(a, tf="1d" if a in HAS_1D else "4h"))
    bh_df = pd.DataFrame(bh)

    # Report
    write_report(df, bh_df)


def write_report(df: pd.DataFrame, bh_df: pd.DataFrame):
    lines = []
    lines.append("# Wave 2 PERP — Family B (mean-reversion) results\n")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat()}_\n")
    lines.append(f"\nTotal cells: **{len(df)}**\n")
    if len(df) == 0:
        with open(OUT_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return

    # Summary by variant
    lines.append("\n## Summary by variant\n")
    g = df.groupby("variant").agg(
        cells=("strategy_id", "count"),
        n50=("n_trades", lambda x: (x >= 50).sum()),
        total_pnl=("total_pnl_usd", "sum"),
        med_sharpe=("sharpe_ann", "median"),
        med_oos_sharpe=("oos_sharpe", "median"),
        med_calmar=("calmar", "median"),
        med_pf=("profit_factor", "median"),
    ).round(3)
    lines.append(g.to_markdown())
    lines.append("\n")

    # Top-10 by OOS Sharpe (n>=30 only)
    qualified = df[df["n_trades"] >= 30].copy()
    if len(qualified) > 0:
        top = qualified.sort_values("oos_sharpe", ascending=False).head(10)
        lines.append("\n## Top-10 by OOS annualized Sharpe (n>=30)\n")
        cols = ["strategy_id", "n_trades", "win_rate", "avg_pnl_usd",
                "total_pnl_usd", "sharpe_ann", "oos_sharpe", "calmar",
                "profit_factor", "max_dd_usd", "avg_bars_held"]
        lines.append(top[cols].round(3).to_markdown(index=False))
        lines.append("\n")
    else:
        lines.append("\n_No cells with n>=30._\n")

    # Buy-hold benchmark
    lines.append("\n## Buy-and-hold benchmark (per asset)\n")
    lines.append(bh_df.round(3).to_markdown(index=False))
    lines.append("\n")

    # Worst cells
    losers = df.sort_values("total_pnl_usd").head(10)
    lines.append("\n## Worst-10 by total PnL\n")
    cols = ["strategy_id", "n_trades", "win_rate", "total_pnl_usd",
            "sharpe_ann", "max_dd_usd"]
    lines.append(losers[cols].round(3).to_markdown(index=False))
    lines.append("\n")

    # Best per variant
    lines.append("\n## Best cell per variant (by OOS Sharpe, n>=30 fallback to n>=10)\n")
    for v in sorted(df["variant"].unique()):
        sub = df[df["variant"] == v]
        q = sub[sub["n_trades"] >= 30]
        if len(q) == 0:
            q = sub[sub["n_trades"] >= 10]
        if len(q) == 0:
            lines.append(f"- **{v}**: no cells with n>=10\n")
            continue
        b = q.sort_values("oos_sharpe", ascending=False).iloc[0]
        lines.append(
            f"- **{v}**: {b['asset']} {b['tf']} — "
            f"n={int(b['n_trades'])} wr={b['win_rate']:.2f} "
            f"pnl=${b['total_pnl_usd']:+.0f} sharpe={b['sharpe_ann']:+.2f} "
            f"oos_sharpe={b['oos_sharpe']:+.2f} calmar={b['calmar']:+.2f}\n"
        )

    # Generalization note
    lines.append("\n## Family generalization\n")
    by_var = df.groupby("variant").agg(
        med_sharpe=("sharpe_ann", "median"),
        med_oos=("oos_sharpe", "median"),
        pct_pos=("total_pnl_usd", lambda x: float((x > 0).mean())),
    ).round(3)
    lines.append(by_var.to_markdown())
    lines.append("\n")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[B] Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
