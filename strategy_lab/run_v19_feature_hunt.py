"""
V19 — feature-driven signal hunt for BTC & SOL.

Motivation: V18 classic breakouts capped at ~37% CAGR on BTC/SOL, far below
the 55% target that ETH hit. The features parquets already contain funding
rate, open interest, premium, liquidation, and long/short ratio data —
none of which V14-V18 used. V19 mines that.

Signal families tested:
  S1. OI-confirmed breakout L/S  (Donchian + OI rising confirmation)
  S2. Funding-extreme fade L/S   (funding_z extreme → fade)
  S3. Liq-cascade contrarian L/S (big longs liquidated → long / vice versa)
  S4. Premium-z mean-revert L/S  (perp-spot premium extreme → fade)
  S5. Taker-ratio momentum L/S   (aggressive buying/selling ignition)
  S6. Trend+Funding combo L/S    (breakout only if funding is not crowded)
  S7. OI-divergence reversal L/S (price up + OI down = distribution → short)

Output: CSV + print top configs for BTC and SOL under taker fees
with DD >= -40% and CAGR >= 55%.
"""
from __future__ import annotations
import sys, itertools, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, atr, donchian_up, donchian_dn,
)

FEAT = Path(__file__).resolve().parent / "features"
OUT = Path(__file__).resolve().parent / "results" / "v19"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045           # taker
RISK = 0.03
LEV  = 3.0


# ============================================================
# Helpers
# ============================================================
def rolling_z(s, n):
    m = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return (s - m) / sd


def dedupe(sig):
    return sig & ~sig.shift(1).fillna(False)


def _load(sym, start="2021-12-01", end="2026-04-01"):
    """Load feature parquet filtered to window where OI/funding data exists."""
    df = pd.read_parquet(FEAT / f"{sym}_1h_features.parquet")
    df = df.dropna(subset=["open", "high", "low", "close", "volume",
                           "funding_rate", "sum_open_interest"]).copy()
    df = df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index < pd.Timestamp(end, tz="UTC"))]
    return df


# ============================================================
# S1. OI-confirmed Donchian breakout
# ============================================================
def sig_oi_breakout_long(df, don_n=24, oi_lookback=4, oi_min_chg=0.005, regime_len=600):
    up = donchian_up(df["high"], don_n).values
    oi = df["sum_open_interest"].values
    oi_chg = (oi - np.roll(oi, oi_lookback)) / np.roll(oi, oi_lookback)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > up) & (oi_chg > oi_min_chg) & regime
    return pd.Series(sig, index=df.index).fillna(False)


def sig_oi_breakout_short(df, don_n=24, oi_lookback=4, oi_min_chg=0.005, regime_len=600):
    dn = donchian_dn(df["low"], don_n).values
    oi = df["sum_open_interest"].values
    oi_chg = (oi - np.roll(oi, oi_lookback)) / np.roll(oi, oi_lookback)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values < dn) & (oi_chg > oi_min_chg) & regime_bear
    return pd.Series(sig, index=df.index).fillna(False)


# ============================================================
# S2. Funding-extreme fade
# ============================================================
def sig_funding_fade_long(df, z_len=72, z_thresh=-2.0, regime_len=200):
    """Funding very negative (shorts paying longs heavily) + bounce from recent low → long."""
    f_z = rolling_z(df["funding_rate"], z_len)
    recent_low = df["low"].rolling(24).min()
    near_low = df["close"] < recent_low * 1.005  # within 0.5% of 24h low
    # Confirm with bullish candle: close > open
    bullish = df["close"] > df["open"]
    sig = (f_z < z_thresh) & near_low & bullish
    return sig.fillna(False)


def sig_funding_fade_short(df, z_len=72, z_thresh=2.0, regime_len=200):
    """Funding very positive (longs paying) + rejection from recent high → short."""
    f_z = rolling_z(df["funding_rate"], z_len)
    recent_hi = df["high"].rolling(24).max()
    near_hi = df["close"] > recent_hi * 0.995
    bearish = df["close"] < df["open"]
    sig = (f_z > z_thresh) & near_hi & bearish
    return sig.fillna(False)


