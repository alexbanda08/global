"""TASK 5 — Cross-exchange basis as fire signal.

basis_X(t) = log(price_X(t)) - log(price_binance(t))

Hypothesis: extreme positive basis = X is rich = arb will sell X and buy binance
            => binance about to RISE.
Conversely extreme negative basis => binance about to FALL.

Test: at each fire_us, compute basis with each (X ∈ {coinbase,kraken,okx,hyperliquid}),
classify into terciles, and overlay as gate on the deploy sleeves.
"""
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

WIN_START_S = int(pd.Timestamp("2026-04-30", tz="UTC").timestamp())
WIN_END_S   = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").timestamp())

SLEEVES = [
    ("S1", "Baseline_v1",                "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive),
    ("S2", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive),
    ("S3", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.f7  & d.mpass_w20_1m_voladaptive),
    ("S5", "Baseline_v2",                "ETH", "5m",  lambda d: d.f7  & d.mpass_w20_5m_fixed),
]

def asof_searchsorted(target_us, ref_us, ref_vals):
    pos = np.searchsorted(ref_us, target_us, side="right") - 1
    out = np.full(len(target_us), np.nan)
    valid = pos >= 0
    out[valid] = ref_vals[pos[valid]]
    return out

def binance_arr(asset, sub_minute=False):
    if sub_minute:
        df = load_klines_1s(asset=asset)
        df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
        return (df.time_period_start_us.values + 1_000_000).astype("int64"), df.price_close.astype("float64").values
    else:
        df = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
        df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
        return (df.time_period_start_us.values + 60_000_000).astype("int64"), df.price_close.astype("float64").values

def hl_1s_arr(asset):
    df = load_hyperliquid_trades(asset=asset)
    cols = df.columns.tolist(); pcol = "px" if "px" in cols else "price"; qcol = "sz" if "sz" in cols else "size"
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    g = pd.DataFrame({"ts_s": ts_s, "pq": df[pcol].astype("float64").values*df[qcol].astype("float64").values, "q": df[qcol].astype("float64").values}).groupby("ts_s").agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]; g["vwap"] = g.pq / g.q
    return (g.index.values * 1_000_000 + 1_000_000).astype("int64"), g["vwap"].astype("float64").values

def venue_arr(asset, venue):
    if venue == "binance": return binance_arr(asset, sub_minute=False)
    if venue == "hyperliquid": return hl_1s_arr(asset)
    if venue == "coinbase":
        df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue == "kraken":
        df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue == "okx":
        df = load_okx_klines(asset=asset, period_id="1MIN")
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 60_000_000).astype("int64"), df.price_close.astype("float64").values

def add_basis_cols(sub, asset):
    fire_us = (sub.fire_s.values * 1_000_000).astype("int64")
    bn_end, bn_px = binance_arr(asset, sub_minute=True)
    p_bn = asof_searchsorted(fire_us - 1, bn_end, bn_px)
    sub = sub.copy()
    sub["bn_p"] = p_bn
    for v in ["coinbase","kraken","okx","hyperliquid"]:
        e, p = venue_arr(asset, v)
        p_v = asof_searchsorted(fire_us - 1, e, p)
        with np.errstate(invalid="ignore", divide="ignore"):
            sub[f"basis_{v}"] = np.log(p_v / p_bn)
    return sub

def stats(arr_pnl, won):
    if len(arr_pnl) == 0: return {"n":0,"wr":None,"mean":None,"sum":0.0}
    return {"n": int(len(arr_pnl)), "wr": float(won.mean()), "mean": float(arr_pnl.mean()), "sum": float(arr_pnl.sum())}

def main():
    pt = pd.read_parquet(PT_PATH)
    pt = pt[(pt.fire_s >= WIN_START_S) & (pt.fire_s <= WIN_END_S)]
    print(f"loaded {len(pt):,} fires", flush=True)

    rows = []
    for sid, variant, asset, tf, fn in SLEEVES:
        g = pt[(pt.variant == variant) & (pt.asset == asset) & (pt.tf == tf)].copy()
        sub = g[fn(g)].sort_values("fire_s").reset_index(drop=True)
        if len(sub) < 30: continue
        sub = add_basis_cols(sub, asset)
        sig = sub.signal.map({"UP":1.0,"DOWN":-1.0}).values

        # Base
        base = stats(sub.pnl_legacy_usd.values, sub.won.values)
        rows.append({"sleeve":sid,"venue":"","gate":"BASE", **base, "lift":0.0})
        print(f"\n{sid} base: n={base['n']} wr={base['wr']:.3f} mean=${base['mean']:.3f} sum=${base['sum']:.1f}")

        # For each venue, test:
        #  basis > q70 → bet UP (X is rich → arb pushes binance up)
        #  basis < q30 → bet DOWN
        #  also test the OPPOSITE (basis > q70 → bet DOWN — if X already leads)
        for v in ["coinbase","kraken","okx","hyperliquid"]:
            b = sub[f"basis_{v}"].values
            valid = np.isfinite(b)
            if valid.sum() < 30: continue
            q30, q70 = np.nanquantile(b, [0.3, 0.7])
            # Strategy A: signal-aligned basis (use basis to confirm sleeve direction)
            #   basis>0 (X rich) AND sleeve says UP → take
            mask_a_with = ((b > q70) & (sig > 0)) | ((b < q30) & (sig < 0))
            mask_a_against = ((b > q70) & (sig < 0)) | ((b < q30) & (sig > 0))
            sub_pn = sub.pnl_legacy_usd.values
            sub_w  = sub.won.values
            for label, mask in [("basis_extreme_with_sleeve", mask_a_with),
                                ("basis_extreme_against_sleeve", mask_a_against)]:
                if mask.sum() < 10: continue
                st = stats(sub_pn[mask], sub_w[mask])
                rows.append({"sleeve":sid,"venue":v,"gate":label,**st,
                             "lift": st["mean"] - base["mean"] if st["mean"] is not None else None})

    res = pd.DataFrame(rows)
    res.to_csv(OUT_DIR / "_basis_gate.csv", index=False)
    # Show top
    print("\n=== TOP basis gates (n>=15) ===")
    show = res[(res.gate!="BASE") & (res.n>=15)].sort_values("mean", ascending=False)
    print(show.to_string(index=False))

main()
