"""Task 3 re-run with CORRECT F7-off filter (f7_mode == 'off')."""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines_1s, load_orderbook_l25_streaming, load_trades

fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
# CORRECT FILTER: f7_mode == 'off' AND tf == '5m'
f7off = fills[(fills.f7_mode == "off") & (fills.tf == "5m")]
print(f"F7-off 5m fires: {len(f7off)}")
print(f"  per-asset:")
print(f7off.groupby("asset").size().to_string())

results = {}
for asset in ("BTC", "ETH", "SOL"):
    sub = f7off[f7off.asset == asset].copy()
    n = len(sub)
    if n == 0:
        continue
    if n > 1500:
        sub = sub.sample(1500, random_state=42)
    print(f"\n== {asset} (n_fires={n}, sampled={len(sub)}) ==")

    # (a) 1s kline coverage
    klines = load_klines_1s(asset)
    ts_k = klines.time_period_start_us.values.astype("int64")
    fire = sub.fire_us.values.astype("int64")
    lo = fire - 300_000_000
    hi = fire + 300_000_000
    lo_idx = np.searchsorted(ts_k, lo, side="left")
    hi_idx = np.searchsorted(ts_k, hi, side="right")
    cnt = hi_idx - lo_idx
    a_pct = (cnt >= 1).mean() * 100
    a_dense = (cnt >= 500).mean() * 100
    print(f"  (a) 1s kline any-in [fire-300s, fire+300s]: {a_pct:.1f}%  >=500 samples: {a_dense:.1f}%  median_n={int(np.median(cnt))}")
    del klines, ts_k; gc.collect()

    # (b) L25 book coverage
    unique_sl = sub.slug.drop_duplicates()
    if len(unique_sl) > 300:
        unique_sl = unique_sl.sample(300, random_state=42).tolist()
    else:
        unique_sl = unique_sl.tolist()
    t0 = time.time()
    books = load_orderbook_l25_streaming(asset, slugs=set(unique_sl), subsample_1hz=True)
    print(f"  (L25 load {time.time()-t0:.1f}s, {len(books)} (slug,oc) entries)")
    have = 0
    for sl in unique_sl:
        slot_start = int(sl.rsplit("-", 1)[1])
        fire_us = (slot_start - 300 + 120) * 1_000_000
        slot_end_us = (slot_start + 300) * 1_000_000
        for oc in ("Up", "Down"):
            if (sl, oc) in books:
                ts = books[(sl, oc)][0]
                if ((ts >= fire_us) & (ts <= slot_end_us)).any():
                    have += 1
                    break
    b_pct = have / len(unique_sl) * 100
    print(f"  (b) L25 any-sample in [fire_us, slot_end]: {b_pct:.1f}% (of {len(unique_sl)} slugs)")
    del books; gc.collect()

    # (c) trades
    try:
        trades = load_trades(asset)
        if "slug" in trades.columns:
            slugs_with_trades = set(trades.slug.unique().tolist())
            covered = sum(1 for sl in unique_sl if sl in slugs_with_trades)
            c_pct = covered / len(unique_sl) * 100
            # Joint: kline + L25 + trades (per slug subset for L25/trades and per fire for kline)
            # For joint over fires: have_kline(per fire) & per-slug has_book & has_trade
            slug_has_book = {sl for sl in unique_sl}  # we already got 100% L25 above; reuse
            # Actually let's compute joint per fire: kline_ok AND (slug has trade)
            slug_in_trade = sub.slug.isin(slugs_with_trades).values
            kline_ok = cnt >= 1
            joint = (kline_ok & slug_in_trade).mean() * 100  # assume L25=100%
            print(f"  (c) trades for slug: {c_pct:.1f}%  joint(kline+trades, L25=100%): {joint:.1f}%")
            results[asset] = dict(n=n, kline=a_pct, l25=b_pct, trades=c_pct, joint=joint)
        else:
            print(f"  trades cols: {list(trades.columns)[:15]}")
            results[asset] = dict(n=n, kline=a_pct, l25=b_pct, trades=None, joint=None)
        del trades; gc.collect()
    except FileNotFoundError as e:
        print(f"  (c) trades unavailable: {e}")
        results[asset] = dict(n=n, kline=a_pct, l25=b_pct, trades=None, joint=None)

print("\n== SUMMARY ==")
for a, d in results.items():
    print(f"  {a}: {d}")