# ============================================================
# S3. Liquidation cascade contrarian
# ============================================================
def sig_liq_cascade_long(df, liq_z_thresh=2.0, z_len=168):
    """Massive long liquidations (z-score of liq_notional high) → often local bottom, long."""
    if "liq_notional_usd" not in df.columns:
        return pd.Series(False, index=df.index)
    # Only count long-side liquidations. liq_notional in feature is aggregate —
    # use liq_z combined with red candle as proxy for longs getting washed.
    liq_z = rolling_z(df["liq_notional_usd"], z_len)
    red = df["close"] < df["open"]
    big_down = df["close"] / df["close"].shift(4) - 1 < -0.03   # >3% drop in 4h
    sig = (liq_z > liq_z_thresh) & red & big_down
    return sig.fillna(False)


def sig_liq_cascade_short(df, liq_z_thresh=2.0, z_len=168):
    """Massive short liquidations / green candle spike → local top, short."""
    if "liq_notional_usd" not in df.columns:
        return pd.Series(False, index=df.index)
    liq_z = rolling_z(df["liq_notional_usd"], z_len)
    green = df["close"] > df["open"]
    big_up = df["close"] / df["close"].shift(4) - 1 > 0.03
    sig = (liq_z > liq_z_thresh) & green & big_up
    return sig.fillna(False)


# ============================================================
# S4. Premium-z mean reversion
# ============================================================
def sig_premium_revert_long(df, z_thresh=-2.0):
    """Perp trading at deep discount to spot → mean-revert long."""
    if "premium_z_30d" not in df.columns:
        return pd.Series(False, index=df.index)
    pz = df["premium_z_30d"]
    sig = (pz < z_thresh) & (df["close"] > df["open"])  # bullish candle
    return sig.fillna(False)


def sig_premium_revert_short(df, z_thresh=2.0):
    """Perp trading at premium → fade."""
    if "premium_z_30d" not in df.columns:
        return pd.Series(False, index=df.index)
    pz = df["premium_z_30d"]
    sig = (pz > z_thresh) & (df["close"] < df["open"])
    return sig.fillna(False)


# ============================================================
# S5. Taker-ratio momentum (aggressive buying / selling ignition)
# ============================================================
def sig_taker_momo_long(df, z_thresh=1.5, regime_len=200):
    """Aggressive taker buying ignites → momentum long."""
    if "taker_ratio_z_7d" not in df.columns:
        return pd.Series(False, index=df.index)
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    sig = (df["taker_ratio_z_7d"] > z_thresh) & regime & (df["close"] > df["open"])
    return sig.fillna(False)


def sig_taker_momo_short(df, z_thresh=-1.5, regime_len=200):
    regime_bear = df["close"] < df["close"].rolling(regime_len).mean()
    sig = (df["taker_ratio_z_7d"] < z_thresh) & regime_bear & (df["close"] < df["open"])
    return sig.fillna(False)


# ============================================================
# S6. Trend + Funding alignment (breakout only if funding NOT crowded)
# ============================================================
def sig_trend_funding_long(df, don_n=48, f_z_max=1.0, regime_len=600):
    """Breakout long ONLY if funding_z is not already extremely long-crowded."""
    up = donchian_up(df["high"], don_n).values
    f_z = rolling_z(df["funding_rate"], 168).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > up) & (f_z < f_z_max) & regime
    return pd.Series(sig, index=df.index).fillna(False)


def sig_trend_funding_short(df, don_n=48, f_z_min=-1.0, regime_len=600):
    dn = donchian_dn(df["low"], don_n).values
    f_z = rolling_z(df["funding_rate"], 168).values
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values < dn) & (f_z > f_z_min) & regime_bear
    return pd.Series(sig, index=df.index).fillna(False)


