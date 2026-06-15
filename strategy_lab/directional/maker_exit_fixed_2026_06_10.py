"""
MAKER-EXIT with taker-+60 fallback — CORRECTED EXIT MODEL (2026-06-10).
Port of maker_exit_queue_2026_06_09.py (queue-aware L25 maker fill) to the corrected exit model:
  - TAKER-60 FALLBACK no longer uses outcome-as-price when bid_60 is missing: the position is HELD to
    resolution (winner-only 0.07 valuation). The taker cross is also SIZE-CAPPED at L25 best-bid depth;
    any unsold remainder is held to resolution.
  - MAKER fill (queue-fixed & peg-trail) is SIZE-CAPPED at the resting-order size we can realistically place
    (we sell min(shares, fillable); remainder taker-crossed at +60 under the same size-capped+held model).
  - Maker rebate income applies only to the maker-sold lot.
Every policy reports ALL + CLEAN(frac_held==0). Paired diff vs taker60. OLD CLAIM: maker beats taker60 +$0.42/tr CI[+0.02,+0.82].
Env: ME_LIMIT (first N slugs total, smoke).
"""
import sys, math, warnings, os
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab")); sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_l25_streaming  # noqa
from scalp_fill_lib_2026_06_10 import bpnl, held_value, boot  # noqa
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
LAT = 85_000; HOR = 60; BATCH = 300; STALE_US = 120_000_000
LIMIT = int(os.environ.get("ME_LIMIT", "0"))

