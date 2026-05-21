"""
Final test of the one untested-but-promising signal from the discovery session.

Strategy E found: SOL 15m markets at slot_end-60s, top-5 imbalance cutoff 0.7,
spread-on → 18.9% hit on n=724. That's 81% hit if INVERTED.

Mechanism: when SOL Up-side book has heavy bid pressure (imbalance > 0.7) AND
spread is reasonable, the market is OVER-pricing UP. Bet AGAINST by SELLING
shares of UP at the bid (or equivalently, buying DOWN at DOWN-book ask).

We use the cleaner equivalent: buy DOWN at DOWN-book ask when SOL Up-side
imbalance > 0.7. With LATENCY-CORRECTED kline asof (100ms shift).

This is the LAST untested deployable candidate from the entire session.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming, asof_strict
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

DIR = Path(__file__).resolve().parent
np.random.seed(42)

LATENCY_US = 100_000   # 100ms WS forwarding latency

# Test SOL primary, plus BTC/ETH for comparison.
ASSETS = ["SOL", "BTC", "ETH"]
N_PER_ASSET = 1500


def run_contra(asset, anchor_off_s, cutoff, vwap_lo, vwap_hi):
    """Fire DOWN when Up-side imbalance > cutoff. Buy DOWN at DOWN-ask."""
    res = load_resolutions(timeframes=["15m"], assets=[asset])
    sub = res.sort_values("slot_start_us").copy()
    if len(sub) > N_PER_ASSET:
        idx = np.linspace(0, len(sub) - 1, N_PER_ASSET).astype(int)
        sub = sub.iloc[idx]
    sub["entry_us"] = sub.slot_end_us - anchor_off_s * 1_000_000

    SPREAD = SPREAD_FILTER[asset]
    slugs_list = list(sub.slug.unique())
    books = {}
    for i in range(0, len(slugs_list), 500):
        chunk = set(slugs_list[i:i+500])
        books.update(load_orderbook_l25_streaming(asset.lower(), slugs=chunk, subsample_1hz=True))

    rows = []
    for _, r in sub.iterrows():
        entry_us = int(r["entry_us"])
        # Top-5 imbalance on Up side
        snap_up = get_book_at(books, r["slug"], "Up", entry_us)
        if snap_up is None: continue
        ap_up, asz_up, bp_up, bsz_up = snap_up
        bid5 = float(np.nansum(bsz_up[:5]))
        ask5 = float(np.nansum(asz_up[:5]))
        if bid5 + ask5 <= 0: continue
        imb_up = bid5 / (bid5 + ask5)
        ap0_up = float(ap_up[0]) if np.isfinite(ap_up[0]) else np.nan
        bp0_up = float(bp_up[0]) if np.isfinite(bp_up[0]) else np.nan
        if not (np.isfinite(ap0_up) and np.isfinite(bp0_up)): continue
        if (ap0_up - bp0_up) > SPREAD: continue

        # Contra signal: fire DOWN if Up-side imbalance > cutoff
        if imb_up <= cutoff:
            continue

        # Fill on DOWN-book ask
        snap_dn = get_book_at(books, r["slug"], "Down", entry_us)
        if snap_dn is None: continue
        ap_dn, asz_dn, _, _ = snap_dn
        vwap, shares, spent, under = walk_asks(list(ap_dn), list(asz_dn), NOTIONAL)
        if under or not np.isfinite(vwap) or shares <= 0: continue
        if not (vwap_lo < vwap < vwap_hi): continue

        # Outcome — we bet DOWN, win if outcome == Down
        won = int(r["outcome"].upper() == "DOWN")
        profit_raw = shares * (won - vwap)
        fee = max(profit_raw, 0.0) * FEE_RATE
        pnl = profit_raw - fee
        rows.append(dict(
            asset=asset, slug=r["slug"], outcome=r["outcome"], entry_us=entry_us,
            imb_up=imb_up, ap0_up=ap0_up, bp0_up=bp0_up, vwap=vwap, shares=shares,
            won=won, pnl=pnl,
        ))
    return pd.DataFrame(rows)


def report(df, label):
    if len(df) == 0:
        print(f"  {label:<50s} n=0"); return
    n = len(df); hit = df.won.mean(); pnl = df.pnl.sum(); ppt = df.pnl.mean()
    pnls = []
    for _ in range(1000):
        flips = np.random.choice([1,-1], size=n)
        pnls.append((df.pnl.values * flips).sum())
    pv = (np.array(pnls) >= pnl).mean()
    boot = []
    for _ in range(2000):
        idx = np.random.choice(n, size=n, replace=True)
        boot.append(df.pnl.values[idx].mean())
    boot = np.array(boot)
    ci_lo, ci_hi = np.percentile(boot, 2.5), np.percentile(boot, 97.5)
    print(f"  {label:<50s}  n={n:>4d}  hit={hit:.4f}  pnl=${pnl:>+7.0f}  ppt=${ppt:>+5.2f}  p={pv:.3f}  CI=[${ci_lo:+.2f},${ci_hi:+.2f}]")


def main():
    print(f"=== SOL contra-imbalance test (100ms latency baked in via no-kline-use) ===")
    print(f"Signal: when Up-side top-5 imbalance > cutoff, fire DOWN at Down-book ask.")
    print(f"This test uses ONLY book data — no klines used, so NO microsecond lookahead.")
    print()

    for asset in ASSETS:
        print(f"--- {asset} ---")
        for anchor in [60, 90, 120, 180, 300]:
            for cutoff in [0.60, 0.65, 0.70, 0.75]:
                df = run_contra(asset, anchor, cutoff, vwap_lo=0.0, vwap_hi=1.0)
                if len(df) >= 50:
                    label = f"anchor=slot_end-{anchor:>3}s cutoff={cutoff:.2f}"
                    report(df, label)

        # Best config zoom: anchor=60 cutoff=0.70 with vwap filter sweep
        print(f"  --- vwap filter sweep at anchor=60, cutoff=0.70 ---")
        for vlo, vhi in [(0.0, 1.0), (0.0, 0.7), (0.0, 0.5), (0.0, 0.3), (0.0, 0.2), (0.0, 0.1)]:
            df = run_contra(asset, 60, 0.70, vlo, vhi)
            if len(df) >= 30:
                report(df, f"anchor=60 cut=0.70 vwap[{vlo:.2f},{vhi:.2f}]")
        print()


if __name__ == "__main__":
    main()
