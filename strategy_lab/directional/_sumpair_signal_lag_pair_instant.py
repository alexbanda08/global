"""
SUM-PAIR VARIANT 1 — LAG-GATED INSTANT PAIR (2026-06-13).

THE UNTESTED GAP (operator directive): use the VALIDATED Binance->Polymarket lag signal
(|bar-END causal ret|*1e4 >= 3) to acquire the cheap LAGGING leg, then IMMEDIATELY pair the
OTHER side (taker book-walk its ask at the SAME decision+85ms instant). HOLD BOTH to chainlink
resolution. This differs from every prior pairing test (V1-V12): the 2nd leg is NOT passively
price/inventory-gated and NOT maker-resting -- it is lifted instantly at the lag-fire moment.

EXPECTED RISK (operator stated, MUST quantify): at the lag instant the OTHER side is
lag-EXPENSIVE -> paired sum ~ overround. We measure exactly how expensive.

CAUSALITY (NON-NEGOTIABLE, reuse scalp_causal_asof_oneshot_2026_06_12 definitions):
  1. Signal = causal bar-END asof on klines_1s. ret_C(t) = closeEND(t)/closeEND(t-5s)-1
     where closeEND(t) = bar whose END (start+1e6) <= t. NEVER bar-START.
  2. Causal rolling decision grid within each window: ticks every 5s from ss+5s..slot_end-65s.
     First eligible tick (|ret_C|*1e4>=3 AND signal-leg book-walk vwap<0.55) is the FIRE.
     Signal uses data <= decision time only.
  3. FILL at decision + 85ms latency. L25 native 10Hz (subsample_1hz=False), stream per-slug.
  4. SETTLE from CHAINLINK (load_resolutions outcome) for ALL gated slugs.
  5. FEE = winner-only 0.07*p*(1-p) on the winning leg, $0 loser, fee-free redeem.

ARMS (same fires):
  A [PRIMARY]   instant-pair both legs, HOLD both to resolution.
  B [CONTROL]   deployed scalp: +60s time-sell the SIGNAL (lagging) leg only, NO pairing.
  (ref)         pure-hold signal leg only to resolution (no pairing, no sell).

GRID (pre-declared trials = 6 cells): {BTC,ETH,SOL} x {5m,15m}. One config.
SPLITS: IS Apr22-May20 | OOS May21-Jun11.

DECISION (pre-registered, written before any PnL): edge-found ONLY if
  (1) ArmA OOS net/slug CI95_lo>0 AND (2) ArmA beats ArmB paired-diff CI95 excludes 0
  AND (3) paired sum<1 real (median paircost<1 on material fraction) AND (4) bar-END asof.
  Else dead (or breakeven if CI straddles 0).

Book-walk fill: top-of-book $25, size-capped via resolve_size (artifact sizes), spread<=0.05
on the signal leg (production gate); the PAIR leg is a forced taker lift -> we walk its top ask
at the same instant WITHOUT the spread gate (we are intentionally crossing to lock the pair),
size-capped to match the signal-leg share count (true pair: equal shares both sides).
"""
from __future__ import annotations
import os, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from load import load_resolutions, load_orderbook_l25_streaming           # noqa: E402
from scalp_fill_lib_2026_06_10 import (entry_fill, exit_fill, resolve_size,  # noqa: E402
                                       held_value, boot, cell)

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(exist_ok=True)

LAT_US = 85_000
STAKE = 25.0
SPREAD = 0.05
FEE = 0.07
DELTA_BPS = 3.0
LOOKBACK_US = 5_000_000        # 5s causal lag window (same as the deployed scalp signal)
GRID_STEP_US = 5_000_000       # decision grid cadence
VWAP_GATE = 0.55               # production scalp entry gate on the SIGNAL leg
CHUNK = 120

COINS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m"]
IS_LO = pd.Timestamp("2026-04-22", tz="UTC").value // 1000
IS_HI = pd.Timestamp("2026-05-20", tz="UTC").value // 1000
OOS_LO = pd.Timestamp("2026-05-21", tz="UTC").value // 1000
OOS_HI = pd.Timestamp("2026-06-11", tz="UTC").value // 1000


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    starts = df.time_period_start_us.values.astype("int64")
    return starts + 1_000_000, df.price_close.values.astype(float)   # (ENDS, close)


