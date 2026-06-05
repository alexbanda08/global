"""
lag_taker_oos_reval_2026_06_01.py — LONGER-WINDOW OOS RE-VALIDATION of the leg-1
binance->chainlink directional lag taker (the FAST_TAKER_LAGV2 edge).

WHY: the foundation backtest (lag_taker_foundation_2026_05_29.py) was fit on
May 8 -> May 29 13:00 (binance-spot-ws 1s coverage at the time), config frozen
2026-05-29 19:51. The CLAUDE.md handoff flags "longer-window OOS re-validation
before any real-money sizing". Two things changed since the freeze:

  1. Canonical refreshed to 2026-06-01 09:07 -> ~3 days of forward-unseen data.
  2. We now also use the binance-VISION 1SEC source (Apr 7 -> May 6), which the
     foundation IGNORED (it filtered source=='binance-spot-ws' only, hence the
     May 8 floor). Combined 1s signal now spans Apr 7 -> Jun 1. Bounded by L25
     (Apr 22) + resolutions (Apr 24), the usable FILL window is Apr 24 -> Jun 1.

This unlocks TWO genuinely-unseen segments relative to the frozen config:
  - bwd_oos : ss <  May 8 00:00        (Apr 24 -> May 8, ~14d, earlier regime)
  - fwd_oos : ss >= May 29 13:00       (May 29 -> Jun 1, ~3d, forward)
and re-scores the original fit window (fit_IS May8-18, fit_OOS May18-29) on the
SAME engine for an internally-consistent comparison.

ENGINE NOTE: uses the CURRENT working-tree engine_v2, where the 2026-05-30 fix
ENFORCES min_book_events=25 (the foundation ran before that fix). All segments are
scored with the same (now-stricter) engine -> the fit-vs-unseen comparison is valid;
absolute numbers may differ slightly from the May-29 printed report.

SIGNAL / FILL / FEE: identical to the foundation —
  ret = binance_1s(slot_start+5s)/binance_1s(slot_start) - 1 ; delta_bps=|ret|*1e4
  lead = Up if ret>0 else Down ; fire_us=(slot_start+5)*1e6
  fill = engine_v2.fill_at_book ($25 walk, 85ms latency, spread<=0.05, native-10Hz L25)
  fee  = 0.07 winner-only: pnl_won=(1-v)*sh*(1-0.07v) ; pnl_loss=-v*sh

SCOPE: core hold-to-resolution edge only (base >=3, >=5, ex-18-23, per-asset, per-tf).
Full R5 (confluence+depth gates), reversal-stop, and confidence sizing are a Phase-2
follow-up IF the core edge survives unseen data.

Usage: C:/Python314/python.exe strategy_lab/directional/lag_taker_oos_reval_2026_06_01.py
"""
from __future__ import annotations
import sys
import gc
import time
import traceback
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
FIRE_PARQUET = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
SEG_CSV = OUT / "lag_taker_oos_segments_2026_06_01.csv"

SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSETS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m"]

# ---- window: usable fill window = max(L25 start Apr22, resolutions Apr24) .. Jun1 09:00 ----
LO = int(pd.Timestamp("2026-04-24 00:00", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-06-01 09:00", tz="UTC").timestamp())
# segment boundaries (relative to the frozen config):
ORIG_LO = int(pd.Timestamp("2026-05-08 00:00", tz="UTC").timestamp())   # foundation fit floor
IS_CUT = int(pd.Timestamp("2026-05-18 00:00", tz="UTC").timestamp())    # foundation IS/OOS split
FREEZE = int(pd.Timestamp("2026-05-29 13:00", tz="UTC").timestamp())    # foundation HI = config freeze

OFFSET = 5
B_FLOOR = 2.0          # collection floor (so downstream can re-sweep >=3,>=5)
NOTIONAL = 25.0
SPREAD = 0.05
FEE_RATE = 0.07
MAX_STALE_US = 10_000_000   # asof staleness guard: reject matches > 10s old (covers vision/spot gap)
CHUNK_DAYS = 3              # smaller chunks -> lower peak L25 memory (native-10Hz can be huge mid-May)


def seg_of(ss: int) -> str:
    if ss < ORIG_LO:
        return "bwd_oos"
    if ss < IS_CUT:
        return "fit_IS"
    if ss < FREEZE:
        return "fit_OOS"
    return "fwd_oos"


def unified_binance_1s(asset: str):
    """vision (Apr7->May6) + spot-ws (May7->Jun1), concatenated & sorted.
    Returns (ts_us[bar-END], close). bar-END = start_us + 1e6 (causal close ts)."""
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.period_id == "1SEC")
            & df.source.isin(["binance-vision", "binance-spot-ws"])]
    df = df.sort_values("time_period_start_us")
    ts = df.time_period_start_us.values.astype(np.int64) + 1_000_000
    px = df.price_close.values.astype(float)
    # de-dup identical timestamps (shouldn't happen: sources are disjoint) keeping last
    keep = np.concatenate([np.diff(ts) != 0, [True]])
    return ts[keep], px[keep]


