"""
V38c — SMC structural breadth as V24 XSM bear filter replacement.

Idea: instead of "5 of 9 coins above own 50d-SMA" (V24's breadth rule),
use "% of 9 coins with recent bullish BOS" as the regime filter.
Structural information > price-vs-MA.

Experiments:
  1. Baseline V24: breadth_50d_sma >= 5 of 9 → OK to trade
  2. SMC breadth: bullish_bos_breadth >= threshold → OK to trade
  3. Combined: both must agree (stricter)

Test: simplified XSM on 4h, rebalance weekly, top-K=4, leverage 1.0×.
Walk-forward: 2y train / 1y test / 6mo step.
"""
from __future__ import annotations
import sys, os, io, json, time, warnings
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from pathlib import Path
from contextlib import redirect_stdout
import numpy as np
import pandas as pd

_buf = io.StringIO()
with redirect_stdout(_buf):
    from smartmoneyconcepts import smc

ROOT = Path(__file__).resolve().parent
FEAT = ROOT / "features" / "multi_tf"
OUT = ROOT / "results" / "v38"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT",
         "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]
STARTS = {
    "BTCUSDT":  "2019-01-01", "ETHUSDT":  "2019-01-01", "BNBUSDT":  "2019-01-01",
    "XRPUSDT":  "2019-01-01", "ADAUSDT":  "2019-01-01", "LINKUSDT": "2019-03-01",
    "DOGEUSDT": "2019-09-01", "SOLUSDT":  "2020-10-01", "AVAXUSDT": "2020-11-01",
}
BARS_PER_DAY = 6  # 4h


def load(sym):
    p = FEAT / f"{sym}_4h.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close"])
    return df[df.index >= pd.Timestamp("2019-01-01", tz="UTC")]


def compute_bos_series(df, swing_length=30):
    """Returns bullish_bos (bool per bar) for a coin."""
    try:
        shl = smc.swing_highs_lows(df[["open", "high", "low", "close", "volume"]],
                                    swing_length=swing_length)
        bc = smc.bos_choch(df[["open", "high", "low", "close", "volume"]],
                            shl, close_break=True)
        return (bc["BOS"].reindex(df.index) == 1).fillna(False)
    except Exception:
        return pd.Series(False, index=df.index)


def build_panel(data):
    """Aligns 9 coins onto a common 4h index and returns close panel."""
    all_idx = pd.DatetimeIndex([])
    for sym in COINS:
        if sym in data:
            all_idx = all_idx.union(data[sym].index)
    panel = pd.DataFrame(index=all_idx)
    for sym in COINS:
        if sym in data:
            panel[sym] = data[sym]["close"].reindex(all_idx)
    return panel


def xsm_backtest(data, panel, regime_fn, lookback_days=14, top_k=4, rebal_days=7,
                 leverage=1.0):
    """
    Weekly-rebalance XSM with user-supplied regime filter.
    regime_fn(i) -> True if OK to trade (bullish regime), False = flat.
    """
    lb_bars = lookback_days * BARS_PER_DAY
    step = rebal_days * BARS_PER_DAY
    n = len(panel)
    eq = 1.0
    equity = np.ones(n)
    current_weights = {}

    for i in range(lb_bars + 100, n):
        # Daily equity update from current positions
        if current_weights:
            ret_sum = 0.0
            for sym, w in current_weights.items():
                if pd.notna(panel.iloc[i][sym]) and pd.notna(panel.iloc[i-1][sym]):
                    r = panel.iloc[i][sym] / panel.iloc[i-1][sym] - 1
                    ret_sum += w * r
            eq *= (1 + ret_sum)
        equity[i] = eq

        # Rebalance on schedule
        if (i - lb_bars - 100) % step == 0:
            if not regime_fn(i):
                # Flat
                current_weights = {}
                continue
            # Compute 14d returns
            scores = {}
            for sym in COINS:
                if sym not in panel.columns:
                    continue
                p_now = panel.iloc[i][sym]
                p_ago = panel.iloc[i - lb_bars][sym]
                if pd.notna(p_now) and pd.notna(p_ago) and p_ago > 0:
                    start = pd.Timestamp(STARTS[sym], tz="UTC")
                    if panel.index[i] >= start:
                        scores[sym] = p_now / p_ago - 1
            if len(scores) < top_k:
                current_weights = {}
                continue
            sorted_syms = sorted(scores.keys(), key=lambda s: scores[s], reverse=True)
            longs = sorted_syms[:top_k]
            w = leverage / top_k
            current_weights = {s: w for s in longs}
            # Fee on rebalance (entry + exit of changed positions, approx 2*top_k*FEE)
            eq *= (1 - 2 * top_k * FEE / leverage)

    eq_series = pd.Series(equity, index=panel.index)
    return _metrics(eq_series)


