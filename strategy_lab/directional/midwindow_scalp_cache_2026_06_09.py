"""Universal BEGIN/MID-window lag-rebound scalp cache (2026-06-09).
Generalizes the proven +5s oracle-lag scalp to mid-window offsets.

For each BTC/ETH 5m+15m slug, at offsets {begin,mid}:
  entry_us = slot_start + offset
  lag_bps  = (binance(entry)/binance(entry-5s) - 1)*1e4     # rolling oracle-lag
  tok      = leading side (Up if lag>0 else Down)            # the momentarily-cheap side
  -> fill tok (buy $25, LiveMimic 10Hz), record entry_vwap/shares, bid path +{30,45,60,90},
     hold(won = outcome==tok), and causal features (lag_bps, mom_30s, rv_60s, hour_utc).
Downstream gate search: |lag_bps| in band & entry_vwap<0.55 & regime -> scalp $/tr CI>0, by offset.

Out: strategy_lab/directional/_results/midwindow_scalp_cache_2026_06_09.parquet
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab")); sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from engine_v2 import LiveMimicConfig, find_book_strict, fill_at_book, sell_at_bid_partial  # noqa
from load import load_orderbook_l25_streaming, load_resolutions, load_klines_1s  # noqa

OUT = ROOT / "strategy_lab" / "directional" / "_results" / "midwindow_scalp_cache_2026_06_09.parquet"
cfg = LiveMimicConfig(); LAT = 85_000; NOTIONAL = 25.0; SPREAD = 0.05
WIN = {"5m": 300, "15m": 900}
OFFSETS = {"5m": [30, 60, 120, 180, 240], "15m": [60, 150, 300, 450, 600]}
EXIT_DTS = [30, 45, 60, 90]
BATCH = 300

def px_at(ts_arr, px_arr, t_us):
    i = int(np.searchsorted(ts_arr, t_us, side="right")) - 1
    return float(px_arr[i]) if i >= 0 else np.nan

def bid_vwap_at(books, slug, tok, ts_us, shares):
    bk = find_book_strict(books, slug, tok, int(ts_us) + LAT, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None: return np.nan
    bp, bs = bk.get("bp"), bk.get("bsz")
    if bp is None or not len(bp): return np.nan
    vw, fsh, _ = sell_at_bid_partial(np.asarray(bp, float), np.asarray(bs, float), shares)
    return vw if fsh > 0 else np.nan

# binance 1s price series per asset
KL = {}
for a in ["BTC", "ETH"]:
    k = load_klines_1s(a).sort_values("time_period_start_us")
    KL[a] = (k["time_period_start_us"].to_numpy("int64"), k["price_close"].to_numpy(float))
    print(f"[{a}] 1s bars={len(k)} {k['time_period_start_us'].min()}..{k['time_period_start_us'].max()}", flush=True)

res = load_resolutions(assets=["BTC", "ETH"], timeframes=["5m", "15m"]).dropna(subset=["slug"]).copy()
res["slot_s"] = (res["slot_start_us"] // 1_000_000).astype("int64")
res["asset"] = res["slug"].str.split("-").str[0].str.upper()
res["tf"] = res["slug"].str.extract(r"-(\d+m)-")
res = res[res.tf.isin(["5m", "15m"])].drop_duplicates("slug")
print(f"slugs={len(res)} {res.groupby(['asset','tf']).size().to_dict()}", flush=True)

rows = []
for asset in ["BTC", "ETH"]:
    ts_b, px_b = KL[asset]
    for tf in ["5m", "15m"]:
        sub = res[(res.asset == asset) & (res.tf == tf)].reset_index(drop=True)
        slugs_all = sorted(sub.slug.unique())
        print(f"[{asset} {tf}] {len(slugs_all)} slugs", flush=True)
        out_map = sub.set_index("slug")["outcome"].astype(str).to_dict()
        slot_map = sub.set_index("slug")["slot_s"].to_dict()
        for b0 in range(0, len(slugs_all), BATCH):
            bs = set(slugs_all[b0:b0 + BATCH])
            ss = [slot_map[s] for s in bs]
            tmin = min(ss) * 1_000_000 - 5_000_000
            tmax = (max(ss) + WIN[tf]) * 1_000_000 + 5_000_000
            try:
                books = load_orderbook_l25_streaming(asset.lower(), slugs=bs, subsample_1hz=False,
                                                     min_ts_us=tmin, max_ts_us=tmax)
            except Exception as e:
                print(f"   batch {b0//BATCH} LOAD FAIL {e}", flush=True); continue
            for slug in bs:
                ss0 = slot_map[slug]; send = (ss0 + WIN[tf]) * 1_000_000
                oc = out_map.get(slug, "")
                for off in OFFSETS[tf]:
                    e_us = (ss0 + off) * 1_000_000
                    pe = px_at(ts_b, px_b, e_us); p5 = px_at(ts_b, px_b, e_us - 5_000_000)
                    if not (math.isfinite(pe) and math.isfinite(p5) and p5 > 0): continue
                    lag = (pe / p5 - 1.0) * 1e4
                    tok = "Up" if lag > 0 else "Down"
                    f = fill_at_book(books, slug, tok, e_us, cfg=cfg, spread_filter=SPREAD, notional_usd=NOTIONAL)
                    if f is None: continue
                    ev, sh = f["vwap"], f["shares"]
                    p30 = px_at(ts_b, px_b, e_us - 30_000_000)
                    mom30 = (pe / p30 - 1.0) * 1e4 if (math.isfinite(p30) and p30 > 0) else np.nan
                    # rv_60s: std of 1s log-returns last 60s
                    lo = int(np.searchsorted(ts_b, e_us - 60_000_000)); hi = int(np.searchsorted(ts_b, e_us))
                    seg = px_b[lo:hi]
                    rv = float(np.std(np.diff(np.log(seg)))) * 1e4 if len(seg) > 3 else np.nan
                    rec = dict(slug=slug, asset=asset, tf=tf, offset=off, e_us=e_us,
                               lag_bps=lag, abs_lag=abs(lag), mom30=mom30, rv60=rv,
                               hour=int((e_us // 1_000_000 // 3600) % 24),
                               tok=tok, won=(oc == tok), entry_vwap=ev, shares=sh,
                               secs_to_end=(send - e_us) / 1e6)
                    for dt in EXIT_DTS:
                        rec[f"bid_{dt}"] = bid_vwap_at(books, slug, tok, e_us + dt * 1_000_000, sh)
                    rows.append(rec)
            del books
            if (b0 // BATCH) % 3 == 0:
                print(f"   [{asset} {tf}] batch {b0//BATCH} rows={len(rows)}", flush=True)

out = pd.DataFrame(rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(OUT, index=False)
print(f"\nwrote {OUT} n={len(out)} by offset:\n{out.groupby(['asset','tf','offset']).size()}", flush=True)
