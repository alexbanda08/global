"""Walk-forward validation including basis gates."""
from __future__ import annotations
import sys
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_trades, load_klines, load_okx_klines

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"
PT_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"

TRAIN_END_S = int(pd.Timestamp("2026-05-13 00:00", tz="UTC").timestamp())
OOS_END_S   = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").timestamp())
WIN_START_S = int(pd.Timestamp("2026-04-30", tz="UTC").timestamp())

SLEEVES = [
    ("S1", "Baseline_v1",                "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive),
    ("S2", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive),
    ("S3", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.f7  & d.mpass_w20_1m_voladaptive),
    ("S5", "Baseline_v2",                "ETH", "5m",  lambda d: d.f7  & d.mpass_w20_5m_fixed),
]

def asof_searchsorted(target_us, ref_us, ref_vals):
    pos = np.searchsorted(ref_us, target_us, side="right") - 1
    out = np.full(len(target_us), np.nan)
    valid = pos >= 0; out[valid] = ref_vals[pos[valid]]
    return out

def binance_1s_arr(asset):
    df = load_klines_1s(asset=asset)
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 1_000_000).astype("int64"), df.price_close.astype("float64").values

def hl_1s_arr(asset):
    df = load_hyperliquid_trades(asset=asset)
    cols = df.columns.tolist(); pcol = "px" if "px" in cols else "price"; qcol = "sz" if "sz" in cols else "size"
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    g = pd.DataFrame({"ts_s": ts_s, "pq": df[pcol].astype("float64").values*df[qcol].astype("float64").values, "q": df[qcol].astype("float64").values}).groupby("ts_s").agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]; g["vwap"] = g.pq / g.q
    return (g.index.values * 1_000_000 + 1_000_000).astype("int64"), g["vwap"].astype("float64").values

def venue_arr(asset, venue):
    if venue == "hyperliquid": return hl_1s_arr(asset)
    if venue == "coinbase": df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue == "kraken": df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue == "okx": df = load_okx_klines(asset=asset, period_id="1MIN")
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 60_000_000).astype("int64"), df.price_close.astype("float64").values

def add_basis(sub, asset):
    fire_us = (sub.fire_s.values * 1_000_000).astype("int64")
    bn_end, bn_px = binance_1s_arr(asset)
    p_bn = asof_searchsorted(fire_us - 1, bn_end, bn_px)
    sub = sub.copy(); sub["bn_p"] = p_bn
    for v in ["coinbase","kraken","okx","hyperliquid"]:
        e, p = venue_arr(asset, v)
        p_v = asof_searchsorted(fire_us - 1, e, p)
        with np.errstate(invalid="ignore", divide="ignore"):
            sub[f"basis_{v}"] = np.log(p_v / p_bn)
    return sub

def basis_gate_mask(sub, venue, kind, q_lo, q_hi):
    """kind ∈ {'against','with'}.
    Quantiles passed in — fit on IS only to avoid lookahead."""
    sig = sub.signal.map({"UP":1.0,"DOWN":-1.0}).values
    b = sub[f"basis_{venue}"].values
    valid = np.isfinite(b)
    extreme_pos = b > q_hi
    extreme_neg = b < q_lo
    if kind == "against":
        mask = ((extreme_pos & (sig < 0)) | (extreme_neg & (sig > 0))) & valid
    else:
        mask = ((extreme_pos & (sig > 0)) | (extreme_neg & (sig < 0))) & valid
    return mask

def stats(arr, won):
    if len(arr) == 0: return {"n":0,"wr":None,"mean":None,"sum":0.0}
    return {"n": int(len(arr)), "wr": float(won.mean()), "mean": float(arr.mean()), "sum": float(arr.sum())}

def main():
    pt = pd.read_parquet(PT_PATH)
    pt = pt[(pt.fire_s >= WIN_START_S) & (pt.fire_s <= OOS_END_S)]
    out = []
    for sid, variant, asset, tf, fn in SLEEVES:
        g = pt[(pt.variant == variant) & (pt.asset == asset) & (pt.tf == tf)].copy()
        sub = g[fn(g)].sort_values("fire_s").reset_index(drop=True)
        if len(sub) < 30: continue
        sub = add_basis(sub, asset)
        is_mask = sub.fire_s.values < TRAIN_END_S
        oos_mask = sub.fire_s.values >= TRAIN_END_S

        for venue in ["coinbase","kraken","okx","hyperliquid"]:
            b = sub[f"basis_{venue}"].values
            # Fit q30/q70 on IS data only
            b_is = b[is_mask & np.isfinite(b)]
            if len(b_is) < 30: continue
            q_lo, q_hi = np.nanquantile(b_is, [0.3, 0.7])
            for kind in ["against","with"]:
                m_all = basis_gate_mask(sub, venue, kind, q_lo, q_hi)
                m_is = m_all & is_mask
                m_oos = m_all & oos_mask
                st_is = stats(sub.loc[m_is].pnl_legacy_usd.values, sub.loc[m_is].won.values)
                st_oos = stats(sub.loc[m_oos].pnl_legacy_usd.values, sub.loc[m_oos].won.values)
                passes = (st_is.get("mean") is not None and st_oos.get("mean") is not None
                           and st_oos["mean"] > 0 and st_oos["n"] >= 5
                           and st_oos["mean"] > st_is["mean"] - 5)
                out.append({"sleeve": sid, "venue": venue, "kind": kind,
                             **{f"is_{k}": v for k,v in st_is.items()},
                             **{f"oos_{k}": v for k,v in st_oos.items()},
                             "PASS": passes,
                             "q_lo": q_lo, "q_hi": q_hi})

    res = pd.DataFrame(out)
    res.to_csv(OUT_DIR / "_walkforward_basis.csv", index=False)
    # Show all
    print("\n=== WF basis gates ===")
    print(res.to_string(index=False))
    n_pass = res.PASS.sum()
    print(f"\nPASS count: {n_pass} / {len(res)}")

main()
