"""TASK 8 — Walk-forward validation of top gate × sleeve combos.

Split: train Apr 30 → May 14 (15d), test May 15 → May 22 (7d, but actually limited
to May 16 ~07 because alt-venues end then).

For each (sleeve, gate) in the top-10 from the gate_overlay table:
  - Compute IS mean/WR/n on train
  - Compute OOS mean/WR/n on test
  - PASS if OOS mean > 0 AND OOS WR > IS WR - 5pp.
"""
from __future__ import annotations
import sys
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_trades, load_klines, load_okx_klines, load_hyperliquid_liquidations

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"
PT_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"

# Train / OOS split timestamps (epoch seconds)
# alt-venues end ~May 16 07:00 — so OOS is May 14 → May 16 07 (a tight 2 days)
TRAIN_END_S = int(pd.Timestamp("2026-05-13 00:00", tz="UTC").timestamp())
OOS_START_S = TRAIN_END_S
OOS_END_S   = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").timestamp())  # alt-venue cutoff
WIN_START_S = int(pd.Timestamp("2026-04-30", tz="UTC").timestamp())

SLEEVES = [
    ("S1", "Baseline_v1",                "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive),
    ("S2", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive),
    ("S3", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.f7  & d.mpass_w20_1m_voladaptive),
    ("S5", "Baseline_v2",                "ETH", "5m",  lambda d: d.f7  & d.mpass_w20_5m_fixed),
]

TOP_GATES = [
    # (sleeve, gate_name, leader_venue, lookback_s, direction_op)
    ("S1", "g_bn_with_5s",  "bn", 5,  "with"),
    ("S1", "g_hl_with_15s", "hl", 15, "with"),
    ("S1", "g_xchg_all_with_120s", "xchg_all", 120, "with"),
    ("S1", "g_hl_with_5s",  "hl", 5,  "with"),
    ("S2", "g_kr_against_120s", "kr", 120, "against"),
    ("S2", "g_bn_against_60s", "bn", 60, "against"),
    ("S2", "g_hl_with_60s", "hl", 60, "with"),
    ("S3", "g_bn_against_60s", "bn", 60, "against"),
    ("S3", "g_hl_with_60s", "hl", 60, "with"),
    ("S5", "g_hl_with_5s",  "hl", 5,  "with"),
    ("S5", "g_hl_with_15s", "hl", 15, "with"),
    ("S5", "g_hl_with_60s", "hl", 60, "with"),
]


def asof_searchsorted(target_us, ref_us, ref_vals):
    pos = np.searchsorted(ref_us, target_us, side="right") - 1
    out = np.full(len(target_us), np.nan)
    valid = pos >= 0
    out[valid] = ref_vals[pos[valid]]
    return out

def binance_1s_arr(asset):
    df = load_klines_1s(asset=asset)
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 1_000_000).astype("int64"), df.price_close.astype("float64").values

def hl_trades_per_sec(asset):
    df = load_hyperliquid_trades(asset=asset)
    cols = df.columns.tolist(); pcol = "px" if "px" in cols else "price"; qcol = "sz" if "sz" in cols else "size"
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    g = pd.DataFrame({"ts_s": ts_s, "pq": df[pcol].astype("float64").values*df[qcol].astype("float64").values, "q": df[qcol].astype("float64").values}).groupby("ts_s").agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]; g["vwap"] = g.pq / g.q
    return (g.index.values * 1_000_000 + 1_000_000).astype("int64"), g["vwap"].astype("float64").values

def kline_1min_arr(asset, venue):
    if venue == "coinbase":
        df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue == "kraken":
        df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue == "okx":
        df = load_okx_klines(asset=asset, period_id="1MIN")
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 60_000_000).astype("int64"), df.price_close.astype("float64").values

def add_direction_cols(sub: pd.DataFrame, asset: str) -> pd.DataFrame:
    fire_us = (sub.fire_s.values * 1_000_000).astype("int64")
    bn_end, bn_px = binance_1s_arr(asset)
    hl_end, hl_px = hl_trades_per_sec(asset)
    cb_end, cb_px = kline_1min_arr(asset, "coinbase")
    kr_end, kr_px = kline_1min_arr(asset, "kraken")
    ok_end, ok_px = kline_1min_arr(asset, "okx")

    def ret(ref_end, ref_px, lookback_s):
        p_now = asof_searchsorted(fire_us - 1, ref_end, ref_px)
        p_old = asof_searchsorted(fire_us - lookback_s*1_000_000, ref_end, ref_px)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.log(p_now / p_old)
    sub = sub.copy()
    sub["bn_5s"]  = ret(bn_end, bn_px, 5)
    sub["bn_15s"] = ret(bn_end, bn_px, 15)
    sub["bn_60s"] = ret(bn_end, bn_px, 60)
    sub["hl_5s"]  = ret(hl_end, hl_px, 5)
    sub["hl_15s"] = ret(hl_end, hl_px, 15)
    sub["hl_60s"] = ret(hl_end, hl_px, 60)
    sub["cb_60s"] = ret(cb_end, cb_px, 60)
    sub["cb_120s"] = ret(cb_end, cb_px, 120)
    sub["kr_60s"] = ret(kr_end, kr_px, 60)
    sub["kr_120s"] = ret(kr_end, kr_px, 120)
    sub["ok_60s"] = ret(ok_end, ok_px, 60)
    sub["ok_120s"] = ret(ok_end, ok_px, 120)
    return sub

