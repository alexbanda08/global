"""
scalp_exit_oos_2026_06_02.py — OOS-robust exit-vs-hold scalp validation

Extends scalp_exit_validation_2026_06_02.py to:
 1. Run on FULL fire universe (delta>=3, BTC+ETH all segments)
 2. Report TIME+90s and TP@0.65 per SEGMENT (bwd_oos/fit_IS/fit_OOS/fwd_oos)
 3. Fee-breakeven sweep: TIME+90s $/tr at fee per-leg = {0,0.01,...,0.07}
 4. Exit-time sweep: {+45,+60,+90,+120,+150,+180s} to find optimal

Usage: C:/Python314/python.exe strategy_lab/directional/scalp_exit_oos_2026_06_02.py
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial

FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
FEE_RATE = 0.07
LAT = 85_000  # 85ms

EXIT_TIMES = [45, 60, 90, 120, 150, 180]  # seconds
FEE_SWEEP = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07]
DELTA_THRESH = 3


def fee_share(v, rate):
    return rate * v * (1.0 - v)


def stat(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return np.nan, np.nan, n
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    t = m / se if se > 0 else np.nan
    return m, t, n


def hold_pnl_07(row):
    """Hold to resolution under 0.07 winner-only fee (production fee model)."""
    if row.won:
        return (1 - row.entry_vwap) * row.shares * (1 - FEE_RATE * row.entry_vwap)
    else:
        return -row.entry_vwap * row.shares


def roundtrip(exit_vwap, entry_vwap, shares, fee_rate):
    rt = (exit_vwap - entry_vwap) * shares
    if fee_rate > 0:
        rt -= (fee_share(entry_vwap, fee_rate) + fee_share(exit_vwap, fee_rate)) * shares
    return rt


def run():
    t0 = time.time()
    F = pd.read_parquet(FIRES)
    F = F[(F.asset.isin(["BTC", "ETH"])) & (F.delta_bps >= DELTA_THRESH)].copy()
    print(f"universe: {len(F)} fires (BTC+ETH delta>={DELTA_THRESH})", flush=True)
    print(f"segments: {F.groupby('segment').size().to_dict()}", flush=True)

    cfg = LiveMimicConfig()
    recs = []

    for asset in ["BTC", "ETH"]:
        sub = F[F.asset == asset]
        if sub.empty:
            continue
        slugs = set(sub.slug.values)
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
        print(f"[{asset}] L25 loaded n_slugs={len(slugs)} t={time.time()-t0:.0f}s", flush=True)

        for _, r in sub.iterrows():
            slug = r.slug
            side = r.direction
            ss = int(r.slot_start)
            fire_us = int(r.fire_us)
            shares = float(r.shares)
            ev = float(r.entry_vwap)
            won = bool(r.won)
            win = WIN[r.tf]
            slot_end = (ss + win) * 1_000_000

            def bid_walk_at(ts):
                bk = find_book_strict(books, slug, side, int(ts) + LAT,
                                      max_staleness_us=cfg.max_book_staleness_us)
                if bk is None or not len(bk.get("bp", [])):
                    return None
                vwap, fsh, _usd = sell_at_bid_partial(
                    np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), shares)
                return vwap if fsh > 0 else None

            # time exits
            time_exits = {}
            for dt in EXIT_TIMES:
                ts = fire_us + dt * 1_000_000
                if ts < slot_end:
                    time_exits[dt] = bid_walk_at(ts)
                else:
                    time_exits[dt] = None

            # TP@0.65 — scan at 10s intervals
            tp065_vwap = None
            t_scan = fire_us
            while t_scan < slot_end:
                bk = find_book_strict(books, slug, side, t_scan + LAT,
                                      max_staleness_us=cfg.max_book_staleness_us)
                if bk is not None and len(bk.get("bp", [])):
                    bb = float(bk["bp"][0])
                    if bb >= 0.65:
                        vw, fsh, _u = sell_at_bid_partial(
                            np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), shares)
                        if fsh > 0:
                            tp065_vwap = vw
                            break
                t_scan += 10_000_000  # 10s steps

            rec = dict(
                slug=slug, asset=asset, tf=r.tf, side=side, won=won,
                entry_vwap=ev, shares=shares,
                hold_pnl=float(r.pnl),
                segment=r.segment,
                tp065=tp065_vwap,
            )
            for dt in EXIT_TIMES:
                rec[f"time{dt}"] = time_exits[dt]
            recs.append(rec)

        del books

    R = pd.DataFrame(recs)
    R.to_parquet(OUT / "scalp_exit_oos_2026_06_02.parquet", index=False)
    print(f"\nProcessed {len(R)} rows in {time.time()-t0:.0f}s", flush=True)

    # ── helper ───────────────────────────────────────────────────────────────
    def eval_exit(col, fee_rate, fallback_to_hold=True):
        """Return per-fire PnL list; if exit not hit, fall back to hold (07 winner-only)."""
        pnls = []
        for _, x in R.iterrows():
            ex = x[col]
            if pd.notna(ex):
                pnls.append(roundtrip(ex, x.entry_vwap, x.shares, fee_rate))
            elif fallback_to_hold:
                pnls.append(hold_pnl_07(x))
        return pnls

    # ── SECTION 1: per-segment table ─────────────────────────────────────────
    print("\n" + "=" * 90)
    print("SECTION 1: PER-SEGMENT — TIME+90s and TP@0.65 (fallback=hold, fee=0 and fee=0.07 both legs)")
    print(f"{'segment':<12}{'n':>5}{'HOLD$/tr':>10}{'HOLD_t':>8}"
          f"{'T90_f0$/tr':>12}{'T90_f0_t':>9}{'T90_f07$/tr':>12}{'T90_f07_t':>10}"
          f"{'TP65_f0$/tr':>13}{'TP65_f0_t':>10}{'TP65_f07$/tr':>13}{'TP65_f07_t':>11}")
    print("-" * 90)

    for seg in ["bwd_oos", "fit_IS", "fit_OOS", "fwd_oos"]:
        Rs = R[R.segment == seg]
        if len(Rs) < 5:
            continue
        # hold
        h = Rs.apply(hold_pnl_07, axis=1).to_numpy()
        mh, th, nh = stat(h)
        # time90
        t90_f0 = []
        t90_f07 = []
        tp65_f0 = []
        tp65_f07 = []
        for _, x in Rs.iterrows():
            # time90
            ex90 = x["time90"]
            if pd.notna(ex90):
                t90_f0.append(roundtrip(ex90, x.entry_vwap, x.shares, 0.0))
                t90_f07.append(roundtrip(ex90, x.entry_vwap, x.shares, 0.07))
            else:
                hp = hold_pnl_07(x)
                t90_f0.append(hp)
                t90_f07.append(hp)
            # tp065
            ex65 = x["tp065"]
            if pd.notna(ex65):
                tp65_f0.append(roundtrip(ex65, x.entry_vwap, x.shares, 0.0))
                tp65_f07.append(roundtrip(ex65, x.entry_vwap, x.shares, 0.07))
            else:
                hp = hold_pnl_07(x)
                tp65_f0.append(hp)
                tp65_f07.append(hp)

        m90f0, t90f0, _ = stat(t90_f0)
        m90f7, t90f7, _ = stat(t90_f07)
        m65f0, t65f0, _ = stat(tp65_f0)
        m65f7, t65f7, _ = stat(tp65_f07)

        n_reach90 = sum(pd.notna(x["time90"]) for _, x in Rs.iterrows())
        print(f"{seg:<12}{len(Rs):>5}{mh:>10.3f}{th:>8.2f}"
              f"{m90f0:>12.3f}{t90f0:>9.2f}{m90f7:>12.3f}{t90f7:>10.2f}"
              f"{m65f0:>13.3f}{t65f0:>10.2f}{m65f7:>13.3f}{t65f7:>11.2f}")

    # ALL combined
    h_all = R.apply(hold_pnl_07, axis=1).to_numpy()
    mh_all, th_all, n_all = stat(h_all)
    t90_f0_all, t90_f07_all, tp65_f0_all, tp65_f07_all = [], [], [], []
    for _, x in R.iterrows():
        ex90 = x["time90"]
        if pd.notna(ex90):
            t90_f0_all.append(roundtrip(ex90, x.entry_vwap, x.shares, 0.0))
            t90_f07_all.append(roundtrip(ex90, x.entry_vwap, x.shares, 0.07))
        else:
            hp = hold_pnl_07(x)
            t90_f0_all.append(hp)
            t90_f07_all.append(hp)
        ex65 = x["tp065"]
        if pd.notna(ex65):
            tp65_f0_all.append(roundtrip(ex65, x.entry_vwap, x.shares, 0.0))
            tp65_f07_all.append(roundtrip(ex65, x.entry_vwap, x.shares, 0.07))
        else:
            hp = hold_pnl_07(x)
            tp65_f0_all.append(hp)
            tp65_f07_all.append(hp)
    m90f0_all, t90f0_all, _ = stat(t90_f0_all)
    m90f7_all, t90f7_all, _ = stat(t90_f07_all)
    m65f0_all, t65f0_all, _ = stat(tp65_f0_all)
    m65f7_all, t65f7_all, _ = stat(tp65_f07_all)
    print("-" * 90)
    print(f"{'ALL':<12}{n_all:>5}{mh_all:>10.3f}{th_all:>8.2f}"
          f"{m90f0_all:>12.3f}{t90f0_all:>9.2f}{m90f7_all:>12.3f}{t90f7_all:>10.2f}"
          f"{m65f0_all:>13.3f}{t65f0_all:>10.2f}{m65f7_all:>13.3f}{t65f7_all:>11.2f}")

    # ── SECTION 2: fee breakeven sweep (TIME+90s) ────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 2: FEE-BREAKEVEN SWEEP — TIME+90s $/tr + t-stat vs fee-per-leg")
    print(f"{'fee_rate':>10}{'$/tr':>10}{'t-stat':>10}{'significant':>14}")
    print("-" * 44)
    for fee in FEE_SWEEP:
        pnls = []
        for _, x in R.iterrows():
            ex90 = x["time90"]
            if pd.notna(ex90):
                pnls.append(roundtrip(ex90, x.entry_vwap, x.shares, fee))
            else:
                pnls.append(hold_pnl_07(x))
        m, t, _ = stat(pnls)
        sig = "YES (t>=2)" if abs(t) >= 2 else "no"
        print(f"{fee:>10.2f}{m:>10.3f}{t:>10.2f}{sig:>14}")

    # ── SECTION 3: exit-time sweep ───────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 3: EXIT-TIME SWEEP — fee=0 (left) and fee=0.07 both legs (right)")
    print(f"{'exit_time':>11}{'reach%':>8}{'f0_$/tr':>10}{'f0_t':>8}{'f07_$/tr':>10}{'f07_t':>8}")
    print("-" * 60)

    # first: hold baseline
    print(f"{'HOLD':>11}{'100%':>8}{mh_all:>10.3f}{th_all:>8.2f}{mh_all:>10.3f}{th_all:>8.2f}")

    for dt in EXIT_TIMES:
        col = f"time{dt}"
        f0_pnl, f07_pnl = [], []
        reached = 0
        total = len(R)
        for _, x in R.iterrows():
            ex = x[col]
            if pd.notna(ex):
                reached += 1
                f0_pnl.append(roundtrip(ex, x.entry_vwap, x.shares, 0.0))
                f07_pnl.append(roundtrip(ex, x.entry_vwap, x.shares, 0.07))
            else:
                hp = hold_pnl_07(x)
                f0_pnl.append(hp)
                f07_pnl.append(hp)
        mf0, tf0, _ = stat(f0_pnl)
        mf7, tf7, _ = stat(f07_pnl)
        print(f"{'+'+str(dt)+'s':>11}{100*reached/total:>7.0f}%{mf0:>10.3f}{tf0:>8.2f}{mf7:>10.3f}{tf7:>8.2f}")

    print(f"\nTotal runtime: {time.time()-t0:.0f}s")
    print(f"Sanity check — check $/tr within ±$25 above. If not, unpacking bug.")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    run()
