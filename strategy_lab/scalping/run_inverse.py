"""Run inverse-side variants on existing iter-2 signals.

Reads the signal parquets from iter-2 (where original strategies all had
WR ~40% / PF ~0.6), flips them via `inverse_signals()`, re-runs through
the same simulator, and compares.

If the WR-asymmetry is real and stable, inverse should flip:
    iter-2 WR 40%, PF 0.66, avg -0.13%
  → inverse WR 60%, PF 1.5+, avg +0.13%  (in theory)

Reality check: fees apply to both directions (so inverse-edge is
diminished), and stops/targets are at fixed price levels — they don't
mirror perfectly bar-by-bar. Test empirically.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_5m_with_features
from inverse_signals import inverse_signals
from scalp_simulator import simulate_single_target, trade_stats

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "scalping"
INV_DIR = OUT / "inverse"
INV_DIR.mkdir(parents=True, exist_ok=True)
for sub in ["bella_fade", "offside", "vwap_bounce", "liquidity_sweep", "equity"]:
    (INV_DIR / sub).mkdir(exist_ok=True)


STRATEGIES = ["bella_fade", "offside", "vwap_bounce", "liquidity_sweep"]


def fmt(s: dict, weeks: float) -> str:
    if s["n"] == 0:
        return "  no trades"
    return (
        f"n={s['n']:>4} ({s['n']/weeks:>4.1f}/wk)  "
        f"WR={s['wr']*100:>5.1f}%  PF={s['pf']:>5.2f}  "
        f"avg={s['avg_R']:>+6.3f}%  total_pnl=${s['sum_pnl']:>+10.2f}"
    )


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--risk", type=float, default=0.01)
    args = ap.parse_args()

    rows_orig = pd.read_csv(OUT / "scalping_results_iter2.csv")
    print(f"Original iter-2 results:\n{rows_orig.to_string(index=False)}\n", flush=True)

    rows_out = []
    for sym in args.symbols:
        print(f"══════════ {sym} (inverse) ══════════", flush=True)
        df = load_5m_with_features(sym, start=args.start, end=args.end, extra=True, vp_window=60)
        weeks = (df.index[-1] - df.index[0]).total_seconds() / (7 * 86400)

        for strat in STRATEGIES:
            sig_path = OUT / strat / f"{sym}_signals.parquet"
            if not sig_path.exists():
                print(f"  {strat}: no signals file, skip")
                continue
            sigs = pd.read_parquet(sig_path)
            if "side" not in sigs.columns:
                sigs["side"] = 1  # default for long-only strategies
            if len(sigs) == 0:
                print(f"  {strat}: 0 signals, skip")
                continue

            # Need a 'tp' column; some iter-1 sigs only had tp1/tp2
            if "tp" not in sigs.columns and "tp2" in sigs.columns:
                sigs["tp"] = sigs["tp2"]
            elif "tp" not in sigs.columns:
                # Construct from stop & default 1.2R
                risk = sigs["entry_price"] - sigs["stop"]
                sigs["tp"] = sigs["entry_price"] + 1.2 * risk * sigs["side"]

            inv = inverse_signals(sigs, mode="mirror_rr")
            inv.to_parquet(INV_DIR / strat / f"{sym}_signals_inv.parquet")

            trades, eq = simulate_single_target(df, inv, risk_per_trade=args.risk)
            stats = trade_stats(trades)
            print(f"  {strat:<18} INVERSE  {fmt(stats, weeks)}", flush=True)
            if trades:
                pd.DataFrame(trades).to_csv(INV_DIR / strat / f"{sym}_trades_inv.csv", index=False)
                eq.to_frame("equity").to_parquet(INV_DIR / "equity" / f"{sym}_{strat}_inv.parquet")
                # Side breakdown for two-sided strategies
                longs = [t for t in trades if t["side"] == 1]
                shorts = [t for t in trades if t["side"] == -1]
                if longs and shorts:
                    print(f"      longs:  {fmt(trade_stats(longs), weeks)}")
                    print(f"      shorts: {fmt(trade_stats(shorts), weeks)}")
                rows_out.append({
                    "symbol": sym, "strategy": strat, "variant": "inverse",
                    **stats,
                    "per_week": stats["n"] / weeks,
                    "final_eq_x": float(eq.iloc[-1] / eq.iloc[0]),
                })
        print()

    if rows_out:
        rdf = pd.DataFrame(rows_out)
        rdf.to_csv(OUT / "scalping_results_inverse.csv", index=False)
        print(f"\nSaved: {OUT/'scalping_results_inverse.csv'}")

        # Side-by-side comparison
        print("\n" + "═" * 100)
        print("ORIGINAL vs INVERSE")
        print("═" * 100)
        print(f"{'sym':<8} {'strategy':<18} {'orig n/WR/PF':<25} {'inv n/WR/PF':<25} {'orig $':>12} {'inv $':>12} {'flip?':>6}")
        for sym in args.symbols:
            for strat in STRATEGIES:
                orig = rows_orig[(rows_orig["symbol"] == sym) & (rows_orig["strategy"] == strat)]
                inv = rdf[(rdf["symbol"] == sym) & (rdf["strategy"] == strat)]
                if orig.empty or inv.empty:
                    continue
                o = orig.iloc[0]
                i = inv.iloc[0]
                flip = "✓" if i["sum_pnl"] > 0 and o["sum_pnl"] < 0 else ""
                print(
                    f"{sym:<8} {strat:<18} "
                    f"{int(o['n']):>4} {o['wr']*100:>5.1f}% PF{o['pf']:.2f}    "
                    f"{int(i['n']):>4} {i['wr']*100:>5.1f}% PF{i['pf']:.2f}    "
                    f"{o['sum_pnl']:>+12,.0f} {i['sum_pnl']:>+12,.0f} {flip:>6}"
                )


if __name__ == "__main__":
    main()
