"""4-hour timeframe strategy using GB-validated cross-asset signals.

Plugs the regime_detector_v2 winners (cross_institutional_lead + z_top_lsr_count + brigalS)
into the canonical perps simulator from strategy_lab/eval/perps_simulator.py — which already
handles ATR trailing stops, TP, SL, ATR-risk position sizing, max_hold, cooldown.

The only feature added on top: equity-curve filter (R_3loss_pause from research_v5).

Sweep matrix:
  Entry composites:
    A1_zlsr_only           — control: same as v4 baseline (z_lsr<-1.5)
    A2_top_lsr             — z_top_lsr_count<-1.0  (4h top corr -0.36 on ETH/SOL)
    A3_brigalS             — brigalS<-1.0         (4h corr -0.31)
    A4_cross_inst_lead     — cross_institutional_lead>0  (universal cross-asset signal)
    A5_2of3_composite      — ≥2 of {A2, A3, A4}
    A6_3of3_composite      — all 3 of {A2, A3, A4} (strictest)

  TP / SL / Trail (ATR multiples, fed straight to perps_simulator.simulate):
    TP_5_SL_2_TRAIL_3p5  (default canonical)
    TP_8_SL_2_TRAIL_5     (looser TP, looser trail)

  Equity-curve filter:
    R_none
    R_3loss_pause      (skip new entries if last 3 trades were all losses;
                        unpause after one winning trade)
"""
from __future__ import annotations
from pathlib import Path
import argparse
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

from eval.perps_simulator import simulate, compute_metrics

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "strategy_4h"
REPORTS.mkdir(parents=True, exist_ok=True)

BARS_PER_YEAR_4H = 6 * 365  # 4h bars in a year
FEE = 4.5e-4  # Hyperliquid taker
SLIP = 1.5e-4  # 1.5bp slip estimate


# ─────────────────────────────────────────
#  Data loading at 4h
# ─────────────────────────────────────────

