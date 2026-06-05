"""
Comprehensive per-fire cache for the autonomous scalp/hedge/physics sweep (2026-06-03).
Builds ONE parquet with, per lag-taker fire (10Hz L25, 85ms latency):
  - entry fill (re-filled at 10Hz), shares, won
  - HELD-token bid exit path: bid_vwap at {30,45,60,75,90,120,150,180}s + path max/min + TP cross times
  - OPPOSITE-token ask path: ask_vwap at {30,60,90}s + path min  (for buy-opposite hedge)
  - PHYSICS vol-regime features at fire_us: speed_abs, dist_abs, speed_away, d_speed, cross, margin, bucket
Then the sweep script reads this cache (fast, no re-load).
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from engine_v2 import LiveMimicConfig, find_book_strict, fill_at_book, sell_at_bid_partial, book_walk_fill  # noqa
from load import load_orderbook_l25_streaming, load_chainlink_asof, load_resolutions  # noqa
sys.path.insert(0, str(ROOT / "strategy_lab" / "physics"))
from physics_signal import physics_at, speed_bucket  # noqa

FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
OUT = ROOT / "strategy_lab" / "directional" / "_results" / "scalp_hedge_physics_cache_2026_06_03.parquet"
cfg = LiveMimicConfig(); LAT = 85_000; NOTIONAL = 25.0; SPREAD = 0.05
WIN = {"5m": 300, "15m": 900}
EXIT_DTS = [30, 45, 60, 75, 90, 120, 150, 180]
OPP_DTS = [30, 60, 90]
TP = [0.60, 0.65, 0.70, 0.75]
BATCH = 350

OTHER = {"Up": "Down", "Down": "Up"}

def bid_vwap_at(books, slug, tok, ts_us, shares, cfg):
    bk = find_book_strict(books, slug, tok, int(ts_us) + LAT, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None: return np.nan
    bp, bs = bk.get("bp"), bk.get("bsz")
    if bp is None or not len(bp): return np.nan
    vw, fsh, _ = sell_at_bid_partial(np.asarray(bp, float), np.asarray(bs, float), shares)
    return vw if fsh > 0 else np.nan

def ask_vwap_at(books, slug, tok, ts_us, notional, cfg):
    bk = find_book_strict(books, slug, tok, int(ts_us) + LAT, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None: return np.nan
    ap, asz = bk.get("ap"), bk.get("asz")
    if ap is None or not len(ap): return np.nan
    vw, sh, usd, lv, under = book_walk_fill([float(x) for x in ap], [float(x) for x in asz], notional, side="buy")
    return vw if sh > 0 else np.nan

def path_scan_bid(books, slug, tok, t0, t1, shares, step_us=2_000_000):
    """Scan held-token bid_vwap every ~2s in (t0,t1]. Returns (max_vw, t_max, ever_ge_dict)."""
    rec = books.get((slug, tok))
    if rec is None: return np.nan, np.nan, {}
    ts = rec[0]
    if not len(ts): return np.nan, np.nan, {}
    best = -1.0; tbest = np.nan; ge = {tp: np.nan for tp in TP}
    t = t0
    while t <= t1:
        vw = bid_vwap_at(books, slug, tok, t, shares, cfg)
        if math.isfinite(vw):
            if vw > best: best, tbest = vw, t
            for tp in TP:
                if math.isnan(ge[tp]) and vw >= tp: ge[tp] = (t - t0) / 1e6
        t += step_us
    return (best if best >= 0 else np.nan), tbest, ge

# ---- load fires + resolutions + chainlink ----
df = pd.read_parquet(FIRES)
print(f"fires={len(df)}  assets={df.asset.value_counts().to_dict()}", flush=True)
res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
res = res.drop_duplicates("slug").set_index("slug")
cl = {a: tuple(np.asarray(x) for x in load_chainlink_asof(a)) for a in ["BTC", "ETH", "SOL"]}

# slot_end + strike per fire
def slot_end_us(r):
    return int((int(r.slot_start) + WIN[r.tf]) * 1_000_000)

rows = []
for asset in ["BTC", "ETH", "SOL"]:
    sub = df[df.asset == asset].reset_index(drop=True)
    if not len(sub): continue
    slugs_all = sorted(sub.slug.unique())
    ts_cl, px_cl = cl[asset]
    print(f"[{asset}] {len(sub)} fires {len(slugs_all)} slugs", flush=True)
    for b0 in range(0, len(slugs_all), BATCH):
        bs = set(slugs_all[b0:b0 + BATCH])
        bsub = sub[sub.slug.isin(bs)]
        tmin = int(bsub.fire_us.min()) - 5_000_000
        tmax = int(bsub.fire_us.max()) + WIN["15m"] * 1_000_000 + 5_000_000
        books = load_orderbook_l25_streaming(asset.lower(), slugs=bs, subsample_1hz=False,
                                             min_ts_us=tmin, max_ts_us=tmax)
        for r in bsub.itertuples():
            tok = "Up" if str(r.direction).upper().startswith("U") else "Down"
            f = fill_at_book(books, r.slug, tok, int(r.fire_us), cfg=cfg, spread_filter=SPREAD, notional_usd=NOTIONAL)
            if f is None:
                rows.append(dict(slug=r.slug, asset=asset, tf=r.tf, fire_us=int(r.fire_us), won=bool(r.won),
                                 delta_bps=float(r.delta_bps), orig_vwap=float(r.entry_vwap), filled=False))
                continue
            ev, sh = f["vwap"], f["shares"]
            send = slot_end_us(r)
            rec = dict(slug=r.slug, asset=asset, tf=r.tf, fire_us=int(r.fire_us), won=bool(r.won),
                       delta_bps=float(r.delta_bps), orig_vwap=float(r.entry_vwap), filled=True,
                       entry_vwap=ev, shares=sh)
            for dt in EXIT_DTS:
                rec[f"bid_{dt}"] = bid_vwap_at(books, r.slug, tok, int(r.fire_us) + dt * 1_000_000, sh, cfg)
            for dt in OPP_DTS:
                rec[f"oppask_{dt}"] = ask_vwap_at(books, r.slug, OTHER[tok], int(r.fire_us) + dt * 1_000_000, NOTIONAL, cfg)
            mx, tmx, ge = path_scan_bid(books, r.slug, tok, int(r.fire_us) + 10_000_000, send, sh)
            rec["bid_pathmax"] = mx
            rec["bid_pathmax_dt"] = (tmx - int(r.fire_us)) / 1e6 if isinstance(tmx, float) and math.isfinite(tmx) else np.nan
            for tp in TP:
                rec[f"tp_hit_{int(tp*100)}_dt"] = ge.get(tp, np.nan)
            # opposite path min ask (cheapest hedge)
            recopp = books.get((r.slug, OTHER[tok]))
            if recopp is not None and len(recopp[0]):
                tsl = recopp[0]
                mask = (tsl >= int(r.fire_us)) & (tsl <= send)
                if mask.any():
                    a0 = recopp[1][mask][:, 0]
                    a0 = a0[np.isfinite(a0)]
                    rec["opp_ask_min"] = float(a0.min()) if len(a0) else np.nan
            # physics (anchored at fire_us, which already encodes ws_s+offset)
            try:
                strike = float(res.loc[r.slug, "strike_price"]) if r.slug in res.index else np.nan
                if math.isfinite(strike):
                    pa = physics_at(ts_cl, px_cl, strike, int(r.fire_us), send, speed_win_s=60)
                    pap = physics_at(ts_cl, px_cl, strike, int(r.fire_us) - 30_000_000, send, speed_win_s=60)
                    rec.update(phys_speed_abs=pa["speed_abs"], phys_dist_abs=pa["dist_abs"],
                               phys_speed_away=pa["speed_away"], phys_cross=pa["cross"], phys_margin=pa["margin"],
                               phys_have_m=pa["have_m"], phys_d_speed=pa["speed"] - pap["speed"],
                               phys_bucket=speed_bucket(pa["speed_abs"]))
            except Exception:
                pass
            rows.append(rec)
        del books
        print(f"   [{asset}] batch {b0//BATCH} done, rows={len(rows)}", flush=True)

out = pd.DataFrame(rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(OUT, index=False)
print(f"\nwrote {OUT}  n={len(out)} filled={int(out.filled.sum())}", flush=True)
