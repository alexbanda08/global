"""
V17 — Micro-tune the V16 winner: ETH RangeKalman_LS (long+short).

Goal: push net CAGR to >=55% under TAKER fees (realistic execution) while
keeping DD <= -40%.

Sweep: TP/SL/Trail multipliers, max_hold, risk_per_trade, params (alpha, rng_mult).
Blended fee model: entries maker-likely (0.00020), exits taker (0.00045)
  — avg 0.000325 for a 50/50 mix. Plus a pessimistic pure-taker scenario.
"""
from __future__ import annotations
import sys, itertools
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_rangekalman, sig_rangekalman_short,
)

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "strategy_lab" / "features"
OUT = ROOT / "strategy_lab" / "results" / "v17"
OUT.mkdir(parents=True, exist_ok=True)


def run_variant(df, params, tp, sl, trail, mh, risk, lev, fee):
    ls = sig_rangekalman(df, **params); ls = ls & ~ls.shift(1).fillna(False)
    ss = sig_rangekalman_short(df, **params); ss = ss & ~ss.shift(1).fillna(False)
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=fee)
    return trades, eq


def main():
    df = pd.read_parquet(FEAT / "ETHUSDT_1h_features.parquet")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
    df = df[df.index >= pd.Timestamp("2019-01-01", tz="UTC")]
    print(f"ETH 1h bars: {len(df):,}")

    # Base: alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800
    # Sweep around this.
    param_grid = [
        {"alpha": a, "rng_len": rl, "rng_mult": rm, "regime_len": 800}
        for a in [0.05, 0.07, 0.09]
        for rl in [300, 400, 500]
        for rm in [2.0, 2.5, 3.0]
    ]
    # Exit grid
    exit_grid = [
        {"tp": tp, "sl": sl, "trail": tr, "mh": mh}
        for tp in [4.0, 5.0, 6.0, 7.0]
        for sl in [1.5, 2.0, 2.5]
        for tr in [2.5, 3.5, 4.5]
        for mh in [48, 72, 120]
    ]
    # Risk / leverage
    rl_grid = [(0.03, 3.0), (0.04, 3.0), (0.05, 3.0)]
    # Fees
    FEES = [("taker_0.045", 0.00045), ("blend_0.033", 0.000325), ("maker_0.015", 0.00015)]

    rows = []
    # Exploration is O(27*36*3*3) ≈ 8748 runs — too slow.
    # Smart: do a two-pass search:
    #   Pass 1: fix params to best (0.07, 400, 2.5, 800), sweep exit/risk/fee.
    #   Pass 2: fix exit to best, sweep params.
    print("\n--- Pass 1: fix params, sweep exits & risk & fees ---", flush=True)
    params0 = {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800}
    for exits in exit_grid:
        for (risk, lev) in rl_grid:
            for (fee_name, fee) in FEES:
                try:
                    tr, eq = run_variant(df, params0, exits["tp"], exits["sl"], exits["trail"],
                                         exits["mh"], risk, lev, fee)
                    r = metrics(f"p1_{fee_name}_tp{exits['tp']}_sl{exits['sl']}_tr{exits['trail']}_mh{exits['mh']}_r{risk}",
                                eq, tr)
                    r.update({"pass": 1, "fee_mode": fee_name, "risk": risk, "leverage": lev,
                              "params": "a=0.07,rl=400,rm=2.5", **exits})
                    rows.append(r)
                except Exception as e:
                    pass
    print(f"  Pass1 done: {len(rows)} runs", flush=True)

    # find best exit under taker fees (realistic)
    df_rows = pd.DataFrame(rows)
    taker_rows = df_rows[(df_rows["fee_mode"] == "taker_0.045") & (df_rows["dd"] >= -0.40)]
    if len(taker_rows):
        best = taker_rows.sort_values("cagr_net", ascending=False).iloc[0]
        print("\nBest taker-fee exit config:", best.to_dict())
    else:
        best = df_rows.sort_values("cagr_net", ascending=False).iloc[0]

    print("\n--- Pass 2: fix exit to best, sweep params ---", flush=True)
    best_exit = {"tp": float(best["tp"]), "sl": float(best["sl"]),
                 "trail": float(best["trail"]), "mh": int(best["mh"])}
    best_rl = (float(best["risk"]), float(best["leverage"]))
    for params in param_grid:
        for (fee_name, fee) in FEES:
            try:
                tr, eq = run_variant(df, params, best_exit["tp"], best_exit["sl"],
                                     best_exit["trail"], best_exit["mh"],
                                     best_rl[0], best_rl[1], fee)
                plabel = ",".join(f"{k}={v}" for k, v in params.items())
                r = metrics(f"p2_{fee_name}_{plabel}", eq, tr)
                r.update({"pass": 2, "fee_mode": fee_name, "risk": best_rl[0],
                          "leverage": best_rl[1], "params": plabel, **best_exit})
                rows.append(r)
            except Exception as e:
                pass
    print(f"  Pass2 done: {len(rows)} total", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v17_eth_tune_results.csv", index=False)

    cols = ["pass", "fee_mode", "risk", "leverage", "params", "tp", "sl", "trail", "mh",
            "avg_lev", "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf",
            "exposure", "funding_drag", "final"]

    print("\n=== Best under TAKER fees (net CAGR, DD>=-40%) ===")
    tk = out[(out["fee_mode"] == "taker_0.045") & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.9)]
    if len(tk):
        print(tk.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))

    print("\n=== Best under BLEND fees (net CAGR, DD>=-40%) ===")
    bl = out[(out["fee_mode"] == "blend_0.033") & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.9)]
    if len(bl):
        print(bl.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))

    print("\n=== Best under MAKER fees (net CAGR, DD>=-40%) ===")
    mk = out[(out["fee_mode"] == "maker_0.015") & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.9)]
    if len(mk):
        print(mk.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
