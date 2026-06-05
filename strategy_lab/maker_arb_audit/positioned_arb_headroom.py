"""
positioned_arb_headroom.py — headroom for SEQUENTIAL leg-in maker arb.

My earlier scan tested ATOMIC take-both-when-sum<$1 (rare). The positioned arb is
SEQUENTIAL: buy UP cheap at one moment, DOWN cheap at another, hold both, MERGE for
~$1. The right question is whether `min(UP_ask) + min(DOWN_ask)` over the window is
< $1 — i.e. could a patient maker have legged into a cheap pair at all.

For each resolved slug (native-10Hz L25, May 22-26):
  minUP / minDN = lowest best-ask each side over the window (the cheapest a resting
                  maker BID could have filled). p10 = 10th-pct ask (more realistic,
                  avoids 1-tick blips). pair_cost = sum; margin = 0.9975 - sum.
Also report timing separation of the two minima (the hold-risk window) and direction.

NOTE: this is HEADROOM (upper bound on legging-in), not realized PnL — it ignores
fill probability at your exact bid, queue, and the directional risk during the hold.
But if sum-of-minima is rarely < $1, the positioned arb has no room either.

Usage: py -X utf8 strategy_lab/maker_arb_audit/positioned_arb_headroom.py
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
MERGE_RATE = 0.9975
LO = int(pd.Timestamp("2026-05-22", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27", tz="UTC").timestamp())


def ask0(arr):
    ts, ap, asz, bp, bsz = arr
    a = ap[:, 0].astype(float)
    ok = np.isfinite(a) & (a > 0) & (a < 1.0)
    return ts.astype(np.int64)[ok], a[ok]


def scan(asset, tf, res):
    pref = f"{asset.lower()}-updown-{tf}-"
    sub = res[(res.ticker == asset) & (res.timeframe == tf)]
    sub = sub[sub.slug.str.startswith(pref)].copy()
    sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
    sub = sub[(sub.ss >= LO) & (sub.ss <= HI)]
    slugs = set(sub.slug)
    if not slugs:
        return None
    books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
    recs = []
    for slug in slugs:
        up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
        if up is None or dn is None:
            continue
        tu, au = ask0(up); td, ad = ask0(dn)
        if au.size < 5 or ad.size < 5:
            continue
        minU, minD = au.min(), ad.min()
        p10U, p10D = np.percentile(au, 10), np.percentile(ad, 10)
        recs.append((minU + minD, p10U + p10D))
    if not recs:
        return None
    a = np.array(recs)
    smin, sp10 = a[:, 0], a[:, 1]
    n = len(smin)
    def frac(x, thr): return round(100 * np.mean(x < thr), 1)
    return dict(asset=asset, tf=tf, n_slug=n,
                pct_min_lt_9975=frac(smin, MERGE_RATE),
                pct_min_lt_95=frac(smin, 0.95),
                pct_min_lt_90=frac(smin, 0.90),
                med_min_sum=round(float(np.median(smin)), 4),
                pct_p10_lt_9975=frac(sp10, MERGE_RATE),
                med_p10_sum=round(float(np.median(sp10)), 4),
                med_margin_min=round(float(np.median(MERGE_RATE - smin)), 4))


def main():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []
    for asset in ["BTC", "ETH", "SOL"]:
        for tf in ["5m", "15m"]:
            t0 = time.time()
            r = scan(asset, tf, res)
            if r:
                rows.append(r)
                print(f"[{asset} {tf}] {time.time()-t0:.0f}s  n={r['n_slug']} "
                      f"min<.9975={r['pct_min_lt_9975']}% p10<.9975={r['pct_p10_lt_9975']}% "
                      f"med_min_sum={r['med_min_sum']}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "positioned_arb_headroom.csv", index=False)
    pd.set_option("display.width", 220)
    print("\n" + "=" * 100)
    print("POSITIONED (sequential leg-in) ARB HEADROOM — min(UP_ask)+min(DN_ask) over window")
    print("=" * 100)
    print(df.to_string(index=False))
    print("\nmin = absolute cheapest each side (optimistic). p10 = 10th-pct ask (realistic fill).")
    print("pct_*_lt_.9975 = fraction of slugs where legging into a pair below merge value was possible.")
    print(f"wrote {OUT/'positioned_arb_headroom.csv'}")


if __name__ == "__main__":
    main()
