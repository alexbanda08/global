"""End-to-end scalping driver — iter 2.

Runs FOUR strategies on BTC/ETH/SOL 5m data with the extended feature set
(OBV / CMF / MFI / Volume-Profile / VWAP-bands / sweep / delta):

  1. Bella Fade        — long-only dip-buy after seller exhaustion
                         (single TP at 1.2R, ATR stop, OBV/CMF/vol gates)
  2. Offside           — short-only failed-breakout fade
                         (retest gate, vol spike, OBV divergence)
  3. VWAP-Bounce       — long pullback-to-VWAP-and-bounce
                         (CMF + MFI + cum-delta gates)
  4. Liquidity-Sweep   — long+short fade of session high/low takeout
                         (vol spike + delta divergence on sweep bar)

Outputs go to strategy_lab/reports/scalping/ + per-strategy subdirs.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_5m_with_features
from detect_bella_fade import detect as detect_bf, BellaFadeParams
from detect_offside import detect as detect_off, OffsideParams
from detect_vwap_bounce import detect as detect_vb, VwapBounceParams
from detect_liquidity_sweep import detect as detect_ls, LiquiditySweepParams
from scalp_simulator import (
    simulate_two_target, simulate_single_target, trade_stats,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "scalping"
OUT.mkdir(parents=True, exist_ok=True)
for sub in ["bella_fade", "offside", "vwap_bounce", "liquidity_sweep", "equity"]:
    (OUT / sub).mkdir(exist_ok=True)


def fmt(stats: dict, weeks: float) -> str:
    if stats["n"] == 0:
        return "  no trades"
    return (
        f"n={stats['n']:>4} ({stats['n']/weeks:>4.1f}/wk)  "
        f"WR={stats['wr']*100:>5.1f}%  PF={stats['pf']:>5.2f}  "
        f"avg={stats['avg_R']:>+6.3f}%  total_pnl=${stats['sum_pnl']:>+10.2f}"
    )


def split_by_side(trades: list[dict]) -> tuple[list, list]:
    return ([t for t in trades if t["side"] == 1],
            [t for t in trades if t["side"] == -1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--risk", type=float, default=0.01)
    ap.add_argument("--strategies", nargs="+",
                    default=["bella", "offside", "vwap", "sweep"],
                    choices=["bella", "offside", "vwap", "sweep"])
    args = ap.parse_args()

    print(f"Window: {args.start} → {args.end}, risk-per-trade={args.risk*100:.1f}%")
    print(f"Strategies: {args.strategies}\n", flush=True)

    rows = []
    for sym in args.symbols:
        print(f"══════════ {sym} ══════════", flush=True)
        t0 = time.time()
        df = load_5m_with_features(sym, start=args.start, end=args.end, extra=True, vp_window=60)
        weeks = (df.index[-1] - df.index[0]).total_seconds() / (7 * 86400)
        print(f"  bars: {len(df):,}  weeks: {weeks:.1f}  load+features: {time.time()-t0:.1f}s",
              flush=True)

        # ── Bella Fade ──
        if "bella" in args.strategies:
            t1 = time.time()
            bf_sigs = detect_bf(df, BellaFadeParams())
            print(f"  Bella Fade signals: {len(bf_sigs)}  ({time.time()-t1:.1f}s)", flush=True)
            bf_sigs.to_parquet(OUT / "bella_fade" / f"{sym}_signals.parquet")
            if len(bf_sigs):
                # Use single-target with TP=1.2R (already in the "tp" col)
                bf_trades, bf_eq = simulate_single_target(df, bf_sigs, risk_per_trade=args.risk)
                bf_stats = trade_stats(bf_trades)
                print(f"    {fmt(bf_stats, weeks)}", flush=True)
                pd.DataFrame(bf_trades).to_csv(OUT / "bella_fade" / f"{sym}_trades.csv", index=False)
                bf_eq.to_frame("equity").to_parquet(OUT / "equity" / f"{sym}_bella.parquet")
                rows.append({"symbol": sym, "strategy": "bella_fade", **bf_stats,
                             "per_week": bf_stats["n"] / weeks,
                             "final_eq_x": float(bf_eq.iloc[-1] / bf_eq.iloc[0])})

        # ── Offside ──
        if "offside" in args.strategies:
            t1 = time.time()
            off_sigs = detect_off(df, OffsideParams())
            print(f"  Offside signals: {len(off_sigs)}  ({time.time()-t1:.1f}s)", flush=True)
            off_sigs.to_parquet(OUT / "offside" / f"{sym}_signals.parquet")
            if len(off_sigs):
                off_trades, off_eq = simulate_single_target(df, off_sigs, risk_per_trade=args.risk)
                off_stats = trade_stats(off_trades)
                print(f"    {fmt(off_stats, weeks)}", flush=True)
                if off_trades:
                    longs, shorts = split_by_side(off_trades)
                    if longs:  print(f"      longs:  {fmt(trade_stats(longs), weeks)}")
                    if shorts: print(f"      shorts: {fmt(trade_stats(shorts), weeks)}")
                pd.DataFrame(off_trades).to_csv(OUT / "offside" / f"{sym}_trades.csv", index=False)
                off_eq.to_frame("equity").to_parquet(OUT / "equity" / f"{sym}_offside.parquet")
                rows.append({"symbol": sym, "strategy": "offside", **off_stats,
                             "per_week": off_stats["n"] / weeks,
                             "final_eq_x": float(off_eq.iloc[-1] / off_eq.iloc[0])})

        # ── VWAP-Bounce ──
        if "vwap" in args.strategies:
            t1 = time.time()
            vb_sigs = detect_vb(df, VwapBounceParams())
            print(f"  VWAP-Bounce signals: {len(vb_sigs)}  ({time.time()-t1:.1f}s)", flush=True)
            vb_sigs.to_parquet(OUT / "vwap_bounce" / f"{sym}_signals.parquet")
            if len(vb_sigs):
                vb_trades, vb_eq = simulate_single_target(df, vb_sigs, risk_per_trade=args.risk)
                vb_stats = trade_stats(vb_trades)
                print(f"    {fmt(vb_stats, weeks)}", flush=True)
                pd.DataFrame(vb_trades).to_csv(OUT / "vwap_bounce" / f"{sym}_trades.csv", index=False)
                vb_eq.to_frame("equity").to_parquet(OUT / "equity" / f"{sym}_vwap.parquet")
                rows.append({"symbol": sym, "strategy": "vwap_bounce", **vb_stats,
                             "per_week": vb_stats["n"] / weeks,
                             "final_eq_x": float(vb_eq.iloc[-1] / vb_eq.iloc[0])})

        # ── Liquidity-Sweep ──
        if "sweep" in args.strategies:
            t1 = time.time()
            ls_sigs = detect_ls(df, LiquiditySweepParams())
            print(f"  Liquidity-Sweep signals: {len(ls_sigs)}  ({time.time()-t1:.1f}s)", flush=True)
            ls_sigs.to_parquet(OUT / "liquidity_sweep" / f"{sym}_signals.parquet")
            if len(ls_sigs):
                ls_trades, ls_eq = simulate_single_target(df, ls_sigs, risk_per_trade=args.risk)
                ls_stats = trade_stats(ls_trades)
                print(f"    {fmt(ls_stats, weeks)}", flush=True)
                if ls_trades:
                    longs, shorts = split_by_side(ls_trades)
                    if longs:  print(f"      longs:  {fmt(trade_stats(longs), weeks)}")
                    if shorts: print(f"      shorts: {fmt(trade_stats(shorts), weeks)}")
                pd.DataFrame(ls_trades).to_csv(OUT / "liquidity_sweep" / f"{sym}_trades.csv", index=False)
                ls_eq.to_frame("equity").to_parquet(OUT / "equity" / f"{sym}_sweep.parquet")
                rows.append({"symbol": sym, "strategy": "liquidity_sweep", **ls_stats,
                             "per_week": ls_stats["n"] / weeks,
                             "final_eq_x": float(ls_eq.iloc[-1] / ls_eq.iloc[0])})

        print()

    if rows:
        rdf = pd.DataFrame(rows)
        rdf.to_csv(OUT / "scalping_results_iter2.csv", index=False)
        print(f"Results: {OUT/'scalping_results_iter2.csv'}")

        # Build SUMMARY
        lines = ["# Crypto Scalping — iter 2 (4 strategies, extended features)", "",
                 f"**Window:** {args.start} → {args.end}",
                 f"**Risk per trade:** {args.risk*100:.1f}% of equity",
                 f"**Fees:** Hyperliquid 4.5bp/side taker + 1.5bp slippage", "",
                 "## Strategy roster",
                 "- **Bella Fade**     (long-only) — dip-buy after seller exhaustion + OBV/CMF/vol-z gates",
                 "- **Offside**        (short-only) — failed-breakout fade with retest + OBV divergence",
                 "- **VWAP-Bounce**    (long-only) — pullback to VWAP + CMF/MFI/cum-delta confirmation",
                 "- **Liquidity-Sweep** (long+short) — session high/low takeout reversal + delta divergence",
                 "",
                 "## Per-strategy results",
                 "",
                 "| Symbol | Strategy | n | per_wk | WR | PF | avg ret/trade | total $PnL | final eq× |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for _, r in rdf.iterrows():
            lines.append(
                f"| {r['symbol']} | {r['strategy']} | {int(r['n'])} | "
                f"{r['per_week']:.2f} | {r['wr']*100:.1f}% | {r['pf']:.2f} | "
                f"{r['avg_R']:+.3f}% | ${r['sum_pnl']:+,.0f} | {r['final_eq_x']:.3f}× |"
            )
        lines.append("")
        lines.append("## Aggregate (cross-asset average per strategy)")
        lines.append("")
        agg = rdf.groupby("strategy").agg(
            n_total=("n", "sum"),
            avg_per_wk=("per_week", "mean"),
            avg_wr=("wr", "mean"),
            avg_pf=("pf", "mean"),
            avg_ret_pct=("avg_R", "mean"),
            sum_pnl=("sum_pnl", "sum"),
        ).round(3)
        lines.append(agg.to_markdown())
        lines.append("")
        lines.append("## Files")
        lines.append("```")
        for sub in ["bella_fade", "offside", "vwap_bounce", "liquidity_sweep"]:
            lines.append(f"strategy_lab/reports/scalping/{sub}/")
            lines.append(f"  {{sym}}_signals.parquet  {{sym}}_trades.csv")
        lines.append(f"strategy_lab/reports/scalping/equity/{{sym}}_{{strategy}}.parquet")
        lines.append("```")
        (OUT / "ITER2_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"Summary: {OUT/'ITER2_SUMMARY.md'}")


if __name__ == "__main__":
    main()
