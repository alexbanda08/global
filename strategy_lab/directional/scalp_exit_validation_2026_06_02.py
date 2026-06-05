"""
scalp_exit_validation_2026_06_02.py — FAST validation of the intra-window SCALP idea:
does SELLING the lag-taker token on the book mid-window beat HOLD-to-resolution?

Tests (on the existing lag_taker_fires_oos universe, BTC+ETH, delta>=5, native-10Hz L25):
  baseline   HOLD to resolution (0.07 winner-only fee)           [from parquet pnl, recomputed]
  TP@0.60/.65/.70  sell when best-bid of held token >= target (scan fire->slot_end @10s)
  TIME@+90s/+half  sell at the bid at a fixed time into the window
Round-trip PnL = (exit_vwap_bid - entry_vwap_ask)*shares - fees, under fee scenarios:
  FEE0  (feeRate=0, best case — the spread IS the cost)   |  FEE07 (0.07 taker curve BOTH legs, worst)
Also S2 STALE-LOCK: was the entry ask frozen >=N(=10) snaps (~1s) before fire? split entry quality.
Usage: C:/Python314/python.exe strategy_lab/directional/scalp_exit_validation_2026_06_02.py
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial  # noqa: E402

FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
FEE = 0.07
LAT = 85_000  # 85ms


def fee_share(v):  # poly taker curve per share
    return FEE * v * (1.0 - v)


def stat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def run():
    t0 = time.time()
    F = pd.read_parquet(FIRES)
    F = F[(F.asset.isin(["BTC", "ETH"])) & (F.delta_bps >= 5)].copy()
    print(f"universe: {len(F)} fires (BTC+ETH delta>=5)", flush=True)
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
            slug = r.slug; side = r.direction; ss = int(r.slot_start)
            fire_us = int(r.fire_us); shares = float(r.shares); ev = float(r.entry_vwap)
            won = bool(r.won); win = WIN[r.tf]; slot_end = (ss + win) * 1_000_000
            # STALE-LOCK: best-ask of held token frozen over the 10 snaps before fire?
            ask_now = None; frozen = None
            b0 = find_book_strict(books, slug, side, fire_us + LAT, max_staleness_us=cfg.max_book_staleness_us)
            if b0 is not None and len(b0.get("ap", [])):
                ask_now = float(b0["ap"][0])
                prev = find_book_strict(books, slug, side, fire_us - 1_000_000, max_staleness_us=cfg.max_book_staleness_us)
                if prev is not None and len(prev.get("ap", [])):
                    frozen = abs(float(prev["ap"][0]) - ask_now) < 1e-9
            # EXIT scans
            def bid_walk_at(ts):
                bk = find_book_strict(books, slug, side, int(ts) + LAT, max_staleness_us=cfg.max_book_staleness_us)
                if bk is None or not len(bk.get("bp", [])):
                    return None
                vwap, fsh, _usd = sell_at_bid_partial(np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), shares)
                return vwap if fsh > 0 else None
            # scan for target hits + record exit vwap
            targets = {"TP060": 0.60, "TP065": 0.65, "TP070": 0.70}
            hit_vwap = {k: None for k in targets}
            t_scan = fire_us
            while t_scan < slot_end:
                bk = find_book_strict(books, slug, side, t_scan + LAT, max_staleness_us=cfg.max_book_staleness_us)
                if bk is not None and len(bk.get("bp", [])):
                    bb = float(bk["bp"][0])
                    for k, tgt in targets.items():
                        if hit_vwap[k] is None and bb >= tgt:
                            vw, fsh, _u = sell_at_bid_partial(np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), shares)
                            if fsh > 0:
                                hit_vwap[k] = vw
                t_scan += 10_000_000  # 10s steps
            ev_time90 = bid_walk_at(fire_us + 90_000_000)
            ev_timeh = bid_walk_at(fire_us + (win // 2) * 1_000_000)
            recs.append(dict(slug=slug, asset=asset, tf=r.tf, side=side, won=won,
                             entry_vwap=ev, shares=shares, hold_pnl=float(r.pnl),
                             stale_frozen=frozen, ask_at_fire=ask_now,
                             tp060=hit_vwap["TP060"], tp065=hit_vwap["TP065"], tp070=hit_vwap["TP070"],
                             time90=ev_time90, timeh=ev_timeh))
        del books
    R = pd.DataFrame(recs)
    R.to_parquet(OUT / "scalp_exit_validation_2026_06_02.parquet", index=False)

    def roundtrip(exit_vwap, ev, shares, fee):
        # if target never hit -> fall back to HOLD (won*1 settle), handled by caller
        rt = (exit_vwap - ev) * shares
        if fee:
            rt -= (fee_share(ev) + fee_share(exit_vwap)) * shares
        return rt

    print("\n" + "=" * 86)
    print("SCALP EXIT vs HOLD — lag-taker fires (BTC+ETH delta>=5). $/tr; FEE0=no fee, FEE07=0.07 both legs")
    print("exit=target: if bid hit target -> scalp PnL; else FALL BACK to hold-to-resolution")
    print("=" * 86)
    n = len(R)
    # hold baseline (recompute under 0.07 winner-only)
    hold = R.apply(lambda x: (1 - x.entry_vwap) * x.shares * (1 - FEE * x.entry_vwap) if x.won else -x.entry_vwap * x.shares, axis=1).to_numpy()
    mh, th = stat(hold)
    print(f"{'policy':<14}{'n':>5}{'%reach':>8}{'$/tr_FEE0':>11}{'t_FEE0':>8}{'$/tr_FEE07':>12}{'t_FEE07':>9}")
    print(f"{'HOLD(base)':<14}{n:>5}{'-':>8}{mh:>11.3f}{th:>8.2f}{mh:>12.3f}{th:>9.2f}")
    for pol, col in [("TP@0.60", "tp060"), ("TP@0.65", "tp065"), ("TP@0.70", "tp070"),
                     ("TIME+90s", "time90"), ("TIME+half", "timeh")]:
        for fee in [0.0, FEE]:
            pnl = []
            reached = 0
            for _, x in R.iterrows():
                ex = x[col]
                if pd.notna(ex):
                    reached += 1
                    pnl.append(roundtrip(ex, x.entry_vwap, x.shares, fee))
                else:
                    # fall back to hold
                    pnl.append((1 - x.entry_vwap) * x.shares * (1 - FEE * x.entry_vwap) if x.won else -x.entry_vwap * x.shares)
            m, t = stat(pnl)
            if fee == 0.0:
                line = f"{pol:<14}{n:>5}{100*reached/n:>7.0f}%{m:>11.3f}{t:>8.2f}"
            else:
                print(line + f"{m:>12.3f}{t:>9.2f}")
    # S2 stale-lock split (hold pnl by frozen entry)
    print("\n--- S2 STALE-LOCK: entry quality by ask-frozen-before-fire ---")
    for fr, lab in [(True, "frozen"), (False, "not_frozen")]:
        g = R[R.stale_frozen == fr]
        if len(g) >= 5:
            hp = g.apply(lambda x: (1 - x.entry_vwap) * x.shares * (1 - FEE * x.entry_vwap) if x.won else -x.entry_vwap * x.shares, axis=1)
            m, t = stat(hp.to_numpy())
            print(f"  {lab:<11} n={len(g):>4} WR={100*g.won.mean():.1f}% mean_entry_vwap={g.entry_vwap.mean():.3f} hold$/tr={m:+.3f} t={t:.2f}")
    print(f"\ntotal {time.time()-t0:.0f}s ; wrote scalp_exit_validation_2026_06_02.parquet")


if __name__ == "__main__":
    run()
