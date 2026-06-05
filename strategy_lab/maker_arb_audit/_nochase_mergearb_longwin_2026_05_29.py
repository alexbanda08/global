"""
_nochase_mergearb_longwin_2026_05_29.py — the ONE undisproven maker-arb variant.

Tests the strict NO-CHASE merge-arb on the LONGER canonical window (May 20 -> May 29,
vs the ~1.5d the censoring reversal had). Policy:
  1. Rest a limit at L1 on one side; fill = ask crosses <= L1 before flatten time.
  2. Try to COMPLETE the pair on the other side at b2 = BUDGET - L1, before flatten.
     -> you NEVER overpay: if the other leg never reaches b2, you do NOT chase it.
  3. Stuck (only leg1 filled) is settled two ways for comparison:
        hold    : carry naked leg to chainlink resolution  (the adverse residual that
                  sank the production sleeves -> coin flip the maker loses)
        flatten : sell the stuck leg back at the BID at flatten time (NO-CHASE exit)
  completed pnl/share = (1 - BUDGET) + 2*rebate         (merge matched pair for $1)
  stuck/hold          = (won?1:0) - L1 + rebate
  stuck/flatten       = bid_leg1@flatten - L1 + rebate

Deploy bar: pooled pnl_flatten must clear ZERO (bootstrap 95% CI lower bound > 0).
This is the test that decides whether no-chase merge-arb is a real deploy candidate.

Usage: py -X utf8 strategy_lab/maker_arb_audit/_nochase_mergearb_longwin_2026_05_29.py
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
LO = int(pd.Timestamp("2026-05-20", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-29 13:00", tz="UTC").timestamp())
L1 = 0.50
BUDGETS = [0.90, 0.93, 0.94, 0.97]   # tighter sum gate added (0.90 / 0.93)
FLATTEN = 120
REBATE = 0.0035
RNG = np.random.default_rng(7)
N_BOOT = 5000


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


def boot_ci(x, n_boot=N_BOOT):
    x = np.asarray(x, float)
    if x.size < 2:
        return (np.nan, np.nan)
    idx = RNG.integers(0, x.size, size=(n_boot, x.size))
    means = x[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    rows = []
    # collect per-slug pnl arrays per budget across all asset/tf cells for pooled CI
    pool_flat = {b: [] for b in BUDGETS}
    pool_hold = {b: [] for b in BUDGETS}
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
                comp_pnl = []; per_slug_hold = []; per_slug_flat = []
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
                        p = (1.0 - BUD) + 2 * REBATE
                        comp_pnl.append(p)
                        per_slug_hold.append(p); per_slug_flat.append(p)
                    else:
                        stuck += 1
                        won = won_up[slug] if leg1 == "up" else (not won_up[slug])
                        per_slug_hold.append((1.0 if won else 0.0) - L1 + REBATE)
                        bf = b_flat if np.isfinite(b_flat) else 0.0
                        per_slug_flat.append(bf - L1 + REBATE)
                n = comp + stuck
                if n < 30: continue
                pool_flat[BUD].extend(per_slug_flat)
                pool_hold[BUD].extend(per_slug_hold)
                sh = np.array(per_slug_hold); sf = np.array(per_slug_flat)
                rows.append(dict(asset=asset, tf=tf, budget=BUD, n=n,
                                 comp_pct=round(100 * comp / n, 1),
                                 pnl_hold=round(float(sh.mean()), 4),
                                 pnl_flatten=round(float(sf.mean()), 4),
                                 total_flatten=round(float(sf.sum()), 1)))
            print(f"[{asset} {tf}] {time.time()-t0:.0f}s slugs={len(ser)}", flush=True)
    df = pd.DataFrame(rows); df.to_csv(OUT / "_nochase_mergearb_longwin.csv", index=False)
    pd.set_option("display.width", 240)
    print("\n" + "=" * 100)
    print(f"NO-CHASE MERGE-ARB  window {pd.to_datetime(LO,unit='s')} -> {pd.to_datetime(HI,unit='s')}  "
          f"(L1={L1}, rebate={REBATE}, flatten={FLATTEN}s, merge=$1)")
    print("=" * 100)
    print(df.to_string(index=False))
    print("\nPOOLED across all asset/tf cells, with bootstrap 95% CI (deploy bar: flatten CI-low > 0):")
    prows = []
    for BUD in BUDGETS:
        sf = np.array(pool_flat[BUD]); sh = np.array(pool_hold[BUD])
        if sf.size < 2: continue
        flo, fhi = boot_ci(sf); hlo, hhi = boot_ci(sh)
        prows.append(dict(budget=BUD, n=sf.size,
                          pnl_hold=round(float(sh.mean()), 4),
                          hold_ci=f"[{hlo:.3f}, {hhi:.3f}]",
                          pnl_flatten=round(float(sf.mean()), 4),
                          flat_ci=f"[{flo:.3f}, {fhi:.3f}]",
                          flat_clears_zero="YES" if flo > 0 else "no",
                          total_flatten=round(float(sf.sum()), 1)))
    pooled = pd.DataFrame(prows)
    print(pooled.to_string(index=False))
    print(f"\nwrote {OUT/'_nochase_mergearb_longwin.csv'}")
    # verdict
    any_pos = (pooled["flat_clears_zero"] == "YES").any() if len(pooled) else False
    print("\nVERDICT:", "NO-CHASE CLEARS ZERO on >=1 budget -> deploy candidate (shadow-confirm)"
          if any_pos else "NO-CHASE still <= 0 -> maker-arb has no edge for us; close the line.")


if __name__ == "__main__":
    run()