c = pd.read_parquet(ROOT / "strategy_lab/directional/_results/scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[(c.asset.isin(["BTC", "ETH"])) & (c.filled == 1) & (c.entry_vwap < 0.55)].copy()
lf = pd.read_parquet(ROOT / "strategy_lab/lag_taker_fires_oos_2026_06_01.parquet")[["slug", "direction"]].drop_duplicates("slug")
c = c.merge(lf, on="slug", how="left").dropna(subset=["direction"]).sort_values("fire_us").reset_index(drop=True)
if LIMIT > 0:
    c = c.iloc[:LIMIT].reset_index(drop=True)
print(f"gated scalp fires (BTC/ETH vwap<0.55) w/ direction = {len(c)}", flush=True)

tk = lambda p: 0.07 * p * (1 - p); reb = lambda p: 0.20 * 0.07 * p * (1 - p)

# buy-trade tape per (slug,lead)
TAPE = {}
for a in ["btc", "eth"]:
    ca = c[c.asset == a.upper()]
    if not len(ca): continue
    t = pd.read_parquet(CANON / "trades_polymarket" / f"{a}.parquet",
                        columns=["slug", "outcome", "timestamp_us", "price", "size"],
                        filters=[("slug", "in", set(ca.slug)), ("side", "in", {"buy", "BUY"})]).sort_values("timestamp_us")
    for k, v in t.groupby(["slug", "outcome"]):
        TAPE[k] = (v["timestamp_us"].values, v["price"].values.astype(float), v["size"].values.astype(float))


def book_lookup(books, slug, tok, t0, t1):
    """return (ts, ap[N,25], asz[N,25], bp[N,25], bsz[N,25]) restricted to [t0,t1], else None."""
    rec = books.get((slug, tok))
    if rec is None: return None
    ts, ap, asz, bp, bsz = rec
    m = (ts >= t0) & (ts <= t1)
    if not m.any(): return None
    return ts[m], ap[m], asz[m], bp[m], bsz[m]


def taker_bid_capped(books, slug, lead, fire, ev, sh, won):
    """Corrected taker +60 exit on L25: best-bid asof fire+60s, size-capped at level-0 bid depth,
    remainder held to resolution. If no usable quote -> whole position held. Returns pnl."""
    rec = books.get((slug, lead))
    if rec is None:
        return held_value(sh, ev, won)
    ts, ap, asz, bp, bsz = rec
    ext = fire + HOR * 1_000_000
    jx = np.searchsorted(ts, ext, "right") - 1
    if jx < 0 or jx >= len(ts) or (ext - ts[jx]) > STALE_US:
        return held_value(sh, ev, won)
    b0 = bp[jx, 0]; b0sz = bsz[jx, 0]
    if not np.isfinite(b0):
        return held_value(sh, ev, won)
    sold = min(sh, float(b0sz) if np.isfinite(b0sz) else 0.0)
    rem = sh - sold
    return ((b0 - ev) * sold - tk(b0) * sold if sold > 0 else 0.0) + held_value(rem, ev, won)


def queue_ahead(ap_row, asz_row, peg):
    px = np.asarray(ap_row, float); sz = np.asarray(asz_row, float)
    g = np.isfinite(px) & np.isfinite(sz) & (px > 0) & (px <= peg + 1e-9)
    return float(sz[g].sum())


recs = []
slugs = sorted(c.slug.unique())
asset_of = c.set_index("slug")["asset"].to_dict()
for a in ["BTC", "ETH"]:
    sa = [s for s in slugs if asset_of[s] == a]
    for b0i in range(0, len(sa), BATCH):
        bs = set(sa[b0i:b0i + BATCH]); cc = c[c.slug.isin(bs)]
        if not len(cc): continue
        tmin = int(cc.fire_us.min()) - 2_000_000; tmax = int(cc.fire_us.max()) + HOR * 1_000_000 + 5_000_000
        books = load_orderbook_l25_streaming(a.lower(), slugs=bs, subsample_1hz=False, min_ts_us=tmin, max_ts_us=tmax)
        for r in cc.itertuples():
            ev, sh, lead = float(r.entry_vwap), float(r.shares), r.direction; fire = int(r.fire_us)
            won = bool(r.won)
            # ---- (0) corrected taker +60 baseline (size-capped, held remainder) ----
            taker60 = taker_bid_capped(books, r.slug, lead, fire, ev, sh, won)
            snaps = book_lookup(books, r.slug, lead, fire, fire + HOR * 1_000_000)
            tape = TAPE.get((r.slug, lead))
            # ---- (A) queue-aware FIXED peg at entry best-ask (size-capped maker sell + taker fallback) ----
            maker_fix = taker60; fix_frac = 1.0
            if snaps is not None:
                ts0, ap0, asz0, bp0, bsz0 = snaps
                peg = float(ap0[0, 0]) if np.isfinite(ap0[0, 0]) else np.nan
                if math.isfinite(peg) and peg > ev and tape is not None:
                    Q = queue_ahead(ap0[0], asz0[0], peg)
                    rest_sz = float(asz0[0, 0]) if np.isfinite(asz0[0, 0]) else sh  # our placeable size at peg
                    tt, pp, ss = tape; w = (tt > fire) & (tt <= fire + HOR * 1_000_000) & (pp >= peg - 1e-9)
                    cum = np.cumsum(ss[w]) if w.any() else np.array([])
                    if len(cum) and cum[-1] > Q:
                        # volume past our queue position absorbs up to (incoming-Q); cap by our resting size & shares
                        avail = float(cum[-1] - Q)
                        sold = min(sh, rest_sz, max(avail, 0.0))
                        rem = sh - sold
                        maker_fix = ((peg - ev) * sold + reb(peg) * sold if sold > 0 else 0.0)
                        # remainder taker-crossed at +60 (already-held-aware)
                        maker_fix += taker_bid_capped(books, r.slug, lead, fire, ev, rem, won) if rem > 0 else 0.0
                        fix_frac = (rem / sh if sh > 0 else 1.0)
                        # taker_bid_capped on rem already holds what it can't sell; approximate frac_held by its hold
            # ---- (B) peg-to-ask TRAIL (size-capped) ----
            maker_trail = taker60; trail_frac = 1.0
            if snaps is not None and tape is not None:
                ts0, ap0, asz0, bp0, bsz0 = snaps; tt, pp, ss = tape
                cur_peg = float(ap0[0, 0]) if np.isfinite(ap0[0, 0]) else np.nan
                qi = 0
                if math.isfinite(cur_peg):
                    Q = queue_ahead(ap0[0], asz0[0], cur_peg); cum = 0.0
                    rest_sz = float(asz0[0, 0]) if np.isfinite(asz0[0, 0]) else sh
                    w = (tt > fire) & (tt <= fire + HOR * 1_000_000); filled = False
                    for j in np.where(w)[0]:
                        while qi + 1 < len(ts0) and ts0[qi + 1] <= tt[j]:
                            qi += 1
                            na = float(ap0[qi, 0])
                            if math.isfinite(na) and na > cur_peg:
                                cur_peg = na; Q = queue_ahead(ap0[qi], asz0[qi], cur_peg); cum = 0.0
                                rest_sz = float(asz0[qi, 0]) if np.isfinite(asz0[qi, 0]) else sh
                        if pp[j] >= cur_peg - 1e-9:
                            cum += ss[j]
                            if cum > Q:
                                sold = min(sh, rest_sz, float(cum - Q))
                                rem = sh - sold
                                maker_trail = ((cur_peg - ev) * sold + reb(cur_peg) * sold if sold > 0 else 0.0)
                                maker_trail += taker_bid_capped(books, r.slug, lead, fire, ev, rem, won) if rem > 0 else 0.0
                                trail_frac = (rem / sh if sh > 0 else 1.0); filled = True; break
            recs.append(dict(asset=a, slug=r.slug, fire_us=fire, ev=ev, sh=sh, won=won,
                             taker60=taker60, maker_fix=maker_fix, maker_trail=maker_trail,
                             fix_frac=fix_frac, trail_frac=trail_frac))
        del books
    print(f"  [{a}] done rows={len(recs)}", flush=True)
D = pd.DataFrame(recs).sort_values("fire_us").reset_index(drop=True)
D.to_parquet(RES / "maker_exit_fixed_2026_06_10.parquet")


def show(v, name):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: print(f"  {name:22s} n={len(v)} (few)"); return
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    print(f"  {name:22s} n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] {'POS' if lo > 0 else '.'}")


cut = int(len(D) * 0.6)
for split, sl in [("ALL", slice(None)), ("IS", slice(0, cut)), ("OOS", slice(cut, None))]:
    d = D.iloc[sl]
    print(f"\n=== {split} n={len(d)} ===")
    show(d.taker60.values, "taker60 [baseline]")
    show(d.maker_fix.values, "maker queue-fixed")
    show(d.maker_trail.values, "maker peg-trail")
    for col, fcol in [("maker_fix", "fix_frac"), ("maker_trail", "trail_frac")]:
        diff = (d[col] - d.taker60).values; lo, hi = boot(diff)
        sig = "SIG+" if lo > 0 else ("SIG-" if hi < 0 else "ns")
        print(f"    {col} - taker60: {diff.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] {sig}")
        clean = d[d[fcol] == 0]
        if len(clean) >= 5:
            dc = (clean[col] - clean.taker60).values; lo, hi = boot(dc)
            print(f"      CLEAN(frac==0) n={len(clean)} diff={dc.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]")
for a in ["BTC", "ETH"]:
    d = D[D.asset == a]
    if len(d) < 20: continue
    df = (d.maker_trail - d.taker60).values; lo, hi = boot(df)
    print(f"  [{a}] maker_trail-taker60: {df.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]")
print("\nREAD: deploy maker-exit only if (queue-fixed OR peg-trail) beats taker60 paired CI>0 AND both BTC+ETH positive.")
print("CAVEAT: maker fill = trade-tape volume past L25 queue (optimistic on queue priority); corrected exit model.")