def gate_mask(sub: pd.DataFrame, venue: str, lb: int, direction: str) -> np.ndarray:
    sig = sub.signal.map({"UP": 1.0, "DOWN": -1.0}).values
    if venue == "xchg_all":
        cb = sub[f"cb_{lb}s"].values; kr = sub[f"kr_{lb}s"].values; ok = sub[f"ok_{lb}s"].values
        agree = ((np.sign(cb) == sig) & np.isfinite(cb)).astype(int) + \
                ((np.sign(kr) == sig) & np.isfinite(kr)).astype(int) + \
                ((np.sign(ok) == sig) & np.isfinite(ok)).astype(int)
        return agree >= 3
    r = sub[f"{venue}_{lb}s"].values
    if direction == "with":
        return (np.sign(r) == sig) & np.isfinite(r)
    else:
        return (np.sign(r) == -sig) & np.isfinite(r)

def stats(arr_pnl: np.ndarray, won: np.ndarray) -> dict:
    n = len(arr_pnl)
    if n == 0: return {"n": 0, "wr": None, "mean_pnl": None, "sum_pnl": 0.0}
    return {"n": int(n), "wr": float(won.mean()), "mean_pnl": float(arr_pnl.mean()), "sum_pnl": float(arr_pnl.sum())}

def main():
    pt = pd.read_parquet(PT_PATH)
    pt = pt[(pt.fire_s >= WIN_START_S) & (pt.fire_s <= OOS_END_S)]
    print(f"per-trade markov restricted: {len(pt):,}", flush=True)

    out_rows = []
    for sid, variant, asset, tf, fn in SLEEVES:
        g = pt[(pt.variant == variant) & (pt.asset == asset) & (pt.tf == tf)].copy()
        sub = g[fn(g)].sort_values("fire_s").reset_index(drop=True)
        if len(sub) < 30: continue
        sub = add_direction_cols(sub, asset)

        # IS / OOS split
        is_mask  = sub.fire_s.values < TRAIN_END_S
        oos_mask = sub.fire_s.values >= OOS_START_S
        is_sub = sub.loc[is_mask].copy()
        oos_sub = sub.loc[oos_mask].copy()

        # Base stats per split
        base_is  = stats(is_sub.pnl_legacy_usd.values, is_sub.won.values)
        base_oos = stats(oos_sub.pnl_legacy_usd.values, oos_sub.won.values)
        out_rows.append({"sleeve": sid, "gate": "BASE",
                         "is_n": base_is["n"], "is_wr": base_is["wr"], "is_mean": base_is["mean_pnl"], "is_sum": base_is["sum_pnl"],
                         "oos_n": base_oos["n"], "oos_wr": base_oos["wr"], "oos_mean": base_oos["mean_pnl"], "oos_sum": base_oos["sum_pnl"]})

        for (s_id, gname, venue, lb, direction) in TOP_GATES:
            if s_id != sid: continue
            m_all = gate_mask(sub, venue, lb, direction)
            # apply IS / OOS
            m_is  = m_all & is_mask
            m_oos = m_all & oos_mask
            st_is  = stats(sub.loc[m_is].pnl_legacy_usd.values,  sub.loc[m_is].won.values)
            st_oos = stats(sub.loc[m_oos].pnl_legacy_usd.values, sub.loc[m_oos].won.values)
            passes = (st_oos["mean_pnl"] is not None and st_oos["mean_pnl"] > 0
                       and st_is["mean_pnl"] is not None and st_oos["mean_pnl"] > st_is["mean_pnl"] - 5
                       and st_oos["n"] >= 5)
            out_rows.append({"sleeve": sid, "gate": gname,
                             "is_n": st_is["n"], "is_wr": st_is["wr"], "is_mean": st_is["mean_pnl"], "is_sum": st_is["sum_pnl"],
                             "oos_n": st_oos["n"], "oos_wr": st_oos["wr"], "oos_mean": st_oos["mean_pnl"], "oos_sum": st_oos["sum_pnl"],
                             "PASS": passes})

    res = pd.DataFrame(out_rows)
    res.to_csv(OUT_DIR / "_walkforward.csv", index=False)
    print(res.to_string(index=False))
    print(f"\nWrote {OUT_DIR / '_walkforward.csv'}")

main()
