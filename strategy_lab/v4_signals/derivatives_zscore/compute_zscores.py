"""Compute the 10-metric Z-score panel for the Crypto Derivatives Z-Score indicator.

Implements the Pine Script spec from `Derivativo Zscore Indicador Pine Script.txt`.
All calcs use a 21-bar rolling window (default `Z_LEN=21`).

Inputs (all on the 5-minute Binance metrics grid):
  data/v4/derivatives_zscore/metrics/{symbol}.parquet     ← OI + LSR + taker ratios
  data/v4/derivatives_zscore/funding/{symbol}.parquet     ← 8h funding (forward-filled to 5min)
  data/v4/derivatives_zscore/spot/COINBASE-BTC-1h.parquet ← optional, for cb_premium
  data/v4/derivatives_zscore/spot/BINANCE-BTC-1h.parquet  ← optional, for cb_premium
  data/v4/derivatives_zscore/stables/market_caps.parquet  ← optional, for stable dominance

Output:
  data/v4/derivatives_zscore/panels/{symbol}_zscore.parquet  ← single wide DataFrame

Skipped (no public data source): brigaliqui, z_liqB, z_liqS — drop 15 of 100 score points.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "v4" / "derivatives_zscore"

Z_LEN = 21  # bars (matches the Pine indicator default)


# ────────────────────────────────────────────────────────────
#  Core math (mirrors Pine Script's f_z and ema_safe)
# ────────────────────────────────────────────────────────────

def zscore(s: pd.Series, window: int = Z_LEN) -> pd.Series:
    m = s.rolling(window, min_periods=window).mean()
    sd = s.rolling(window, min_periods=window).std(ddof=0)  # Pine uses population stdev
    out = (s - m) / sd.replace(0, np.nan)
    return out


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def roc(s: pd.Series, n: int) -> pd.Series:
    return s.pct_change(n) * 100


def pct_change_ema(s: pd.Series, span: int = 3, lookback: int = 14,
                   min_baseline: float = 1e-9) -> pd.Series:
    """delta = pct_change(EMA(s, 3), 14)  — used for stable dominance Δ metrics.

    Clamps denominator to NaN when |baseline| < min_baseline OR when result is non-finite,
    preventing the ±inf values that polluted cross_real_money / cross_leverage_heat.
    """
    smooth = ema(s, span)
    baseline = smooth.shift(lookback)
    # Replace tiny / zero / NaN baselines with NaN so the division yields NaN (not inf)
    safe_baseline = baseline.where(baseline.abs() > min_baseline, np.nan)
    out = (smooth - baseline) / safe_baseline * 100
    # Final safety net: turn any residual inf into NaN
    return out.replace([np.inf, -np.inf], np.nan)


# ────────────────────────────────────────────────────────────
#  Loaders
# ────────────────────────────────────────────────────────────

def load_metrics(symbol: str) -> pd.DataFrame:
    p = BASE / "metrics" / f"{symbol}.parquet"
    df = pd.read_parquet(p)
    df = df.set_index("create_time").sort_index()
    return df


def load_funding(symbol: str) -> pd.DataFrame:
    p = BASE / "funding" / f"{symbol}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df = df.set_index("calc_time").sort_index()
    # Vision uses `funding_interval_hours` and `last_funding_rate` columns
    # plus 'symbol'. Normalize to a single 'funding_rate' col.
    rate_col = next((c for c in ["last_funding_rate", "fundingRate", "funding_rate"] if c in df.columns), None)
    if rate_col is None:
        raise ValueError(f"no funding rate col in {df.columns}")
    df = df.rename(columns={rate_col: "funding_rate"})
    return df[["funding_rate"]].astype(float)


def load_spot_coinbase() -> pd.Series | None:
    p = BASE / "spot" / "COINBASE-BTC-1h.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p).set_index("time")["close"].astype(float).sort_index()


def load_spot_binance(symbol: str = "BTCUSDT") -> pd.Series | None:
    """Load Binance spot 1h close for a given perp symbol."""
    tag = symbol.replace("USDT", "")
    p = BASE / "spot" / f"BINANCE-{tag}-1h.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p).set_index("time")["close"].astype(float).sort_index()


def load_stable_caps() -> pd.DataFrame | None:
    p = BASE / "stables" / "market_caps.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    return df.pivot_table(index="time", columns="tag", values="market_cap")


# ────────────────────────────────────────────────────────────
#  Main panel build
# ────────────────────────────────────────────────────────────

def build_panel(symbol: str) -> pd.DataFrame:
    m = load_metrics(symbol)
    if m.empty:
        raise SystemExit(f"no metrics for {symbol}")

    fund = load_funding(symbol)

    # 5-minute base grid from metrics
    out = pd.DataFrame(index=m.index)
    out["sum_open_interest"] = m["sum_open_interest"].astype(float)
    out["count_long_short_ratio"] = m["count_long_short_ratio"].astype(float)
    out["count_toptrader_long_short_ratio"] = m["count_toptrader_long_short_ratio"].astype(float)
    out["sum_toptrader_long_short_ratio"] = m["sum_toptrader_long_short_ratio"].astype(float)
    out["sum_taker_long_short_vol_ratio"] = m["sum_taker_long_short_vol_ratio"].astype(float)

    # ── Derive long_acc% / short_acc% from LSR ──
    R = out["count_long_short_ratio"]
    out["long_acc"] = R / (1 + R)
    out["short_acc"] = 1 / (1 + R)

    # ── Funding: forward-fill from 8h cadence to 5min ──
    if not fund.empty:
        fund_5m = fund.reindex(out.index, method="ffill")
        out["funding_rate"] = fund_5m["funding_rate"]
    else:
        out["funding_rate"] = np.nan

    # ── 1. Primary z-scores (Pine: f_z(src, 21)) ──
    out["z_lsr"] = zscore(out["count_long_short_ratio"])
    out["z_longA"] = zscore(out["long_acc"])
    out["z_shtA"] = zscore(out["short_acc"])
    out["z_fund"] = zscore(out["funding_rate"])
    out["z_oi"] = zscore(out["sum_open_interest"])
    # bonus dims (TV indicator doesn't use these but they're free)
    out["z_top_lsr_count"] = zscore(out["count_toptrader_long_short_ratio"])
    out["z_top_lsr_sum"] = zscore(out["sum_toptrader_long_short_ratio"])
    out["z_taker_ratio"] = zscore(out["sum_taker_long_short_vol_ratio"])

    # ── 2. Composites ──
    out["brigalS"] = out["z_longA"] - out["z_shtA"]
    out["oilsr"] = out["z_oi"] - out["z_lsr"]

    # ── 3. OI silent (smart-money accumulation) ──
    # Need spot price aligned to 5min grid; fall back to OI value / OI to back into mark price
    spot_bn = load_spot_binance(symbol)
    if spot_bn is not None:
        spot = spot_bn.reindex(out.index, method="ffill")
    else:
        # use OI USD value / OI quantity → implied mark price proxy
        spot = (m["sum_open_interest_value"].astype(float) / m["sum_open_interest"].astype(float))
    out["spot_price"] = spot
    oi_roc3 = roc(out["sum_open_interest"], 3)
    px_roc3 = roc(out["spot_price"], 3)
    z_oi_fast = zscore(oi_roc3)
    z_px_fast = zscore(px_roc3)
    raw = np.where(z_oi_fast > 1.0, z_oi_fast - z_px_fast, 0.0)
    out["z_oi_silent"] = zscore(ema(pd.Series(raw, index=out.index), 3))

    # ── 4. Coinbase Premium (BTC-only — Coinbase doesn't have liquid ETH/SOL perp basis) ──
    if symbol == "BTCUSDT":
        spot_cb = load_spot_coinbase()
        spot_bn_btc = load_spot_binance("BTCUSDT")
        if spot_cb is not None and spot_bn_btc is not None:
            cb_h = spot_cb.reindex(out.index, method="ffill")
            bn_h = spot_bn_btc.reindex(out.index, method="ffill")
            prem_pct = (cb_h - bn_h) / bn_h * 100
            out["cb_premium_pct"] = prem_pct
            out["z_cb_premium"] = zscore(ema(prem_pct, 3))
        else:
            out["cb_premium_pct"] = np.nan
            out["z_cb_premium"] = np.nan
    else:
        out["cb_premium_pct"] = np.nan
        out["z_cb_premium"] = np.nan

    # ── 5. Stablecoin dominance metrics (CoinGecko daily; reindex to 5min ffill) ──
    caps = load_stable_caps()
    if caps is not None and not caps.empty:
        # total stable mcap = sum of available coins
        caps["TOTAL"] = caps.sum(axis=1, min_count=1)
        # dominance = each coin / TOTAL_CRYPTO_MCAP (we don't have BTC/ETH mcap in scope here);
        # the indicator's `delta_*` are pct-changes of mcap-weighted EMAs, so absolute mcap
        # works fine — we only need RELATIVE moves.
        s1 = caps.get("USDT")
        s2 = caps.get("USDC", pd.Series(dtype=float)).reindex(caps.index).fillna(0) + \
             caps.get("PYUSD", pd.Series(dtype=float)).reindex(caps.index).fillna(0) + \
             caps.get("RLUSD", pd.Series(dtype=float)).reindex(caps.index).fillna(0)
        s3 = caps.get("USDE", pd.Series(dtype=float)).reindex(caps.index).fillna(0) + \
             caps.get("FDUSD", pd.Series(dtype=float)).reindex(caps.index).fillna(0)
        s4 = caps.get("DAI",  pd.Series(dtype=float)).reindex(caps.index).fillna(0)
        sm_total = caps["TOTAL"]

        delta_s1 = pct_change_ema(s1)
        delta_s2 = pct_change_ema(s2)
        delta_s3 = pct_change_ema(s3)
        delta_s4 = pct_change_ema(s4)
        delta_tot = pct_change_ema(sm_total)

        # crosses
        cil = delta_s2 - delta_s1     # institutional lead
        crl = delta_s1 - delta_s2     # retail lead
        clh = delta_s3 - delta_s2     # leverage heat
        cro = delta_tot - (delta_s1 * 0.6 + delta_s2 * 0.4)  # risk-off
        crm = (delta_s1 + delta_s2) - (delta_s3 * 2)         # real money

        # Reindex everything to 5min grid
        idx = out.index
        out["delta_s1"] = delta_s1.reindex(idx, method="ffill")
        out["delta_s2"] = delta_s2.reindex(idx, method="ffill")
        out["delta_s3"] = delta_s3.reindex(idx, method="ffill")
        out["delta_s4"] = delta_s4.reindex(idx, method="ffill")
        out["delta_tot"] = delta_tot.reindex(idx, method="ffill")
        out["cross_institutional_lead"] = cil.reindex(idx, method="ffill")
        out["cross_retail_lead"] = crl.reindex(idx, method="ffill")
        out["cross_leverage_heat"] = clh.reindex(idx, method="ffill")
        out["cross_risk_off"] = cro.reindex(idx, method="ffill")
        out["cross_real_money"] = crm.reindex(idx, method="ffill")
        out["z_dom_stables"] = zscore(out["delta_tot"])
        # spread quality: USDC.D - USDT.D — proxy via mcap share
        share_usdt = (s1 / sm_total).reindex(idx, method="ffill")
        share_usdc = (caps.get("USDC") / sm_total).reindex(idx, method="ffill") if "USDC" in caps.columns else np.nan
        if isinstance(share_usdc, pd.Series):
            spread_qual = share_usdc - share_usdt
            out["z_spread_qual"] = zscore(ema(-spread_qual, 3))
        else:
            out["z_spread_qual"] = np.nan
    else:
        for c in ["delta_s1", "delta_s2", "delta_s3", "delta_s4", "delta_tot",
                  "cross_institutional_lead", "cross_retail_lead", "cross_leverage_heat",
                  "cross_risk_off", "cross_real_money", "z_dom_stables", "z_spread_qual"]:
            out[c] = np.nan

    return out


# ────────────────────────────────────────────────────────────
#  Score (per the Pine spec — minus the 15 pts for liquidations)
# ────────────────────────────────────────────────────────────

def add_scores(p: pd.DataFrame) -> pd.DataFrame:
    """Compute SCORE_BULL and SCORE_BEAR. Liquidations component dropped (15 pts).
    Max possible bull score = 85 instead of 100. Same for bear. We expose `_scaled`
    columns rescaled back to 0..100 for direct comparison with the Pine indicator's regime classifier.
    """
    p = p.copy()
    p["score_bull"] = (
        15 * (p["z_lsr"] < -1.5).astype(int)
        + 10 * (p["z_lsr"] < -0.5).astype(int)
        + 15 * (p["z_fund"] < -1.0).astype(int)
        # 15 pts brigaliqui > +1.0  — DROPPED (no liquidation data)
        + 5  * (p["z_oi"] > 0.5).astype(int)
        + 10 * (p["z_dom_stables"] < -1.0).astype(int)
        + 10 * (p["cross_institutional_lead"] > 0).astype(int)
        + 5  * (p["cross_risk_off"] < 0).astype(int)
        + 10 * (p["z_cb_premium"] > 1.0).astype(int)
        + 5  * (p["z_oi_silent"] > 1.5).astype(int)
    )
    p["score_bear"] = (
        15 * (p["z_lsr"] > 1.5).astype(int)
        + 10 * (p["z_lsr"] > 0.5).astype(int)
        + 15 * (p["z_fund"] > 1.0).astype(int)
        # 15 pts brigaliqui < -1.0 — DROPPED
        + 5  * (p["z_oi"] < -0.5).astype(int)
        + 10 * (p["z_dom_stables"] > 1.0).astype(int)
        + 10 * (p["cross_leverage_heat"] > 1.5).astype(int)
        + 5  * (p["cross_risk_off"] > 0).astype(int)
        + 10 * (p["z_cb_premium"] < -1.0).astype(int)
    )
    # rescale 0..85 → 0..100 to keep the Pine regime thresholds (75 / 50 / 30) interpretable
    p["score_bull_scaled"] = (p["score_bull"] * (100 / 85)).clip(upper=100)
    p["score_bear_scaled"] = (p["score_bear"] * (100 / 85)).clip(upper=100)
    return p


def classify_regime(p: pd.DataFrame) -> pd.Series:
    sb, sB = p["score_bull_scaled"], p["score_bear_scaled"]
    out = pd.Series("LATERAL", index=p.index)
    out[(sb > 70) & (sB > 70)] = "REVERSAL_IMMINENT"
    out[(sb >= 75) & (sB < 30)] = "STRONG_UP"
    out[(sB >= 75) & (sb < 30)] = "STRONG_DOWN"
    out[(sb >= 50) & (sb < 75) & (sB < 40)] = "WEAK_UP"
    out[(sB >= 50) & (sB < 75) & (sb < 40)] = "WEAK_DOWN"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    out_dir = BASE / "panels"
    out_dir.mkdir(parents=True, exist_ok=True)

    for sym in args.symbols:
        print(f"\n[{sym}] building panel ...")
        p = build_panel(sym)
        p = add_scores(p)
        p["regime"] = classify_regime(p)
        out = out_dir / f"{sym}_zscore.parquet"
        p.to_parquet(out)
        print(f"  rows={len(p):,}  range={p.index.min()} → {p.index.max()}")
        print(f"  cols={list(p.columns)}")
        print(f"  regime counts: {p['regime'].value_counts().to_dict()}")
        print(f"  -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
