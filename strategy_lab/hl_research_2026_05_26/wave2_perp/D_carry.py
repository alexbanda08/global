"""
W2P-D — Basis-carry (N3) and funding-extreme (N2) deep refinement on Hyperliquid.

Builds on W2b results. Tests:
  D1: Basis-carry refinement — z ∈ {1.0,1.5,2.0,2.5,3.0}, hold ∈ {4,8,24,48,72,168}h,
      z-window ∈ {7,14,30,60,90}d, expected-basis proxies {fund30davg, zero-fund, term_next}.
  D1-ATR: Same with early exit if convergence >1.5σ within target hold.
  D2: Funding contrarian vs momentum head-to-head — directional verdict per asset.
  D3: Cross-venue hedged basis arb — LONG HL perp + SHORT Binance perp (delta-neutral).
  D4: Funding-regime → strategy switch composite (basis-carry when extreme, cash otherwise).

Gates G1-G7 from MASTER_PLAN.md:
  G1 binomial p<0.05, G2 net PnL>0, G3 walk-forward 3-fold stable,
  G4 permutation p<0.05, G5 ≥2/3 positive WF folds, G6 bootstrap lo>0, G7 regime hold-out.

Outputs:
  - D_results.csv
  - D_carry.md
  - D_top_candidates.json
"""
from __future__ import annotations

import sys, json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from strategy_lab.hl_research_2026_05_26.hl_engine import (  # noqa: E402
    HyperliquidConfig, run_backtest, _ensure_open_time_us, _ensure_funding_us,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ASSETS_BASIS = ["BTC", "ETH", "SOL"]
ASSETS_FUND  = ["BTC", "ETH", "SOL", "HYPE"]
HL_PERIOD_MAP = {
    "BTC":  "HYPERLIQUID_PERP_BTC_USD",
    "ETH":  "HYPERLIQUID_PERP_ETH_USD",
    "SOL":  "HYPERLIQUID_PERP_SOL_USD",
    "HYPE": "HYPERLIQUID_PERP_HYPE_USD",
}
BNC_PERIOD_MAP = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}
BNC_FUT_PARQUET = {
    "BTC": REPO / "data/binance/parquet/BTCUSDT/1h",
    "ETH": REPO / "data/binance/parquet/ETHUSDT/1h",
    "SOL": REPO / "data/binance/parquet/SOLUSDT/1h",
}
BNC_PREM_PARQUET = {
    "BTC": REPO / "data/binance/futures/premiumIndexKlines/BTCUSDT/1h/parquet/premium_1h.parquet",
    "ETH": REPO / "data/binance/futures/premiumIndexKlines/ETHUSDT/1h/parquet/premium_1h.parquet",
    "SOL": REPO / "data/binance/futures/premiumIndexKlines/SOLUSDT/1h/parquet/premium_1h.parquet",
}
NOTIONAL_USD = 250.0
LEVERAGE     = 1.0
N_PERM       = 1000
N_BOOT       = 10000
RNG_SEED     = 7
MIN_N        = 20


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_hl_klines_1h(asset: str) -> pd.DataFrame:
    p = REPO / "data/v4/canonical/hyperliquid_klines.parquet"
    df = pd.read_parquet(p)
    sub = df[(df.symbol_id == HL_PERIOD_MAP[asset]) & (df.period_id == "1HRS")].copy()
    sub = sub.rename(columns={
        "time_period_start_us": "open_time_us",
        "price_open":   "open",
        "price_high":   "high",
        "price_low":    "low",
        "price_close":  "close",
        "volume_traded": "volume",
    })[["open_time_us", "open", "high", "low", "close", "volume"]]
    return sub.sort_values("open_time_us").reset_index(drop=True)


def load_hl_funding(asset: str) -> pd.DataFrame:
    p = REPO / "data/v4/canonical/hyperliquid_funding.parquet"
    df = pd.read_parquet(p)
    sub = df[df.symbol == asset].copy()
    sub["funding_rate"] = pd.to_numeric(sub["funding_rate"], errors="coerce")
    sub = sub.dropna(subset=["funding_rate"]).sort_values("funding_time_us").reset_index(drop=True)
    return sub[["funding_time_us", "funding_rate", "premium"]]


