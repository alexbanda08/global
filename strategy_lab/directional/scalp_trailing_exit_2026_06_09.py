"""
TICK-LEVEL TRAILING / PEG EXIT on the open exit-scalp  —  2026-06-09  (THREAD A)

The dynamic-exit study (SCALP_DYNAMIC_EXIT_2026_06_04) found the bid PATH-MAX averages ~0.84 (oracle peak-sell
+$18/tr) but the fixed +45/+60s samples only ~0.59 -> the peak is a transient spike a fixed-time exit misses.
It flagged a "tick-level trailing exit" as untested future work. This tests it on the ~200Hz event-driven BBO
bid path (disjoint Mar30-Apr21 window). KEY REALISM: the live engine polls the exit every ~5s -> a sub-second
trailing stop may NOT be executable. So every trailing policy is evaluated on a 5s poll grid (LIVE-realistic) AND
a 1s grid (optimistic bracket). If a policy beats FIXED_60 with paired CI>0 on the 5s grid -> deployable.

Fires = deployed cell: lag-taker (binance 5s ret at slot_start, |delta|>=3, lead=sign), fire +5s, entry $25 @
best_ask (top-of-book, size-capped, spread<=0.05), gate entry_vwap<0.55. Exit policies sell at best_bid:
  FIXED_{45,60,90}          fixed-time (baseline = FIXED_60)
  TRAIL_{.02,.03,.05,.08}   sell when bid <= (running max bid since entry) - X
  ARM.05_TRAIL{.03,.05}     let bid run until >= entry+.05, THEN trail by X (avoids stopping out on entry noise)
  PEAK_oracle               max bid over [fire, slot_end]  (untradeable upper bound)
Poll grid in {1s, 5s}. PnL fee 0.015 round-trip. Paired bootstrap vs FIXED_60.
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("TR_COINS", "BTC,ETH,SOL").split(",")
TFS = os.environ.get("TR_TFS", "15m,5m").split(",")
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("TR_TAG", "")
TF_SEC = {"5m": 300, "15m": 900}

def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)
def bpnl(sell, ev, sh): return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))

def bid_on_grid(ts, bid, t0, t1, step_us):
    """sampled best_bid at t0, t0+step, ... <=t1 (asof each grid point). returns (grid_us, bidvals)."""
    grid = np.arange(t0, t1 + 1, step_us)
    idx = np.searchsorted(ts, grid, "right") - 1
    ok = idx >= 0
    return grid[ok], bid[np.clip(idx[ok], 0, len(bid) - 1)]

def exit_trail(grid, bids, X, arm=None, entry_bid=None):
    """trailing stop: sell when bid <= runmax - X. If arm set, only start trailing after bid >= entry_bid+arm.
    returns sell price (bid at trigger), else last grid bid (held to deadline)."""
    runmax = -np.inf; armed = (arm is None)
    for b in bids:
        if not np.isfinite(b): continue
        if not armed:
            if entry_bid is not None and b >= entry_bid + arm: armed = True; runmax = b
            continue
        runmax = max(runmax, b)
        if b <= runmax - X: return b
    return bids[np.isfinite(bids)][-1] if np.isfinite(bids).any() else np.nan

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
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float))
            for _, r in chunk.iterrows():
                key = (r.slug, r.lead)
                if key not in bk: continue
                ts, ask, bid, asz = bk[key]
                fire = int(r.fire_us); send = int(r.slot_end_us)
                je = np.searchsorted(ts, fire + LAT_US, "right") - 1
                if je < 0 or je >= len(ts): continue
                a0, b0, s0 = ask[je], bid[je], asz[je]
                if not (np.isfinite(a0) and np.isfinite(b0)) or (a0 - b0) > SPREAD: continue
                if a0 >= 0.55: continue                       # deployed cheap gate
                sh = min(STAKE / a0, s0)
                if sh * a0 < STAKE * 0.5: continue
                won = (r.ret > 0) == (r.outcome == "Up")
                ev = a0
                def fixed(dt):
                    jx = np.searchsorted(ts, min(fire + dt * 1_000_000, send), "right") - 1
                    return bid[jx] if (0 <= jx < len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
                rec = dict(coin=coin, tf=tf, slug=r.slug, ev=ev, won=won, delta=r.delta_bps,
                           f45=bpnl(fixed(45), ev, sh), f60=bpnl(fixed(60), ev, sh), f90=bpnl(fixed(90), ev, sh))
                # bid path on poll grids; trailing policies (deadline = slot_end)
                for step_lbl, step in [("1s", 1_000_000), ("5s", 5_000_000)]:
                    grid, bids = bid_on_grid(ts, bid, fire + LAT_US, send, step)
                    if len(bids) == 0:
                        for k in [".02", ".03", ".05", ".08", "arm05_.03", "arm05_.05", "peak"]:
                            rec[f"{step_lbl}_{k}"] = np.nan
                        continue
                    peak = np.nanmax(bids)
                    for X in [0.02, 0.03, 0.05, 0.08]:
                        rec[f"{step_lbl}_{X:.2f}"[:].replace("0.", ".")] = bpnl(exit_trail(grid, bids, X), ev, sh)
                    rec[f"{step_lbl}_arm05_.03"] = bpnl(exit_trail(grid, bids, 0.03, arm=0.05, entry_bid=b0), ev, sh)
                    rec[f"{step_lbl}_arm05_.05"] = bpnl(exit_trail(grid, bids, 0.05, arm=0.05, entry_bid=b0), ev, sh)
                    rec[f"{step_lbl}_peak"] = bpnl(peak, ev, sh)
                ROWS.append(rec)
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_trailing_2026_06_09{TAG}.parquet")
        print(f"  [ckpt] {coin} {tf}: fires={len(F[(F.coin==coin)&(F.tf==tf)])}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_trailing_2026_06_09{TAG}.parquet")
print(f"\nsaved {len(F)} fires")

def boot(v, nb=5000):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def stat(v):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return f"n={len(v):4d}(few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"

POLS = ["f45", "f60", "f90", "5s_.02", "5s_.03", "5s_.05", "5s_.08", "5s_arm05_.03", "5s_arm05_.05",
        "5s_peak", "1s_.03", "1s_.05", "1s_arm05_.05", "1s_peak"]
print("\n===== EXIT POLICY $/tr (pooled, cheap-gated fires) =====")
for p in POLS:
    if p in F: print(f"  {p:16s} {stat(F[p].values)}")
print("\n===== PAIRED vs FIXED_60 (policy - f60), pooled =====")
for p in POLS:
    if p in F and p != "f60":
        diff = (F[p] - F["f60"]).values
        print(f"  {p:16s} {stat(diff)}")
print("\n===== per coin-tf: best 5s-grid trailing vs f60 =====")
for (coin, tf), g in F.groupby(["coin", "tf"]):
    print(f"  {coin} {tf}: f60 {stat(g.f60.values)} | 5s_.05 {stat(g['5s_.05'].values)} | 5s_arm05_.05 {stat(g['5s_arm05_.05'].values)}")
print("\nREAD: a trailing exit is deployable only if (policy - f60) paired CI>0 on a 5s grid (live polls 5s).")
print("peak = untradeable oracle upper bound. CAVEAT: BBO top-of-book; confirm on native-10Hz L25 if a 5s policy wins.")
