"""
W2b — Funding-rate divergence (N2) and Spot-perp basis carry (N3) on Hyperliquid.

Tests:
- N2 sub-theory A (contrarian): funding > +2σ (30d roll) -> SHORT
- N2 sub-theory B (contrarian): funding < -2σ -> LONG
- N2 sub-theory C (momentum): high funding = strong trend -> LONG with it
- N2 trigger variant: funding zero-crossing (pos->neg => LONG; neg->pos => SHORT)
- N2 regime filter: split by panel `regime_label`
- N3: hourly basis vs expected (30d avg fund x hours/8) -> trade convergence

Gates per cell:
- G1: binomial p < 0.05 vs 50%
- G2: net PnL > 0 with HyperliquidConfig (fees + funding accrual modeled)
- G3: walk-forward (constrained to HL window Jan 30 -> May 16)
- G4: permutation test on signal timestamps (n=1000)
- Bootstrap MC: 10k Sharpe lower-95% CI

Outputs:
- wave2/W2b_funding_basis.md (markdown report)
- wave2/W2b_results.csv (cell-level grid)
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

# Project setup
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from strategy_lab.hl_research_2026_05_26.hl_engine import (  # noqa: E402
    HyperliquidConfig, run_backtest,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ASSETS_N2 = ["BTC", "ETH", "SOL", "HYPE"]
ASSETS_N3 = ["BTC", "ETH", "SOL"]   # no HYPE on Binance
HL_PERIOD_MAP = {
    "BTC":  "HYPERLIQUID_PERP_BTC_USD",
    "ETH":  "HYPERLIQUID_PERP_ETH_USD",
    "SOL":  "HYPERLIQUID_PERP_SOL_USD",
    "HYPE": "HYPERLIQUID_PERP_HYPE_USD",
}
BINANCE_PERIOD_MAP = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}
NOTIONAL_USD = 250.0
LEVERAGE     = 1.0
N_PERM       = 1000
N_BOOT       = 10000
RNG_SEED     = 7
HOLD_HOURS_N2 = [1, 4, 8, 24, 72]
HOLD_HOURS_N3 = [4, 24, 72]
MIN_N         = 20


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_hl_klines_1h(asset: str) -> pd.DataFrame:
    """Load HL 1h klines for one asset, renamed to engine convention."""
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
    })
    sub = sub[["open_time_us", "open", "high", "low", "close", "volume"]]
    sub = sub.sort_values("open_time_us").reset_index(drop=True)
    return sub


def load_hl_funding(asset: str) -> pd.DataFrame:
    """Load HL funding for one asset (hourly)."""
    p = REPO / "data/v4/canonical/hyperliquid_funding.parquet"
    df = pd.read_parquet(p)
    sub = df[df.symbol == asset].copy()
    sub["funding_rate"] = pd.to_numeric(sub["funding_rate"], errors="coerce")
    sub = sub.dropna(subset=["funding_rate"])
    sub = sub.sort_values("funding_time_us").reset_index(drop=True)
    return sub[["funding_time_us", "funding_rate", "premium"]]


def load_binance_spot_1h(asset: str) -> pd.DataFrame:
    """Binance 1h spot, unified from vision parquet + ws-1m extension.

    Vision covers thru Apr 14 2026 23:00; we resample WS 1m thru May 15.
    """
    # Vision 1h
    v = pd.read_parquet(REPO / "data/v4/canonical/binance_vision_klines.parquet")
    vsub = v[(v.symbol_id == BINANCE_PERIOD_MAP[asset]) & (v.period_id == "1HRS")].copy()
    vsub = vsub.rename(columns={
        "time_period_start_us": "open_time_us",
        "price_open":   "open",
        "price_high":   "high",
        "price_low":    "low",
        "price_close":  "close",
        "volume_traded": "volume",
    })[["open_time_us", "open", "high", "low", "close", "volume"]]

    # WS 1m -> resample to 1h
    m = pd.read_parquet(REPO / "data/v4/canonical/klines_1m.parquet")
    msub = m[(m.symbol_id == BINANCE_PERIOD_MAP[asset])
             & (m.source == "binance-spot-ws")
             & (m.period_id == "1MIN")].copy()
    if len(msub):
        msub = msub.rename(columns={
            "time_period_start_us": "open_time_us",
            "price_open":   "open",
            "price_high":   "high",
            "price_low":    "low",
            "price_close":  "close",
            "volume_traded": "volume",
        })[["open_time_us", "open", "high", "low", "close", "volume"]]
        msub["dt"] = pd.to_datetime(msub["open_time_us"], unit="us", utc=True)
        msub = msub.set_index("dt").sort_index()
        ohlc = pd.DataFrame({
            "open":   msub["open"].resample("1h").first(),
            "high":   msub["high"].resample("1h").max(),
            "low":    msub["low"].resample("1h").min(),
            "close":  msub["close"].resample("1h").last(),
            "volume": msub["volume"].resample("1h").sum(),
        }).dropna()
        ohlc = ohlc.reset_index()
        ohlc["open_time_us"] = (ohlc["dt"].astype("int64") // 1_000).astype("int64")
        ohlc = ohlc[["open_time_us", "open", "high", "low", "close", "volume"]]
    else:
        ohlc = pd.DataFrame(columns=["open_time_us", "open", "high", "low", "close", "volume"])

    cat = pd.concat([vsub, ohlc], ignore_index=True)
    cat = cat.drop_duplicates(subset=["open_time_us"]).sort_values("open_time_us").reset_index(drop=True)
    return cat


def load_regime_labels(asset: str) -> pd.DataFrame:
    """Load regime labels from native HL panel at 1h."""
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
# Signal builders
# ---------------------------------------------------------------------------
def build_funding_features(funding: pd.DataFrame, window_hours: int = 30 * 24) -> pd.DataFrame:
    """Add rolling z-score, mean, and crossing flags to funding."""
    f = funding.copy().sort_values("funding_time_us").reset_index(drop=True)
    r = f["funding_rate"]
    mu = r.rolling(window_hours, min_periods=24).mean()
    sd = r.rolling(window_hours, min_periods=24).std()
    f["fund_mu_30d"] = mu
    f["fund_sd_30d"] = sd
    f["fund_z"]      = (r - mu) / sd
    # Sign change crossing (current sign != prev sign)
    sign = np.sign(r)
    f["fund_sign"]     = sign
    f["fund_cross_to_neg"] = (sign < 0) & (sign.shift(1) > 0)
    f["fund_cross_to_pos"] = (sign > 0) & (sign.shift(1) < 0)
    return f


def build_signals_n2(
    funding_f: pd.DataFrame,
    sub_theory: str,
    hold_hours: int,
    z_thresh: float = 2.0,
    regime_filter: str | None = None,
    regime_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Generate one trade per qualifying funding-rate event.

    De-duplicated: a "fire" is the TRANSITION INTO the extreme zone (or the
    crossing event) — NOT every hourly bar that sits in the zone. Avoids the
    issue where a multi-hour over-funded streak inflates n by 5-20x.

    sub_theory:
      "A"  : extreme high funding (z > +z_thresh) -> SHORT
      "B"  : extreme low funding  (z < -z_thresh) -> LONG
      "C_pos": extreme high funding -> LONG (momentum)
      "C_neg": extreme low funding -> SHORT (momentum)
      "cross_to_neg": pos->neg crossing -> LONG
      "cross_to_pos": neg->pos crossing -> SHORT
    """
    f = funding_f.copy()
    z = f["fund_z"]
    z_prev = z.shift(1)
    # Boolean transitions (was NOT in zone, now IS) so we get one fire per streak.
    high_z   = (z > z_thresh) & ~(z_prev > z_thresh)
    low_z    = (z < -z_thresh) & ~(z_prev < -z_thresh)
    if sub_theory == "A":
        mask = high_z
        direction = "SHORT"
    elif sub_theory == "B":
        mask = low_z
        direction = "LONG"
    elif sub_theory == "C_pos":
        mask = high_z
        direction = "LONG"
    elif sub_theory == "C_neg":
        mask = low_z
        direction = "SHORT"
    elif sub_theory == "cross_to_neg":
        mask = f["fund_cross_to_neg"]
        direction = "LONG"
    elif sub_theory == "cross_to_pos":
        mask = f["fund_cross_to_pos"]
        direction = "SHORT"
    else:
        raise ValueError(f"unknown sub_theory {sub_theory}")
    fires = f.loc[mask.fillna(False), ["funding_time_us"]].copy()
    fires = fires.rename(columns={"funding_time_us": "signal_us"})
    fires["direction"] = direction
    fires["exit_us"] = fires["signal_us"] + int(hold_hours * 3_600_000_000)

    # Optional regime filter — asof join at signal_us
    if regime_filter and regime_df is not None and len(regime_df) > 0 and len(fires) > 0:
        rdf = regime_df.sort_values("open_time_us")
        fires = fires.sort_values("signal_us")
        merged = pd.merge_asof(
            fires, rdf, left_on="signal_us", right_on="open_time_us",
            direction="backward", allow_exact_matches=True,
        )
        fires = merged[merged["regime_label"] == regime_filter][["signal_us", "direction", "exit_us"]].copy()
    return fires.reset_index(drop=True)


