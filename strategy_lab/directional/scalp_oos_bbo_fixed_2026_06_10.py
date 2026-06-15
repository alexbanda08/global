"""
SCALP DIFFERENT-WINDOW OOS — CORRECTED EXIT MODEL (2026-06-10).
Fixed clone of scalp_oos_bbo_2026_06_05.py. See scalp_fill_lib_2026_06_10.py for the two bug fixes:
  (1) no outcome-leak exit fallback (held-to-resolution settlement instead);
  (2) sell capped at best_bid_size; remainder held to resolution.
Every cell reports BOTH (a) ALL fires and (b) CLEAN subset (frac_held==0) = the dual bound.
ALSO: per-fire STOP simulation (poll bid 5s grid; trigger bid<=entry-0.10; size-capped exit, rem held)
      -> paired stop-ON minus stop-OFF, ALL and CLEAN. OLD CLAIM: stop adds +0.88/tr.
Env: OOS_COINS, OOS_TAG, OOS_LIMIT (first N slugs per coin, for smoke).
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, held_value, bpnl, boot, cell, resolve_size
CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
STOP_DROP = 0.10; STOP_STEP_US = 5_000_000

COINS = os.environ.get("OOS_COINS", "BTC,ETH,SOL").split(",")
LIMIT = int(os.environ.get("OOS_LIMIT", "0"))   # 0 = no limit
_FULL = ("2026-03-30", "2026-04-21"); _NEW = ("2026-04-06", "2026-04-21")
WIN = {"BTC": _FULL, "ETH": _FULL, "SOL": _FULL, "DOGE": _NEW, "BNB": _NEW, "XRP": ("2026-04-07", "2026-04-21")}
OUTTAG = os.environ.get("OOS_TAG", "")
ALL_FIRES = []


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    # CAUSAL FIX 2026-06-13: index on bar END (start+1s), NOT bar START. A 1s bar [T,T+1s)
    # realizes its close at T+1s, so asof(t) must return the bar whose END<=t (close KNOWN by t).
    # Indexing on start gave the bar OPENING<=t -> its close at ~t+1s = ~1s lookahead in the
    # delta signal (verified: inflated pooled gated $/tr +1.71->+1.01, scalp_causal_asof_oneshot).
    starts = df.time_period_start_us.values.astype("int64")
    return starts + 1_000_000, df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def stop_sim(ts, bid, bidsz, entry_idx, fire_us, ext_us, shares, ev, won):
    """Poll bid on a 5s grid from fire+LAT to ext. Trigger when bid<=ev-STOP_DROP.
    Sell at that bid (size-capped), remainder held to resolution. If never triggered,
    fall back to the corrected +60 exit (so pnl_stop == pnl60 when no stop)."""
    grid = np.arange(fire_us + LAT_US, ext_us + 1, STOP_STEP_US)
    thr = ev - STOP_DROP
    for g in grid:
        jx = np.searchsorted(ts, g, "right") - 1
        if jx < entry_idx or jx < 0 or jx >= len(ts):
            continue
        bx = bid[jx]
        if not np.isfinite(bx) or (g - ts[jx]) > 120_000_000:
            continue
        if bx <= thr + 1e-12:
            bsz, _carried = resolve_size(ts, bidsz, jx)   # artifact sizes resolved (2026-06-10b)
            sold_sh = min(shares, bsz)
            rem = shares - sold_sh
            pnl_sold = bpnl(float(bx), ev, sold_sh) if sold_sh > 0 else 0.0
            return pnl_sold + held_value(rem, ev, won)
    # no trigger -> same as corrected +60 exit
    ef = exit_fill(ts, bid, bidsz, entry_idx, ext_us, shares, ev, won)
    return ef["pnl"]


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]

for coin in COINS:
    lo = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000; hi = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo) & (res.slot_start_us <= hi)].copy()
    if not len(d):
        print(f"\n=== {coin}: no slugs in window ==="); continue
    be, bc = unified_1s(coin)
    ss = d.slot_start_us.values
    ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret=ret,
                 delta_bps=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta_bps >= 3.0)].reset_index(drop=True)
    if LIMIT > 0:
        d = d.iloc[:LIMIT].reset_index(drop=True)
    print(f"\n=== {coin} OOS {WIN[coin][0]}..{WIN[coin][1]}: candidate fires (delta>=3) = {len(d)} ===", flush=True)
    recs = []; slugs = d.slug.tolist(); B = 120
    n_oldfallback = 0   # fires where the OLD code would have used outcome-as-price
    for i in range(0, len(slugs), B):
        chunk = d.iloc[i:i + B]
        cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end.max()) + 2_000_000
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
            won = (r.ret > 0) == (r.outcome == "Up")
            ent = entry_fill(ts, ask, asz, int(r.fire_us) + LAT_US, STAKE, SPREAD, bid)
            if ent is None: continue
            ev = ent["ev"]; shares = ent["shares"]; eidx = ent["entry_idx"]
            ext = min(int(r.fire_us) + 60_000_000, int(r.slot_end))
            ef = exit_fill(ts, bid, bsz, eidx, ext, shares, ev, won)
            # old-fallback incidence: old code searchsorted ext (no entry_idx/staleness guard)
            jx_old = np.searchsorted(ts, ext, "right") - 1
            if not (0 <= jx_old < len(ts) and np.isfinite(bid[jx_old])):
                n_oldfallback += 1
            pnl_stop = stop_sim(ts, bid, bsz, eidx, int(r.fire_us), ext, shares, ev, won)
            hour = (int(r.fire_us) // 1_000_000 % 86_400) // 3600
            recs.append(dict(coin=coin, fire_us=int(r.fire_us), hour=hour, ev=ev, won=won,
                             pnl60=ef["pnl"], pnl_stop=pnl_stop, frac_held=ef["frac_held"],
                             held_full=ef["held_full"], delta=r.delta_bps,
                             entry_size_carried=ent["entry_size_carried"],
                             exit_size_carried=ef["exit_size_carried"]))
        del bbo, bk
    F = pd.DataFrame(recs)
    ALL_FIRES.extend(recs)
    print(f"  filled fires: {len(F)} (of {len(d)} candidates)  old-fallback-incidence={n_oldfallback}")
    if len(F):
        print(f"  frac_held: mean={F.frac_held.mean():.3f} held_full={F.held_full.mean():.3f} "
              f"clean(frac==0)={(F.frac_held == 0).mean():.3f} "
              f"entry_carried={F.entry_size_carried.mean():.3f} exit_carried={F.exit_size_carried.mean():.3f}")
    for lab, sub in [("ALL filled", F), ("GATED vwap<0.55", F[F.ev < 0.55]),
                     ("GATED vwap<0.55 & d>=5", F[(F.ev < 0.55) & (F.delta >= 5)])]:
        if len(sub) < 5:
            print(f"  {lab:26s} n={len(sub)} (few)"); continue
        clean = sub[sub.frac_held == 0]
        print(f"  {lab:26s} ALL   {cell(sub.pnl60.values)} won={sub.won.mean():.3f}")
        print(f"  {'':26s} CLEAN {cell(clean.pnl60.values)}")

print("\nVERDICT: gated $/tr>0 with CI>0 on Mar30-Apr21 (disjoint) = scalp survives clean OOS (corrected exit).")
print("CAVEAT: BBO top-of-book fill (no L25 depth walk) -> entry slightly optimistic; re-check on full L25 if it passes.")

A = pd.DataFrame(ALL_FIRES)
A.to_parquet(RES / f"scalp_oos_bbo_fires_fixed_2026_06_10{OUTTAG}.parquet")

# ---- STOP study (replaces old stop study): paired stop-ON minus stop-OFF ----
print(f"\n===== STOP SIM (paired pnl_stop - pnl60), gated vwap<0.55 =====")
g = A[A.ev < 0.55]
for lab, sub in [("ALL", g), ("CLEAN (frac_held==0)", g[g.frac_held == 0])]:
    if len(sub) < 5:
        print(f"  {lab:22s} n={len(sub)} (few)"); continue
    diff = (sub.pnl_stop - sub.pnl60).values
    lo, hi = boot(diff)
    sig = "SIG+" if lo > 0 else ("SIG-" if hi < 0 else "ns")
    print(f"  {lab:22s} stopON {cell(sub.pnl_stop.values)}")
    print(f"  {'':22s} stopOFF{cell(sub.pnl60.values)}")
    print(f"  {'':22s} DIFF  mean={diff.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] {sig}  (OLD CLAIM +0.88/tr)")

# ---- TIME-OF-DAY OOS cross-validation (pooled, gated cell) ----
print(f"\n===== TIME-OF-DAY OOS (pooled, gated vwap<0.55, n={len(g)}) =====")
print(f"  base (all hours)        ALL   {cell(g.pnl60.values)}")
print(f"  {'':22s}  CLEAN {cell(g[g.frac_held == 0].pnl60.values)}")
for lab, mask in [("22-02 UTC", g.hour.isin([22, 23, 0, 1])),
                  ("exclude dead {12,17}", ~g.hour.isin([12, 17])),
                  ("exclude {2,12,16,17,18}", ~g.hour.isin([2, 12, 16, 17, 18])),
                  ("dead hours {12,17} only", g.hour.isin([12, 17]))]:
    s = g[mask]
    print(f"  {lab:23s} ALL   {cell(s.pnl60.values)}")
    print(f"  {'':23s} CLEAN {cell(s[s.frac_held == 0].pnl60.values)}")
print("READ: time-of-day gate validated OOS if 22-02 > base and exclude-dead >= base on Mar30-Apr21.")
