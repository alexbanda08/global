"""
W2P-A — Trend-following on Hyperliquid perpetuals (rerun, perp-native).

Strategies:
  A1 — Donchian breakout (N in {20,50,100}) + ATR trailing stop (mult in {1.5,2,3})
  A2 — EMA stack score >= +bull / <= -bull, exit signal-flip
  A3 — ADX-gated EMA trend: adx>25 + close>ema_50 + ema_50 slope up;
       exit signal-flip OR ATR-trail
  A4 — Range Filter dir-flip entry; exit at next dir flip
  A5 — A1 with Cyclops 3-axis coherence filter

Validation: per (strategy, asset, tf, variant) → n_trades, win_rate,
avg_pnl_usd, sharpe_ann, calmar, max_dd_usd, profit_factor, OOS metrics
(70/30 walk-forward), buy-and-hold benchmark comparison.

Outputs:
  - A_results.csv
  - A_trend_following.md
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hl_engine import HyperliquidConfig  # noqa: E402
from perp_exit_rules import (  # noqa: E402
    run_strategy,
    summarize,
    _ts_us,
    signal_flip_exit,
    atr_trailing_stop_exit,
)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

PANELS_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"
BINANCE_DIR = REPO / "data" / "binance" / "parquet"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2_perp"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Assets:
# - BTC/ETH/SOL: panel + HL funding (full feature set)
# - AVAX/LINK: binance klines + HL funding
# - BNB/ADA/DOGE/XRP/SUI/TON: binance klines + funding ignored
HL_FUND_ASSETS = {"BTC", "ETH", "SOL", "AVAX", "LINK"}
ALL_ASSETS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "BNB", "ADA", "DOGE", "XRP", "SUI", "TON"]

ASSETS_WITH_PANELS = ["BTC", "ETH", "SOL"]   # have indicator panels
ASSETS_BINANCE_ONLY = ["AVAX", "LINK", "BNB", "ADA", "DOGE", "XRP", "SUI", "TON"]

TFS = ["1h", "4h", "1d"]
NOTIONAL = 250.0
LEVERAGE = 1.0
DATA_START = pd.Timestamp("2023-01-01", tz="UTC")    # 3+ years of data for n>=50

CFG_FUND = HyperliquidConfig(funding_method="hourly_accrual")
CFG_NOFUND = HyperliquidConfig(funding_method="ignore")


# -----------------------------------------------------------------------------
# Loaders
# -----------------------------------------------------------------------------

def _binance_sym(asset: str) -> str:
    return f"{asset}USDT"


def load_binance_klines(asset: str, tf: str) -> pd.DataFrame:
    """Load + concat Binance klines for asset, returning columns:
    [open_time, open, high, low, close, volume, open_time_us]."""
    sym = _binance_sym(asset)
    if tf == "1d":
        # Synthesize 1d from 4h by resampling
        files = sorted((BINANCE_DIR / sym / "4h").glob("year=*/part.parquet"))
        if not files:
            return pd.DataFrame()
        df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df = df.set_index("open_time").sort_index()
        agg = df.resample("1D").agg({
            "open": "first", "high": "max", "low": "min", "close": "last",
            "volume": "sum",
        }).dropna().reset_index()
    else:
        files = sorted((BINANCE_DIR / sym / tf).glob("year=*/part.parquet"))
        if not files:
            return pd.DataFrame()
        agg = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        agg["open_time"] = pd.to_datetime(agg["open_time"], utc=True)
        agg = agg[["open_time", "open", "high", "low", "close", "volume"]].copy()

    agg = agg[agg["open_time"] >= DATA_START].reset_index(drop=True)
    agg["open_time_us"] = (agg["open_time"].astype("int64") // 1_000).astype("int64")
    agg = agg.sort_values("open_time_us").reset_index(drop=True)
    return agg


def load_panel_klines(asset: str, tf: str) -> pd.DataFrame:
    """Panel-based klines + indicators (for BTC/ETH/SOL only)."""
    if tf == "1d":
        # Synthesize 1d from 4h panel
        p = PANELS_DIR / f"hl_panel_{asset}_4h.parquet"
        if not p.exists():
            return pd.DataFrame()
        df = pd.read_parquet(p)
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df = df[df["open_time"] >= DATA_START].copy()
        # Resample OHLCV and key indicators
        df = df.set_index("open_time").sort_index()
        # Take last 1d (resample): use last value of each indicator from the 1d window
        agg_dict = {
            "open": "first", "high": "max", "low": "min", "close": "last",
            "volume": "sum",
        }
        out = df.resample("1D").agg(agg_dict).dropna().reset_index()
    else:
        p = PANELS_DIR / f"hl_panel_{asset}_{tf}.parquet"
        if not p.exists():
            return pd.DataFrame()
        df = pd.read_parquet(p)
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df = df[df["open_time"] >= DATA_START].copy().reset_index(drop=True)
        out = df

    if len(out) == 0:
        return out
    out["open_time_us"] = (out["open_time"].astype("int64") // 1_000).astype("int64")
    out = out.sort_values("open_time_us").reset_index(drop=True)
    return out


def load_funding(asset: str) -> pd.DataFrame:
    """HL funding parquet or empty df."""
    p = FUNDING_DIR / f"{asset}_funding.parquet"
    if not p.exists():
        return pd.DataFrame()
    f = pd.read_parquet(p)
    return f


# -----------------------------------------------------------------------------
# Indicator helpers
# -----------------------------------------------------------------------------

def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def compute_ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def compute_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    dn = -low.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan))
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return adx


def ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure ATR/EMA stack/ADX present (compute if missing). Returns enriched df."""
    out = df.copy()
    if "atr_14" not in out.columns:
        out["atr_14"] = compute_atr(out, 14)
    if "ema_50" not in out.columns:
        out["ema_50"] = compute_ema(out["close"], 50)
    if "ema_21" not in out.columns:
        out["ema_21"] = compute_ema(out["close"], 21)
    if "ema_100" not in out.columns:
        out["ema_100"] = compute_ema(out["close"], 100)
    if "ema_200" not in out.columns:
        out["ema_200"] = compute_ema(out["close"], 200)
    if "adx_14" not in out.columns:
        out["adx_14"] = compute_adx(out, 14)
    if "rsi_14" not in out.columns:
        out["rsi_14"] = compute_rsi(out["close"], 14)
    # Computed EMA stack: bull if ema_21>ema_50>ema_100>ema_200, etc.
    # Score = sum of pairwise alignments → range [-4, +4]
    if "ema_stack_score" not in out.columns:
        e21, e50, e100, e200 = out["ema_21"], out["ema_50"], out["ema_100"], out["ema_200"]
        # bullish pairs (>): (21>50)+(50>100)+(100>200)+(close>21) all sign +1 / -1
        c = out["close"]
        sgn = lambda a, b: np.sign(a - b)
        out["ema_stack_score"] = (sgn(c, e21) + sgn(e21, e50) +
                                   sgn(e50, e100) + sgn(e100, e200))
    # ema_50 slope (bars-over-bars)
    if "ema_50_slope" not in out.columns:
        out["ema_50_slope"] = out["ema_50"].diff(3)
    return out