def build_signals_n3(
    hl_klines: pd.DataFrame,
    bnc_klines: pd.DataFrame,
    funding_f: pd.DataFrame,
    hold_hours: int,
    z_thresh: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """N3 signal:
       basis_bps_t       = (binance_spot_close - hl_perp_close) / hl_perp_close * 1e4
       expected_basis_bps_t = 30d_avg_funding_rate_t * (hold_hours / 8) * 1e4
       mispricing_bps_t  = basis_bps_t - expected_basis_bps_t
       z_t = (mispricing - 30d_roll_mean) / 30d_roll_sd
       Direction:
         mispricing very POSITIVE (binance > hl) => HL too cheap => LONG HL perp
         mispricing very NEGATIVE => HL too expensive => SHORT HL perp

    Returns (signals_df, panel_with_basis)
    """
    # Asof-join binance spot to hl perp on each hourly bar
    hl = hl_klines.sort_values("open_time_us").reset_index(drop=True)[["open_time_us", "close"]]
    hl = hl.rename(columns={"close": "hl_close"})
    bn = bnc_klines.sort_values("open_time_us").reset_index(drop=True)[["open_time_us", "close"]]
    bn = bn.rename(columns={"close": "bnc_close"})
    panel = pd.merge_asof(
        hl, bn, on="open_time_us", direction="backward",
        tolerance=int(3_600_000_000),
    )
    panel = panel.dropna(subset=["bnc_close"]).reset_index(drop=True)
    panel["basis_bps"] = (panel["bnc_close"] - panel["hl_close"]) / panel["hl_close"] * 1e4

    # Asof-join funding (use the 30d avg already in funding_f as fund_mu_30d)
    fa = funding_f[["funding_time_us", "funding_rate", "fund_mu_30d"]].copy()
    panel = pd.merge_asof(
        panel.sort_values("open_time_us"),
        fa.sort_values("funding_time_us").rename(columns={"funding_time_us": "open_time_us"}),
        on="open_time_us", direction="backward",
        tolerance=int(3_600_000_000),
    )
    panel = panel.dropna(subset=["fund_mu_30d"])

    # Expected basis for the hold-window
    panel["expected_basis_bps"] = panel["fund_mu_30d"] * (hold_hours / 8.0) * 1e4
    panel["mispricing_bps"] = panel["basis_bps"] - panel["expected_basis_bps"]
    # 30d-roll z of mispricing
    panel["misp_mu"] = panel["mispricing_bps"].rolling(30 * 24, min_periods=24).mean()
    panel["misp_sd"] = panel["mispricing_bps"].rolling(30 * 24, min_periods=24).std()
    panel["misp_z"] = (panel["mispricing_bps"] - panel["misp_mu"]) / panel["misp_sd"]

    # Long HL if HL too cheap (mispricing very positive -> binance > HL)
    long_mask  = panel["misp_z"] > z_thresh
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
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"]), panel
    out = pd.concat(sigs, ignore_index=True).rename(columns={"open_time_us": "signal_us"})
    out["exit_us"] = out["signal_us"] + int(hold_hours * 3_600_000_000)
    out = out.sort_values("signal_us").reset_index(drop=True)
    return out, panel


# ---------------------------------------------------------------------------
# Stats / Gates
# ---------------------------------------------------------------------------
def binomial_p(n_wins: int, n_trades: int) -> float:
    if n_trades == 0:
        return float("nan")
    return float(stats.binomtest(n_wins, n_trades, 0.5, alternative="two-sided").pvalue)


def perm_test_sharpe(pnls: np.ndarray, n_perm: int = N_PERM, seed: int = RNG_SEED) -> float:
    """For binary direction signals, permutation = sign-flip on pnls.
       Returns the fraction of permutations whose Sharpe >= observed (one-sided).
       This tests whether the observed mean PnL beats random sign flips."""
    if len(pnls) < 3 or pnls.std() == 0:
        return float("nan")
    obs = pnls.mean() / pnls.std()
    rng = np.random.default_rng(seed)
    higher = 0
    for _ in range(n_perm):
        signs = rng.choice([-1, 1], size=len(pnls))
        shuffled = pnls * signs
        s = shuffled.mean() / (shuffled.std() + 1e-12)
        if s >= obs:
            higher += 1
    return (higher + 1) / (n_perm + 1)


def bootstrap_sharpe_ci(pnls: np.ndarray, n_boot: int = N_BOOT, seed: int = RNG_SEED) -> tuple[float, float]:
    if len(pnls) < 3 or pnls.std() == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n = len(pnls)
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        sample = pnls[idx]
        s = sample.mean() / (sample.std() + 1e-12)
        sharpes[i] = s
    lo, hi = np.percentile(sharpes, [2.5, 97.5])
    return float(lo), float(hi)


def walk_forward(
    klines: pd.DataFrame,
    funding: pd.DataFrame,
    signals: pd.DataFrame,
    asset: str,
    cfg: HyperliquidConfig,
    n_folds: int = 3,
) -> dict:
    """Simple time-based walk-forward: split signals into n_folds, each fold
       backtests on its own slice. Returns mean Sharpe and fold-Sharpe std."""
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
        tdf, st = run_backtest(
            klines, funding, f, asset,
            notional_usd=NOTIONAL_USD, leverage=LEVERAGE, cfg=cfg,
        )
        s_val = st.get("sharpe", float("nan"))
        sharpes.append(s_val)
        if not np.isnan(s_val) and s_val > 0:
            pos += 1
    arr = np.array(sharpes, dtype=float)
    finite = arr[np.isfinite(arr)]
    mean_s = float(finite.mean()) if len(finite) else float("nan")
    return {
        "wf_n_folds": int(np.isfinite(arr).sum()),
        "wf_mean_sharpe": mean_s,
        "wf_pos_folds": int(pos),
        "wf_stable": bool(pos >= 2 and np.isfinite(arr).sum() == n_folds),
    }


# ---------------------------------------------------------------------------
# Cell runner
# ---------------------------------------------------------------------------
@dataclass
class Cell:
    hypothesis: str       # "N2-A" / "N2-B" / "N2-C_pos" / "N2-cross_to_neg" / "N3"
    asset: str
    hold_h: int
    z_thresh: float
    regime_filter: str | None

    @property
    def label(self) -> str:
        parts = [self.hypothesis, self.asset, f"h{self.hold_h}h", f"z{self.z_thresh}"]
        if self.regime_filter:
            parts.append(f"reg-{self.regime_filter}")
        return "|".join(parts)


def run_n2_cell(
    cell: Cell,
    klines: pd.DataFrame,
    funding: pd.DataFrame,
    funding_f: pd.DataFrame,
    regime_df: pd.DataFrame,
    cfg: HyperliquidConfig,
) -> dict:
    sub = cell.hypothesis.split("-", 1)[1]   # "A" / "B" / "C_pos" / "C_neg" / "cross_to_neg" / ...
    signals = build_signals_n2(
        funding_f=funding_f, sub_theory=sub, hold_hours=cell.hold_h,
        z_thresh=cell.z_thresh,
        regime_filter=cell.regime_filter, regime_df=regime_df,
    )
    return _score(cell, signals, klines, funding, cfg)


def run_n3_cell(
    cell: Cell,
    hl_klines: pd.DataFrame,
    bnc_klines: pd.DataFrame,
    funding: pd.DataFrame,
    funding_f: pd.DataFrame,
    cfg: HyperliquidConfig,
) -> dict:
    signals, _panel = build_signals_n3(
        hl_klines=hl_klines, bnc_klines=bnc_klines, funding_f=funding_f,
        hold_hours=cell.hold_h, z_thresh=cell.z_thresh,
    )
    return _score(cell, signals, hl_klines, funding, cfg)


def _score(cell: Cell, signals: pd.DataFrame, klines: pd.DataFrame,
           funding: pd.DataFrame, cfg: HyperliquidConfig) -> dict:
    n_sig = len(signals)
    if n_sig < MIN_N:
        return {
            "label": cell.label, "hypothesis": cell.hypothesis, "asset": cell.asset,
            "hold_h": cell.hold_h, "z_thresh": cell.z_thresh,
            "regime_filter": cell.regime_filter or "",
            "n_signals": n_sig, "status": "INSUFFICIENT",
            "n_trades": 0, "win_rate": float("nan"),
            "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"),
            "sharpe": float("nan"),
            "g1_p": float("nan"), "g1_pass": False,
            "g2_pnl_pos": False,
            "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
            "g4_perm_p": float("nan"), "g4_pass": False,
            "boot_lo": float("nan"), "boot_hi": float("nan"),
            "boot_pos": False, "avg_funding": 0.0, "avg_fees": 0.0,
        }
    trades_df, stats_d = run_backtest(
        klines, funding, signals, cell.asset,
        notional_usd=NOTIONAL_USD, leverage=LEVERAGE, cfg=cfg,
    )
    n_trades = int(stats_d["n_trades"])
    if n_trades < MIN_N:
        return {
            "label": cell.label, "hypothesis": cell.hypothesis, "asset": cell.asset,
            "hold_h": cell.hold_h, "z_thresh": cell.z_thresh,
            "regime_filter": cell.regime_filter or "",
            "n_signals": n_sig, "status": "INSUFFICIENT",
            "n_trades": n_trades, "win_rate": stats_d.get("win_rate", float("nan")),
            "total_pnl_usd": stats_d.get("total_pnl_usd", 0.0),
            "avg_pnl_usd": stats_d.get("avg_pnl_usd", float("nan")),
            "sharpe": stats_d.get("sharpe", float("nan")),
            "g1_p": float("nan"), "g1_pass": False,
            "g2_pnl_pos": False,
            "g3_wf_stable": False, "g3_wf_mean_sharpe": float("nan"),
            "g4_perm_p": float("nan"), "g4_pass": False,
            "boot_lo": float("nan"), "boot_hi": float("nan"),
            "boot_pos": False,
            "avg_funding": stats_d.get("avg_funding_paid", 0.0),
            "avg_fees": stats_d.get("avg_fees_paid", 0.0),
        }
    pnls = trades_df["pnl_net_usd"].to_numpy()
    n_wins = int(stats_d["n_wins"])
    p_g1 = binomial_p(n_wins, n_trades)
    p_g4 = perm_test_sharpe(pnls, n_perm=N_PERM)
    boot_lo, boot_hi = bootstrap_sharpe_ci(pnls, n_boot=N_BOOT)
    wf = walk_forward(klines, funding, signals, cell.asset, cfg)
    g1_pass = (not np.isnan(p_g1)) and (p_g1 < 0.05)
    g2_pass = stats_d["total_pnl_usd"] > 0
    g4_pass = (not np.isnan(p_g4)) and (p_g4 < 0.05)
    return {
        "label": cell.label, "hypothesis": cell.hypothesis, "asset": cell.asset,
        "hold_h": cell.hold_h, "z_thresh": cell.z_thresh,
        "regime_filter": cell.regime_filter or "",
        "n_signals": n_sig, "status": "OK",
        "n_trades": n_trades, "win_rate": stats_d["win_rate"],
        "total_pnl_usd": stats_d["total_pnl_usd"],
        "avg_pnl_usd": stats_d["avg_pnl_usd"],
        "sharpe": stats_d["sharpe"],
        "g1_p": p_g1, "g1_pass": g1_pass,
        "g2_pnl_pos": g2_pass,
        "g3_wf_stable": wf["wf_stable"], "g3_wf_mean_sharpe": wf["wf_mean_sharpe"],
        "g4_perm_p": p_g4, "g4_pass": g4_pass,
        "boot_lo": boot_lo, "boot_hi": boot_hi,
        "boot_pos": (not np.isnan(boot_lo)) and (boot_lo > 0),
        "avg_funding": stats_d["avg_funding_paid"],
        "avg_fees": stats_d["avg_fees_paid"],
    }


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
def main():
    cfg = HyperliquidConfig()
    print(f"=== W2b funding+basis test ===")
    print(f"Engine: {cfg}")
    print()

    rows = []

    # =============== N2 — funding extremes ===============
    for asset in ASSETS_N2:
        try:
            kl = load_hl_klines_1h(asset)
            fnd = load_hl_funding(asset)
            fund_f = build_funding_features(fnd)
            reg = load_regime_labels(asset)
            print(f"\n[N2 {asset}] klines={len(kl)}  funding={len(fnd)}  regime_rows={len(reg)}")
            print(f"  rate quantiles:")
            print(f"    q99={fund_f['funding_rate'].quantile(0.99):.6e}")
            print(f"    q01={fund_f['funding_rate'].quantile(0.01):.6e}")
            print(f"  |z|>2 count: high={int((fund_f['fund_z']>2).sum())}  low={int((fund_f['fund_z']<-2).sum())}")
            print(f"  crossing counts: to_neg={int(fund_f['fund_cross_to_neg'].sum())}  to_pos={int(fund_f['fund_cross_to_pos'].sum())}")
        except Exception as e:
            print(f"  N2 {asset} load failed: {e}")
            continue

        # Sub-theories vs holds, no regime. Run z=1.5 and z=2.0.
        sub_specs = ["A", "B", "C_pos", "C_neg", "cross_to_neg", "cross_to_pos"]
        for sub in sub_specs:
            for h in HOLD_HOURS_N2:
                for z_thr in [1.5, 2.0]:
                    # crossings don't use z thresh — skip duplicate
                    if sub in ("cross_to_neg", "cross_to_pos") and z_thr != 2.0:
                        continue
                    cell = Cell(
                        hypothesis=f"N2-{sub}", asset=asset, hold_h=h,
                        z_thresh=z_thr, regime_filter=None,
                    )
                    res = run_n2_cell(cell, kl, fnd, fund_f, reg, cfg)
                    rows.append(res)
                    print(f"  {cell.label}: n={res['n_trades']} WR={res.get('win_rate', float('nan')):.3f} "
                          f"pnl=${res['total_pnl_usd']:+.2f} sharpe={res.get('sharpe', float('nan')):.2f} "
                          f"g1={res.get('g1_pass', False)} g4={res.get('g4_pass', False)} "
                          f"status={res['status']}")

        # Best 1 sub-theory × regime filter for ranging vs trending_up
        # Use sub-theory A and B at h=24 (mean-revert horizon) with regime gate
        for sub in ["A", "B"]:
            for reg_lbl in ["ranging", "trending_up", "trending_dn"]:
                cell = Cell(
                    hypothesis=f"N2-{sub}", asset=asset, hold_h=24,
                    z_thresh=2.0, regime_filter=reg_lbl,
                )
                res = run_n2_cell(cell, kl, fnd, fund_f, reg, cfg)
                rows.append(res)
                print(f"  {cell.label}: n={res['n_trades']} pnl=${res['total_pnl_usd']:+.2f} status={res['status']}")

    # =============== N3 — basis carry ===============
    for asset in ASSETS_N3:
        try:
            kl = load_hl_klines_1h(asset)
            fnd = load_hl_funding(asset)
            fund_f = build_funding_features(fnd)
            bnc = load_binance_spot_1h(asset)
            print(f"\n[N3 {asset}] hl_klines={len(kl)} bnc_klines={len(bnc)} funding={len(fnd)}")
            # check raw basis dist
            tmp_sigs, panel = build_signals_n3(kl, bnc, fund_f, hold_hours=24, z_thresh=1.0)
            print(f"  panel rows with basis: {len(panel)}")
            if len(panel):
                print(f"  basis_bps quantiles: mean={panel['basis_bps'].mean():.2f} p5={panel['basis_bps'].quantile(0.05):.2f} p95={panel['basis_bps'].quantile(0.95):.2f}")
                print(f"  mispricing |z|>1 long_signals={int((panel['misp_z']>1).sum())} short_signals={int((panel['misp_z']<-1).sum())}")
        except Exception as e:
            print(f"  N3 {asset} load failed: {e}")
            import traceback; traceback.print_exc()
            continue

        for h in HOLD_HOURS_N3:
            for z in [1.0, 1.5, 2.0]:
                cell = Cell(
                    hypothesis="N3", asset=asset, hold_h=h, z_thresh=z, regime_filter=None,
                )
                res = run_n3_cell(cell, kl, bnc, fnd, fund_f, cfg)
                rows.append(res)
                print(f"  {cell.label}: n={res['n_trades']} pnl=${res['total_pnl_usd']:+.2f} "
                      f"sharpe={res.get('sharpe', float('nan')):.2f} "
                      f"g1={res.get('g1_pass', False)} g4={res.get('g4_pass', False)} status={res['status']}")

    # =============== Write CSV ===============
    df = pd.DataFrame(rows)
    out_csv = REPO / "strategy_lab/hl_research_2026_05_26/wave2/W2b_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")
    print(f"Total cells: {len(df)}")
    print(f"INSUFFICIENT cells: {(df['status']=='INSUFFICIENT').sum()}")
    print(f"G1+G2+G4 pass: {((df['g1_pass'])&(df['g2_pnl_pos'])&(df['g4_pass'])).sum()}")
    print(f"All gates pass (G1+G2+G3+G4+boot_pos): {((df['g1_pass'])&(df['g2_pnl_pos'])&(df['g3_wf_stable'])&(df['g4_pass'])&(df['boot_pos'])).sum()}")
    return df


if __name__ == "__main__":
    df = main()