def asof_on(ts, v, t):
    """Scalar/array causal asof: value of last entry with ts <= t."""
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def book_walk_ask(ap_row, asz_row, stake):
    """Walk the L25 ask ladder to fill ~stake notional. Returns (vwap, shares_filled, depth_avail)."""
    spent = 0.0; shares = 0.0
    for lvl in range(ap_row.shape[0]):
        px = ap_row[lvl]; sz = asz_row[lvl]
        if not (np.isfinite(px) and px > 0):
            break
        if not (np.isfinite(sz) and sz > 0):
            continue
        budget = stake - spent
        if budget <= 1e-9:
            break
        want_sh = budget / px
        take = min(want_sh, sz)
        shares += take; spent += take * px
        if spent >= stake - 1e-9:
            break
    if shares <= 0:
        return np.nan, 0.0, 0.0
    return spent / shares, shares, shares


_L25_COLS = (["timestamp_us", "slug", "outcome"] +
             [f"ask_price_{i}" for i in range(25)] + [f"ask_size_{i}" for i in range(25)] +
             [f"bid_price_{i}" for i in range(25)] + [f"bid_size_{i}" for i in range(25)])


def load_l25_window(asset, slugs, min_ts_us, max_ts_us):
    """Row-group-pruned native-10Hz L25 reader -> dict[(slug,outcome)] -> (ts,ap,asz,bp,bsz).

    The canonical parquet is time-ordered with per-row-group timestamp_us stats; we read ONLY
    the row groups whose [min,max] overlaps [min_ts_us,max_ts_us]. Far faster than the generic
    loader (which scans all 837 row groups every call). Same record layout as
    load_orderbook_l25_streaming. Memory-bounded: only the windowed slug set, one chunk at a time.
    """
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import pyarrow as pa
    p = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / f"{asset.lower()}.parquet"
    pf = pq.ParquetFile(str(p))
    ts_ci = pf.schema_arrow.names.index("timestamp_us")
    rgs = []
    for i in range(pf.num_row_groups):
        st = pf.metadata.row_group(i).column(ts_ci).statistics
        if st is None or not (st.max < min_ts_us or st.min > max_ts_us):
            rgs.append(i)
    if not rgs:
        return {}
    slugs_arr = pa.array(sorted(slugs))
    ap_c = [f"ask_price_{i}" for i in range(25)]; as_c = [f"ask_size_{i}" for i in range(25)]
    bp_c = [f"bid_price_{i}" for i in range(25)]; bs_c = [f"bid_size_{i}" for i in range(25)]
    parts = []
    for rg in rgs:
        tbl = pf.read_row_group(rg, columns=_L25_COLS)
        m = pc.is_in(tbl.column("slug"), value_set=slugs_arr)
        m = pc.and_(m, pc.and_(pc.greater_equal(tbl.column("timestamp_us"), pa.scalar(min_ts_us, pa.int64())),
                               pc.less_equal(tbl.column("timestamp_us"), pa.scalar(max_ts_us, pa.int64()))))
        if pc.sum(m).as_py() == 0:
            continue
        parts.append(tbl.filter(m).to_pandas())
    if not parts:
        return {}
    df = pd.concat(parts, ignore_index=True)
    out = {}
    for (sl, oc), g in df.groupby(["slug", "outcome"], sort=False):
        g = g.sort_values("timestamp_us")
        out[(sl, oc)] = (g.timestamp_us.values.astype("int64"),
                         g[ap_c].values.astype(float), g[as_c].values.astype(float),
                         g[bp_c].values.astype(float), g[bs_c].values.astype(float))
    return out


def pair_settle(sh, p_sig, p_pair, sig_won):
    """Both legs held to resolution. Exactly one wins. Winner-only 0.07 fee on the winning leg.
    sig_won True -> signal leg wins (pays (1-p_sig)(1-fee*p_sig)), pair leg loses (-p_pair).
    Returns per-leg pnl on `sh` shares each (equal-share pair)."""
    if sig_won:
        p_w, p_l = p_sig, p_pair
    else:
        p_w, p_l = p_pair, p_sig
    return sh * ((1 - p_w) * (1 - FEE * p_w) - p_l)