# -----------------------------------------------------------------------------
# Signal builders
# -----------------------------------------------------------------------------

def build_donchian_signal(df: pd.DataFrame, n: int) -> pd.Series:
    """+1 when close > prior N-bar high; -1 when close < prior N-bar low; 0 else.
    Uses prior bars (shifted by 1) to avoid using current bar's own data."""
    prior_high = df["high"].shift(1).rolling(n).max()
    prior_low = df["low"].shift(1).rolling(n).min()
    sig = pd.Series(0, index=df.index)
    sig[df["close"] > prior_high] = 1
    sig[df["close"] < prior_low] = -1
    return sig


def build_ema_stack_signal(df: pd.DataFrame, bull_thr: int = 3, bear_thr: int = -3) -> pd.Series:
    """+1 when stack score >= bull_thr, -1 when <= bear_thr.
    With our range [-4,+4], a threshold of 3 catches strong bull/bear alignment."""
    score = df["ema_stack_score"]
    sig = pd.Series(0, index=df.index)
    sig[score >= bull_thr] = 1
    sig[score <= bear_thr] = -1
    return sig


def build_adx_ema_signal(df: pd.DataFrame, adx_thr: float = 25.0) -> pd.Series:
    """+1 when adx>thr AND close>ema_50 AND ema_50 slope up;
       -1 when adx>thr AND close<ema_50 AND ema_50 slope down;
       0 otherwise."""
    adx = df["adx_14"]
    c = df["close"]
    e50 = df["ema_50"]
    slope = df["ema_50_slope"]
    sig = pd.Series(0, index=df.index)
    sig[(adx > adx_thr) & (c > e50) & (slope > 0)] = 1
    sig[(adx > adx_thr) & (c < e50) & (slope < 0)] = -1
    return sig