# ============================================================
# S7. OI-divergence reversal
# ============================================================
def sig_oi_div_short(df, price_up_thresh=0.03, oi_lookback=12, oi_chg_thresh=-0.01, regime_len=600):
    """Price rallied >3% over last 12h BUT OI is shrinking → rally losing sponsorship → short."""
    pc = df["close"] / df["close"].shift(oi_lookback) - 1
    oi = df["sum_open_interest"]
    oi_chg = oi / oi.shift(oi_lookback) - 1
    regime_bear = df["close"] < df["close"].rolling(regime_len).mean()
    # Fire when we see the first bar after divergence forms and price turns red
    sig = (pc > price_up_thresh) & (oi_chg < oi_chg_thresh) & (df["close"] < df["open"]) & regime_bear
    return sig.fillna(False)


def sig_oi_div_long(df, price_dn_thresh=-0.03, oi_lookback=12, oi_chg_thresh=-0.01, regime_len=600):
    pc = df["close"] / df["close"].shift(oi_lookback) - 1
    oi = df["sum_open_interest"]
    oi_chg = oi / oi.shift(oi_lookback) - 1
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    sig = (pc < price_dn_thresh) & (oi_chg < oi_chg_thresh) & (df["close"] > df["open"]) & regime
    return sig.fillna(False)


# ============================================================
# Registry
# ============================================================
SIGNALS = {
    "OI_Breakout_LS":    (sig_oi_breakout_long, sig_oi_breakout_short,
                          dict(don_n=24, oi_lookback=4, oi_min_chg=0.005, regime_len=600)),
    "Funding_Fade_LS":   (sig_funding_fade_long, sig_funding_fade_short,
                          dict(z_len=72, z_thresh=None, regime_len=200)),  # thresh swept below
    "Liq_Cascade_LS":    (sig_liq_cascade_long, sig_liq_cascade_short,
                          dict(liq_z_thresh=2.0, z_len=168)),
    "Premium_Revert_LS": (sig_premium_revert_long, sig_premium_revert_short,
                          dict(z_thresh=None)),
    "Taker_Momo_LS":     (sig_taker_momo_long, sig_taker_momo_short,
                          dict(z_thresh=None, regime_len=200)),
    "Trend_Funding_LS":  (sig_trend_funding_long, sig_trend_funding_short,
                          dict(don_n=48, f_z_max=None, f_z_min=None, regime_len=600)),
    "OI_Divergence_LS":  (sig_oi_div_long, sig_oi_div_short,
                          dict(price_up_thresh=0.03, price_dn_thresh=-0.03,
                               oi_lookback=12, oi_chg_thresh=-0.01, regime_len=600)),
}


def run_one(df, label, long_fn, short_fn, params, tp, sl, trail, mh,
            risk=RISK, lev=LEV, fee=FEE):
    ls = dedupe(long_fn(df, **{k: v for k, v in params.items() if k in long_fn.__code__.co_varnames}))
    ss_params = {k: v for k, v in params.items() if k in (short_fn.__code__.co_varnames if short_fn else [])}
    ss = dedupe(short_fn(df, **ss_params)) if short_fn else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=fee)
    r = metrics(label, eq, trades)
    r.update({"tp": tp, "sl": sl, "trail": trail, "mh": mh,
              "risk": risk, "lev": lev})
    return r


# ============================================================
# Pass 1: each signal with a small exit grid + key param sweep
# ============================================================
EXIT_GRID = [
    {"tp": tp, "sl": sl, "trail": tr, "mh": mh}
    for tp in [5.0, 7.0]
    for sl in [1.5, 2.0]
    for tr in [3.5, 4.5]
    for mh in [48, 72]
]


