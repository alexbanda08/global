"""Phase A continued: add F7 and Markov gates to the clean backtest.

If clean spec + F7 produces healthy WR while production's F7 sleeve shows 5% WR,
that PROVES production has a bug (not regime).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, "strategy_lab/markov_filter")
from markov_regime_micro import build_labels_for_asset, regime_at_us, BULL, BEAR  # noqa: E402

OUT_DIR = Path("strategy_lab/markov_filter/_results/clean_backtest_phase_a")
FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
ASSETS = ("BTC", "ETH", "SOL")
TIMEFRAMES = {"5m": 300, "15m": 900}

MARKOV_VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
}


def wilder_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    diffs = np.diff(closes)
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)
    avg_g = gains[:period].mean()
    avg_l = losses[:period].mean()
    for i in range(period, n - 1):
        rsi[i + 1] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    return rsi


def main():
    print("[1] Loading fires + klines...")
    fires = pd.read_csv(OUT_DIR / "all_fires.csv")
    fires["fire_us"] = np.where(
        fires["strategy"] == "momo_v1",
        (fires["ws_s"] + 120) * 1_000_000,
        np.where(fires["strategy"] == "momo_v2",
                 (fires["ws_s"] + 60) * 1_000_000,
                 fires["slot_start_s"] * 1_000_000),
    )
    fires["ws_us"] = fires["ws_s"].astype("int64") * 1_000_000
    print(f"   {len(fires):,} fires loaded")

    # RSI cache for F7
    k = pd.read_csv(FRESH_KLINES)
    rsi_cache = {}
    for asset in ASSETS:
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = k[k["symbol_id"] == sym].drop_duplicates("time_period_start_us") \
                                       .sort_values("time_period_start_us")
        close = sub["price_close"].values.astype("float64")
        end_us = sub["time_period_start_us"].values.astype("int64") + 60_000_000
        rsi = wilder_rsi(close, 14)
        rsi_cache[asset] = (end_us, rsi)

    # F7 lookup
    print("[2] Computing F7 (RSI at ws_s)...")
    rsis = np.full(len(fires), np.nan)
    for i, r in enumerate(fires.itertuples(index=False)):
        end_us, rsi = rsi_cache[r.asset]
        idx = int(np.searchsorted(end_us, int(r.ws_us), side="right")) - 1
        if 0 <= idx < len(rsi):
            rsis[i] = rsi[idx]
    fires["rsi_14"] = rsis
    fires["f7_pass"] = ((fires["signal"] == "UP") & (fires["rsi_14"] > 50)) | \
                      ((fires["signal"] == "DOWN") & (fires["rsi_14"] < 50))
    print(f"   F7 pass rate: {fires.f7_pass.mean()*100:.1f}%")

    # Markov cache
    print("[3] Markov label cache...")
    mk_cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ASSETS:
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"],
                      fresh_klines_csv=FRESH_KLINES)
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            mk_cache[(vname, asset)] = (end_us, labels)
    print(f"   {len(mk_cache)} (variant × asset) cached")

    print("[4] Markov regime at fire_us...")
    for vname, _ in MARKOV_VARIANTS:
        regs = np.full(len(fires), -1, dtype=np.int8)
        for i, r in enumerate(fires.itertuples(index=False)):
            end_us, labels = mk_cache[(vname, r.asset)]
            regs[i] = regime_at_us(end_us, labels, int(r.fire_us))
        fires[f"regime_{vname}"] = regs
        fires[f"markov_pass_{vname}"] = (
            ((fires["signal"] == "UP") & (regs == BULL)) |
            ((fires["signal"] == "DOWN") & (regs == BEAR))
        )

    fires.to_csv(OUT_DIR / "all_fires_with_gates.csv", index=False)

    # Per-strategy per-cell per-gate summary
    print("\n[5] Per-strategy × cell × gate summary")
    best_variant = "w20_1m_fixed"  # use best from earlier analysis

    def summarize(g, label):
        n = len(g)
        if n == 0: return {"filter": label, "n": 0, "wr": 0.0}
        return {"filter": label, "n": n, "wr": round(g["won"].mean()*100, 2)}

    rows = []
    for strat in ("momo_v1", "momo_v2", "sniper"):
        sub_strat = fires[fires["strategy"] == strat]
        for cell, g in sub_strat.groupby("cell"):
            rows_cell = [
                summarize(g, "BASE"),
                summarize(g[g["f7_pass"]], "F7"),
            ]
            for vname, _ in MARKOV_VARIANTS:
                mk = f"markov_pass_{vname}"
                rows_cell.append(summarize(g[g[mk]], f"M:{vname.replace('w20_','')}"))
                rows_cell.append(summarize(g[g["f7_pass"] & g[mk]], f"F7+M:{vname.replace('w20_','')}"))
            for row in rows_cell:
                row["strategy"] = strat
                row["cell"] = cell
                rows.append(row)
    summ = pd.DataFrame(rows)[["strategy","cell","filter","n","wr"]]
    summ.to_csv(OUT_DIR / "scorecard_clean.csv", index=False)

    # Pretty print: for each (strategy, cell) show BASE, F7, best Markov, best F7+M
    print("\n=== CLEAN BACKTEST WR per (strategy, cell, gate) ===")
    print(f"{'strategy':<10}{'cell':<10}{'BASE':>10}{'F7':>10}{'M:1m_fixed':>12}{'F7+M:1m_fixed':>16}")
    for (strat, cell), g in summ.groupby(["strategy", "cell"]):
        base = g[g["filter"] == "BASE"].iloc[0]
        f7   = g[g["filter"] == "F7"].iloc[0]
        mkr  = g[g["filter"] == "M:1m_fixed"].iloc[0]
        fmk  = g[g["filter"] == "F7+M:1m_fixed"].iloc[0]
        def fmt(row): return f"{row['wr']:.1f}%(n={row['n']})"
        print(f"{strat:<10}{cell:<10}{fmt(base):>10}{fmt(f7):>10}{fmt(mkr):>12}{fmt(fmk):>16}")


if __name__ == "__main__":
    main()