def asof(ts, v, t):
    """close of bar ended at-or-before t, NaN if no bar or match older than MAX_STALE_US."""
    t = t.astype(np.int64)
    i = np.searchsorted(ts, t, side="right") - 1
    out = np.full(len(t), np.nan)
    ok = i >= 0
    out[ok] = v[i[ok]]
    stale = ok & ((t - ts[np.clip(i, 0, len(ts) - 1)]) > MAX_STALE_US)
    out[stale] = np.nan
    return out


def pnl_007(vwap, shares, won):
    if won:
        return (1.0 - vwap) * shares * (1.0 - FEE_RATE * vwap)
    return -vwap * shares


def stat(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = float(x.mean())
    se = float(x.std(ddof=1)) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def max_dd(p):
    if len(p) == 0:
        return 0.0
    c = np.cumsum(p)
    return float((c - np.maximum.accumulate(c)).min())


def run():
    t0 = time.time()
    res = load_resolutions()
    res["slug"] = res["slug"].astype(str)
    bz = {a: unified_binance_1s(a) for a in ASSETS}
    for a in ASSETS:
        ts, _ = bz[a]
        print(f"[1s {a}] {pd.Timestamp(int(ts.min()),unit='us',tz='UTC')} -> "
              f"{pd.Timestamp(int(ts.max()),unit='us',tz='UTC')} n={len(ts):,}", flush=True)

    fire_recs = []
    bounds = list(range(LO, HI, CHUNK_DAYS * 86400)) + [HI]
    for ci in range(len(bounds) - 1):
        clo, chi = bounds[ci], bounds[ci + 1]
        for asset in ASSETS:
            be, bc = bz[asset]
            for tf in TFS:
                books = None
                try:
                    pref = f"{asset.lower()}-updown-{tf}-"
                    sub = res[(res.ticker == asset) & (res.timeframe == tf)]
                    sub = sub[sub.slug.str.startswith(pref)].copy()
                    if sub.empty:
                        continue
                    sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
                    sub = sub[(sub.ss >= clo) & (sub.ss < chi)]
                    if sub.empty:
                        continue
                    ss = sub.ss.values.astype(np.int64)
                    sl = sub.slug.values
                    won_up = (sub.outcome.str.lower() == "up").values
                    fire = (ss + OFFSET) * 1_000_000
                    px_fire = asof(be, bc, fire)
                    px_open = asof(be, bc, ss * 1_000_000)
                    ret_off = px_fire / px_open - 1.0

                    slugs = set(sl)
                    books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                    cfg = LiveMimicConfig()
                    for k in range(len(sl)):
                        r = ret_off[k]
                        if not np.isfinite(r) or abs(r) < 1e-12:
                            continue
                        db = abs(r) * 1e4
                        if db < B_FLOOR:
                            continue
                        lead = "Up" if r > 0 else "Down"
                        fill = fill_at_book(books, sl[k], lead, int(fire[k]), cfg=cfg,
                                            side="buy", spread_filter=SPREAD, notional_usd=NOTIONAL)
                        if fill is None:
                            continue
                        vwap = float(fill["vwap"])
                        shares = float(fill["shares"])
                        won = (r > 0) == bool(won_up[k])
                        pnl = pnl_007(vwap, shares, won)
                        hour = pd.Timestamp(int(ss[k]), unit="s", tz="UTC").hour
                        fire_recs.append(dict(slug=sl[k], asset=asset, tf=tf,
                                              fire_us=int(fire[k]), slot_start=int(ss[k]),
                                              direction=lead, delta_bps=round(db, 3),
                                              entry_vwap=round(vwap, 5), shares=round(shares, 3),
                                              outcome="Up" if won_up[k] else "Down",
                                              won=bool(won), pnl=round(pnl, 5), hour=int(hour),
                                              segment=seg_of(int(ss[k]))))
                except Exception:
                    print(f"  !! CELL FAILED {asset} {tf} chunk "
                          f"{pd.to_datetime(clo, unit='s', utc=True):%m-%d}:", flush=True)
                    traceback.print_exc()
                finally:
                    del books
                    gc.collect()
        print(f"[chunk {pd.to_datetime(clo, unit='s', utc=True):%m-%d}] "
              f"fires={len(fire_recs)} t={time.time()-t0:.0f}s", flush=True)

    F = pd.DataFrame(fire_recs)
    F.to_parquet(FIRE_PARQUET, index=False)

    def cell(g):
        p = g.pnl.to_numpy()
        m, t = stat(p)
        return dict(n=len(g), wr=round(100 * g.won.mean(), 1),
                    vwap=round(g.entry_vwap.mean(), 3), per_tr=round(m, 3),
                    total=round(p.sum(), 1), maxdd=round(max_dd(p), 1), t=round(t, 2))

    SEG_ORDER = ["bwd_oos", "fit_IS", "fit_OOS", "fwd_oos"]
    SEG_DAYS = {"bwd_oos": (ORIG_LO - LO) / 86400, "fit_IS": (IS_CUT - ORIG_LO) / 86400,
                "fit_OOS": (FREEZE - IS_CUT) / 86400, "fwd_oos": (HI - FREEZE) / 86400}

    # BTC+ETH only (deploy universe). gate variants.
    be_all = F[F.asset.isin(["BTC", "ETH"])]
    rows = []
    for gate_name, gmask in [("ge3", be_all.delta_bps >= 3),
                             ("ge5", be_all.delta_bps >= 5),
                             ("ge3_ex18-23", (be_all.delta_bps >= 3) & ~be_all.hour.between(18, 23))]:
        g0 = be_all[gmask]
        for seg in SEG_ORDER:
            g = g0[g0.segment == seg]
            if len(g) < 5:
                rows.append(dict(config=gate_name, seg=seg, n=len(g)))
                continue
            d = cell(g); d.update(config=gate_name, seg=seg)
            d["per_day"] = round(len(g) / SEG_DAYS[seg], 1)
            rows.append(d)
        # combined unseen vs fit
        for combo, segs in [("UNSEEN(bwd+fwd)", ["bwd_oos", "fwd_oos"]),
                            ("FIT(IS+OOS)", ["fit_IS", "fit_OOS"])]:
            g = g0[g0.segment.isin(segs)]
            if len(g) >= 5:
                d = cell(g); d.update(config=gate_name, seg=combo); rows.append(d)
    SEG = pd.DataFrame(rows)
    SEG.to_csv(SEG_CSV, index=False)

    def show(df, cols=None):
        cols = cols or ["config", "seg", "n", "wr", "vwap", "per_tr", "total", "maxdd", "t", "per_day"]
        cc = [c for c in cols if c in df.columns]
        print(df[cc].to_string(index=False))

    pd.set_option("display.width", 240)
    print("\n" + "=" * 96)
    print("LAG-TAKER OOS RE-VALIDATION — BTC+ETH, hold-to-resolution, 0.07 fee, current engine")
    print(f"window Apr24->Jun1 | freeze={pd.Timestamp(FREEZE,unit='s',tz='UTC'):%m-%d %H:%M} | total fires={len(F)}")
    print("=" * 96)
    print("\n--- by segment x gate (bwd_oos/fwd_oos = UNSEEN by frozen config) ---")
    show(SEG[SEG.seg.isin(SEG_ORDER)].sort_values(["config", "seg"]))
    print("\n--- UNSEEN vs FIT (the headline OOS test) ---")
    show(SEG[SEG.seg.str.contains("UNSEEN|FIT")].sort_values(["config", "seg"]),
         cols=["config", "seg", "n", "wr", "vwap", "per_tr", "total", "maxdd", "t"])

    # per-asset / per-tf stability on UNSEEN (ge3)
    uns = be_all[(be_all.delta_bps >= 3) & be_all.segment.isin(["bwd_oos", "fwd_oos"])]
    print("\n--- UNSEEN (ge3) by ASSET ---")
    ar = []
    for a in ["BTC", "ETH"]:
        g = uns[uns.asset == a]
        if len(g) >= 5:
            d = cell(g); d.update(asset=a); ar.append(d)
    if ar:
        show(pd.DataFrame(ar), cols=["asset", "n", "wr", "vwap", "per_tr", "total", "maxdd", "t"])
    print("\n--- UNSEEN (ge3) by TF ---")
    tr = []
    for tf in TFS:
        g = uns[uns.tf == tf]
        if len(g) >= 5:
            d = cell(g); d.update(tf=tf); tr.append(d)
    if tr:
        show(pd.DataFrame(tr), cols=["tf", "n", "wr", "vwap", "per_tr", "total", "maxdd", "t"])

    # SOL sanity (should remain a drag)
    sol = F[(F.asset == "SOL") & (F.delta_bps >= 3)]
    if len(sol) >= 5:
        print("\n--- SOL (ge3, all segs) sanity — expect drag ---")
        d = cell(sol); print({k: d[k] for k in ["n", "wr", "per_tr", "total", "t"]})

    print(f"\nwrote {FIRE_PARQUET} ({len(F)} fires)")
    print(f"wrote {SEG_CSV}")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    run()