def hunt_signal(df, sym, sig_name):
    """Hunt best config for a single signal family by sweeping its unique params."""
    lfn, sfn, defaults = SIGNALS[sig_name]
    rows = []

    # Build per-signal param grid
    if sig_name == "OI_Breakout_LS":
        grid = [dict(don_n=dn, oi_lookback=ol, oi_min_chg=mc, regime_len=rg)
                for dn in [12, 24, 48]
                for ol in [2, 4, 8]
                for mc in [0.0, 0.003, 0.005, 0.01]
                for rg in [300, 600]]
    elif sig_name == "Funding_Fade_LS":
        grid = [dict(z_len=zl, z_thresh=zt, regime_len=rg)
                for zl in [72, 168, 336]
                for zt in [-3.0, -2.0, -1.5]        # (used for long; short flips sign)
                for rg in [200, 600]]
    elif sig_name == "Liq_Cascade_LS":
        grid = [dict(liq_z_thresh=lt, z_len=zl)
                for lt in [1.5, 2.0, 2.5, 3.0]
                for zl in [72, 168, 336]]
    elif sig_name == "Premium_Revert_LS":
        grid = [dict(z_thresh=zt) for zt in [-3.0, -2.0, -1.5]]
    elif sig_name == "Taker_Momo_LS":
        grid = [dict(z_thresh=zt, regime_len=rg)
                for zt in [1.0, 1.5, 2.0]
                for rg in [100, 200, 400]]
    elif sig_name == "Trend_Funding_LS":
        grid = [dict(don_n=dn, f_z_max=fz, f_z_min=-fz, regime_len=rg)
                for dn in [24, 48, 96]
                for fz in [0.5, 1.0, 1.5, 2.0]
                for rg in [300, 600]]
    elif sig_name == "OI_Divergence_LS":
        grid = [dict(price_up_thresh=pt, price_dn_thresh=-pt,
                     oi_lookback=ol, oi_chg_thresh=-0.01, regime_len=rg)
                for pt in [0.02, 0.03, 0.04]
                for ol in [6, 12, 24]
                for rg in [300, 600]]
    else:
        grid = [defaults]

    for params in grid:
        # For "Funding_Fade_LS" the threshold must flip sign between long and short
        if sig_name == "Funding_Fade_LS":
            plong = dict(z_len=params["z_len"], z_thresh=params["z_thresh"], regime_len=params["regime_len"])
            pshort = dict(z_len=params["z_len"], z_thresh=-params["z_thresh"], regime_len=params["regime_len"])
            for exits in EXIT_GRID:
                try:
                    ls = dedupe(lfn(df, **plong))
                    ss = dedupe(sfn(df, **pshort))
                    trades, eq = simulate(df, ls, short_entries=ss,
                                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                                          trail_atr=exits["trail"], max_hold=exits["mh"],
                                          risk_per_trade=RISK, leverage_cap=LEV, fee=FEE)
                    r = metrics(f"{sig_name}_{params}_{exits}", eq, trades)
                    r.update(params); r.update(exits); r["signal"] = sig_name; r["asset"] = sym
                    r["params_str"] = ",".join(f"{k}={v}" for k, v in params.items())
                    rows.append(r)
                except Exception as e:
                    pass
            continue

        # For Premium_Revert_LS, flip z_thresh sign for short
        if sig_name == "Premium_Revert_LS":
            plong = dict(z_thresh=params["z_thresh"])
            pshort = dict(z_thresh=-params["z_thresh"])
            for exits in EXIT_GRID:
                try:
                    ls = dedupe(lfn(df, **plong))
                    ss = dedupe(sfn(df, **pshort))
                    trades, eq = simulate(df, ls, short_entries=ss,
                                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                                          trail_atr=exits["trail"], max_hold=exits["mh"],
                                          risk_per_trade=RISK, leverage_cap=LEV, fee=FEE)
                    r = metrics(f"{sig_name}_{params}_{exits}", eq, trades)
                    r.update(params); r.update(exits); r["signal"] = sig_name; r["asset"] = sym
                    r["params_str"] = ",".join(f"{k}={v}" for k, v in params.items())
                    rows.append(r)
                except Exception as e:
                    pass
            continue

        # For Taker_Momo_LS, flip sign for short
        if sig_name == "Taker_Momo_LS":
            plong = dict(z_thresh=params["z_thresh"], regime_len=params["regime_len"])
            pshort = dict(z_thresh=-params["z_thresh"], regime_len=params["regime_len"])
            for exits in EXIT_GRID:
                try:
                    ls = dedupe(lfn(df, **plong))
                    ss = dedupe(sfn(df, **pshort))
                    trades, eq = simulate(df, ls, short_entries=ss,
                                          tp_atr=exits["tp"], sl_atr=exits["sl"],
                                          trail_atr=exits["trail"], max_hold=exits["mh"],
                                          risk_per_trade=RISK, leverage_cap=LEV, fee=FEE)
                    r = metrics(f"{sig_name}_{params}_{exits}", eq, trades)
                    r.update(params); r.update(exits); r["signal"] = sig_name; r["asset"] = sym
                    r["params_str"] = ",".join(f"{k}={v}" for k, v in params.items())
                    rows.append(r)
                except Exception as e:
                    pass
            continue

        # Standard case
        for exits in EXIT_GRID:
            try:
                r = run_one(df, f"{sig_name}_{params}_{exits}",
                            lfn, sfn, params,
                            exits["tp"], exits["sl"], exits["trail"], exits["mh"])
                r.update(params); r["signal"] = sig_name; r["asset"] = sym
                r["params_str"] = ",".join(f"{k}={v}" for k, v in params.items())
                rows.append(r)
            except Exception as e:
                pass
    return rows


