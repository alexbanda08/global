"""
Edge hunt — run our validated strategies against every pair x timeframe
in the expanded universe to find new deploy-ready combinations.

Universe:
  9 pairs: BTC, ETH, SOL (baseline) + BNB, XRP, DOGE, AVAX, LINK, ADA (new)
  3 timeframes: 4h, 1h, 15m

Strategies:
  4h  -> V4C_range_kalman, V3B_adx_gate, V2B_volume_breakout
         (via vbt engine, from strategies_v2/v3/v4)
  1h  -> V13A range_kalman, V13B adx_gate, V13C volume_breakout
         (ATR-stop simulate() from run_v13_trend_1h)
  15m -> V15A/B/C = V13 ports with 4x smaller lookbacks, ATR-scaled stops

Pass flag = sharpe > 0.5 AND cagr > 0.  Surfaces any new edge.

Output: strategy_lab/results/edge_hunt.csv + printed ranked summary.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2
from strategy_lab.strategies_v3 import STRATEGIES_V3
from strategy_lab.strategies_v4 import STRATEGIES_V4
from strategy_lab.run_v13_trend_1h import (
    v13_range_kalman, v13_adx_gate, v13_volume_breakout,
    simulate, report,
)

OUT = Path(__file__).resolve().parent / "results"

PAIRS_ORIG = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PAIRS_NEW  = ["BNBUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "ADAUSDT"]
PAIRS = PAIRS_ORIG + PAIRS_NEW

# Per-pair safe start (~1 month after first bar).
STARTS = {
    "BTCUSDT":  "2018-01-01",
    "ETHUSDT":  "2018-01-01",
    "SOLUSDT":  "2020-10-01",
    "BNBUSDT":  "2018-01-01",
    "XRPUSDT":  "2018-06-01",
    "ADAUSDT":  "2018-06-01",
    "LINKUSDT": "2019-03-01",
    "DOGEUSDT": "2019-09-01",
    "AVAXUSDT": "2020-11-01",
}
END = "2026-04-01"
INIT = 10_000.0


# ---------------------------------------------------------------------
# 4h — V4C / V3B / V2B via vbt engine
# ---------------------------------------------------------------------
STRAT_4H = {
    "V4C_range_kalman":    STRATEGIES_V4["V4C_range_kalman"],
    "V3B_adx_gate":        STRATEGIES_V3["V3B_adx_gate"],
    "V2B_volume_breakout": STRATEGIES_V2["V2B_volume_breakout"],
}


def run_4h(sym: str, name: str, fn) -> dict:
    df = engine.load(sym, "4h", STARTS[sym], END)
    sig = fn(df)
    res = engine.run_backtest(df,
        entries=sig["entries"], exits=sig["exits"],
        short_entries=sig.get("short_entries"),
        short_exits=sig.get("short_exits"),
        sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
        init_cash=INIT, label=f"{name}|{sym}|4h")
    m = res.metrics
    return {
        "pair": sym, "tf": "4h", "strategy": name,
        "trades": int(m["n_trades"]),
        "cagr":   round(m["cagr"], 3),
        "sharpe": round(m["sharpe"], 3),
        "dd":     round(m["max_dd"], 3),
        "final":  round(m["final_equity"], 0),
        "pf":     round(m.get("profit_factor", 0), 3),
    }


# ---------------------------------------------------------------------
# 1h / 15m — V13 variants via simulate()
# ---------------------------------------------------------------------
# V13 default params were tuned for 1h; for 15m we scale lookbacks 4x smaller.
STRAT_1H = {
    "V13A_range_kalman":    (v13_range_kalman,   dict(alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800)),
    "V13B_adx_gate":        (v13_adx_gate,       dict(don_len=120, vol_len=80, vol_mult=1.3, regime_len=600, adx_min=20)),
    "V13C_volume_breakout": (v13_volume_breakout, dict(don_len=120, vol_len=80, vol_mult=1.3, regime_len=600)),
}
STRAT_15M = {
    "V15A_range_kalman":    (v13_range_kalman,   dict(alpha=0.05, rng_len=100, rng_mult=2.5, regime_len=200)),
    "V15B_adx_gate":        (v13_adx_gate,       dict(don_len=30, vol_len=20, vol_mult=1.3, regime_len=150, adx_min=20)),
    "V15C_volume_breakout": (v13_volume_breakout, dict(don_len=30, vol_len=20, vol_mult=1.3, regime_len=150)),
}

TP, SL, TRAIL, MAX_HOLD = 5.0, 2.0, 3.5, 72


def run_atr(sym: str, tf: str, name: str, fn, params: dict) -> dict:
    df = engine.load(sym, tf, STARTS[sym], END)
    df = df.dropna(subset=["open","high","low","close","volume"]).copy()
    sig = fn(df, **params)
    sig = sig & ~sig.shift(1).fillna(False)
    trades, eq = simulate(df, sig, tp_atr=TP, sl_atr=SL, trail_atr=TRAIL,
                          max_hold=MAX_HOLD)
    r = report(f"{name}|{sym}|{tf}", eq, trades)
    return {
        "pair": sym, "tf": tf, "strategy": name,
        "trades": int(r["n"]),
        "cagr":   round(r["cagr"], 3),
        "sharpe": round(r["sharpe"], 3),
        "dd":     round(r["dd"], 3),
        "final":  round(r["final"], 0),
        "pf":     round(r["pf"], 3),
    }


# ---------------------------------------------------------------------
def main():
    rows = []

    print("[1/3] 4h strategies across 9 pairs (V4C / V3B / V2B) ...", flush=True)
    for sym in PAIRS:
        for name, fn in STRAT_4H.items():
            try:
                rows.append(run_4h(sym, name, fn))
            except Exception as e:
                rows.append({"pair": sym, "tf": "4h", "strategy": name, "error": str(e)})

    print("[2/3] 1h strategies across 9 pairs (V13A / V13B / V13C) ...", flush=True)
    for sym in PAIRS:
        for name, (fn, p) in STRAT_1H.items():
            try:
                rows.append(run_atr(sym, "1h", name, fn, p))
            except Exception as e:
                rows.append({"pair": sym, "tf": "1h", "strategy": name, "error": str(e)})

    print("[3/3] 15m strategies across 9 pairs (V15 = 4x downscaled V13) ...", flush=True)
    for sym in PAIRS:
        for name, (fn, p) in STRAT_15M.items():
            try:
                rows.append(run_atr(sym, "15m", name, fn, p))
            except Exception as e:
                rows.append({"pair": sym, "tf": "15m", "strategy": name, "error": str(e)})

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "edge_hunt.csv", index=False)
    print(f"\nWrote {OUT/'edge_hunt.csv'}")

    good = df.dropna(subset=["sharpe"]) if "sharpe" in df.columns else df
    good = good.assign(pass_=(good["sharpe"] > 0.5) & (good["cagr"] > 0))

    print("\n=== TOP 20 by Sharpe (all pair x TF x strategy) ===")
    top = good.sort_values("sharpe", ascending=False).head(20)
    print(top[["pair","tf","strategy","trades","cagr","sharpe","dd","final","pass_"]].to_string(index=False))

    print("\n=== PASSING (sharpe > 0.5 AND cagr > 0) ===")
    pas = good[good["pass_"]].sort_values(["tf","sharpe"], ascending=[True, False])
    print(pas[["pair","tf","strategy","trades","cagr","sharpe","dd","final"]].to_string(index=False))

    print("\n=== PASS COUNT per TF ===")
    print(good.groupby("tf")["pass_"].agg(["sum","count"]).to_string())

    # Per-pair best
    print("\n=== BEST STRATEGY PER PAIR PER TF ===")
    best = good.loc[good.groupby(["pair","tf"])["sharpe"].idxmax()]
    print(best[["pair","tf","strategy","trades","cagr","sharpe","dd","final","pass_"]].sort_values(["pair","tf"]).to_string(index=False))


if __name__ == "__main__":
    main()
