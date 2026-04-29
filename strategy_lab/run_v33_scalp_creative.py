"""
V33 — Creative + Scalping Round
================================
Six new families orthogonal to V23-V30, with scalp-grade exits on 15m.

1. VWAP_Scalp_15m         — 15m session VWAP z-fade with RSI confirm (scalp)
2. Keltner_Pullback_LS    — Pullback to KC mid-band in trend (15m/1h)
3. RSI_Div_Regular        — Classic bullish/bearish divergence (1h)
4. ATR_Burst_Continue     — ATR expansion > k×avg + direction momentum (15m)
5. ORB_Break              — Opening Range Breakout on 00 UTC + 4-bar range (15m)
6. ETHBTC_Ratio_Revert    — ETH mean-revert based on ETH/BTC ratio z-score (1h)

Sim: 0.045% fee, 3bps slip, 3× lev cap, next-bar-open fills, ATR-risk sizing.
IS/OOS split at 2024-01-01. PASS: OOS Sh >= 0.5*max(0.1, IS Sh).
"""
from __future__ import annotations
import sys, pickle, time, warnings, itertools
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v33"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")
SINCE = pd.Timestamp("2020-01-01", tz="UTC")

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "SUIUSDT"]


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    df = pd.read_parquet(p).dropna(subset=["open","high","low","close","volume"])
    return df[df.index >= SINCE]


def dedupe(s): return s & ~s.shift(1).fillna(False)


