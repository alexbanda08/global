"""
positioned_leg_in_flatten.py — same sequential leg-in, but FLATTEN stuck legs.

Adds agent-2's key control: when leg2 never fills, don't hold the stuck leg to
resolution (loses ~$0.50). Instead SELL it back at the best BID at flatten_time
(taker sell). Compares hold-to-resolution vs flatten-at-bid for the strongest
params. If flatten still loses, positioned-arb has no edge for us without a
directional signal or sub-100ms speed.

stuck (hold)    pnl/share = (won?1:0) - L1 + rebate
stuck (flatten) pnl/share = bid_leg1@flatten - L1 + rebate   (sell back at bid)
completed       pnl/share = (1 - BUDGET) + 2*rebate

Usage: py -X utf8 strategy_lab/maker_arb_audit/positioned_leg_in_flatten.py
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
L1 = 0.50
BUDGETS = [0.94, 0.97]
FLATTEN = 120
REBATE = 0.0035


def series(arr):
    ts, ap, asz, bp, bsz = arr
    a = ap[:, 0].astype(float); b = bp[:, 0].astype(float)
    ok = np.isfinite(a) & (a > 0) & (a < 1.0)
    return ts.astype(np.int64)[ok], a[ok], b[ok]


def first_cross(ts, ask, thr, t_after=None, t_before=None):
    m = ask <= thr
    if t_after is not None: m &= ts > t_after
    if t_before is not None: m &= ts < t_before
    return int(ts[np.argmax(m)]) if m.any() else None


def bid_asof(ts, bid, t):
    i = int(np.searchsorted(ts, t, side="right")) - 1
    return float(bid[i]) if i >= 0 else np.nan


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
            if sub.empty: continue
            slugs = set(sub.slug)
            won_up = dict(zip(sub.slug, sub.outcome.str.lower() == "up"))
            t0 = time.time()
            books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
            ser = {}
            for slug in slugs:
                up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
                if up is None or dn is None: continue
                tu, au, bu = series(up); td, ad, bd = series(dn)
                if au.size < 5 or ad.size < 5: continue
                ser[slug] = (tu, au, bu, td, ad, bd)
            for BUD in BUDGETS:
                b2 = BUD - L1
                comp = 0; stuck = 0
                comp_pnl = []; stuck_hold = []; stuck_flat = []
                for slug, (tu, au, bu, td, ad, bd) in ser.items():
                    ss = int(slug.rsplit("-", 1)[-1])
                    flat = (ss + WIN[tf] - FLATTEN) * 1_000_000
                    t_up = first_cross(tu, au, L1, t_before=flat)
                    t_dn = first_cross(td, ad, L1, t_before=flat)
                    if t_up is None and t_dn is None: continue
                    if t_dn is None or (t_up is not None and t_up <= t_dn):
                        leg1, l1t = "up", t_up
                        t2 = first_cross(td, ad, b2, t_after=l1t, t_before=flat)
                        b_flat = bid_asof(tu, bu, flat)
                    else:
                        leg1, l1t = "dn", t_dn
                        t2 = first_cross(tu, au, b2, t_after=l1t, t_before=flat)
                        b_flat = bid_asof(td, bd, flat)
                    if t2 is not None:
                        comp += 1
                        comp_pnl.append((1.0 - BUD) + 2 * REBATE)
                    else:
                        stuck += 1
                        won = won_up[slug] if leg1 == "up" else (not won_up[slug])
                        stuck_hold.append((1.0 if won else 0.0) - L1 + REBATE)
                        # flatten: sell at bid (fallback to 0 if no bid)
                        bf = b_flat if np.isfinite(b_flat) else 0.0
                        stuck_flat.append(bf - L1 + REBATE)
                n = comp + stuck
                if n < 30: continue
                cp = np.array(comp_pnl); sh = np.array(stuck_hold); sf = np.array(stuck_flat)
                hold_mean = (cp.sum() + sh.sum()) / n
                flat_mean = (cp.sum() + sf.sum()) / n
                rows.append(dict(asset=asset, tf=tf, budget=BUD, n=n,
                                 comp_pct=round(100 * comp / n, 1),
                                 stuck_hold_mean=round(float(sh.mean()), 3) if len(sh) else 0,
                                 stuck_flat_mean=round(float(sf.mean()), 3) if len(sf) else 0,
                                 pnl_hold=round(float(hold_mean), 4),
                                 pnl_flatten=round(float(flat_mean), 4),
                                 total_flatten=round(float(cp.sum() + sf.sum()), 1)))
            print(f"[{asset} {tf}] {time.time()-t0:.0f}s slugs={len(ser)}", flush=True)
    df = pd.DataFrame(rows); df.to_csv(OUT / "positioned_leg_in_flatten.csv", index=False)
    pd.set_option("display.width", 240)
    print("\n" + "=" * 100)
    print("LEG-IN with FLATTEN stuck legs (L1=0.50, rebate=0.0035, merge=$1)")
    print("=" * 100)
    print(df.to_string(index=False))
    pooled = (df.groupby("budget").apply(lambda g: pd.Series({
        "n": int(g.n.sum()),
        "comp_pct": round(float((g.comp_pct*g.n).sum()/g.n.sum()),1),
        "pnl_hold": round(float((g.pnl_hold*g.n).sum()/g.n.sum()),4),
        "pnl_flatten": round(float((g.pnl_flatten*g.n).sum()/g.n.sum()),4)}),
        include_groups=False).reset_index())
    print("\nPOOLED:")
    print(pooled.to_string(index=False))
    print(f"\nwrote {OUT/'positioned_leg_in_flatten.csv'}")


if __name__ == "__main__":
    run()