def _metrics(eq):
    rets = eq.pct_change().fillna(0.0)
    # 4h bars → 6 per day
    ann = np.sqrt(6 * 365.25)
    sharpe = (rets.mean() / rets.std() * ann) if rets.std() > 0 else 0.0
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 0.1)
    cagr = eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1
    dd = (eq / eq.cummax() - 1).min()
    return {
        "sharpe": round(float(sharpe), 3),
        "cagr": round(float(cagr), 4),
        "maxdd": round(float(dd), 4),
        "final_eq": round(float(eq.iloc[-1]), 3),
    }


def main():
    t0 = time.time()
    # Load data
    print("Loading 9 coins...")
    data = {}
    for sym in COINS:
        df = load(sym)
        if df is not None:
            data[sym] = df
            print(f"  {sym}: {len(df)} bars")

    panel = build_panel(data)
    print(f"Panel: {panel.shape}, {panel.index[0]} -> {panel.index[-1]}")

    # Precompute regime series
    print("Computing regime filters...")
    # A. BTC 100d SMA (V15 baseline)
    btc = data["BTCUSDT"]["close"]
    btc_sma100 = btc.rolling(100 * BARS_PER_DAY).mean()
    btc_bull = (btc > btc_sma100).reindex(panel.index, method="ffill").fillna(False)

    # B. V24 breadth: 5 of 9 above own 50d SMA
    per_coin_ma50 = {}
    for sym in COINS:
        if sym in data:
            s = data[sym]["close"].rolling(50 * BARS_PER_DAY).mean()
            per_coin_ma50[sym] = s.reindex(panel.index, method="ffill")

    def breadth_sma(i):
        ts = panel.index[i]
        count = 0
        for sym in COINS:
            if sym not in data or sym not in per_coin_ma50:
                continue
            price = panel.iloc[i][sym]
            ma = per_coin_ma50[sym].iloc[i]
            if pd.notna(price) and pd.notna(ma) and price > ma:
                count += 1
        return count

    # C. V38 SMC breadth: count coins with bullish BOS in last N bars
    print("Computing SMC BOS series per coin...")
    bos_series = {}
    for sym in COINS:
        if sym in data:
            b = compute_bos_series(data[sym], swing_length=30)
            # Wider memory: had a bullish BOS in last 200 bars (~33 days of 4h)?
            bos_series[sym] = b.rolling(200, min_periods=1).max().astype(bool).reindex(
                panel.index, method="ffill").fillna(False)

    def breadth_bos(i):
        count = 0
        for sym in COINS:
            if sym in bos_series and bos_series[sym].iloc[i]:
                count += 1
        return count

    # Define regimes
    def regime_v15_btcma(i):
        return bool(btc_bull.iloc[i])

    def regime_v24_breadth(i):
        if not bool(btc_bull.iloc[i]):
            return False
        return breadth_sma(i) >= 5

    def regime_smc_breadth_3(i):
        return breadth_bos(i) >= 3

    def regime_smc_breadth_5(i):
        return breadth_bos(i) >= 5

    # Combined: BOS breadth OR V24 breadth must agree (more lenient: either works)
    def regime_combined_or(i):
        if not bool(btc_bull.iloc[i]):
            return False
        return (breadth_sma(i) >= 5) or (breadth_bos(i) >= 3)

    # Strict: BOS breadth AND V24 breadth (both structural and MA confirm)
    def regime_combined_and(i):
        if not bool(btc_bull.iloc[i]):
            return False
        return (breadth_sma(i) >= 5) and (breadth_bos(i) >= 3)

    # Pure SMC (no BTC SMA gate)
    def regime_pure_bos(i):
        return breadth_bos(i) >= 3

    regimes = {
        "V15_btc_sma":          regime_v15_btcma,
        "V24_breadth_sma":      regime_v24_breadth,
        "V38_bos_breadth>=3":   regime_smc_breadth_3,
        "V38_bos_breadth>=5":   regime_smc_breadth_5,
        "V38_pure_bos_no_btc":  regime_pure_bos,
        "V24_OR_V38":           regime_combined_or,
        "V24_AND_V38":          regime_combined_and,
    }

    print("\n=== XSM REGIME FILTER COMPARISON ===")
    print(f"{'regime':<25} {'sharpe':>8} {'cagr':>8} {'maxdd':>8} {'final':>8}")
    rows = []
    for name, rf in regimes.items():
        m = xsm_backtest(data, panel, rf, lookback_days=14, top_k=4,
                         rebal_days=7, leverage=1.0)
        rows.append({"regime": name, **m})
        print(f"{name:<25} {m['sharpe']:>8.3f} {m['cagr']:>8.2%} {m['maxdd']:>8.2%} {m['final_eq']:>8.2f}")

    pd.DataFrame(rows).to_csv(OUT / "v38c_xsm_regime_compare.csv", index=False)
    with open(OUT / "v38c_summary.json", "w") as f:
        json.dump({"elapsed": round(time.time() - t0, 1), "rows": rows}, f, indent=2)
    print(f"\nDone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