def main():
    t0 = time.time()
    res = load_resolutions(assets=COINS, timeframes=TFS)
    res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug").copy()
    print(f"resolutions: {len(res)} prod slugs  t={time.time()-t0:.0f}s", flush=True)

    rows = []
    feas = {}  # (coin,tf) -> dict of feasibility counters

    for coin in COINS:
        ends, close = unified_1s(coin)
        d = res[(res.ticker == coin) & res.timeframe.isin(TFS) &
                (res.slot_start_us >= IS_LO) & (res.slot_start_us <= OOS_HI)].copy()
        d = d.sort_values("slot_start_us").reset_index(drop=True)
        if len(d) == 0:
            print(f"=== {coin}: no slugs ==="); continue
        meta = {r.slug: (int(r.slot_start_us), int(r.slot_end_us), r.outcome, r.timeframe)
                for _, r in d.iterrows()}
        for tf in TFS:
            feas[(coin, tf)] = dict(n_windows=int((d.timeframe == tf).sum()), n_grid=0, fired=0)

        # ONE sequential row-group pass over the coin's L25 file; buffer books per (slug,outcome)
        # and evaluate+evict each slug once the read cursor advances past its slot_end+buffer.
        import pyarrow.parquet as pq
        import pyarrow.compute as pc
        import pyarrow as pa
        p = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / f"{coin.lower()}.parquet"
        pf = pq.ParquetFile(str(p))
        ts_ci = pf.schema_arrow.names.index("timestamp_us")
        slugs_arr = pa.array(sorted(meta))
        ap_c = [f"ask_price_{i}" for i in range(25)]; as_c = [f"ask_size_{i}" for i in range(25)]
        bp_c = [f"bid_price_{i}" for i in range(25)]; bs_c = [f"bid_size_{i}" for i in range(25)]
        WLO = IS_LO; WHI = OOS_HI  # us bounds for prod window (IS_LO/OOS_HI already in us)
        buf = {}        # slug -> {"Up":[list of arrays], "Down":[...]} accumulated row-group slices
        done = set()
        EVICT_PAD = 2_000_000

        def evaluate(slug):
            ss, se, out, tf = meta[slug]
            recs = buf.pop(slug, None)
            # build per-side arrays
            def assemble(side):
                lst = recs.get(side) if recs else None
                if not lst:
                    return None
                ts = np.concatenate([a[0] for a in lst])
                ap = np.concatenate([a[1] for a in lst]); asz = np.concatenate([a[2] for a in lst])
                bp = np.concatenate([a[3] for a in lst]); bsz = np.concatenate([a[4] for a in lst])
                o = np.argsort(ts, kind="stable")
                return ts[o], ap[o], asz[o], bp[o], bsz[o]
            rec_up = assemble("Up"); rec_dn = assemble("Down")
            if rec_up is None or rec_dn is None:
                return
            grid = np.arange(ss + 5_000_000, se - 65_000_000 + 1, GRID_STEP_US)
            if len(grid) == 0:
                return
            feas[(coin, tf)]["n_grid"] += 1
            fire = None
            for t_dec in grid:
                c_now = asof_on(ends, close, t_dec)
                c_prev = asof_on(ends, close, t_dec - LOOKBACK_US)
                if not (np.isfinite(c_now) and np.isfinite(c_prev) and c_prev > 0):
                    continue
                ret = c_now / c_prev - 1.0
                dlt = abs(ret) * 1e4
                if dlt < DELTA_BPS:
                    continue
                lead = "Up" if ret > 0 else "Down"
                sig_rec = rec_up if lead == "Up" else rec_dn
                pair_rec = rec_dn if lead == "Up" else rec_up
                ts_s, ap_s, asz_s, bp_s, bsz_s = sig_rec
                ent = entry_fill(ts_s, ap_s[:, 0], asz_s[:, 0],
                                 int(t_dec) + LAT_US, STAKE, SPREAD, bp_s[:, 0])
                if ent is None:
                    continue
                ev_sig = ent["ev"]
                if ev_sig >= VWAP_GATE:
                    continue
                ts_p, ap_p, asz_p, bp_p, bsz_p = pair_rec
                jp = int(np.searchsorted(ts_p, int(t_dec) + LAT_US, "right")) - 1
                if jp < 0:
                    continue
                ev_pair, sh_pair, _ = book_walk_ask(ap_p[jp], asz_p[jp], STAKE)
                if not np.isfinite(ev_pair) or sh_pair <= 0:
                    continue
                fire = dict(t_dec=int(t_dec), lead=lead, ret=ret, delta=dlt,
                            ev_sig=ev_sig, sh_sig=ent["shares"], entry_idx=ent["entry_idx"],
                            ev_pair=ev_pair, sh_pair=sh_pair)
                break
            if fire is None:
                return
            feas[(coin, tf)]["fired"] += 1
            sig_won = (fire["lead"] == "Up") == (out == "Up")
            sh = min(fire["sh_sig"], fire["sh_pair"])
            paircost = fire["ev_sig"] + fire["ev_pair"]
            pnlA = pair_settle(sh, fire["ev_sig"], fire["ev_pair"], sig_won)
            sig_rec2 = rec_up if fire["lead"] == "Up" else rec_dn
            ts_s, ap_s, asz_s, bp_s, bsz_s = sig_rec2
            ext = min(fire["t_dec"] + 60_000_000, se)
            ef = exit_fill(ts_s, bp_s[:, 0], bsz_s[:, 0], fire["entry_idx"], ext,
                           fire["sh_sig"], fire["ev_sig"], sig_won)
            pnlB = ef["pnl"]
            pnl_hold = held_value(fire["sh_sig"], fire["ev_sig"], sig_won)
            split = "IS" if ss <= IS_HI else "OOS"
            rows.append(dict(coin=coin, tf=tf, slug=slug, split=split,
                             slot_start_us=ss, t_dec=fire["t_dec"], offset_s=(fire["t_dec"] - ss) / 1e6,
                             lead=fire["lead"], delta=fire["delta"], sig_won=sig_won,
                             ev_sig=fire["ev_sig"], ev_pair=fire["ev_pair"], paircost=paircost,
                             sub1=bool(paircost < 1.0), sh_pair=sh,
                             pnlA=pnlA, pnlB=pnlB, pnl_hold=pnl_hold, diff_AB=pnlA - pnlB))

        for rg in range(pf.num_row_groups):
            st = pf.metadata.row_group(rg).column(ts_ci).statistics
            if st is not None and (st.max < WLO or st.min > WHI):
                continue
            tbl = pf.read_row_group(rg, columns=_L25_COLS)
            m = pc.is_in(tbl.column("slug"), value_set=slugs_arr)
            if pc.sum(m).as_py() == 0:
                del tbl; continue
            g = tbl.filter(m).to_pandas(); del tbl
            for (sl, oc), sub in g.groupby(["slug", "outcome"], sort=False):
                if sl in done:
                    continue
                sub = sub.sort_values("timestamp_us")
                arr = (sub.timestamp_us.values.astype("int64"),
                       sub[ap_c].values.astype(float), sub[as_c].values.astype(float),
                       sub[bp_c].values.astype(float), sub[bs_c].values.astype(float))
                buf.setdefault(sl, {}).setdefault(oc, []).append(arr)
            # evict + evaluate slugs whose window fully ended before this rg's MIN time
            rg_min = st.min if st is not None else None
            if rg_min is not None:
                ready = [sl for sl in list(buf) if meta[sl][1] + EVICT_PAD < rg_min]
                for sl in ready:
                    evaluate(sl); done.add(sl)
            del g
            if rg % 100 == 0:
                print(f"  {coin} rg {rg}/{pf.num_row_groups} buf={len(buf)} done={len(done)} "
                      f"rows={len(rows)}  t={time.time()-t0:.0f}s", flush=True)
        # flush remaining buffered slugs
        for sl in list(buf):
            if sl not in done:
                evaluate(sl); done.add(sl)
        for tf in TFS:
            v = feas[(coin, tf)]
            print(f"=== {coin} {tf}: windows={v['n_windows']} grid-eligible={v['n_grid']} "
                  f"FIRED={v['fired']} ({v['fired']/max(v['n_grid'],1):.1%})  t={time.time()-t0:.0f}s",
                  flush=True)

    R = pd.DataFrame(rows)
    outp = OUT / "sumpair_signal_lag_pair_instant_2026_06_13.parquet"
    R.to_parquet(outp, index=False)
    print(f"\nsaved {len(R)} fires -> {outp}  t={time.time()-t0:.0f}s", flush=True)

    if len(R) == 0:
        print("\n*** NO FIRES — FEASIBILITY-DEAD ***")
        return

    # ---- FEASIBILITY (pre-registered, reported BEFORE PnL) ----
    print("\n" + "=" * 90)
    print("FEASIBILITY (fires per coin x tf):")
    for k, v in feas.items():
        print(f"  {k[0]} {k[1]}: {v['fired']:5d} fires / {v['n_grid']:5d} grid-eligible windows "
              f"= {v['fired']/max(v['n_grid'],1):.1%}")
    tot_fired = sum(v["fired"] for v in feas.values())
    tot_grid = sum(v["n_grid"] for v in feas.values())
    print(f"  TOTAL: {tot_fired}/{tot_grid} = {tot_fired/max(tot_grid,1):.1%}")

    # ---- PAIRED SUM ----
    print("\n" + "=" * 90)
    print("PAIRED SUM (paircost = ev_sig + ev_pair):")
    print(f"  median paircost   = {R.paircost.median():.4f}")
    print(f"  mean   paircost   = {R.paircost.mean():.4f}")
    print(f"  %% sub-1 (sum<1)   = {R.sub1.mean():.1%}")
    print(f"  ev_sig  median    = {R.ev_sig.median():.4f}  (the cheap lagging leg)")
    print(f"  ev_pair median    = {R.ev_pair.median():.4f}  (the lag-EXPENSIVE other side)")

    # ---- PnL per arm, IS/OOS ----
    print("\n" + "=" * 90)
    for split in ["IS", "OOS", "ALL"]:
        sub = R if split == "ALL" else R[R.split == split]
        print(f"\n--- {split} (n={len(sub)}) ---")
        print(f"  ARM A (instant-pair hold) : {cell(sub.pnlA.values)}")
        print(f"  ARM B (ctrl +60s sell)    : {cell(sub.pnlB.values)}")
        print(f"  ref pure-hold sig leg     : {cell(sub.pnl_hold.values)}")
        if len(sub) >= 5:
            dlo, dhi = boot(sub.diff_AB.values)
            print(f"  PAIRED A-B: mean={sub.diff_AB.mean():+.4f} CI[{dlo:+.4f},{dhi:+.4f}]")

    # ex-top2 robustness on OOS Arm A
    oos = R[R.split == "OOS"]
    if len(oos) >= 5:
        s = np.sort(oos.pnlA.values)[::-1]
        ex2 = s[2:]
        print(f"\nOOS Arm A ex-top2: n={len(ex2)} $/slug={ex2.mean():+.4f}")

    # per-coin-tf OOS Arm A
    print("\nper coin x tf (OOS) Arm A vs Arm B:")
    for coin in COINS:
        for tf in TFS:
            sub = oos[(oos.coin == coin) & (oos.tf == tf)]
            if len(sub) >= 5:
                la, ha = boot(sub.pnlA.values)
                print(f"  {coin} {tf}: n={len(sub)} A={sub.pnlA.mean():+.3f} CI[{la:+.3f},{ha:+.3f}] "
                      f"B={sub.pnlB.mean():+.3f}  A-B={sub.diff_AB.mean():+.3f}  paircost_med={sub.paircost.median():.3f}")

    print(f"\ntrials this script: 6 cells (3 coins x 2 tf), single config")
    print(f"done t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