def load_binance_spot_1h(asset: str) -> pd.DataFrame:
    """Binance spot 1h: vision + ws extension via canonical."""
    v = pd.read_parquet(REPO / "data/v4/canonical/binance_vision_klines.parquet")
    vsub = v[(v.symbol_id == BNC_PERIOD_MAP[asset]) & (v.period_id == "1HRS")].copy()
    vsub = vsub.rename(columns={
        "time_period_start_us": "open_time_us",
        "price_open": "open", "price_high": "high",
        "price_low": "low", "price_close": "close", "volume_traded": "volume",
    })[["open_time_us", "open", "high", "low", "close", "volume"]]

    m = pd.read_parquet(REPO / "data/v4/canonical/klines_1m.parquet")
    msub = m[(m.symbol_id == BNC_PERIOD_MAP[asset])
             & (m.source == "binance-spot-ws")
             & (m.period_id == "1MIN")].copy()
    if len(msub):
        msub = msub.rename(columns={
            "time_period_start_us": "open_time_us",
            "price_open": "open", "price_high": "high",
            "price_low": "low", "price_close": "close", "volume_traded": "volume",
        })[["open_time_us", "open", "high", "low", "close", "volume"]]
        msub["dt"] = pd.to_datetime(msub["open_time_us"], unit="us", utc=True)
        msub = msub.set_index("dt").sort_index()
        ohlc = pd.DataFrame({
            "open":   msub["open"].resample("1h").first(),
            "high":   msub["high"].resample("1h").max(),
            "low":    msub["low"].resample("1h").min(),
            "close":  msub["close"].resample("1h").last(),
            "volume": msub["volume"].resample("1h").sum(),
        }).dropna().reset_index()
        ohlc["open_time_us"] = (ohlc["dt"].astype("int64") // 1_000).astype("int64")
        ohlc = ohlc[["open_time_us", "open", "high", "low", "close", "volume"]]
    else:
        ohlc = pd.DataFrame(columns=["open_time_us", "open", "high", "low", "close", "volume"])

    cat = pd.concat([vsub, ohlc], ignore_index=True)
    cat = cat.drop_duplicates(subset=["open_time_us"]).sort_values("open_time_us").reset_index(drop=True)
    return cat


def load_binance_premium_1h(asset: str) -> pd.DataFrame:
    """Binance futures premium index: (perp_mark - spot_index)/spot_index.

    Used to reconstruct Binance perp price = spot * (1 + premium_close).
    """
    p = BNC_PREM_PARQUET[asset]
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df["open_time_us"] = (pd.to_datetime(df["open_time"], utc=True).astype("int64") // 1_000).astype("int64")
    return df[["open_time_us", "open", "high", "low", "close"]].rename(columns={
        "open": "premium_open", "high": "premium_high",
        "low": "premium_low", "close": "premium_close",
    }).sort_values("open_time_us").reset_index(drop=True)


def load_binance_fut_1h(asset: str) -> pd.DataFrame:
    """Reconstruct Binance futures perp price 1h by asof-joining premium index to spot."""
    spot = load_binance_spot_1h(asset)
    prem = load_binance_premium_1h(asset)
    if prem.empty:
        spot["fut_close"] = spot["close"]
        spot["fut_open"] = spot["open"]
        return spot
    merged = pd.merge_asof(
        spot.sort_values("open_time_us"),
        prem.sort_values("open_time_us"),
        on="open_time_us", direction="backward",
        tolerance=int(3_600_000_000),
    )
    merged["fut_close"] = merged["close"] * (1.0 + merged["premium_close"].fillna(0.0))
    merged["fut_open"]  = merged["open"]  * (1.0 + merged["premium_open"].fillna(0.0))
    return merged


def load_regime_labels(asset: str) -> pd.DataFrame:
    p = REPO / f"strategy_lab/hl_research_2026_05_26/panels/hl_native_panel_{asset}_1h.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["open_time_us", "regime_label"])
    df = pd.read_parquet(p)
    if "ts_us" in df.columns:
        df["open_time_us"] = df["ts_us"].astype("int64")
    elif "open_time" in df.columns:
        df["open_time_us"] = (pd.to_datetime(df["open_time"], utc=True).astype("int64") // 1_000).astype("int64")
    cols = ["open_time_us"]
    if "regime_label" in df.columns:
        cols.append("regime_label")
    return df[cols].dropna()


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------
def build_funding_features(funding: pd.DataFrame, window_days_list: list[int]) -> pd.DataFrame:
    """Add rolling z-scores for multiple windows."""
    f = funding.copy().sort_values("funding_time_us").reset_index(drop=True)
    r = f["funding_rate"]
    for w in window_days_list:
        hrs = w * 24
        mu = r.rolling(hrs, min_periods=max(24, hrs // 4)).mean()
        sd = r.rolling(hrs, min_periods=max(24, hrs // 4)).std()
        f[f"fund_mu_{w}d"] = mu
        f[f"fund_sd_{w}d"] = sd
        f[f"fund_z_{w}d"]  = (r - mu) / sd
    return f


def build_basis_panel(
    hl_klines: pd.DataFrame,
    bnc_klines: pd.DataFrame,
    funding_f: pd.DataFrame,
    hold_hours: int,
    z_window_days: int,
    expected_basis_proxy: str,   # "fund30davg" | "zero_fund" | "term_next"
    z_mu_window_days: int = None,
) -> pd.DataFrame:
    """Build panel with basis_bps, expected_basis_bps, mispricing, z."""
    z_mu_window_days = z_mu_window_days or z_window_days
    hl = hl_klines.sort_values("open_time_us")[["open_time_us", "close"]].rename(columns={"close": "hl_close"})
    bn = bnc_klines.sort_values("open_time_us")[["open_time_us", "close"]].rename(columns={"close": "bnc_close"})
    panel = pd.merge_asof(
        hl, bn, on="open_time_us", direction="backward",
        tolerance=int(3_600_000_000),
    )
    panel = panel.dropna(subset=["bnc_close"]).reset_index(drop=True)
    panel["basis_bps"] = (panel["bnc_close"] - panel["hl_close"]) / panel["hl_close"] * 1e4

    # Asof join funding feature columns
    fa = funding_f.copy()
    keepcols = ["funding_time_us", "funding_rate"]
    for c in fa.columns:
        if c.startswith("fund_mu_") or c.startswith("fund_z_"):
            keepcols.append(c)
    fa = fa[keepcols].rename(columns={"funding_time_us": "open_time_us"})
    panel = pd.merge_asof(
        panel.sort_values("open_time_us"),
        fa.sort_values("open_time_us"),
        on="open_time_us", direction="backward",
        tolerance=int(3_600_000_000),
    )

    # Expected basis proxy
    fund_mu_col = f"fund_mu_{z_mu_window_days}d"
    if fund_mu_col not in panel.columns:
        fund_mu_col = "fund_mu_30d"  # fallback
    if expected_basis_proxy == "fund30davg":
        # 30d-avg funding × hold_hours/8 funding cycles
        panel["expected_basis_bps"] = panel[fund_mu_col] * (hold_hours / 8.0) * 1e4
    elif expected_basis_proxy == "zero_fund":
        # Pure spot-perp, no funding adjustment
        panel["expected_basis_bps"] = 0.0
    elif expected_basis_proxy == "term_next":
        # Use latest realized funding × hours/8 as proxy for next-cycle
        panel["expected_basis_bps"] = panel["funding_rate"] * (hold_hours / 8.0) * 1e4
    else:
        raise ValueError(f"unknown expected_basis_proxy={expected_basis_proxy}")
    panel["mispricing_bps"] = panel["basis_bps"] - panel["expected_basis_bps"]
    hrs = z_window_days * 24
    panel["misp_mu"] = panel["mispricing_bps"].rolling(hrs, min_periods=max(24, hrs // 4)).mean()
    panel["misp_sd"] = panel["mispricing_bps"].rolling(hrs, min_periods=max(24, hrs // 4)).std()
    panel["misp_z"]  = (panel["mispricing_bps"] - panel["misp_mu"]) / panel["misp_sd"]
    return panel


def build_signals_n3_refined(
    panel: pd.DataFrame,
    hold_hours: int,
    z_thresh: float,
    atr_early_exit: bool = False,
    sigma_target: float = 1.5,
) -> pd.DataFrame:
    """
    Mispricing very POSITIVE (binance > hl)  => HL too cheap => LONG HL
    Mispricing very NEGATIVE                  => HL too expensive => SHORT HL

    ATR early-exit: if |misp_z| drops below sigma_target before time_stop, exit early.
    """
    long_mask  = panel["misp_z"] >  z_thresh
    short_mask = panel["misp_z"] < -z_thresh
    sigs = []
    if long_mask.any():
        s = panel.loc[long_mask, ["open_time_us"]].copy()
        s["direction"] = "LONG"
        sigs.append(s)
    if short_mask.any():
        s = panel.loc[short_mask, ["open_time_us"]].copy()
        s["direction"] = "SHORT"
        sigs.append(s)
    if not sigs:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    out = pd.concat(sigs, ignore_index=True).rename(columns={"open_time_us": "signal_us"})
    out["exit_us"] = out["signal_us"] + int(hold_hours * 3_600_000_000)
    out = out.sort_values("signal_us").reset_index(drop=True)

    if atr_early_exit:
        # For each signal, scan panel for misp_z mean-reversion to ±sigma_target within hold window
        panel_sorted = panel.sort_values("open_time_us").reset_index(drop=True)
        times = panel_sorted["open_time_us"].to_numpy()
        z_arr = panel_sorted["misp_z"].to_numpy()
        for i, row in out.iterrows():
            t0 = row["signal_us"]; t1 = row["exit_us"]
            i0 = np.searchsorted(times, t0, side="right")
            i1 = min(np.searchsorted(times, t1, side="right"), len(times))
            if i0 >= i1:
                continue
            zfwd = z_arr[i0:i1]
            if row["direction"] == "LONG":
                # LONG when z>thresh; exit early when z drops to ≤ sigma_target
                hit = np.where(zfwd <= sigma_target)[0]
            else:
                hit = np.where(zfwd >= -sigma_target)[0]
            if len(hit):
                out.at[i, "exit_us"] = int(times[i0 + hit[0]])
    return out


def build_signals_funding(
    funding_f: pd.DataFrame,
    z_col: str,
    z_thresh: float,
    hold_hours: int,
    direction_pos: Literal["LONG", "SHORT"],
    direction_neg: Literal["LONG", "SHORT"],
) -> pd.DataFrame:
    """Generate funding-extreme signals.

    direction_pos: position to take when z > +z_thresh
    direction_neg: position to take when z < -z_thresh

    Contrarian (mean-reverting): high funding -> SHORT, low -> LONG  (pos=SHORT, neg=LONG)
    Momentum  (trend-confirming): high funding -> LONG, low -> SHORT  (pos=LONG,  neg=SHORT)

    De-duplicates: a "fire" is the TRANSITION INTO the extreme zone (not every bar).
    """
    f = funding_f.copy()
    z = f[z_col]
    z_prev = z.shift(1)
    high_z = (z >  z_thresh) & ~(z_prev >  z_thresh)
    low_z  = (z < -z_thresh) & ~(z_prev < -z_thresh)
    rows = []
    if high_z.any():
        s = f.loc[high_z.fillna(False), ["funding_time_us"]].copy()
        s["direction"] = direction_pos
        rows.append(s)
    if low_z.any():
        s = f.loc[low_z.fillna(False), ["funding_time_us"]].copy()
        s["direction"] = direction_neg
        rows.append(s)
    if not rows:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    out = pd.concat(rows, ignore_index=True).rename(columns={"funding_time_us": "signal_us"})
    out["exit_us"] = out["signal_us"] + int(hold_hours * 3_600_000_000)
    return out.sort_values("signal_us").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Hedged delta-neutral backtest (D3)
# ---------------------------------------------------------------------------
def hedged_basis_arb_backtest(
    hl_klines: pd.DataFrame,
    bnc_fut: pd.DataFrame,
    hl_funding: pd.DataFrame,
    panel: pd.DataFrame,
    z_thresh: float,
    hold_hours: int,
    notional_usd: float = NOTIONAL_USD,
    cfg: HyperliquidConfig = None,
    bnc_taker_bps: float = 4.0,
    bnc_funding_per_8h_bps: float = 1.0,  # avg Binance funding ~0.01% / 8h, approximate
) -> tuple[pd.DataFrame, dict]:
    """
    When HL basis cheap (z>+thresh): LONG HL perp + SHORT Binance perp.
    When HL basis rich  (z<-thresh): SHORT HL perp + LONG Binance perp.

    Each leg = notional_usd; total notional = 2× notional_usd.
    Strategy is delta-neutral by construction.
    PnL = HL_leg_pnl + Bnc_leg_pnl - 2× fees - net_funding_difference.
    """
    if cfg is None:
        cfg = HyperliquidConfig()
    sigs = build_signals_n3_refined(panel, hold_hours, z_thresh, atr_early_exit=False)
    if sigs.empty:
        return pd.DataFrame(), {"n_trades": 0, "total_pnl_usd": 0.0,
                                "sharpe": float("nan"), "n_wins": 0,
                                "win_rate": float("nan"), "avg_pnl_usd": float("nan"),
                                "max_dd_usd": 0.0, "mkt_corr": float("nan")}
    # HL side as usual (signal direction)
    hl_trades, _ = run_backtest(hl_klines, hl_funding, sigs, "HL",
                                notional_usd=notional_usd, leverage=1.0, cfg=cfg)
    # Binance side: opposite direction, same timing
    sigs_bnc = sigs.copy()
    sigs_bnc["direction"] = sigs_bnc["direction"].map({"LONG": "SHORT", "SHORT": "LONG"})
    # Build a synthetic kline df for Binance perp + a zero-funding stub
    bnc_fut_kl = bnc_fut[["open_time_us", "fut_open", "fut_close"]].copy()
    bnc_fut_kl = bnc_fut_kl.rename(columns={"fut_open": "open", "fut_close": "close"})
    bnc_fut_kl["high"] = bnc_fut_kl["close"]
    bnc_fut_kl["low"] = bnc_fut_kl["close"]
    bnc_fut_kl["volume"] = 0.0
    bnc_fut_kl = bnc_fut_kl.dropna()
    # Stub funding for Binance: a single zero row per hour
    stub_fnd = bnc_fut_kl[["open_time_us"]].copy()
    stub_fnd["funding_rate"] = 0.0
    stub_fnd["funding_time_us"] = stub_fnd["open_time_us"]
    bnc_cfg = HyperliquidConfig(taker_fee_bps=bnc_taker_bps, slippage_bps=cfg.slippage_bps,
                                latency_ms=cfg.latency_ms, max_leverage=cfg.max_leverage)
    bnc_trades, _ = run_backtest(bnc_fut_kl, stub_fnd, sigs_bnc, "BNC",
                                 notional_usd=notional_usd, leverage=1.0, cfg=bnc_cfg)
    if hl_trades.empty or bnc_trades.empty:
        return pd.DataFrame(), {"n_trades": 0, "total_pnl_usd": 0.0,
                                "sharpe": float("nan"), "n_wins": 0,
                                "win_rate": float("nan"), "avg_pnl_usd": float("nan"),
                                "max_dd_usd": 0.0, "mkt_corr": float("nan")}
    # Inner-join trades on signal_us (each side should align)
    pair = hl_trades.merge(bnc_trades, on="signal_us", suffixes=("_hl", "_bnc"))
    pair["pnl_combined"] = pair["pnl_net_usd_hl"] + pair["pnl_net_usd_bnc"]

    # Net funding diff: in hedged trade, you're collecting funding on one side and paying on the other.
    # On HL, the funding accrual is already in pnl_net_usd_hl. We need to ADD an estimate for Binance funding.
    # Use Binance avg funding (assumed 0.01% per 8h here); for net-neutral the funding paid on one venue is
    # roughly matched by the funding received on the other, so the NET is the DIFFERENCE in rates.
    # Approx: bnc funding paid per leg ~ pos × bnc_funding_per_8h × hold/8 .
    hours_arr = pair["bars_held_bnc"].to_numpy().astype(float)
    bnc_fund_frac_per_8h = bnc_funding_per_8h_bps / 10_000.0
    # Direction on bnc leg = opposite of hl. If bnc leg is SHORT, receives funding (subtract from cost).
    # If LONG, pays. We approximate net as: bnc_fund_per_8h × hours/8 × sign(short=-1).
    bnc_dir_sign = pair["direction_bnc"].map({"LONG": +1.0, "SHORT": -1.0}).to_numpy()
    bnc_fund_paid = bnc_dir_sign * notional_usd * bnc_fund_frac_per_8h * (hours_arr / 8.0)
    pair["bnc_funding_paid_usd"] = bnc_fund_paid
    pair["pnl_net_combined"] = pair["pnl_combined"] - bnc_fund_paid

    pnls = pair["pnl_net_combined"].to_numpy()
    n = len(pair)
    wins = int((pnls > 0).sum())
    sharpe = float((pnls.mean() / pnls.std()) * np.sqrt(252)) if pnls.std() > 0 else float("nan")
    cum = np.cumsum(pnls); peaks = np.maximum.accumulate(cum); dd = cum - peaks
    max_dd = float(dd.min()) if n else 0.0

    # Market correlation: corr(pnl, hl_return over same period)
    # Use entry price → exit price return on HL kline as "market".
    mkt_ret = (pair["exit_price_hl"] / pair["entry_price_hl"] - 1.0).to_numpy()
    if pnls.std() > 0 and mkt_ret.std() > 0:
        mkt_corr = float(np.corrcoef(pnls, mkt_ret)[0, 1])
    else:
        mkt_corr = float("nan")
    stats_d = {
        "n_trades": n, "n_wins": wins,
        "win_rate": wins / n if n else float("nan"),
        "total_pnl_usd": float(pnls.sum()),
        "avg_pnl_usd": float(pnls.mean()) if n else float("nan"),
        "sharpe": sharpe, "max_dd_usd": max_dd,
        "mkt_corr": mkt_corr,
        "avg_funding_paid": float(pair["funding_paid_usd_hl"].mean()) if n else 0.0,
        "avg_fees_paid": float(pair[["fee_in_usd_hl","fee_out_usd_hl","fee_in_usd_bnc","fee_out_usd_bnc"]].sum(axis=1).mean()) if n else 0.0,
    }
    return pair, stats_d


# ---------------------------------------------------------------------------
# D4: regime-switch composite
# ---------------------------------------------------------------------------
def regime_switch_backtest(
    hl_klines: pd.DataFrame,
    bnc_klines: pd.DataFrame,
    hl_funding: pd.DataFrame,
    funding_f: pd.DataFrame,
    panel: pd.DataFrame,
    z_basis_thresh: float,
    hold_hours: int,
    fund_z_extreme: float = 1.0,
    fund_z_col: str = "fund_z_30d",
    cfg: HyperliquidConfig = None,
) -> tuple[pd.DataFrame, dict]:
    """When funding |z| >= fund_z_extreme: trade basis carry. Otherwise: skip (cash)."""
    if cfg is None:
        cfg = HyperliquidConfig()
    # panel already contains fund_z_* columns from build_basis_panel; use directly.
    if fund_z_col not in panel.columns:
        # Asof-join funding-z to panel (fallback)
        fa = funding_f[["funding_time_us", fund_z_col]].rename(columns={"funding_time_us": "open_time_us"})
        p = pd.merge_asof(panel.sort_values("open_time_us"), fa.sort_values("open_time_us"),
                          on="open_time_us", direction="backward",
                          tolerance=int(3_600_000_000))
    else:
        p = panel
    # Filter: only fire on bars where funding regime is extreme
    p_extreme = p[p[fund_z_col].abs() >= fund_z_extreme].copy()
    if p_extreme.empty:
        return pd.DataFrame(), {"n_trades": 0, "total_pnl_usd": 0.0, "sharpe": float("nan"),
                                "n_wins": 0, "win_rate": float("nan"), "avg_pnl_usd": float("nan"),
                                "max_dd_usd": 0.0}
    sigs = build_signals_n3_refined(p_extreme, hold_hours, z_basis_thresh, atr_early_exit=False)
    if sigs.empty:
        return pd.DataFrame(), {"n_trades": 0, "total_pnl_usd": 0.0, "sharpe": float("nan"),
                                "n_wins": 0, "win_rate": float("nan"), "avg_pnl_usd": float("nan"),
                                "max_dd_usd": 0.0}
    trades, st = run_backtest(hl_klines, hl_funding, sigs, "HL",
                              notional_usd=NOTIONAL_USD, leverage=1.0, cfg=cfg)
    return trades, st


# ---------------------------------------------------------------------------
# Stats / Gates
# ---------------------------------------------------------------------------
def binomial_p(n_wins: int, n_trades: int) -> float:
    if n_trades == 0:
        return float("nan")
    return float(stats.binomtest(n_wins, n_trades, 0.5, alternative="two-sided").pvalue)


def perm_test_sharpe(pnls: np.ndarray, n_perm: int = N_PERM, seed: int = RNG_SEED) -> float:
    """Vectorized sign-flip permutation test."""
    if len(pnls) < 3 or pnls.std() == 0:
        return float("nan")
    obs = pnls.mean() / pnls.std()
    rng = np.random.default_rng(seed)
    n = len(pnls)
    # Build a (n_perm, n) sign matrix
    signs = rng.choice([-1.0, 1.0], size=(n_perm, n))
    shuffled = signs * pnls
    means = shuffled.mean(axis=1)
    stds = shuffled.std(axis=1) + 1e-12
    sharpes = means / stds
    higher = int((sharpes >= obs).sum())
    return (higher + 1) / (n_perm + 1)


def bootstrap_sharpe_ci(pnls: np.ndarray, n_boot: int = N_BOOT, seed: int = RNG_SEED) -> tuple[float, float]:
    """Vectorized bootstrap of Sharpe."""
    if len(pnls) < 3 or pnls.std() == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n = len(pnls)
    idx = rng.integers(0, n, size=(n_boot, n))
    samples = pnls[idx]    # (n_boot, n)
    means = samples.mean(axis=1)
    stds = samples.std(axis=1) + 1e-12
    sharpes = means / stds
    lo, hi = np.percentile(sharpes, [2.5, 97.5])
    return float(lo), float(hi)


def walk_forward(klines, funding, signals, asset, cfg, n_folds=3):
    if len(signals) < n_folds * 5:
        return {"wf_n_folds": 0, "wf_mean_sharpe": float("nan"),
                "wf_pos_folds": 0, "wf_stable": False}
    s = signals.sort_values("signal_us").reset_index(drop=True)
    folds = np.array_split(s, n_folds)
    sharpes = []
    pos = 0
    for f in folds:
        if len(f) < 3:
            sharpes.append(float("nan"))
            continue
        _, st = run_backtest(klines, funding, f, asset,
                             notional_usd=NOTIONAL_USD, leverage=LEVERAGE, cfg=cfg)
        s_val = st.get("sharpe", float("nan"))
        sharpes.append(s_val)
        if not np.isnan(s_val) and s_val > 0:
            pos += 1
    arr = np.array(sharpes, dtype=float)
    finite = arr[np.isfinite(arr)]
    return {
        "wf_n_folds": int(np.isfinite(arr).sum()),
        "wf_mean_sharpe": float(finite.mean()) if len(finite) else float("nan"),
        "wf_pos_folds": int(pos),
        "wf_stable": bool(pos >= 2 and np.isfinite(arr).sum() == n_folds),
        "wf_sharpes": arr.tolist(),
    }


def regime_holdout(klines, funding, signals, asset, cfg, regime_df: pd.DataFrame) -> dict:
    """G7: split signals by regime, require sharpe positive in EACH non-empty regime."""
    if regime_df.empty or len(signals) < 30:
        return {"g7_regime_min_sharpe": float("nan"), "g7_pass": False, "g7_regimes_covered": 0}
    sigs = signals.sort_values("signal_us").copy()
    rdf = regime_df.sort_values("open_time_us")
    merged = pd.merge_asof(sigs, rdf, left_on="signal_us", right_on="open_time_us",
                           direction="backward", allow_exact_matches=True)
    if "regime_label" not in merged.columns:
        return {"g7_regime_min_sharpe": float("nan"), "g7_pass": False, "g7_regimes_covered": 0}
    regimes = merged["regime_label"].dropna().unique().tolist()
    sharpes = []
    for lbl in regimes:
        sub = merged[merged["regime_label"] == lbl][["signal_us", "direction", "exit_us"]]
        if len(sub) < 5:
            continue
        _, st = run_backtest(klines, funding, sub, asset, notional_usd=NOTIONAL_USD,
                             leverage=LEVERAGE, cfg=cfg)
        if st["n_trades"] >= 5:
            sharpes.append(st.get("sharpe", float("nan")))
    finite = [x for x in sharpes if np.isfinite(x)]
    if not finite:
        return {"g7_regime_min_sharpe": float("nan"), "g7_pass": False, "g7_regimes_covered": 0}
    min_s = min(finite)
    return {"g7_regime_min_sharpe": float(min_s), "g7_pass": bool(min_s > 0),
            "g7_regimes_covered": len(finite)}


def score_cell(label: str, params: dict, signals: pd.DataFrame,
               klines: pd.DataFrame, funding: pd.DataFrame, asset: str,
               cfg: HyperliquidConfig, regime_df: pd.DataFrame,
               run_g7: bool = True) -> dict:
    n_sig = len(signals)
    out = {"label": label, **params, "n_signals": n_sig, "status": "OK"}
    if n_sig < MIN_N:
        out.update({"status": "INSUFFICIENT", "n_trades": 0, "win_rate": float("nan"),
                    "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"), "sharpe": float("nan"),
                    "g1_p": float("nan"), "g1_pass": False, "g2_pass": False,
                    "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
                    "g4_perm_p": float("nan"), "g4_pass": False,
                    "g5_pos_folds": 0, "g5_pass": False,
                    "g6_boot_lo": float("nan"), "g6_boot_hi": float("nan"), "g6_pass": False,
                    "g7_regime_min_sharpe": float("nan"), "g7_pass": False,
                    "all_gates_pass": False, "avg_funding": 0.0, "avg_fees": 0.0})
        return out
    trades_df, st = run_backtest(klines, funding, signals, asset,
                                 notional_usd=NOTIONAL_USD, leverage=LEVERAGE, cfg=cfg)
    n_trades = int(st["n_trades"])
    if n_trades < MIN_N:
        out.update({"status": "INSUFFICIENT", "n_trades": n_trades,
                    "win_rate": st.get("win_rate", float("nan")),
                    "total_pnl_usd": st.get("total_pnl_usd", 0.0),
                    "avg_pnl_usd": st.get("avg_pnl_usd", float("nan")),
                    "sharpe": st.get("sharpe", float("nan")),
                    "g1_p": float("nan"), "g1_pass": False, "g2_pass": False,
                    "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
                    "g4_perm_p": float("nan"), "g4_pass": False,
                    "g5_pos_folds": 0, "g5_pass": False,
                    "g6_boot_lo": float("nan"), "g6_boot_hi": float("nan"), "g6_pass": False,
                    "g7_regime_min_sharpe": float("nan"), "g7_pass": False,
                    "all_gates_pass": False, "avg_funding": 0.0, "avg_fees": 0.0})
        return out
    pnls = trades_df["pnl_net_usd"].to_numpy()
    n_wins = int(st["n_wins"])
    p_g1 = binomial_p(n_wins, n_trades)
    p_g4 = perm_test_sharpe(pnls, n_perm=N_PERM)
    boot_lo, boot_hi = bootstrap_sharpe_ci(pnls, n_boot=N_BOOT)
    wf = walk_forward(klines, funding, signals, asset, cfg)
    g7 = regime_holdout(klines, funding, signals, asset, cfg, regime_df) if run_g7 else {
        "g7_regime_min_sharpe": float("nan"), "g7_pass": False, "g7_regimes_covered": 0}
    g1_pass = not np.isnan(p_g1) and p_g1 < 0.05
    g2_pass = st["total_pnl_usd"] > 0
    g3_pass = wf["wf_stable"]
    g4_pass = not np.isnan(p_g4) and p_g4 < 0.05
    g5_pass = wf["wf_pos_folds"] >= 2
    g6_pass = not np.isnan(boot_lo) and boot_lo > 0
    g7_pass = g7["g7_pass"]
    out.update({
        "n_trades": n_trades, "win_rate": st["win_rate"],
        "total_pnl_usd": st["total_pnl_usd"], "avg_pnl_usd": st["avg_pnl_usd"],
        "sharpe": st["sharpe"],
        "g1_p": p_g1, "g1_pass": g1_pass, "g2_pass": g2_pass,
        "g3_wf_stable": g3_pass, "g3_wf_mean_sharpe": wf["wf_mean_sharpe"],
        "g4_perm_p": p_g4, "g4_pass": g4_pass,
        "g5_pos_folds": wf["wf_pos_folds"], "g5_pass": g5_pass,
        "g6_boot_lo": boot_lo, "g6_boot_hi": boot_hi, "g6_pass": g6_pass,
        "g7_regime_min_sharpe": g7["g7_regime_min_sharpe"], "g7_pass": g7_pass,
        "all_gates_pass": bool(g1_pass and g2_pass and g3_pass and g4_pass and g5_pass and g6_pass and g7_pass),
        "avg_funding": st["avg_funding_paid"], "avg_fees": st["avg_fees_paid"],
    })
    return out


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
def main():
    import sys as _sys
    cfg = HyperliquidConfig()
    print(f"=== W2P-D carry refinement ===", flush=True)
    print(f"Engine: {cfg}", flush=True)
    rows = []

    # ---------------- Pre-load all asset data ----------------
    Z_WINDOWS = [7, 14, 30, 60, 90]
    asset_data = {}
    for asset in set(ASSETS_BASIS + ASSETS_FUND):
        try:
            kl  = load_hl_klines_1h(asset)
            fnd = load_hl_funding(asset)
            fund_f = build_funding_features(fnd, Z_WINDOWS)
            reg = load_regime_labels(asset)
            asset_data[asset] = {
                "kl": kl, "fnd": fnd, "fund_f": fund_f, "regime": reg,
            }
            print(f"  loaded {asset}: hl_klines={len(kl)} funding={len(fnd)} regime_rows={len(reg)}")
        except Exception as e:
            print(f"  failed to load {asset}: {e}")

    # =================================================================
    # D1 — Basis-carry refinement
    # =================================================================
    print("\n=========== D1 Basis-carry refinement ===========", flush=True)
    HOLDS_D1 = [4, 8, 24, 48, 72, 168]
    Z_THR_D1 = [1.0, 1.5, 2.0, 2.5, 3.0]
    PROXIES = ["fund30davg", "zero_fund", "term_next"]
    n_d1_target = len(ASSETS_BASIS) * len(Z_WINDOWS) * len(PROXIES) * len(HOLDS_D1) * len(Z_THR_D1) * 2
    print(f"  D1 grid size: {n_d1_target} cells", flush=True)
    panel_cache = {}
    n_done = 0
    for asset in ASSETS_BASIS:
        if asset not in asset_data:
            continue
        kl = asset_data[asset]["kl"]
        fnd = asset_data[asset]["fnd"]
        fund_f = asset_data[asset]["fund_f"]
        reg = asset_data[asset]["regime"]
        try:
            bnc = load_binance_spot_1h(asset)
        except Exception as e:
            print(f"  D1 {asset} bnc load failed: {e}", flush=True)
            continue
        for z_win in Z_WINDOWS:
            for proxy in PROXIES:
                pkey = (asset, z_win, proxy)
                if pkey in panel_cache:
                    panel = panel_cache[pkey]
                else:
                    panel = build_basis_panel(kl, bnc, fund_f, hold_hours=24,
                                              z_window_days=z_win,
                                              expected_basis_proxy=proxy,
                                              z_mu_window_days=z_win)
                    panel_cache[pkey] = panel
                for h in HOLDS_D1:
                    pp = panel.copy()
                    if proxy == "fund30davg":
                        fund_mu_col = f"fund_mu_{z_win}d"
                        if fund_mu_col in pp.columns:
                            pp["expected_basis_bps"] = pp[fund_mu_col] * (h / 8.0) * 1e4
                    elif proxy == "term_next":
                        pp["expected_basis_bps"] = pp["funding_rate"] * (h / 8.0) * 1e4
                    pp["mispricing_bps"] = pp["basis_bps"] - pp["expected_basis_bps"]
                    hrs = z_win * 24
                    pp["misp_mu"] = pp["mispricing_bps"].rolling(hrs, min_periods=max(24, hrs // 4)).mean()
                    pp["misp_sd"] = pp["mispricing_bps"].rolling(hrs, min_periods=max(24, hrs // 4)).std()
                    pp["misp_z"]  = (pp["mispricing_bps"] - pp["misp_mu"]) / pp["misp_sd"]
                    for z_thr in Z_THR_D1:
                        for atr_exit in [False, True]:
                            sigs = build_signals_n3_refined(pp, h, z_thr,
                                                            atr_early_exit=atr_exit,
                                                            sigma_target=1.5)
                            label = f"D1|{asset}|z{z_thr}|h{h}h|zwin{z_win}d|{proxy}|atr{int(atr_exit)}"
                            params = {"family": "D1", "asset": asset,
                                      "z_thresh": z_thr, "hold_h": h,
                                      "z_window_d": z_win, "expected_proxy": proxy,
                                      "atr_exit": int(atr_exit)}
                            res = score_cell(label, params, sigs, kl, fnd, asset, cfg, reg)
                            rows.append(res)
                            n_done += 1
                            if n_done % 100 == 0:
                                print(f"  D1 progress: {n_done}/{n_d1_target}", flush=True)
            ok = sum(1 for r in rows if r.get("family") == "D1" and r["asset"] == asset
                     and r.get("z_window_d") == z_win and r["status"] == "OK")
            print(f"  D1 {asset} z_win={z_win}d done: {ok} OK cells", flush=True)

    # =================================================================
    # D2 — Funding contrarian vs momentum head-to-head
    # =================================================================
    print("\n=========== D2 Funding contrarian vs momentum ===========", flush=True)
    HOLDS_D2 = [24, 48, 72, 168]
    Z_THR_D2 = [0.5, 1.0, 1.5, 2.0]
    for asset in ASSETS_FUND:
        if asset not in asset_data:
            continue
        kl = asset_data[asset]["kl"]
        fnd = asset_data[asset]["fnd"]
        fund_f = asset_data[asset]["fund_f"]
        reg = asset_data[asset]["regime"]
        for z_win in [14, 30, 60]:
            zcol = f"fund_z_{z_win}d"
            if zcol not in fund_f.columns:
                continue
            for h in HOLDS_D2:
                for z_thr in Z_THR_D2:
                    # Contrarian: pos=>SHORT, neg=>LONG
                    sigs_c = build_signals_funding(fund_f, zcol, z_thr, h, "SHORT", "LONG")
                    label_c = f"D2-CONTR|{asset}|z{z_thr}|h{h}h|zwin{z_win}d"
                    pcs = {"family": "D2-CONTR", "asset": asset, "z_thresh": z_thr,
                           "hold_h": h, "z_window_d": z_win, "expected_proxy": "n/a",
                           "atr_exit": 0}
                    rows.append(score_cell(label_c, pcs, sigs_c, kl, fnd, asset, cfg, reg, run_g7=False))

                    # Momentum: pos=>LONG, neg=>SHORT
                    sigs_m = build_signals_funding(fund_f, zcol, z_thr, h, "LONG", "SHORT")
                    label_m = f"D2-MOMO|{asset}|z{z_thr}|h{h}h|zwin{z_win}d"
                    pms = {"family": "D2-MOMO", "asset": asset, "z_thresh": z_thr,
                           "hold_h": h, "z_window_d": z_win, "expected_proxy": "n/a",
                           "atr_exit": 0}
                    rows.append(score_cell(label_m, pms, sigs_m, kl, fnd, asset, cfg, reg, run_g7=False))
        print(f"  D2 {asset} done", flush=True)

    # =================================================================
    # D3 — Cross-venue hedged basis arb (delta-neutral)
    # =================================================================
    print("\n=========== D3 Cross-venue hedged basis arb ===========", flush=True)
    HOLDS_D3 = [24, 48, 72]
    Z_THR_D3 = [1.0, 1.5, 2.0]
    for asset in ASSETS_BASIS:
        if asset not in asset_data:
            continue
        kl = asset_data[asset]["kl"]
        fnd = asset_data[asset]["fnd"]
        fund_f = asset_data[asset]["fund_f"]
        try:
            bnc_fut = load_binance_fut_1h(asset)
        except Exception as e:
            print(f"  D3 {asset} bnc_fut load failed: {e}")
            continue
        for h in HOLDS_D3:
            panel = build_basis_panel(kl, bnc_fut, fund_f, hold_hours=h,
                                      z_window_days=30,
                                      expected_basis_proxy="fund30davg",
                                      z_mu_window_days=30)
            for z_thr in Z_THR_D3:
                try:
                    pair_df, st = hedged_basis_arb_backtest(
                        kl, bnc_fut, fnd, panel, z_thresh=z_thr,
                        hold_hours=h, cfg=cfg,
                    )
                except Exception as e:
                    print(f"  D3 {asset} h{h} z{z_thr} backtest failed: {e}")
                    continue
                n = st["n_trades"]
                if n < MIN_N:
                    rows.append({
                        "label": f"D3|{asset}|z{z_thr}|h{h}h",
                        "family": "D3", "asset": asset, "z_thresh": z_thr,
                        "hold_h": h, "z_window_d": 30, "expected_proxy": "fund30davg",
                        "atr_exit": 0, "n_signals": n, "status": "INSUFFICIENT",
                        "n_trades": n, "win_rate": st["win_rate"],
                        "total_pnl_usd": st["total_pnl_usd"],
                        "avg_pnl_usd": st["avg_pnl_usd"],
                        "sharpe": st["sharpe"],
                        "g1_p": float("nan"), "g1_pass": False, "g2_pass": False,
                        "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
                        "g4_perm_p": float("nan"), "g4_pass": False,
                        "g5_pos_folds": 0, "g5_pass": False,
                        "g6_boot_lo": float("nan"), "g6_boot_hi": float("nan"), "g6_pass": False,
                        "g7_regime_min_sharpe": float("nan"), "g7_pass": False,
                        "all_gates_pass": False, "avg_funding": st.get("avg_funding_paid", 0.0),
                        "avg_fees": st.get("avg_fees_paid", 0.0),
                        "mkt_corr": st.get("mkt_corr", float("nan")),
                        "mkt_neutral": False,
                    })
                    continue
                pnls = pair_df["pnl_net_combined"].to_numpy()
                wins = int((pnls > 0).sum())
                p_g1 = binomial_p(wins, n)
                p_g4 = perm_test_sharpe(pnls)
                boot_lo, boot_hi = bootstrap_sharpe_ci(pnls)
                mkt_corr = st["mkt_corr"]
                mkt_neutral = abs(mkt_corr) < 0.2 if not np.isnan(mkt_corr) else False
                rows.append({
                    "label": f"D3|{asset}|z{z_thr}|h{h}h",
                    "family": "D3", "asset": asset, "z_thresh": z_thr,
                    "hold_h": h, "z_window_d": 30, "expected_proxy": "fund30davg",
                    "atr_exit": 0, "n_signals": n, "status": "OK",
                    "n_trades": n, "win_rate": st["win_rate"],
                    "total_pnl_usd": st["total_pnl_usd"],
                    "avg_pnl_usd": st["avg_pnl_usd"],
                    "sharpe": st["sharpe"],
                    "g1_p": p_g1, "g1_pass": not np.isnan(p_g1) and p_g1 < 0.05,
                    "g2_pass": st["total_pnl_usd"] > 0,
                    "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
                    "g4_perm_p": p_g4, "g4_pass": not np.isnan(p_g4) and p_g4 < 0.05,
                    "g5_pos_folds": 0, "g5_pass": False,
                    "g6_boot_lo": boot_lo, "g6_boot_hi": boot_hi,
                    "g6_pass": not np.isnan(boot_lo) and boot_lo > 0,
                    "g7_regime_min_sharpe": float("nan"), "g7_pass": False,
                    "all_gates_pass": False,
                    "avg_funding": st.get("avg_funding_paid", 0.0),
                    "avg_fees": st.get("avg_fees_paid", 0.0),
                    "mkt_corr": mkt_corr,
                    "mkt_neutral": mkt_neutral,
                })
                print(f"  D3 {asset} h{h} z{z_thr}: n={n} pnl=${st['total_pnl_usd']:+.2f} "
                      f"sharpe={st['sharpe']:.2f} mkt_corr={mkt_corr:.3f} neutral={mkt_neutral}")

    # =================================================================
    # D4 — Funding-regime → basis-carry switch
    # =================================================================
    print("\n=========== D4 Regime-switch composite ===========", flush=True)
    HOLDS_D4 = [24, 72]
    Z_BASIS_D4 = [1.5, 2.0]
    FUND_Z_REG = [1.0, 1.5]
    for asset in ASSETS_BASIS:
        if asset not in asset_data:
            continue
        kl = asset_data[asset]["kl"]
        fnd = asset_data[asset]["fnd"]
        fund_f = asset_data[asset]["fund_f"]
        reg = asset_data[asset]["regime"]
        try:
            bnc = load_binance_spot_1h(asset)
        except Exception:
            continue
        for h in HOLDS_D4:
            panel = build_basis_panel(kl, bnc, fund_f, hold_hours=h,
                                      z_window_days=30,
                                      expected_basis_proxy="fund30davg",
                                      z_mu_window_days=30)
            for z_b in Z_BASIS_D4:
                for fz in FUND_Z_REG:
                    trades, st = regime_switch_backtest(
                        kl, bnc, fnd, fund_f, panel,
                        z_basis_thresh=z_b, hold_hours=h,
                        fund_z_extreme=fz, fund_z_col="fund_z_30d", cfg=cfg,
                    )
                    n = st["n_trades"]
                    label = f"D4|{asset}|zbasis{z_b}|fz{fz}|h{h}h"
                    pcs = {"family": "D4", "asset": asset, "z_thresh": z_b,
                           "hold_h": h, "z_window_d": 30, "expected_proxy": "fund30davg",
                           "atr_exit": 0, "fund_z_filter": fz}
                    if n < MIN_N:
                        rows.append({
                            "label": label, **pcs, "n_signals": n, "status": "INSUFFICIENT",
                            "n_trades": n, "win_rate": st["win_rate"],
                            "total_pnl_usd": st["total_pnl_usd"], "avg_pnl_usd": st["avg_pnl_usd"],
                            "sharpe": st["sharpe"],
                            "g1_p": float("nan"), "g1_pass": False, "g2_pass": False,
                            "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
                            "g4_perm_p": float("nan"), "g4_pass": False,
                            "g5_pos_folds": 0, "g5_pass": False,
                            "g6_boot_lo": float("nan"), "g6_boot_hi": float("nan"), "g6_pass": False,
                            "g7_regime_min_sharpe": float("nan"), "g7_pass": False,
                            "all_gates_pass": False,
                            "avg_funding": st.get("avg_funding_paid", 0.0),
                            "avg_fees": st.get("avg_fees_paid", 0.0),
                        })
                        continue
                    pnls = trades["pnl_net_usd"].to_numpy()
                    wins = int(st["n_wins"])
                    p_g1 = binomial_p(wins, n)
                    p_g4 = perm_test_sharpe(pnls)
                    boot_lo, boot_hi = bootstrap_sharpe_ci(pnls)
                    # Reuse signals for WF (rebuild from regime-filter mask)
                    sig_for_wf = trades[["signal_us", "direction", "exit_us"]].copy()
                    wf = walk_forward(kl, fnd, sig_for_wf, asset, cfg)
                    g7 = regime_holdout(kl, fnd, sig_for_wf, asset, cfg, reg)
                    g1p = not np.isnan(p_g1) and p_g1 < 0.05
                    g4p = not np.isnan(p_g4) and p_g4 < 0.05
                    g6p = not np.isnan(boot_lo) and boot_lo > 0
                    rows.append({
                        "label": label, **pcs, "n_signals": n, "status": "OK",
                        "n_trades": n, "win_rate": st["win_rate"],
                        "total_pnl_usd": st["total_pnl_usd"], "avg_pnl_usd": st["avg_pnl_usd"],
                        "sharpe": st["sharpe"],
                        "g1_p": p_g1, "g1_pass": g1p,
                        "g2_pass": st["total_pnl_usd"] > 0,
                        "g3_wf_stable": wf["wf_stable"], "g3_wf_mean_sharpe": wf["wf_mean_sharpe"],
                        "g4_perm_p": p_g4, "g4_pass": g4p,
                        "g5_pos_folds": wf["wf_pos_folds"], "g5_pass": wf["wf_pos_folds"] >= 2,
                        "g6_boot_lo": boot_lo, "g6_boot_hi": boot_hi, "g6_pass": g6p,
                        "g7_regime_min_sharpe": g7["g7_regime_min_sharpe"], "g7_pass": g7["g7_pass"],
                        "all_gates_pass": bool(g1p and (st["total_pnl_usd"] > 0) and
                                              wf["wf_stable"] and g4p and (wf["wf_pos_folds"] >= 2) and g6p and g7["g7_pass"]),
                        "avg_funding": st.get("avg_funding_paid", 0.0),
                        "avg_fees": st.get("avg_fees_paid", 0.0),
                    })

    # =================================================================
    # Write outputs
    # =================================================================
    df = pd.DataFrame(rows)
    out_csv = REPO / "strategy_lab/hl_research_2026_05_26/wave2_perp/D_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")
    print(f"Total cells: {len(df)}")
    if len(df):
        print(f"OK cells:        {(df['status']=='OK').sum()}")
        print(f"G1+G2+G4 pass:   {(df['g1_pass'] & df['g2_pass'] & df['g4_pass']).sum()}")
        if "g6_pass" in df.columns:
            print(f"ALL gates pass:  {df['all_gates_pass'].sum()}")
            print("\nTop 10 by Sharpe (all_gates_pass=True, status=OK):")
            top = df[df["all_gates_pass"] & (df["status"] == "OK")].sort_values("sharpe", ascending=False).head(10)
            print(top[["label","family","asset","sharpe","total_pnl_usd","n_trades","win_rate"]].to_string())
            print("\nTop 10 by Sharpe (G1+G2+G4+G6 pass, status=OK):")
            top2 = df[(df["status"] == "OK") & df["g1_pass"] & df["g2_pass"] & df["g4_pass"] & df.get("g6_pass", False)].sort_values("sharpe", ascending=False).head(10)
            print(top2[["label","family","asset","sharpe","total_pnl_usd","n_trades","win_rate"]].to_string())
    return df


if __name__ == "__main__":
    df = main()