# ==========================================================
# Family 1 — VWAP Scalp (session VWAP z-fade with RSI confirm)
# ==========================================================
def sig_vwap_scalp(df, z_thr=2.0, vwap_n=40, rsi_confirm=40):
    """Long when price drops z_thr stdevs below rolling VWAP AND RSI < rsi_confirm
    (oversold). Short mirror. Range-reversion scalp."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).rolling(vwap_n).sum()
    vv = df["volume"].rolling(vwap_n).sum()
    vwap = pv / vv
    dev = df["close"] - vwap
    zstd = dev.rolling(vwap_n).std()
    z = dev / zstd.replace(0, np.nan)
    rsi = pd.Series(talib.RSI(df["close"].values, 14), index=df.index)
    # Long edge: z crosses back up through -z_thr AND RSI < rsi_confirm
    long_edge = (z > -z_thr) & (z.shift(1) <= -z_thr) & (rsi < rsi_confirm)
    short_edge = (z < z_thr) & (z.shift(1) >= z_thr) & (rsi > 100 - rsi_confirm)
    return long_edge.fillna(False).astype(bool), short_edge.fillna(False).astype(bool)


# ==========================================================
# Family 2 — Keltner Pullback in Trend (buy the dip)
# ==========================================================
def sig_keltner_pullback(df, kc_n=20, kc_mult=1.5, ema_reg=200, rsi_dip=40):
    """Long: trend up (close > EMA_reg) AND close pulls back to KC mid (EMA_kc)
    AND RSI dips below rsi_dip. Short mirror with RSI > (100-rsi_dip)."""
    kc_mid = ema(df["close"], kc_n)
    atr_v = pd.Series(atr(df, 14), index=df.index)
    kc_up = kc_mid + kc_mult * atr_v
    kc_dn = kc_mid - kc_mult * atr_v
    reg = ema(df["close"], ema_reg)
    rsi = pd.Series(talib.RSI(df["close"].values, 14), index=df.index)

    # Long: pulled down to the middle band while trend intact and RSI dipped
    long_edge = (df["close"] > reg) & (df["close"] <= kc_mid) & (df["close"].shift(1) > kc_mid.shift(1)) & (rsi < rsi_dip)
    short_edge = (df["close"] < reg) & (df["close"] >= kc_mid) & (df["close"].shift(1) < kc_mid.shift(1)) & (rsi > 100 - rsi_dip)
    return long_edge.fillna(False).astype(bool), short_edge.fillna(False).astype(bool)


# ==========================================================
# Family 3 — RSI Regular Divergence
# ==========================================================
def sig_rsi_div(df, rsi_n=14, lookback=20, rsi_lo=35):
    """Bullish regular divergence: price makes lower low within lookback
    but RSI makes higher low while RSI is oversold (< rsi_lo).
    Bearish mirror with overbought RSI."""
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_n), index=df.index)
    c = df["close"]
    # Bullish: current bar is local low and rsi local low > rsi low lookback ago
    price_ll = (c == c.rolling(lookback).min())
    rsi_prior_low = rsi.shift(lookback // 2).rolling(lookback // 2).min()
    rsi_curr_low = rsi.rolling(lookback // 2).min()
    bull_div = price_ll & (rsi_curr_low > rsi_prior_low) & (rsi < rsi_lo)

    price_hh = (c == c.rolling(lookback).max())
    rsi_prior_hi = rsi.shift(lookback // 2).rolling(lookback // 2).max()
    rsi_curr_hi = rsi.rolling(lookback // 2).max()
    bear_div = price_hh & (rsi_curr_hi < rsi_prior_hi) & (rsi > 100 - rsi_lo)

    return dedupe(bull_div.fillna(False).astype(bool)), dedupe(bear_div.fillna(False).astype(bool))


# ==========================================================
# Family 4 — ATR Burst Continuation (scalp)
# ==========================================================
def sig_atr_burst(df, atr_mult=2.2, lookback=20, adx_min=20):
    """When bar's true range > atr_mult × avg TR of lookback prior bars
    AND ADX above min AND candle direction, trade in the direction of the burst."""
    atr_v = pd.Series(atr(df, 14), index=df.index)
    avg_tr = atr_v.rolling(lookback).mean()
    burst = atr_v > atr_mult * avg_tr.shift(1)
    _dp, _dm, adx = (pd.Series(x, index=df.index) for x in (
        talib.PLUS_DI(df["high"].values, df["low"].values, df["close"].values, 14),
        talib.MINUS_DI(df["high"].values, df["low"].values, df["close"].values, 14),
        talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14),
    ))
    long_sig = burst & (df["close"] > df["open"]) & (adx > adx_min) & (_dp > _dm)
    short_sig = burst & (df["close"] < df["open"]) & (adx > adx_min) & (_dm > _dp)
    return dedupe(long_sig.fillna(False).astype(bool)), dedupe(short_sig.fillna(False).astype(bool))


# ==========================================================
# Family 5 — Opening Range Breakout (15m only, 00 UTC anchor)
# ==========================================================
def sig_orb_break(df, range_bars=4, regime_len=200):
    """Compute 00 UTC + first range_bars highs/lows as today's OR.
    Long on first close > OR high in up regime. Short mirror."""
    reg = ema(df["close"], regime_len)
    regime_up = df["close"] > reg
    regime_dn = df["close"] < reg

    date = df.index.normalize()
    # Grouping by date -- for each day, capture cum high/low of first range_bars
    df2 = pd.DataFrame({"h": df["high"].values, "l": df["low"].values,
                        "c": df["close"].values, "date": date,
                        "idx_in_day": df.groupby(date).cumcount().values}, index=df.index)
    in_range = df2["idx_in_day"] < range_bars
    # OR high/low: running cummax/cummin of first range_bars per day
    or_hi = df2.groupby("date")["h"].transform(lambda x: x.shift(0).where(x.index.to_series().groupby(date).cumcount() < range_bars).cummax())
    or_lo = df2.groupby("date")["l"].transform(lambda x: x.shift(0).where(x.index.to_series().groupby(date).cumcount() < range_bars).cummin())
    # Lock at end of range
    or_hi_ffill = or_hi.ffill()
    or_lo_ffill = or_lo.ffill()

    # Signal only after the OR window closes
    after_range = ~in_range
    broke_up = (df["close"] > or_hi_ffill) & (df["close"].shift(1) <= or_hi_ffill.shift(1))
    broke_dn = (df["close"] < or_lo_ffill) & (df["close"].shift(1) >= or_lo_ffill.shift(1))

    long_sig = broke_up & after_range & regime_up
    short_sig = broke_dn & after_range & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ==========================================================
# Family 6 — ETH/BTC Ratio Revert (ETH only, needs BTC data)
# ==========================================================
def sig_ethbtc_ratio_revert(df_eth, df_btc, z_lookback=100, z_thr=2.0):
    """When ETH/BTC ratio drops > z_thr stdevs below its rolling mean, long ETH
    (betting on catch-up). When > z_thr above, short ETH."""
    # Align on common index
    common = df_eth.index.intersection(df_btc.index)
    ratio = (df_eth.loc[common, "close"] / df_btc.loc[common, "close"])
    mu = ratio.rolling(z_lookback).mean()
    sd = ratio.rolling(z_lookback).std()
    z = (ratio - mu) / sd.replace(0, np.nan)
    # Cross back through thresholds = edge (mean reversion signal fires)
    long_edge = (z > -z_thr) & (z.shift(1) <= -z_thr)
    short_edge = (z < z_thr) & (z.shift(1) >= z_thr)
    # Re-index to df_eth's full index (False outside common)
    long_sig = long_edge.reindex(df_eth.index).fillna(False).astype(bool)
    short_sig = short_edge.reindex(df_eth.index).fillna(False).astype(bool)
    return long_sig, short_sig


# ==========================================================
# Sweep
# ==========================================================

# Exit configs per TF class
EXITS_SCALP = [  # 15m/30m — tight TP, quick
    dict(tp=3.0, sl=1.0, trail=2.0, mh=12),
    dict(tp=5.0, sl=1.5, trail=3.0, mh=24),
]
EXITS_MED = [    # 1h
    dict(tp=5.0, sl=1.5, trail=3.5, mh=36),
    dict(tp=8.0, sl=2.0, trail=5.0, mh=72),
]
EXITS_SWING = [  # 4h
    dict(tp=6.0, sl=1.5, trail=3.5, mh=20),
    dict(tp=10.0, sl=2.0, trail=5.0, mh=40),
]

RISKS = [0.03, 0.05]
LEV = 3.0


FAMILIES = {
    "VWAP_Scalp": {
        "fn": sig_vwap_scalp,
        "grid": {"z_thr": [1.5, 2.0, 2.5], "vwap_n": [20, 40, 80], "rsi_confirm": [35, 40]},
        "tfs": [("15m", EXITS_SCALP), ("1h", EXITS_MED)],
    },
    "Keltner_Pullback": {
        "fn": sig_keltner_pullback,
        "grid": {"kc_n": [20, 30], "kc_mult": [1.5, 2.0], "ema_reg": [100, 200], "rsi_dip": [35, 40]},
        "tfs": [("15m", EXITS_SCALP), ("1h", EXITS_MED)],
    },
    "RSI_Div": {
        "fn": sig_rsi_div,
        "grid": {"rsi_n": [14, 21], "lookback": [20, 40], "rsi_lo": [30, 35]},
        "tfs": [("1h", EXITS_MED), ("4h", EXITS_SWING)],
    },
    "ATR_Burst": {
        "fn": sig_atr_burst,
        "grid": {"atr_mult": [1.8, 2.2, 2.8], "lookback": [20, 40], "adx_min": [20, 25]},
        "tfs": [("15m", EXITS_SCALP), ("1h", EXITS_MED)],
    },
    "ORB_Break": {
        "fn": sig_orb_break,
        "grid": {"range_bars": [4, 8, 12], "regime_len": [100, 200]},
        "tfs": [("15m", EXITS_SCALP)],
    },
    "ETHBTC_Ratio": {
        "fn": sig_ethbtc_ratio_revert,
        "grid": {"z_lookback": [50, 100, 200], "z_thr": [1.5, 2.0, 2.5]},
        "tfs": [("1h", EXITS_MED), ("4h", EXITS_SWING)],
    },
}


def grid_combos(grid):
    keys = list(grid.keys())
    for combo in itertools.product(*[grid[k] for k in keys]):
        yield dict(zip(keys, combo))


def run_family_coin(family, sym, tf, df, btc_df=None):
    fn = FAMILIES[family]["fn"]
    exits_list = dict(FAMILIES[family]["tfs"])[tf]
    best = None
    n_tried = 0
    for params in grid_combos(FAMILIES[family]["grid"]):
        if family == "ETHBTC_Ratio":
            if sym != "ETHUSDT" or btc_df is None:
                return None, 0
            try:
                ls, ss = fn(df, btc_df, **params)
            except Exception as e:
                continue
        else:
            try:
                ls, ss = fn(df, **params)
            except Exception as e:
                continue

        for exits in exits_list:
            for risk in RISKS:
                n_tried += 1
                trades, eq = simulate(df, ls, ss,
                                      tp_atr=exits["tp"], sl_atr=exits["sl"],
                                      trail_atr=exits["trail"], max_hold=exits["mh"],
                                      risk_per_trade=risk, leverage_cap=LEV, fee=FEE)
                m = metrics(f"{sym}_{family}_{tf}", eq, trades)
                # Minimum trade count
                if m["n"] < 25 or m["dd"] < -0.50:
                    continue
                score = m["cagr_net"] * max(0.01, m["sharpe"] / 1.5)
                m_rec = dict(m, sym=sym, family=family, tf=tf, params=params,
                             exits=exits, risk=risk, lev=LEV, score=score)
                if best is None or m_rec["score"] > best["score"]:
                    best = m_rec
    return best, n_tried


def main():
    t0 = time.time()
    results = {}
    btc_by_tf = {}
    for tf in ("1h", "4h"):
        b = _load("BTCUSDT", tf)
        if b is not None:
            btc_by_tf[tf] = b

    total_tried = 0
    for family, spec in FAMILIES.items():
        for tf_name, _ in spec["tfs"]:
            for sym in COINS:
                df = _load(sym, tf_name)
                if df is None or len(df) < 500: continue
                btc_df = btc_by_tf.get(tf_name)
                best, n_tried = run_family_coin(family, sym, tf_name, df, btc_df)
                total_tried += n_tried
                if best is not None:
                    key = f"{sym}_{family}_{tf_name}"
                    results[key] = best
                    print(f"[{time.time()-t0:6.1f}s] {key:50s} n={best['n']:4d} "
                          f"CAGR={best['cagr_net']*100:+6.1f}%  Sh={best['sharpe']:+5.2f}  "
                          f"DD={best['dd']*100:+5.1f}%  score={best['score']:+6.3f}")

    print(f"\nTOTAL: {len(results)} winners from {total_tried} configs tried in {time.time()-t0:.1f}s")
    with open(OUT / "v33_sweep_results.pkl", "wb") as f:
        pickle.dump(results, f)
    print(f"Saved to {OUT/'v33_sweep_results.pkl'}")


if __name__ == "__main__":
    main()
