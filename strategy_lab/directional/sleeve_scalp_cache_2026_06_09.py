"""Per-fire scalp cache for PROFITABLE shadow sniper_v5 sleeves (2026-06-09).
For each sleeve fire: re-fill entry at 10Hz L25 (buy signaled side, $25, LiveMimic),
record HELD-token bid_vwap path at {15,30,45,60,90,120,150,180}s + bid_pathmax,
and won. Downstream sweep: does book-exit at +Δ keep the sleeve's directional edge
(scalp) or is it priced-in (hold>scalp)?

Input : strategy_lab/directional/_sleeve_fires_raw.csv  (no header)
Output: strategy_lab/directional/_results/sleeve_scalp_cache_2026_06_09.parquet
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from engine_v2 import LiveMimicConfig, find_book_strict, fill_at_book, sell_at_bid_partial  # noqa
from load import load_orderbook_l25_streaming  # noqa

CSV = ROOT / "strategy_lab" / "directional" / "_sleeve_fires_raw.csv"
OUT = ROOT / "strategy_lab" / "directional" / "_results" / "sleeve_scalp_cache_2026_06_09.parquet"
cfg = LiveMimicConfig(); LAT = 85_000; NOTIONAL = 25.0; SPREAD = 0.05
WIN = {"5m": 300, "15m": 900}
EXIT_DTS = [15, 30, 45, 60, 90, 120, 150, 180]
BATCH = 300
COLS = ["sleeve_id", "slug", "tf", "fire_us", "slot_start", "dir", "won", "ev_live"]

def bid_vwap_at(books, slug, tok, ts_us, shares):
    bk = find_book_strict(books, slug, tok, int(ts_us) + LAT, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None: return np.nan
    bp, bs = bk.get("bp"), bk.get("bsz")
    if bp is None or not len(bp): return np.nan
    vw, fsh, _ = sell_at_bid_partial(np.asarray(bp, float), np.asarray(bs, float), shares)
    return vw if fsh > 0 else np.nan

def path_max_bid(books, slug, tok, t0, t1, shares, step_us=2_000_000):
    best = -1.0; t = t0
    while t <= t1:
        vw = bid_vwap_at(books, slug, tok, t, shares)
        if math.isfinite(vw) and vw > best: best = vw
        t += step_us
    return best if best >= 0 else np.nan

df = pd.read_csv(CSV, sep="|", names=COLS, header=None)
df["won"] = df["won"].astype(str).str.strip().isin(["t", "true", "True"])
df["asset"] = df["slug"].str.split("-").str[0].str.upper()
df["fire_us"] = df["fire_us"].astype("int64")
df["slot_start"] = df["slot_start"].astype("int64")
print(f"fires={len(df)}  assets={df.asset.value_counts().to_dict()}", flush=True)

rows = []
for asset in ["BTC", "ETH", "SOL"]:
    sub = df[df.asset == asset].reset_index(drop=True)
    if not len(sub): continue
    slugs_all = sorted(sub.slug.unique())
    print(f"[{asset}] {len(sub)} fires {len(slugs_all)} slugs", flush=True)
    for b0 in range(0, len(slugs_all), BATCH):
        bs = set(slugs_all[b0:b0 + BATCH])
        bsub = sub[sub.slug.isin(bs)]
        tmin = int(bsub.fire_us.min()) - 5_000_000
        tmax = int(bsub.fire_us.max()) + WIN["15m"] * 1_000_000 + 5_000_000
        try:
            books = load_orderbook_l25_streaming(asset.lower(), slugs=bs, subsample_1hz=False,
                                                 min_ts_us=tmin, max_ts_us=tmax)
        except Exception as e:
            print(f"   [{asset}] batch {b0//BATCH} LOAD FAIL {e}", flush=True); continue
        for r in bsub.itertuples():
            tok = "Up" if str(r.dir).upper().startswith("U") else "Down"
            send = int((int(r.slot_start) + WIN[r.tf]) * 1_000_000)
            f = fill_at_book(books, r.slug, tok, int(r.fire_us), cfg=cfg, spread_filter=SPREAD, notional_usd=NOTIONAL)
            base = dict(sleeve_id=r.sleeve_id, slug=r.slug, asset=asset, tf=r.tf,
                        fire_us=int(r.fire_us), won=bool(r.won), ev_live=float(r.ev_live))
            if f is None:
                base["filled"] = False; rows.append(base); continue
            ev, sh = f["vwap"], f["shares"]
            base.update(filled=True, entry_vwap=ev, shares=sh)
            for dt in EXIT_DTS:
                base[f"bid_{dt}"] = bid_vwap_at(books, r.slug, tok, int(r.fire_us) + dt * 1_000_000, sh)
            base["bid_pathmax"] = path_max_bid(books, r.slug, tok, int(r.fire_us) + 10_000_000, send, sh)
            base["secs_to_slotend"] = (send - int(r.fire_us)) / 1e6
            rows.append(base)
        del books
        print(f"   [{asset}] batch {b0//BATCH} done rows={len(rows)}", flush=True)

out = pd.DataFrame(rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(OUT, index=False)
print(f"\nwrote {OUT}  n={len(out)} filled={int(out.get('filled', pd.Series([],dtype=bool)).sum())}", flush=True)