def main():
    all_rows = []
    for sym, start in [("BTCUSDT", "2021-01-01"), ("SOLUSDT", "2021-12-01")]:
        print(f"\n=== Hunting {sym} (feature-driven) ===", flush=True)
        df = _load(sym, start)
        print(f"  bars: {len(df):,}", flush=True)
        for sig_name in SIGNALS.keys():
            t0 = time.time()
            rows = hunt_signal(df, sym, sig_name)
            all_rows.extend(rows)
            ok = [r for r in rows if r.get("n", 0) >= 20]
            if ok:
                best = max(ok, key=lambda r: r.get("cagr_net", -9))
                print(f"  {sig_name}: {len(rows)} configs in {time.time()-t0:.1f}s  "
                      f"best CAGR {best.get('cagr_net',0)*100:.1f}% Sharpe {best.get('sharpe',0):.2f} "
                      f"DD {best.get('dd',0)*100:.1f}%  trades={best.get('n')}", flush=True)
            else:
                print(f"  {sig_name}: {len(rows)} configs, no valid runs", flush=True)

    out = pd.DataFrame(all_rows)
    out.to_csv(OUT / "v19_results.csv", index=False)

    cols = ["asset", "signal", "params_str", "tp", "sl", "trail", "mh",
            "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "avg_lev"]

    print("\n" + "=" * 70)
    print("BTC: top configs clearing 55% CAGR, DD >= -40%")
    print("=" * 70)
    btc = out[(out["asset"] == "BTCUSDT") & (out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
    if len(btc):
        print(btc.sort_values("cagr_net", ascending=False).head(15)[cols].to_string(index=False))
    else:
        print("  NONE hit 55% — showing top 10 by cagr_net under DD cap")
        btc = out[(out["asset"] == "BTCUSDT") & (out["dd"] >= -0.40) & (out["n"] >= 30)]
        if len(btc):
            print(btc.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))

    print("\n" + "=" * 70)
    print("SOL: top configs clearing 55% CAGR, DD >= -40%")
    print("=" * 70)
    sol = out[(out["asset"] == "SOLUSDT") & (out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
    if len(sol):
        print(sol.sort_values("cagr_net", ascending=False).head(15)[cols].to_string(index=False))
    else:
        print("  NONE hit 55% — showing top 10 by cagr_net under DD cap")
        sol = out[(out["asset"] == "SOLUSDT") & (out["dd"] >= -0.40) & (out["n"] >= 30)]
        if len(sol):
            print(sol.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
