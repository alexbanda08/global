"""
leg2_repricing_study_v1.py — DEEP RESEARCH: leg-2 repricing window + complete-set
lock feasibility ("Buy->Wait->Hedge" §5.3).

Core question: after the leading side's ask rises >=X (0.05 / 0.10) over a window,
HOW LONG (ms) does the complement's ask stay below `1 - leading_ask` (i.e. is the
complete-set sum lockable < 0.97 under the 0.07 fee curve)? Or is the window ~0 =>
idea dead at our infra (Ireland <2ms).

Method (per resolved slug, BOTH UP+DOWN books at NATIVE 10Hz):
  1. Build a time-aligned merged grid of best-ask(Up) and best-ask(Down).
  2. REPRICING EVENTS: scan a sliding W-second window; an event fires when the
     LEADING side's best-ask rises by >= MOVE (0.05, 0.10) across the window.
     leading = the side whose ask rose; record trigger time t0 (end of the move).
  3. DWELL: from t0 forward, measure how long the complement's ask stays
     <= (1 - leading_ask(t0) - 0.03)  [lockable: sum < 0.97 cushion]. Also the
     exact 0.07-curve breakeven sum. Dwell = (last lockable ts - t0) in ms.
     Dwell=0 means the complement had ALREADY repriced by t0 (never lockable).
  4. COMPLETE-SET COST EVOLUTION: at t0 walk BOTH books $25 -> up_vwap+dn_vwap at
     +0/+85/+500/+1000/+2000 ms. Tabulate sum evolution.
  5. LOCK-REACHABILITY: fraction of events whose $25-walked complete-set sum is
     lockable (< 0.07-curve breakeven) within a reachable window (<= 500ms).
  6. CROSS-SIDE CORRELATION: corr of up_ask & dn_ask increments; how often
     up_ask + dn_ask == ~1 vs transient dislocation.

Run: C:/Python314/python.exe strategy_lab/directional/leg2_repricing_study_v1.py
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from book_walk import book_walk_fill  # noqa: E402

OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)

# universe: assets/tf harvested today
UNIVERSE = [("BTC", "5m"), ("BTC", "15m"), ("SOL", "15m"), ("ETH", "15m")]
MAX_SLUGS_PER_CELL = 350           # sample ~200-400 slugs each
WIN = {"5m": 300, "15m": 900}

# repricing-event params
MOVE_THRESHOLDS = [0.05, 0.10]     # leading-side ask rise
LOOKBACK_S = [10, 30, 60]          # window over which the move must occur
LOCK_CUSHION = 0.03                # lockable if complement_ask <= 1 - lead_ask - cushion (sum<0.97)
NOTIONAL = 25.0                    # complete-set walk size
FEE_RATE = 0.07                    # 0.07 fee curve
LAT_MS = [0, 85, 500, 1000, 2000]  # complete-set cost evolution offsets

# reachable window for lock-reachability fraction
REACH_MS = 500


def fee_per_share(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return FEE_RATE * p * (1.0 - p)


def lock_breakeven_sum(up_vwap: float, dn_vwap: float) -> float:
    """Max sum at which a $-per-share complete set still locks > 0 under 0.07 curve.
    PnL/pair-share = 1 - (up+dn) - fee(up) - fee(dn). Lockable when > 0:
       sum < 1 - fee(up) - fee(dn).
    """
    return 1.0 - fee_per_share(up_vwap) - fee_per_share(dn_vwap)


def best_ask_series(arr):
    """(ts_us[N], best_ask[N]) with best_ask in (0,1) or NaN."""
    ts, ap, asz, bp, bsz = arr
    a = ap[:, 0].astype(float)
    a = np.where((a > 0) & (a < 1), a, np.nan)
    return ts.astype(np.int64), a


def asof_idx(ts_sorted: np.ndarray, t: int) -> int:
    return int(np.searchsorted(ts_sorted, int(t), side="right")) - 1


def walk_complete_set(up_arr, dn_arr, t_us):
    """Walk BOTH ask books for $NOTIONAL asof t_us; return (up_vwap, dn_vwap, ok)."""
    out = []
    for arr in (up_arr, dn_arr):
        ts, ap, asz, bp, bsz = arr
        i = asof_idx(ts.astype(np.int64), t_us)
        if i < 0:
            return None
        prices = ap[i].astype(float)
        sizes = asz[i].astype(float)
        vwap, sh, usd, hit, under = book_walk_fill(prices, sizes, NOTIONAL, side="buy")
        if vwap <= 0 or under or not np.isfinite(vwap):
            return None
        out.append(vwap)
    return out[0], out[1]


def detect_events(up_ts, up_a, dn_ts, dn_a, slot_start_us, slot_end_us,
                  move_thr, lookback_s):
    """Detect repricing events on the Up-side ask (then Down-side ask separately).
    An event: leading-side best-ask at time t0 is >= ask(t0 - lookback) + move_thr,
    measured on a ~1s decimated grid for speed. Return list of (t0_us, leading,
    lead_ask_t0).
    Only events strictly inside the prediction window are kept.
    """
    events = []
    lb_us = lookback_s * 1_000_000
    for side, ts, a in (("Up", up_ts, up_a), ("Down", dn_ts, dn_a)):
        if len(ts) < 3:
            continue
        # decimate to ~1Hz grid of valid asks for the trigger scan
        sec = ts // 1_000_000
        _, uniq = np.unique(sec, return_index=True)
        uniq = np.sort(uniq)
        gts = ts[uniq]
        ga = a[uniq]
        ok = np.isfinite(ga)
        gts = gts[ok]; ga = ga[ok]
        if len(gts) < 3:
            continue
        in_win = (gts >= slot_start_us) & (gts <= slot_end_us)
        idxs = np.where(in_win)[0]
        last_fire = -1
        for j in idxs:
            t0 = gts[j]
            a0 = ga[j]
            # ask lookback_s ago
            k = int(np.searchsorted(gts, t0 - lb_us, side="right")) - 1
            if k < 0:
                continue
            a_past = ga[k]
            if not np.isfinite(a_past):
                continue
            if a0 - a_past >= move_thr:
                # debounce: one event per lookback window
                if last_fire >= 0 and (t0 - last_fire) < lb_us:
                    continue
                events.append((int(t0), side, float(a0)))
                last_fire = t0
    return events


def measure_dwell(comp_ts, comp_a, t0_us, lead_ask_t0, slot_end_us):
    """From t0 forward, how long does the complement ask stay
    <= (1 - lead_ask_t0 - cushion)?  Returns dwell_ms (0 if never lockable at t0).
    """
    thr = 1.0 - lead_ask_t0 - LOCK_CUSHION
    if thr <= 0:
        return 0.0
    # complement asks at-or-after t0
    j0 = int(np.searchsorted(comp_ts, t0_us, side="left"))
    # value AT t0 (asof) — does it start lockable?
    i_at = asof_idx(comp_ts, t0_us)
    if i_at < 0:
        return 0.0
    a_at = comp_a[i_at]
    if not (np.isfinite(a_at) and a_at <= thr):
        return 0.0  # already repriced at t0 -> not lockable
    # walk forward while complement stays <= thr (and within window)
    last_lock_ts = t0_us
    k = j0
    while k < len(comp_ts) and comp_ts[k] <= slot_end_us:
        av = comp_a[k]
        if np.isfinite(av):
            if av <= thr:
                last_lock_ts = comp_ts[k]
            else:
                break
        k += 1
    return (last_lock_ts - t0_us) / 1000.0  # ms


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    pctiles = [25, 50, 75, 90]
    dwell_rows = []        # per-event dwell records
    cost_rows = []         # complete-set sum evolution
    corr_rows = []         # cross-side correlation per slug
    reach_rows = []        # lock-reachability per event
    summary = []

    for asset, tf in UNIVERSE:
        pref = f"{asset.lower()}-updown-{tf}-"
        sub = res[(res.ticker == asset) & (res.timeframe == tf)]
        sub = sub[sub.slug.str.startswith(pref)].copy()
        if sub.empty:
            print(f"[{asset} {tf}] no slugs", flush=True)
            continue
        sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
        sub = sub.sort_values("ss")
        # sample most-recent MAX_SLUGS_PER_CELL (freshest books = most relevant)
        sub = sub.tail(MAX_SLUGS_PER_CELL)
        slugs = set(sub.slug)
        win_s = WIN[tf]
        t0t = time.time()
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
        n_ev = 0
        n_slug_with_both = 0
        for slug in slugs:
            up = books.get((slug, "Up"))
            dn = books.get((slug, "Down"))
            if up is None or dn is None:
                continue
            n_slug_with_both += 1
            up_ts, up_a = best_ask_series(up)
            dn_ts, dn_a = best_ask_series(dn)
            ss = int(slug.rsplit("-", 1)[1])
            slot_start_us = ss * 1_000_000
            slot_end_us = (ss + win_s) * 1_000_000

            # --- cross-side correlation (on a common 1Hz grid) ---
            secs = np.arange(ss, ss + win_s)
            grid_us = secs * 1_000_000
            ua = np.array([up_a[asof_idx(up_ts, t)] if asof_idx(up_ts, t) >= 0 else np.nan for t in grid_us])
            da = np.array([dn_a[asof_idx(dn_ts, t)] if asof_idx(dn_ts, t) >= 0 else np.nan for t in grid_us])
            both = np.isfinite(ua) & np.isfinite(da)
            if both.sum() >= 30:
                s = ua[both] + da[both]
                dua = np.diff(ua[both]); dda = np.diff(da[both])
                msk = np.isfinite(dua) & np.isfinite(dda)
                corr = float(np.corrcoef(dua[msk], dda[msk])[0, 1]) if msk.sum() >= 10 and dua[msk].std() > 0 and dda[msk].std() > 0 else np.nan
                corr_rows.append(dict(asset=asset, tf=tf, slug=slug,
                                      mean_sum=float(np.nanmean(s)),
                                      med_sum=float(np.nanmedian(s)),
                                      min_sum=float(np.nanmin(s)),
                                      frac_sum_lt_097=float((s < 0.97).mean()),
                                      ask_incr_corr=corr, n_grid=int(both.sum())))

            # --- repricing events for each move/lookback combo ---
            for move_thr in MOVE_THRESHOLDS:
                for lb in LOOKBACK_S:
                    evs = detect_events(up_ts, up_a, dn_ts, dn_a,
                                        slot_start_us, slot_end_us, move_thr, lb)
                    for (t0, lead, lead_ask) in evs:
                        n_ev += 1
                        comp = "Down" if lead == "Up" else "Up"
                        comp_ts, comp_a = (dn_ts, dn_a) if comp == "Down" else (up_ts, up_a)
                        dwell_ms = measure_dwell(comp_ts, comp_a, t0, lead_ask, slot_end_us)
                        dwell_rows.append(dict(asset=asset, tf=tf, move=move_thr,
                                               lookback=lb, lead=lead,
                                               lead_ask=lead_ask, dwell_ms=dwell_ms))
                        # complete-set cost evolution + reachability (only for the
                        # primary move=0.05/lb=10 events to bound output volume)
                        if move_thr == 0.05 and lb == 10:
                            cs = {}
                            lockable_by = None
                            for off in LAT_MS:
                                cw = walk_complete_set(up, dn, t0 + off * 1000)
                                if cw is None:
                                    cs[off] = np.nan
                                    continue
                                uv, dv = cw
                                ssum = uv + dv
                                be = lock_breakeven_sum(uv, dv)
                                cs[off] = ssum
                                if lockable_by is None and ssum < be and off <= REACH_MS:
                                    lockable_by = off
                            cost_rows.append(dict(asset=asset, tf=tf, lead=lead,
                                                  **{f"sum_{o}ms": cs.get(o, np.nan) for o in LAT_MS}))
                            reach_rows.append(dict(asset=asset, tf=tf,
                                                   lockable=lockable_by is not None,
                                                   lockable_by_ms=lockable_by if lockable_by is not None else -1))
        print(f"[{asset} {tf}] {time.time()-t0t:.0f}s  slugs_both={n_slug_with_both}  events={n_ev}", flush=True)
        summary.append(dict(asset=asset, tf=tf, slugs_both=n_slug_with_both, events=n_ev))

    # ---- persist raw + build report tables ----
    dwell = pd.DataFrame(dwell_rows)
    cost = pd.DataFrame(cost_rows)
    corr = pd.DataFrame(corr_rows)
    reach = pd.DataFrame(reach_rows)
    dwell.to_csv(OUT / "leg2_dwell.csv", index=False)
    cost.to_csv(OUT / "leg2_cost_evolution.csv", index=False)
    corr.to_csv(OUT / "leg2_crossside_corr.csv", index=False)
    reach.to_csv(OUT / "leg2_reachability.csv", index=False)

    pd.set_option("display.width", 240)
    print("\n" + "=" * 90)
    print("DWELL-TIME DIST (ms) the complement stays lockable (sum<0.97) after a move")
    print("=" * 90)
    dwell_tab = None
    if not dwell.empty:
        g = dwell.groupby(["asset", "tf", "move", "lookback"])
        dwell_tab = g["dwell_ms"].agg(
            n="count",
            frac_lockable_at_t0=lambda x: float((x > 0).mean()),
            p25=lambda x: float(np.percentile(x, 25)),
            p50=lambda x: float(np.percentile(x, 50)),
            p75=lambda x: float(np.percentile(x, 75)),
            p90=lambda x: float(np.percentile(x, 90)),
            max=lambda x: float(np.max(x)),
        ).reset_index()
        print(dwell_tab.to_string(index=False))
        dwell_tab.to_csv(OUT / "leg2_dwell_summary.csv", index=False)

    print("\n" + "=" * 90)
    print("COMPLETE-SET SUM EVOLUTION (move>=0.05/lb10, $25-walk both books)")
    print("=" * 90)
    cost_tab = None
    if not cost.empty:
        sum_cols = [f"sum_{o}ms" for o in LAT_MS]
        cost_tab = cost.groupby(["asset", "tf"])[sum_cols].median().round(4).reset_index()
        cost_tab["n"] = cost.groupby(["asset", "tf"]).size().values
        print("MEDIAN complete-set sum by latency offset:")
        print(cost_tab.to_string(index=False))
        cost_tab.to_csv(OUT / "leg2_cost_summary.csv", index=False)
        print("\nPOOLED median sum by offset:")
        print(cost[sum_cols].median().round(4).to_string())

    print("\n" + "=" * 90)
    print(f"LOCK-REACHABILITY (sum < 0.07-curve breakeven within <= {REACH_MS}ms)")
    print("=" * 90)
    reach_tab = None
    if not reach.empty:
        reach_tab = reach.groupby(["asset", "tf"]).agg(
            n=("lockable", "count"),
            frac_lockable=("lockable", "mean"),
        ).reset_index()
        reach_tab["frac_lockable"] = reach_tab["frac_lockable"].round(4)
        print(reach_tab.to_string(index=False))
        reach_tab.to_csv(OUT / "leg2_reach_summary.csv", index=False)
        print(f"\nPOOLED frac lockable <= {REACH_MS}ms: {reach.lockable.mean():.4f}  (n={len(reach)})")

    print("\n" + "=" * 90)
    print("CROSS-SIDE CORRELATION (ask increments) + how often sum<0.97")
    print("=" * 90)
    corr_tab = None
    if not corr.empty:
        corr_tab = corr.groupby(["asset", "tf"]).agg(
            n_slug=("slug", "count"),
            med_mean_sum=("mean_sum", "median"),
            med_min_sum=("min_sum", "median"),
            med_frac_sum_lt_097=("frac_sum_lt_097", "median"),
            med_ask_incr_corr=("ask_incr_corr", "median"),
        ).round(4).reset_index()
        print(corr_tab.to_string(index=False))
        corr_tab.to_csv(OUT / "leg2_corr_summary.csv", index=False)

    print("\nDONE. CSVs in", OUT, flush=True)
    return dict(dwell_tab=dwell_tab, cost_tab=cost_tab, reach_tab=reach_tab,
                corr_tab=corr_tab, summary=summary)


if __name__ == "__main__":
    run()
