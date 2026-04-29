"""
Portfolio combiner — run a strategy (or per-asset strategies) and produce
a risk-adjusted combined equity curve.

Key rule: each sub-portfolio is simulated with its own allocation of the
$10k, and contributes proportionally to the combined curve.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
import json
import pandas as pd

from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2

OUT_DIR = Path(__file__).resolve().parent / "results"


def run_combined(
    strategy_map: dict[str, tuple[str, str]],   # sym -> (strategy_name, tf)
    allocation: dict[str, float] = engine.PORTFOLIO_ALLOC,
    total: float = engine.TOTAL_CAPITAL,
    start: str = "2018-01-01",
    end: str = "2026-04-01",
    tag: str = "combined",
) -> dict:
    """
    Run a per-asset strategy combo. Returns a dict with:
      * equity_curve (DataFrame)
      * asset_reports (dict of per-asset metrics)
      * portfolio metrics (CAGR/Sharpe/DD/...)
      * buy_and_hold benchmark
    """
    per_asset_pfs = {}
    asset_reports = {}

    # Build BH benchmark on same assets/alloc.
    bh_curves = []

    for sym, (strat, tf) in strategy_map.items():
        df = engine.load(sym, tf, start, end)
        fn = STRATEGIES_V2[strat]
        sig = fn(df)

        init = allocation[sym] * total
        res = engine.run_backtest(
            df,
            entries=sig["entries"], exits=sig["exits"],
            short_entries=sig.get("short_entries"),
            short_exits=sig.get("short_exits"),
            sl_stop=sig.get("sl_stop"),
            tsl_stop=sig.get("tsl_stop"),
            init_cash=init,
            label=f"{strat}|{sym}|{tf}",
        )
        per_asset_pfs[sym] = res.pf
        asset_reports[sym] = {k: v for k, v in res.metrics.items()
                              if k not in ("label",)}

        # BH: scaled price curve — start at allocation, ride price.
        bh = df["close"].reindex_like(res.pf.value())
        bh = (bh / bh.iloc[0]) * init
        bh_curves.append(bh.rename(sym))

    # Combined equity (already-scaled curves sum to $10k × sum_weights)
    scaled_eq = []
    for sym, pf in per_asset_pfs.items():
        eq = pf.value().copy()
        scaled_eq.append(eq.rename(sym))

    port = pd.concat(scaled_eq, axis=1).ffill().fillna(method="bfill")
    port["portfolio_equity"] = port.sum(axis=1)

    bh_port = pd.concat(bh_curves, axis=1).ffill().fillna(method="bfill")
    bh_port["bh_equity"] = bh_port.sum(axis=1)

    # Metrics
    port_metrics = engine.portfolio_metrics(port["portfolio_equity"])
    bh_metrics   = engine.portfolio_metrics(bh_port["bh_equity"])

    out = {
        "tag": tag,
        "strategy_map": strategy_map,
        "allocation": allocation,
        "portfolio": port_metrics,
        "buy_and_hold_portfolio": bh_metrics,
        "per_asset": asset_reports,
    }

    # Persist
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{tag}_metrics.json").write_text(json.dumps(out, default=str, indent=2))
    port.to_csv(OUT_DIR / f"{tag}_equity.csv")
    bh_port.to_csv(OUT_DIR / f"{tag}_bh_equity.csv")
    return out


if __name__ == "__main__":
    # Test: V2B volume-breakout on all three at 4h
    combo = {
        "BTCUSDT": ("V2B_volume_breakout", "4h"),
        "ETHUSDT": ("V2B_volume_breakout", "4h"),
        "SOLUSDT": ("V2B_volume_breakout", "4h"),
    }
    r = run_combined(combo, tag="combo_v2b_4h_allweights")
    print(json.dumps(r["portfolio"], indent=2))
    print("BH:", json.dumps(r["buy_and_hold_portfolio"], indent=2))
