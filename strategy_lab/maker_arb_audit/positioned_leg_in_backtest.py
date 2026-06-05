"""
positioned_leg_in_backtest.py — SEQUENTIAL leg-in positioned maker-arb.

Tests the technique the profitable makers use (and that ACC-M botched by posting
both legs simultaneously). Sequential policy per slug:
  1. Post resting BIDs on BOTH sides at price L1. A maker bid fills when that side's
     best ASK drops to <= L1 (a seller crosses us). Take the FIRST side to fill = leg1
     (cost L1). [Realistically leg1 fills on the side the market is moving AGAINST.]
  2. Now short the other side. Post leg2 bid at price (BUDGET - L1). It fills if the
     OTHER side's ask drops to <= that price before flatten_time (slot_end - FLATTEN).
  3. Completed -> MERGE for $1 (1:1, verified on-chain). pnl/share = (1 - BUDGET) + 2*rebate.
  4. Stuck (leg2 never fills) -> hold leg1 to resolution. pnl/share = (won?1:0) - L1 + rebate.
  5. leg1 never fills -> no trade.

Merge = $1 (no fee, verified vs 0x89b5cdaa 270k shares). Rebate swept {0, 0.0035}.
Fill model: maker bid fills at its price when ask<=bid (ignores queue; mildly optimistic).

Usage: py -X utf8 strategy_lab/maker_arb_audit/positioned_leg_in_backtest.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402

OUT = ROOT / "strategy_lab" / "maker_arb_audit" / "_results"
WIN = {"5m": 300, "15m": 900}
LO = int(pd.Timestamp("2026-05-22", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27", tz="UTC").timestamp())
L1_GRID = [0.45, 0.50]
BUDGET_GRID = [0.94, 0.97]
FLATTEN = 120  # stop completing / hold residual this many s before slot_end
REBATES = [0.0, 0.0035]


def ask_series(arr):
    ts, ap, asz, bp, bsz = arr
    a = ap[:, 0].astype(float)
    ok = np.isfinite(a) & (a > 0) & (a < 1.0)
    return ts.astype(np.int64)[ok], a[ok]


def first_cross(ts, ask, thr, t_after=None, t_before=None):
    m = ask <= thr
    if t_after is not None:
        m &= ts > t_after
    if t_before is not None:
        m &= ts < t_before
    idx = np.argmax(m) if m.any() else -1
    return int(ts[idx]) if (m.any()) else None


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []
    for asset in ["BTC", "ETH", "SOL"]:
        for tf in ["5m", "15m"]:
            pref = f"{asset.lower()}-updown-{tf}-"
            sub = res[(res.ticker == asset) & (res.timeframe == tf)]
            sub = sub[sub.slug.str.startswith(pref)].copy()
            sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
            sub = sub[(sub.ss >= LO) & (sub.ss <= HI)]
            if sub.empty:
                continue
            slugs = set(sub.slug)
            won_up = dict(zip(sub.slug, sub.outcome.str.lower() == "up"))
            t0 = time.time()
            books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
            # precompute per-slug ask series
            ser = {}
            for slug in slugs:
                up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
                if up is None or dn is None:
                    continue
                tu, au = ask_series(up); td, ad = ask_series(dn)
                if au.size < 5 or ad.size < 5:
                    continue
                ser[slug] = (tu, au, td, ad)
            for L1 in L1_GRID:
                for BUD in BUDGET_GRID:
                    b2 = BUD - L1
                    comp = 0; stuck = 0; notrade = 0
                    pnl0 = []; pnlR = []
                    for slug, (tu, au, td, ad) in ser.items():
                        ss = int(slug.rsplit("-", 1)[-1])
                        flat = (ss + WIN[tf] - FLATTEN) * 1_000_000
                        t_up = first_cross(tu, au, L1, t_before=flat)
                        t_dn = first_cross(td, ad, L1, t_before=flat)
                        if t_up is None and t_dn is None:
                            notrade += 1; continue
                        if t_dn is None or (t_up is not None and t_up <= t_dn):
                            leg1, l1t = "up", t_up
                            t2 = first_cross(td, ad, b2, t_after=l1t, t_before=flat)
                        else:
                            leg1, l1t = "dn", t_dn
                            t2 = first_cross(tu, au, b2, t_after=l1t, t_before=flat)
                        if t2 is not None:
                            comp += 1
                            base = (1.0 - BUD)
                            pnl0.append(base); pnlR.append(base)  # rebate added below per-rate
                        else:
                            stuck += 1
                            won = won_up[slug] if leg1 == "up" else (not won_up[slug])
                            base = (1.0 if won else 0.0) - L1
                            pnl0.append(base); pnlR.append(base)
                    n = comp + stuck
                    if n < 30:
                        continue
                    arr = np.array(pnl0)
                    # rebate variants: completed get 2 legs, stuck get 1 leg
                    for reb in REBATES:
                        radd = np.where(np.arange(len(arr)) < comp, 2 * reb, 1 * reb) if False else None
                        # rebuild with correct per-trade rebate
                        radd = np.concatenate([np.full(comp, 2 * reb), np.full(stuck, 1 * reb)])
                        net = arr + radd
                        rows.append(dict(asset=asset, tf=tf, L1=L1, budget=BUD, rebate=reb,
                                         n=n, comp_pct=round(100 * comp / n, 1),
                                         pnl_per_share=round(float(net.mean()), 4),
                                         total=round(float(net.sum()), 1)))
            print(f"[{asset} {tf}] {time.time()-t0:.0f}s slugs={len(ser)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "positioned_leg_in.csv", index=False)
    pd.set_option("display.width", 240)
    print("\n" + "=" * 100)
    print("SEQUENTIAL POSITIONED LEG-IN BACKTEST (merge=$1, fill@bid when ask<=bid)")
    print("=" * 100)
    # aggregate across cells per (L1,budget,rebate)
    agg = (df.groupby(["L1", "budget", "rebate"])
             .apply(lambda g: pd.Series({
                 "n": int(g.n.sum()),
                 "comp_pct": round(float((g.comp_pct * g.n).sum() / g.n.sum()), 1),
                 "pnl_per_share": round(float((g.pnl_per_share * g.n).sum() / g.n.sum()), 4),
                 "total": round(float(g.total.sum()), 1)}), include_groups=False)
             .reset_index())
    print("POOLED across asset/tf:")
    print(agg.to_string(index=False))
    print("\nPer-cell (rebate=0.0035):")
    print(df[df.rebate == 0.0035].sort_values("pnl_per_share", ascending=False).to_string(index=False))
    print(f"\nwrote {OUT/'positioned_leg_in.csv'}")


if __name__ == "__main__":
    run()