def load_4h(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet")
    # Resample 5min indicators to 4h (last value of each window)
    p_4h = p.resample("4h").last()

    # OHLC from spot 1h → resample to 4h with proper aggregation
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")
    spot = spot[["open", "high", "low", "close", "volume"]].astype(float)
    ohlc_4h = pd.DataFrame({
        "open": spot["open"].resample("4h").first(),
        "high": spot["high"].resample("4h").max(),
        "low": spot["low"].resample("4h").min(),
        "close": spot["close"].resample("4h").last(),
        "volume": spot["volume"].resample("4h").sum(),
    })
    p_4h = p_4h.join(ohlc_4h, how="inner", rsuffix="_spot")
    # Use spot OHLC, not panel close (panel may have synthesized spot_price proxies)
    return p_4h.dropna(subset=["close", "z_lsr"])


# ─────────────────────────────────────────
#  Entry composites
# ─────────────────────────────────────────

def signal_A1_zlsr_only(df: pd.DataFrame) -> pd.Series:
    return (df["z_lsr"] < -1.5).fillna(False)


def signal_A2_top_lsr(df: pd.DataFrame) -> pd.Series:
    return (df["z_top_lsr_count"] < -1.0).fillna(False)


def signal_A3_brigalS(df: pd.DataFrame) -> pd.Series:
    return (df["brigalS"] < -1.0).fillna(False)


def signal_A4_cross_inst_lead(df: pd.DataFrame) -> pd.Series:
    return (df["cross_institutional_lead"] > 0).fillna(False)


def signal_A5_2of3(df: pd.DataFrame) -> pd.Series:
    return ((signal_A2_top_lsr(df).astype(int)
             + signal_A3_brigalS(df).astype(int)
             + signal_A4_cross_inst_lead(df).astype(int)) >= 2)


def signal_A6_3of3(df: pd.DataFrame) -> pd.Series:
    return (signal_A2_top_lsr(df) & signal_A3_brigalS(df) & signal_A4_cross_inst_lead(df))


ENTRIES = {
    "A1_zlsr_only":           signal_A1_zlsr_only,
    "A2_top_lsr":             signal_A2_top_lsr,
    "A3_brigalS":             signal_A3_brigalS,
    "A4_cross_inst_lead":     signal_A4_cross_inst_lead,
    "A5_2of3_composite":      signal_A5_2of3,
    "A6_3of3_composite":      signal_A6_3of3,
}


# ─────────────────────────────────────────
#  Equity-curve filter (R_3loss_pause)
#   — applies post-hoc to the entry signal series
# ─────────────────────────────────────────

def apply_3loss_pause(entries: pd.Series, df: pd.DataFrame, cfg: dict) -> pd.Series:
    """First simulation pass to know which trades happen + their PnL,
    then mask out entries that would have fired during a 3-consecutive-losses pause."""
    trades, _ = simulate(
        df=df, long_entries=entries,
        tp_atr=cfg["tp_atr"], sl_atr=cfg["sl_atr"], trail_atr=cfg["trail_atr"],
        max_hold=cfg["max_hold"],
        risk_per_trade=cfg.get("risk_per_trade", 0.03),
        leverage_cap=cfg.get("leverage_cap", 3.0),
        fee=FEE, slip=SLIP,
    )
    if len(trades) < 4:
        return entries

    # Build a mask: True at exit_idx of a losing trade if the previous 2 were also losses
    n = len(df)
    pause_until = np.full(n, -1, dtype=int)  # bar index up to which entries are paused
    last_3_pnl: list[float] = []
    for t in trades:
        last_3_pnl.append(t["ret"])
        if len(last_3_pnl) > 3:
            last_3_pnl.pop(0)
        if len(last_3_pnl) == 3 and all(p <= 0 for p in last_3_pnl):
            # Pause entries from this exit_idx onward until next winning trade exit
            start = t["exit_idx"]
            # Find the next trade with positive ret, mark pause until just before its exit
            for nt in trades:
                if nt["entry_idx"] > start and nt["ret"] > 0:
                    pause_until[start:nt["exit_idx"]] = nt["exit_idx"]
                    break
            else:
                # never recovered — pause to the end
                pause_until[start:] = n

    # Build masked entries series
    blocked = np.zeros(n, dtype=bool)
    for i in range(n):
        if pause_until[i] > i:
            blocked[i] = True
    masked = entries.to_numpy(dtype=bool) & (~blocked)
    return pd.Series(masked, index=entries.index)


# ─────────────────────────────────────────
#  Exit configs (passed to simulate)
# ─────────────────────────────────────────

EXIT_CONFIGS = {
    "TP5_SL2_TR3p5_H72":  {"tp_atr": 5.0, "sl_atr": 2.0, "trail_atr": 3.5, "max_hold": 72},
    "TP8_SL2_TR5_H96":    {"tp_atr": 8.0, "sl_atr": 2.0, "trail_atr": 5.0, "max_hold": 96},
    "TP6_SL2p5_TR4_H48":  {"tp_atr": 6.0, "sl_atr": 2.5, "trail_atr": 4.0, "max_hold": 48},
}


# ─────────────────────────────────────────
#  Driver
# ─────────────────────────────────────────

def run_one(symbol: str, df: pd.DataFrame, entry_name: str, exit_name: str,
            risk_filter: str) -> dict:
    entry_fn = ENTRIES[entry_name]
    cfg = EXIT_CONFIGS[exit_name]
    entries = entry_fn(df)

    if risk_filter == "R_3loss_pause":
        entries = apply_3loss_pause(entries, df, cfg)

    trades, equity = simulate(
        df=df, long_entries=entries,
        tp_atr=cfg["tp_atr"], sl_atr=cfg["sl_atr"], trail_atr=cfg["trail_atr"],
        max_hold=cfg["max_hold"],
        risk_per_trade=0.03, leverage_cap=3.0,
        fee=FEE, slip=SLIP,
    )

    metrics = compute_metrics(f"{entry_name}__{exit_name}__{risk_filter}",
                              equity, trades, BARS_PER_YEAR_4H)

    bh = float(df["close"].iloc[-1] / df["close"].iloc[0])
    init_cash = 10_000.0
    final_x = metrics["final_equity"] / init_cash
    metrics["buy_hold_x"] = bh
    metrics["final_eq_x"] = final_x
    metrics["outperform"] = final_x / bh
    metrics["entry_signals_total"] = int(entries.sum())
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    all_rows = []
    for sym in args.symbols:
        df = load_4h(sym)
        bh = df["close"].iloc[-1] / df["close"].iloc[0]
        print(f"\n══════ {sym}  bars={len(df):,}  buy-hold={bh:.2f}× ══════")
        print(f"{'entry':<22} {'exit':<22} {'rfilter':<14} {'n':>4} {'WR%':>5} "
              f"{'Sh':>5} {'Cal':>5} {'MDD%':>6} {'eq×':>5} {'B&H':>4}")

        for entry_name in ENTRIES:
            for exit_name in EXIT_CONFIGS:
                for rf in ["R_none", "R_3loss_pause"]:
                    m = run_one(sym, df, entry_name, exit_name, rf)
                    m["symbol"] = sym
                    m["entry"] = entry_name
                    m["exit"] = exit_name
                    m["risk_filter"] = rf
                    all_rows.append(m)
                    print(f"{entry_name:<22} {exit_name:<22} {rf:<14} "
                          f"{m['n_trades']:>4} {m['win_rate']*100:>5.1f} "
                          f"{m['sharpe']:>+5.2f} {m['calmar']:>+5.2f} "
                          f"{m['max_dd']*100:>+6.1f} "
                          f"{m['final_eq_x']:>5.2f} {m['outperform']:>4.2f}")

    out = pd.DataFrame(all_rows)
    # Drop nested per_year for CSV cleanliness
    out_csv = out.drop(columns=["per_year"], errors="ignore")
    out_csv.to_csv(REPORTS / "strategy_4h_results.csv", index=False)

    # Top per symbol by composite score: PF≥1.3, MDD≥-30%, n≥30
    print("\n══════════════ TOP 10 PER SYMBOL  (Calmar≥0.5, MDD≥-30%, n≥30) ══════════════")
    for sym in args.symbols:
        sub = out[out["symbol"] == sym].copy()
        elig = sub[(sub["calmar"] >= 0.5) & (sub["max_dd"] >= -0.30) & (sub["n_trades"] >= 30)]
        elig = elig.sort_values(["sharpe", "outperform"], ascending=False).head(10)
        print(f"\n{sym}:  {len(elig)} eligible (out of {len(sub)} tested)")
        if len(elig) == 0:
            tops = sub.sort_values("sharpe", ascending=False).head(5)
            print(f"  (none clear all 3 filters; top 5 by Sharpe:)")
            for _, r in tops.iterrows():
                print(f"    {r['entry']}__{r['exit']}__{r['risk_filter']:<14} "
                      f"n={r['n_trades']:>3}  WR={r['win_rate']*100:>4.1f}%  "
                      f"Sh={r['sharpe']:+.2f}  Cal={r['calmar']:+.2f}  "
                      f"MDD={r['max_dd']*100:+.1f}%  eq={r['final_eq_x']:.2f}× "
                      f"({r['outperform']:.2f}× B&H)")
        else:
            for _, r in elig.iterrows():
                print(f"    {r['entry']}__{r['exit']}__{r['risk_filter']:<14} "
                      f"n={r['n_trades']:>3}  WR={r['win_rate']*100:>4.1f}%  "
                      f"Sh={r['sharpe']:+.2f}  Cal={r['calmar']:+.2f}  "
                      f"MDD={r['max_dd']*100:+.1f}%  eq={r['final_eq_x']:.2f}× "
                      f"({r['outperform']:.2f}× B&H)")

    print(f"\nFull results: {REPORTS/'strategy_4h_results.csv'} ({len(out)} rows)")


if __name__ == "__main__":
    main()
