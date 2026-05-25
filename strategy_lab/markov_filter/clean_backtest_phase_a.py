"""Phase A: Clean signal recomputation from canonical raw data.

NO shadow data input. NO L25 walk yet (Phase B). Pure outcome-based WR
validation to settle the V2 bug question: does clean spec-compliant momo v2
produce the catastrophic eth_5m / btc_15m WR that production reports?

Inputs:
  - data/v4/canonical/klines_1m.parquet (binance-spot-ws 1MIN, Apr 14 → May 19)
  - VPS3 binance_1m_fresh.csv          (binance-spot-ws 1MIN, Apr 14 → May 21 19:32)
  - data/v4/canonical/resolutions.parquet (chainlink-derived outcomes, Apr 22 → May 21 17:35)

Strategies recomputed (per production code):
  momo v1:  ret_2m = log(close@(ws_s+120) / close@ws_s)         fire ws_s+120
  momo v2:  ret_2m = log(close@(ws_s+60)  / close@(ws_s-60))    fire ws_s+60
  sniper 5m: ret_5m = log(close@slot_start / close@(slot_start-300))  fire slot_start
  sniper 15m: ret_15m = log(close@slot_start / close@(slot_start-900)) fire slot_start

Gate: |ret| >= q90 of rolling 14d |ret| (causal — prior 14d, not including current row).

Where `ws_s` = `slot_start - window_s` per CLAUDE.md.

Output: per-cell WR + signal-direction × outcome cross-tabs.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import load_resolutions, asof_strict  # noqa: E402

FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
OUT_DIR = Path("strategy_lab/markov_filter/_results/clean_backtest_phase_a")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS = ("BTC", "ETH", "SOL")
TIMEFRAMES = {"5m": 300, "15m": 900}
WINDOW_START = pd.Timestamp("2026-04-22 00:00:00", tz="UTC")


def load_klines() -> dict:
    """Return per-asset (end_us, close) from VPS3 fresh klines."""
    print("[1] Loading binance 1m klines from VPS3 pull...")
    k = pd.read_csv(FRESH_KLINES)
    out = {}
    for asset in ASSETS:
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = k[k["symbol_id"] == sym].drop_duplicates("time_period_start_us") \
                                       .sort_values("time_period_start_us")
        end_us = sub["time_period_start_us"].values.astype("int64") + 60_000_000
        close  = sub["price_close"].values.astype("float64")
        out[asset] = (end_us, close)
        t_min = pd.Timestamp(end_us[0] / 1e6, unit="s", tz="UTC")
        t_max = pd.Timestamp(end_us[-1] / 1e6, unit="s", tz="UTC")
        print(f"    {asset}: {len(close):,} bars  {t_min} → {t_max}")
    return out


def load_universe() -> pd.DataFrame:
    print("[2] Loading canonical resolutions (chainlink outcomes)...")
    r = load_resolutions()
    r["slot_start_s"] = (r["slot_start_us"] / 1_000_000).astype("int64")
    r["slot_end_s"]   = (r["slot_end_us"]   / 1_000_000).astype("int64")
    r["slot_start_ts"] = pd.to_datetime(r["slot_start_us"], unit="us", utc=True)
    r = r[r["slot_start_ts"] >= WINDOW_START].copy()
    r["asset"] = r["ticker"].str.upper()
    r = r[r["asset"].isin(ASSETS)].copy()
    r["tf"] = r["timeframe"]
    r = r[r["tf"].isin(["5m", "15m"])].copy()
    r["window_s"] = r["tf"].map(TIMEFRAMES)
    r["ws_s"] = r["slot_start_s"] - r["window_s"]
    print(f"    {len(r):,} slugs in window {WINDOW_START} → {r['slot_start_ts'].max()}")
    print(f"    breakdown: {r.groupby(['asset','tf']).size().to_dict()}")
    return r


def close_at(end_us: np.ndarray, close: np.ndarray, target_us: int) -> float:
    """asof close: returns price of bar that ENDED at-or-before target_us."""
    i = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if i < 0 or i >= len(close):
        return float("nan")
    return float(close[i])


def compute_returns(r: pd.DataFrame, kcache: dict) -> pd.DataFrame:
    """Per-slug compute: ret_2m_v1, ret_2m_v2, ret_window."""
    print("[3] Computing ret per strategy per slug...")
    n = len(r)
    ret_v1 = np.full(n, np.nan)
    ret_v2 = np.full(n, np.nan)
    ret_w  = np.full(n, np.nan)
    for i, row in enumerate(r.itertuples(index=False)):
        end_us, c = kcache[row.asset]
        ws_us = int(row.ws_s) * 1_000_000
        # v1: log(close@ws+120 / close@ws)
        c0 = close_at(end_us, c, ws_us)
        c120 = close_at(end_us, c, ws_us + 120_000_000)
        if np.isfinite(c0) and np.isfinite(c120) and c0 > 0:
            ret_v1[i] = np.log(c120 / c0)
        # v2: log(close@ws+60 / close@ws-60)
        cm60 = close_at(end_us, c, ws_us - 60_000_000)
        c60  = close_at(end_us, c, ws_us + 60_000_000)
        if np.isfinite(cm60) and np.isfinite(c60) and cm60 > 0:
            ret_v2[i] = np.log(c60 / cm60)
        # sniper: log(close@slot_start / close@(slot_start - window_s))
        slot_us = int(row.slot_start_s) * 1_000_000
        cs = close_at(end_us, c, slot_us)
        csb = close_at(end_us, c, slot_us - int(row.window_s) * 1_000_000)
        if np.isfinite(cs) and np.isfinite(csb) and csb > 0:
            ret_w[i] = np.log(cs / csb)
        if (i+1) % 5000 == 0:
            print(f"    {i+1:,}/{n:,}")
    r = r.copy()
    r["ret_v1"] = ret_v1
    r["ret_v2"] = ret_v2
    r["ret_w"]  = ret_w
    return r


def add_thresholds(r: pd.DataFrame) -> pd.DataFrame:
    """For each (asset, tf), compute rolling q90/q80 |ret| from prior 14d."""
    print("[4] Computing q90 thresholds per (asset, tf)...")
    r = r.sort_values("slot_start_s").reset_index(drop=True).copy()
    r["thr_v1"] = np.nan
    r["thr_v2"] = np.nan
    r["thr_w"]  = np.nan
    LOOKBACK_S = 14 * 86400
    for (asset, tf), idxs in r.groupby(["asset", "tf"]).groups.items():
        sub = r.loc[idxs].copy()
        # q is q90 for 5m, q80 for 15m (per Updown5m spec)
        q_w = 0.90 if tf == "5m" else 0.80
        abs_v1 = np.abs(sub["ret_v1"].values)
        abs_v2 = np.abs(sub["ret_v2"].values)
        abs_w  = np.abs(sub["ret_w"].values)
        ss = sub["slot_start_s"].values
        thr_v1 = np.full(len(sub), np.nan)
        thr_v2 = np.full(len(sub), np.nan)
        thr_w  = np.full(len(sub), np.nan)
        for j in range(len(sub)):
            t_now = ss[j]
            mask = (ss >= t_now - LOOKBACK_S) & (ss < t_now)
            if mask.sum() < 50:
                continue
            valid_v1 = abs_v1[mask][~np.isnan(abs_v1[mask])]
            valid_v2 = abs_v2[mask][~np.isnan(abs_v2[mask])]
            valid_w  = abs_w[mask][~np.isnan(abs_w[mask])]
            if len(valid_v1) >= 50:
                thr_v1[j] = float(np.quantile(valid_v1, 0.90))
            if len(valid_v2) >= 50:
                thr_v2[j] = float(np.quantile(valid_v2, 0.90))
            if len(valid_w) >= 50:
                thr_w[j] = float(np.quantile(valid_w, q_w))
        r.loc[idxs, "thr_v1"] = thr_v1
        r.loc[idxs, "thr_v2"] = thr_v2
        r.loc[idxs, "thr_w"]  = thr_w
        print(f"    {asset} {tf}: warmup-skipped={np.isnan(thr_v1).sum()}, gated_v1={(abs_v1>=thr_v1).sum()}")
    return r


def fire_table(r: pd.DataFrame, strategy: str) -> pd.DataFrame:
    """For each strategy, return fires with (signal, outcome) and PnL approximation."""
    if strategy == "momo_v1":
        rcol, tcol = "ret_v1", "thr_v1"
    elif strategy == "momo_v2":
        rcol, tcol = "ret_v2", "thr_v2"
    elif strategy == "sniper":
        rcol, tcol = "ret_w",  "thr_w"
    else:
        raise ValueError(strategy)
    fires = r[(r[rcol].notna()) & (r[tcol].notna()) &
              (r[rcol].abs() >= r[tcol])].copy()
    fires["signal"] = np.where(fires[rcol] > 0, "UP", "DOWN")
    fires["won"] = (
        ((fires["signal"] == "UP") & (fires["outcome"] == "Up")) |
        ((fires["signal"] == "DOWN") & (fires["outcome"] == "Down"))
    )
    fires["strategy"] = strategy
    fires["cell"] = fires["asset"].str.lower() + "_" + fires["tf"]
    return fires[["cell","asset","tf","slot_start_s","ws_s","signal","outcome","won","strategy",rcol,tcol]] \
            .rename(columns={rcol: "ret", tcol: "thr"})


def main():
    kcache = load_klines()
    r = load_universe()
    r = compute_returns(r, kcache)
    r = add_thresholds(r)
    r.to_csv(OUT_DIR / "universe_with_rets.csv", index=False)

    print("\n[5] Per-strategy fire tables...")
    all_fires = []
    for strat in ("momo_v1", "momo_v2", "sniper"):
        f = fire_table(r, strat)
        print(f"\n=== {strat}: {len(f):,} fires ===")
        agg = f.groupby("cell").agg(
            n=("won", "size"),
            wins=("won", "sum"),
            wr=("won", "mean"),
        ).round({"wr": 4})
        agg["wr"] = (agg["wr"]*100).round(2)
        print(agg.to_string())
        all_fires.append(f)
        # Signal × outcome cross-tab per cell
        for cell, g in f.groupby("cell"):
            ct = pd.crosstab(g["signal"], g["outcome"], margins=True)
            print(f"\n   {cell}:\n{ct}")
            # Inversion check
            clean = g[g["outcome"].isin(["Up","Down"])]
            if len(clean):
                inv = (((clean["signal"]=="UP") & (clean["outcome"]=="Down")) |
                       ((clean["signal"]=="DOWN") & (clean["outcome"]=="Up")))
                print(f"   {cell}: orig WR={clean.won.mean()*100:.2f}% inv WR={inv.mean()*100:.2f}%")

    out = pd.concat(all_fires, ignore_index=True)
    out.to_csv(OUT_DIR / "all_fires.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'all_fires.csv'}  ({len(out):,} rows)")


if __name__ == "__main__":
    main()