def build_range_filter_signal(df: pd.DataFrame) -> pd.Series:
    """+1 on rf_dir flips +1 (was non-+1); -1 on flips -1.
    Only emits on the flip bar; subsequent bars are 0 until next flip."""
    if "rf_dir" not in df.columns:
        return pd.Series(0, index=df.index)
    rf = df["rf_dir"].fillna(0)
    prev = rf.shift(1).fillna(0)
    sig = pd.Series(0, index=df.index)
    sig[(rf == 1) & (prev != 1)] = 1
    sig[(rf == -1) & (prev != -1)] = -1
    return sig


def build_cyclops_filter(df: pd.DataFrame) -> pd.Series:
    """Cyclops 3-axis coherence — +1 if (trend>0 AND levels>0); -1 if both <0.
    Trend axis: ema_stack_score sign (range [-4,+4]).
    Levels axis: close vs PP (close_vs_pp_bps sign).
    Momentum: RSI not strongly counter-trend (>= 40 for bull, <= 60 for bear).
    """
    score = df.get("ema_stack_score", pd.Series(0, index=df.index))
    pp_bps = df.get("close_vs_pp_bps", pd.Series(0, index=df.index)).fillna(0)
    rsi = df.get("rsi_14", pd.Series(50, index=df.index)).fillna(50)
    out = pd.Series(0, index=df.index)
    bull = (score >= 1) & (pp_bps > 0) & (rsi >= 40)
    bear = (score <= -1) & (pp_bps < 0) & (rsi <= 60)
    out[bull] = 1
    out[bear] = -1
    return out


# -----------------------------------------------------------------------------
# Cell runner — produces one record per (strategy, asset, tf, variant)
# -----------------------------------------------------------------------------

def _trade_metrics(trades: pd.DataFrame, bars_per_year: float) -> dict:
    """Annualize sharpe by bars/year. Sharpe per-trade × sqrt(trades/year)."""
    if len(trades) == 0:
        return dict(n_trades=0, win_rate=np.nan, avg_pnl_usd=np.nan,
                    total_pnl_usd=0.0, sharpe_ann=np.nan, calmar=np.nan,
                    max_dd_usd=0.0, profit_factor=np.nan, avg_bars_held=np.nan,
                    avg_fees=np.nan, avg_funding=np.nan)
    pnl = trades["pnl_net_usd"].to_numpy()
    n = len(pnl)
    wins = (pnl > 0).sum()
    losses = (pnl < 0).sum()
    pf = float(pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum())) if losses > 0 and pnl[pnl < 0].sum() != 0 else float("inf")
    total = float(pnl.sum())
    cum = np.cumsum(pnl)
    peaks = np.maximum.accumulate(cum)
    dd = cum - peaks
    max_dd = float(dd.min()) if len(dd) else 0.0
    sharpe_per_trade = float(pnl.mean() / pnl.std()) if pnl.std() > 0 else 0.0
    avg_bars_held = float(trades["bars_held"].mean()) if "bars_held" in trades.columns else np.nan
    # Annualized: trades-per-year * sharpe_per_trade ratio
    trades_per_year = bars_per_year / max(1.0, avg_bars_held)
    sharpe_ann = sharpe_per_trade * np.sqrt(trades_per_year)
    calmar = total / abs(max_dd) if max_dd != 0 else float("inf")
    return dict(
        n_trades=n, win_rate=float(wins) / n,
        avg_pnl_usd=float(pnl.mean()),
        total_pnl_usd=total,
        sharpe_ann=sharpe_ann, calmar=calmar, max_dd_usd=max_dd,
        profit_factor=pf, avg_bars_held=avg_bars_held,
        avg_fees=float(trades["fee_paid_usd"].mean()) if "fee_paid_usd" in trades.columns else np.nan,
        avg_funding=float(trades["funding_paid_usd"].mean()) if "funding_paid_usd" in trades.columns else np.nan,
    )


