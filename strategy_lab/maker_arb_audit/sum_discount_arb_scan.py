"""
sum_discount_arb_scan.py — does a take-both-legs-and-MERGE arb exist in our books?

The profitable maker wallets capture the sum<$1 discount: buy 1 Up + 1 Down when
up_ask + dn_ask < $1, then MERGE the pair for $1 (minus 0.25% protocol fee). Atomic,
market-neutral, NO adverse selection, NO directional risk. This scans canonical L25
(NATIVE 10Hz per CLAUDE.md) for those windows and quantifies frequency, depth, size,
and persistence — the decisive test of whether the maker-arb premise is reachable.

profit/pair = MERGE_RATE - (up_ask0 + dn_ask0),  MERGE_RATE = 0.9975
(ignores ~$0.01-0.05 gas/merge — flagged separately). Arb if sum_ask < 0.9975.

Usage: py -X utf8 strategy_lab/maker_arb_audit/sum_discount_arb_scan.py
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
OUT.mkdir(parents=True, exist_ok=True)
MERGE_RATE = 0.9975
# window: L25 canonical covers through ~May 26; scan a recent multi-day slice
LO = int(pd.Timestamp("2026-05-22", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-27", tz="UTC").timestamp())


def best_ask_series(arr):
    ts, ap, asz, bp, bsz = arr
    a0 = ap[:, 0].astype(float)
    s0 = asz[:, 0].astype(float)
    return ts.astype(np.int64), a0, s0


def scan_asset_tf(asset, tf, res):
    pref = f"{asset.lower()}-updown-{tf}-"
    sub = res[(res.ticker == asset) & (res.timeframe == tf)].copy()
    sub = sub[sub.slug.str.startswith(pref)]
    sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
    sub = sub[(sub.ss >= LO) & (sub.ss <= HI)]
    slugs = set(sub.slug)
    if not slugs:
        return None
    books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
    n_slug = 0; n_slug_arb = 0
    ev_count = 0; tot_capturable = 0.0; depths = []; persist_ticks = []
    sample_secs = 0.0; arb_secs = 0.0
    for slug in slugs:
        up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
        if up is None or dn is None:
            continue
        tu, au, su = best_ask_series(up)
        td, ad, sd = best_ask_series(dn)
        if len(tu) < 5 or len(td) < 5:
            continue
        n_slug += 1
        # asof-align dn ask onto up grid
        j = np.searchsorted(td, tu, side="right") - 1
        ok = j >= 0
        sum_ask = np.full(len(tu), np.nan)
        dn_sz = np.full(len(tu), np.nan)
        sum_ask[ok] = au[ok] + ad[j[ok]]
        dn_sz[ok] = sd[j[ok]]
        valid = np.isfinite(sum_ask) & (au > 0) & np.isfinite(au)
        sv = sum_ask[valid]
        if sv.size == 0:
            continue
        arb = sv < MERGE_RATE
        if arb.any():
            n_slug_arb += 1
            ev_count += int(arb.sum())
            pair_sz = np.minimum(su[valid][arb], dn_sz[valid][arb])
            pair_sz = np.clip(pair_sz, 0, 50)  # cap to realistic take size
            cap = (MERGE_RATE - sv[arb]) * pair_sz
            tot_capturable += float(cap.sum())
            depths.extend((MERGE_RATE - sv[arb]).tolist())
            persist_ticks.append(int(arb.sum()))
        # rough seconds: 10Hz -> each tick ~0.1s
        sample_secs += sv.size * 0.1
        arb_secs += int(arb.sum()) * 0.1
    if n_slug == 0:
        return None
    return dict(asset=asset, tf=tf, n_slug=n_slug, n_slug_arb=n_slug_arb,
                pct_slug_arb=round(100 * n_slug_arb / n_slug, 1),
                ev_count=ev_count,
                pct_time_arb=round(100 * arb_secs / sample_secs, 3) if sample_secs else 0,
                mean_depth=round(float(np.mean(depths)), 4) if depths else 0,
                max_depth=round(float(np.max(depths)), 4) if depths else 0,
                capturable_total=round(tot_capturable, 2),
                cap_per_slug=round(tot_capturable / n_slug, 4))


def main():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []
    for asset in ["BTC", "ETH", "SOL"]:
        for tf in ["5m", "15m"]:
            t0 = time.time()
            r = scan_asset_tf(asset, tf, res)
            if r:
                rows.append(r)
                print(f"[{asset} {tf}] {time.time()-t0:.0f}s  "
                      f"slugs={r['n_slug']} arb_slugs={r['pct_slug_arb']}% "
                      f"%time_arb={r['pct_time_arb']} cap/slug=${r['cap_per_slug']}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "sum_discount_arb.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 95)
    print("SUM<$1 TAKE-BOTH-MERGE ARB SCAN (native 10Hz L25, May 22-26, MERGE_RATE=0.9975)")
    print("=" * 95)
    print(df.to_string(index=False))
    if not df.empty:
        print(f"\nTOTAL capturable across cells (size-capped@50, pre-gas): "
              f"${df.capturable_total.sum():.0f} over {int(df.n_slug.sum())} slugs "
              f"(~5 days)")
        print("Interpretation: pct_time_arb = fraction of book-time the pair is buyable <0.9975.")
        print("If pct_time_arb ~0 and cap/slug ~$0 -> no reachable arb (premise dead).")
    print(f"wrote {OUT/'sum_discount_arb.csv'}")


if __name__ == "__main__":
    main()
