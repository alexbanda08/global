"""
TICK-LEVEL TRAILING / PEG EXIT — CORRECTED EXIT MODEL (2026-06-10). Fixed clone of scalp_trailing_exit_2026_06_09.py.
Trailing/fixed sells now use the size-cap + staleness model at the trigger bid; the unsold remainder is HELD to
resolution (winner-only 0.07 valuation) instead of the old outcome-as-price fallback. PEAK oracle row stays as a
bound. Every policy reports ALL + CLEAN (frac_held==0). Env: TR_COINS/TR_TFS/TR_TAG/TR_LIMIT.
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, bpnl, held_value, boot, resolve_size
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000; STALE_US = 120_000_000
COINS = os.environ.get("TR_COINS", "BTC,ETH,SOL").split(",")
TFS = os.environ.get("TR_TFS", "15m,5m").split(",")
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("TR_TAG", ""); LIMIT = int(os.environ.get("TR_LIMIT", "0"))


def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def sell_capped(bid_px, bid_sz, shares, ev, won):
    """Sell up to bid_sz at bid_px; hold the remainder to resolution. Returns (pnl, frac_held)."""
    if not np.isfinite(bid_px):
        return held_value(shares, ev, won), 1.0
    sz = 0.0 if np.isnan(bid_sz) else float(bid_sz)   # inf = DEEP (resolved artifact) -> no cap
    sold = min(shares, sz)
    rem = shares - sold
    pnl = (bpnl(float(bid_px), ev, sold) if sold > 0 else 0.0) + held_value(rem, ev, won)
    return pnl, (rem / shares if shares > 0 else 1.0)


def grid_snaps(ts, bid, bidsz, t0, t1, step_us, entry_idx):
    """grid points t0..t1; per point return (idx, bid, bidsz) honoring entry_idx + staleness."""
    grid = np.arange(t0, t1 + 1, step_us)
    out = []
    for g in grid:
        jx = np.searchsorted(ts, g, "right") - 1
        if jx < entry_idx or jx < 0 or jx >= len(ts):
            out.append((jx, np.nan, np.nan)); continue
        if (g - ts[jx]) > STALE_US or not np.isfinite(bid[jx]):
            out.append((jx, np.nan, np.nan)); continue
        out.append((jx, bid[jx], resolve_size(ts, bidsz, jx)[0]))   # artifact sizes resolved (2026-06-10b)
    return out


def exit_trail_capped(snaps, X, shares, ev, won, arm=None, entry_bid=None):
    """trailing stop on the size-capped model. snaps=list of (idx,bid,bidsz). returns (pnl,frac_held)."""
    runmax = -np.inf; armed = (arm is None); last = None
    for _idx, b, bsz in snaps:
        if not np.isfinite(b): continue
        last = (b, bsz)
        if not armed:
            if entry_bid is not None and b >= entry_bid + arm:
                armed = True; runmax = b
            continue
        runmax = max(runmax, b)
        if b <= runmax - X:
            return sell_capped(b, bsz, shares, ev, won)
    if last is not None:
        return sell_capped(last[0], last[1], shares, ev, won)   # held to deadline -> sell last grid bid
    return held_value(shares, ev, won), 1.0


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []
for coin in COINS:
    be, bc = klines(coin)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d): print(f"{coin} {tf}: none", flush=True); continue
        ss = d.slot_start_us.values
        ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
        d = d.assign(fire_us=ss + 5_000_000, ret=ret, delta_bps=np.abs(ret) * 1e4,
                     lead=np.where(ret > 0, "Up", "Down"))
        d = d[np.isfinite(d.ret) & (d.delta_bps >= 3.0)].reset_index(drop=True)
        if LIMIT > 0: d = d.iloc[:LIMIT].reset_index(drop=True)
        print(f"\n=== {coin} {tf}: {len(d)} candidate fires ===", flush=True)
        slugs = d.slug.tolist(); B = 120
        for i in range(0, len(slugs), B):
            chunk = d.iloc[i:i + B]
            cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end_us.max()) + 2_000_000
            bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
            bk = {}
            for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
                g = g.sort_values("timestamp_us")
                bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                                g.best_bid_size.values.astype(float))
            for _, r in chunk.iterrows():
                key = (r.slug, r.lead)
                if key not in bk: continue
                ts, ask, bid, asz, bsz = bk[key]
                fire = int(r.fire_us); send = int(r.slot_end_us)
                ent = entry_fill(ts, ask, asz, fire + LAT_US, STAKE, SPREAD, bid)
                if ent is None: continue
                ev = ent["ev"]; sh = ent["shares"]; eidx = ent["entry_idx"]; b0 = ent["b0"]
                if ev >= 0.55: continue
                won = (r.ret > 0) == (r.outcome == "Up")

                def fixed(dt):
                    tgt = min(fire + dt * 1_000_000, send)
                    jx = np.searchsorted(ts, tgt, "right") - 1
                    if jx < eidx or jx < 0 or jx >= len(ts) or (tgt - ts[jx]) > STALE_US or not np.isfinite(bid[jx]):
                        return held_value(sh, ev, won), 1.0
                    return sell_capped(bid[jx], resolve_size(ts, bsz, jx)[0], sh, ev, won)
                f45p, f45h = fixed(45); f60p, f60h = fixed(60); f90p, f90h = fixed(90)
                rec = dict(coin=coin, tf=tf, slug=r.slug, ev=ev, won=won, delta=r.delta_bps,
                           f45=f45p, f60=f60p, f90=f90p, f45_h=f45h, f60_h=f60h, f90_h=f90h)
                for step_lbl, step in [("1s", 1_000_000), ("5s", 5_000_000)]:
                    snaps = grid_snaps(ts, bid, bsz, fire + LAT_US, send, step, eidx)
                    fin = [(b, bz) for _i, b, bz in snaps if np.isfinite(b)]
                    if not fin:
                        for k in [".02", ".03", ".05", ".08", "arm05_.03", "arm05_.05", "peak"]:
                            rec[f"{step_lbl}_{k}"] = np.nan; rec[f"{step_lbl}_{k}_h"] = np.nan
                        continue
                    bids_arr = np.array([b for b, _ in fin]); peakidx = int(np.argmax(bids_arr))
                    peak_b, peak_sz = fin[peakidx]
                    for X in [0.02, 0.03, 0.05, 0.08]:
                        p, h = exit_trail_capped(snaps, X, sh, ev, won)
                        lbl = f"{step_lbl}_{X:.2f}".replace("0.", ".")
                        rec[lbl] = p; rec[f"{lbl}_h"] = h
                    p, h = exit_trail_capped(snaps, 0.03, sh, ev, won, arm=0.05, entry_bid=b0)
                    rec[f"{step_lbl}_arm05_.03"] = p; rec[f"{step_lbl}_arm05_.03_h"] = h
                    p, h = exit_trail_capped(snaps, 0.05, sh, ev, won, arm=0.05, entry_bid=b0)
                    rec[f"{step_lbl}_arm05_.05"] = p; rec[f"{step_lbl}_arm05_.05_h"] = h
                    pk, pkh = sell_capped(peak_b, peak_sz, sh, ev, won)
                    rec[f"{step_lbl}_peak"] = pk; rec[f"{step_lbl}_peak_h"] = pkh
                ROWS.append(rec)
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_trailing_fixed_2026_06_10{TAG}.parquet")
        print(f"  [ckpt] {coin} {tf}: fires={len(F[(F.coin == coin) & (F.tf == tf)])}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_trailing_fixed_2026_06_10{TAG}.parquet")
print(f"\nsaved {len(F)} fires")


def stat(v):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return f"n={len(v):4d}(few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"


POLS = ["f45", "f60", "f90", "5s_.02", "5s_.03", "5s_.05", "5s_.08", "5s_arm05_.03", "5s_arm05_.05",
        "5s_peak", "1s_.03", "1s_.05", "1s_arm05_.05", "1s_peak"]
print("\n===== EXIT POLICY $/tr (pooled, cheap-gated fires)  ALL | CLEAN(frac_held==0) =====")
for p in POLS:
    if p in F:
        hcol = f"{p}_h"
        clean = F[F.get(hcol, 1.0) == 0][p].values if hcol in F else np.array([])
        print(f"  {p:16s} ALL {stat(F[p].values)} | CLEAN {stat(clean)}")
print("\n===== PAIRED vs FIXED_60 (policy - f60), pooled (ALL fires) =====")
for p in POLS:
    if p in F and p != "f60":
        diff = (F[p] - F["f60"]).values
        print(f"  {p:16s} {stat(diff)}")
print("\nREAD: a trailing exit is deployable only if (policy - f60) paired CI>0 on a 5s grid (live polls 5s).")
print("peak = untradeable oracle upper bound. CAVEAT: BBO top-of-book; confirm on native-10Hz L25 if a 5s policy wins.")