def _bars_per_year(tf: str) -> float:
    return {"15m": 365.25 * 24 * 4, "1h": 365.25 * 24, "4h": 365.25 * 6, "1d": 365.25}[tf]


def _split_70_30(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Time-ordered 70/30 split by entry_us."""
    if len(trades) < 5:
        return trades, pd.DataFrame(columns=trades.columns)
    tr = trades.sort_values("entry_us").reset_index(drop=True)
    cut = int(len(tr) * 0.7)
    return tr.iloc[:cut].reset_index(drop=True), tr.iloc[cut:].reset_index(drop=True)


def _buy_and_hold(df: pd.DataFrame, bars_per_year: float, cfg: HyperliquidConfig) -> dict:
    """Benchmark: enter long at first bar, exit at last bar. Apply fees+slip."""
    if len(df) < 2:
        return dict(bh_sharpe_ann=np.nan, bh_total_pnl_usd=0.0, bh_max_dd_usd=0.0)
    # Per-bar returns
    rets = df["close"].pct_change().dropna()
    if len(rets) < 2:
        return dict(bh_sharpe_ann=np.nan, bh_total_pnl_usd=0.0, bh_max_dd_usd=0.0)
    bh_pnl_per_bar = NOTIONAL * LEVERAGE * rets  # $ per bar at $250 notional 1x
    cum = bh_pnl_per_bar.cumsum()
    peaks = cum.cummax()
    dd = (cum - peaks).min()
    # Fee/slip on entry+exit only
    fee_drag = NOTIONAL * LEVERAGE * (cfg.taker_fee_bps + cfg.taker_fee_bps + cfg.slippage_bps) / 10_000.0
    total = float(cum.iloc[-1] - fee_drag)
    # Sharpe on per-bar PnL
    sigma = bh_pnl_per_bar.std()
    sharpe_ann = float(bh_pnl_per_bar.mean() / sigma * np.sqrt(bars_per_year)) if sigma > 0 else 0.0
    return dict(bh_sharpe_ann=sharpe_ann, bh_total_pnl_usd=total, bh_max_dd_usd=float(dd))


def run_cell(
    strategy_id: str,
    family: str,
    variant: str,
    asset: str,
    tf: str,
    df: pd.DataFrame,
    funding: pd.DataFrame,
    signals: pd.Series,
    cfg: HyperliquidConfig,
    exit_kind: str,
    exit_params: dict | None = None,
    atr_series: pd.Series | None = None,
) -> dict:
    """Run a strategy, compute IS/OOS metrics, return one row."""
    # Use ts_us-derived index to match perp_exit_rules contract
    df_idx = df.copy()
    df_idx.index = df["open_time_us"]
    # signals re-indexed to same
    sig = signals.copy()
    sig.index = df["open_time_us"]
    atr_s = atr_series.copy() if atr_series is not None else df["atr_14"].copy()
    atr_s.index = df["open_time_us"]

    funding_df = funding if asset in HL_FUND_ASSETS and len(funding) > 0 else pd.DataFrame()
    cfg_use = cfg if len(funding_df) > 0 else CFG_NOFUND

    try:
        trades = run_strategy(
            klines=df_idx,
            funding=funding_df if len(funding_df) else pd.DataFrame({
                "funding_rate": [0.0],
                "funding_time_us": [int(df["open_time_us"].iloc[0])]
            }),
            signals=sig,
            atr_series=atr_s,
            exit_kind=exit_kind,
            exit_params=exit_params or {},
            asset=asset,
            notional_usd=NOTIONAL,
            leverage=LEVERAGE,
            cfg=cfg_use,
        )
    except Exception as e:
        print(f"  ERROR {strategy_id}/{asset}/{tf}/{variant}: {e}")
        trades = pd.DataFrame()

    bpy = _bars_per_year(tf)
    full = _trade_metrics(trades, bpy)
    is_tr, oos_tr = _split_70_30(trades) if len(trades) > 0 else (pd.DataFrame(), pd.DataFrame())
    is_m = _trade_metrics(is_tr, bpy)
    oos_m = _trade_metrics(oos_tr, bpy)
    bh = _buy_and_hold(df, bpy, cfg_use)

    return {
        "strategy_id": strategy_id,
        "family": family,
        "variant": variant,
        "asset": asset,
        "tf": tf,
        **full,
        "oos_sharpe": oos_m["sharpe_ann"],
        "oos_pf": oos_m["profit_factor"],
        "oos_n_trades": oos_m["n_trades"],
        "is_sharpe": is_m["sharpe_ann"],
        "is_pf": is_m["profit_factor"],
        "bh_sharpe_ann": bh["bh_sharpe_ann"],
        "bh_total_pnl_usd": bh["bh_total_pnl_usd"],
        "bh_max_dd_usd": bh["bh_max_dd_usd"],
        "beats_bh_sharpe": int(full["sharpe_ann"] > bh["bh_sharpe_ann"]) if not (np.isnan(full["sharpe_ann"]) or np.isnan(bh["bh_sharpe_ann"])) else 0,
    }


# -----------------------------------------------------------------------------
# Main grid
# -----------------------------------------------------------------------------

def load_asset_tf(asset: str, tf: str) -> pd.DataFrame:
    """Unified loader — panel if available, binance else."""
    if asset in ASSETS_WITH_PANELS:
        df = load_panel_klines(asset, tf)
        if len(df) > 0:
            return ensure_indicators(df)
    df = load_binance_klines(asset, tf)
    return ensure_indicators(df) if len(df) > 0 else df


def main() -> None:
    rows: list[dict] = []

    # Donchian variants per spec
    DONCH_N = [20, 50, 100]
    DONCH_ATR = [1.5, 2.0, 3.0]

    # ------------------- A1 Donchian + ATR-trail (4h, 1d) -------------------
    for asset in ALL_ASSETS:
        for tf in ["4h", "1d"]:
            df = load_asset_tf(asset, tf)
            if len(df) < 200:
                print(f"  [skip] A1 {asset} {tf}: only {len(df)} bars")
                continue
            funding = load_funding(asset)
            for n_donch in DONCH_N:
                sig = build_donchian_signal(df, n_donch)
                for atr_m in DONCH_ATR:
                    variant = f"N{n_donch}_ATR{atr_m}"
                    row = run_cell(
                        "A1", "Donchian", variant, asset, tf,
                        df, funding, sig,
                        cfg=CFG_FUND,
                        exit_kind="atr_trail",
                        exit_params={"atr_mult": atr_m, "max_bars": 500},
                    )
                    rows.append(row)
                    print(f"  A1 {asset} {tf} {variant}: n={row['n_trades']} "
                          f"sh={row['sharpe_ann']:.2f} pnl=${row['total_pnl_usd']:.0f}")

    # ------------------- A2 EMA stack crossover (4h, 1d) -------------------
    EMA_THR_PAIRS = [(3, -3), (2, -2), (4, -4)]
    for asset in ALL_ASSETS:
        for tf in ["4h", "1d"]:
            df = load_asset_tf(asset, tf)
            if len(df) < 200:
                continue
            funding = load_funding(asset)
            for bull, bear in EMA_THR_PAIRS:
                sig = build_ema_stack_signal(df, bull, bear)
                variant = f"thr{bull}"
                row = run_cell(
                    "A2", "EMA_Stack", variant, asset, tf,
                    df, funding, sig,
                    cfg=CFG_FUND,
                    exit_kind="signal_flip",
                )
                rows.append(row)
                print(f"  A2 {asset} {tf} {variant}: n={row['n_trades']} "
                      f"sh={row['sharpe_ann']:.2f} pnl=${row['total_pnl_usd']:.0f}")

    # ------------------- A3 ADX-gated EMA trend (1h, 4h) -------------------
    ADX_VARIANTS = [
        ("ADX25_flip", 25.0, "signal_flip", None),
        ("ADX25_trail2", 25.0, "atr_trail", {"atr_mult": 2.0, "max_bars": 500}),
        ("ADX30_flip", 30.0, "signal_flip", None),
    ]
    for asset in ALL_ASSETS:
        for tf in ["1h", "4h"]:
            df = load_asset_tf(asset, tf)
            if len(df) < 200:
                continue
            funding = load_funding(asset)
            for variant, thr, exit_kind, ep in ADX_VARIANTS:
                sig = build_adx_ema_signal(df, thr)
                row = run_cell(
                    "A3", "ADX_EMA", variant, asset, tf,
                    df, funding, sig,
                    cfg=CFG_FUND,
                    exit_kind=exit_kind,
                    exit_params=ep,
                )
                rows.append(row)
                print(f"  A3 {asset} {tf} {variant}: n={row['n_trades']} "
                      f"sh={row['sharpe_ann']:.2f} pnl=${row['total_pnl_usd']:.0f}")

    # ------------------- A4 Range Filter dir-flip (4h, 1d) -------------------
    # rf_dir only available in panels (BTC/ETH/SOL); compute proxy for others.
    for asset in ALL_ASSETS:
        for tf in ["4h", "1d"]:
            df = load_asset_tf(asset, tf)
            if len(df) < 200:
                continue
            if "rf_dir" not in df.columns:
                # Simple proxy: ema_50 slope sign
                slope_sign = np.sign(df["ema_50"].diff(3).fillna(0))
                df = df.copy()
                df["rf_dir"] = slope_sign.astype(int)
            funding = load_funding(asset)
            sig = build_range_filter_signal(df)
            row = run_cell(
                "A4", "RangeFilter", "dir_flip", asset, tf,
                df, funding, sig,
                cfg=CFG_FUND,
                exit_kind="signal_flip",
            )
            rows.append(row)
            print(f"  A4 {asset} {tf}: n={row['n_trades']} "
                  f"sh={row['sharpe_ann']:.2f} pnl=${row['total_pnl_usd']:.0f}")

    # ------------------- A5 Donchian + Cyclops filter (4h, 1d) -------------------
    # Compare A1 vs A1+cyclops. On 1d the close_vs_pp_bps is unavailable
    # (synthesized from 4h), so we fall back to ema_50_slope as the levels proxy.
    for asset in ASSETS_WITH_PANELS:
        for tf in ["4h", "1d"]:
            df = load_asset_tf(asset, tf)
            if len(df) < 200:
                continue
            if "close_vs_pp_bps" not in df.columns:
                # Fallback levels-axis: ema_50 slope sign (positive=above support)
                df = df.copy()
                df["close_vs_pp_bps"] = df["ema_50_slope"]
            funding = load_funding(asset)
            cy = build_cyclops_filter(df)
            for n_donch in [50, 100]:
                base = build_donchian_signal(df, n_donch)
                # AND-gate: only fire when both same direction
                gated = pd.Series(0, index=df.index)
                gated[(base == 1) & (cy == 1)] = 1
                gated[(base == -1) & (cy == -1)] = -1
                variant = f"N{n_donch}_cyclopsAND"
                row = run_cell(
                    "A5", "Donchian_Cyclops", variant, asset, tf,
                    df, funding, gated,
                    cfg=CFG_FUND,
                    exit_kind="atr_trail",
                    exit_params={"atr_mult": 2.0, "max_bars": 500},
                )
                rows.append(row)
                print(f"  A5 {asset} {tf} {variant}: n={row['n_trades']} "
                      f"sh={row['sharpe_ann']:.2f} pnl=${row['total_pnl_usd']:.0f}")

    # ------------------- Write outputs -------------------
    df_res = pd.DataFrame(rows)
    out_csv = OUT_DIR / "A_results.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv} ({len(df_res)} rows)")

    # Top-10 by OOS sharpe (n>=50)
    valid = df_res[df_res["oos_n_trades"] >= 50].sort_values("oos_sharpe", ascending=False)
    print("\nTop-10 cells (OOS Sharpe, n_OOS>=50):")
    if len(valid) == 0:
        print("  (none — relaxing to n>=20)")
        valid = df_res[df_res["oos_n_trades"] >= 20].sort_values("oos_sharpe", ascending=False)
    print(valid.head(10).to_string())


if __name__ == "__main__":
    main()
