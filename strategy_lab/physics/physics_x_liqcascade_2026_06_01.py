"""
physics_x_liqcascade_2026_06_01.py — COMBINE the physics continuation pocket with the HL
liquidation-cascade direction (the g_a2 family). Hypothesis: a forced liquidation cascade in
the CONTINUATION direction makes the decisive move flow-backed -> less likely to revert in the
final 60s -> sharpens the physics pocket (lifts gap, removes the bad-week-20 reversals).

Physics fires at slot_end-60s (decisive late-window state). g_a2/A1 liq cascade = forced flow.
For side=+1 (BTC above strike, betting Up) continuation-confirming flow = forced BUYING
(Close Short liquidations). For side=-1 = forced SELLING (Close Long). liq_net = buy - sell
over the trailing window ending at fire_us. confirmed = sign(liq_net)==side & |liq_net|>=T.

Physics enriched: strategy_lab/physics/_results/physics_fires_enriched.parquet (BTC, valid fires).
HL liqs only cover -> May27, so restrict to fire_us <= May27 13:30. Fee = pnl_legacy (prod) + pnl_curve.
Usage: C:/Python314/python.exe strategy_lab/physics/physics_x_liqcascade_2026_06_01.py
"""
from __future__ import annotations
import sys, math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_hyperliquid_liquidations_full  # noqa: E402

PHYS = ROOT / "strategy_lab" / "physics" / "_results" / "physics_fires_enriched.parquet"
OUT = ROOT / "strategy_lab" / "physics" / "_results"
HI_HL_US = int(pd.Timestamp("2026-05-27 13:30", tz="UTC").timestamp()) * 1_000_000


def tstat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return (np.nan, np.nan, n)
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n)
    return (m, m / se if se else np.nan, n)


def liq_streams():
    hl = load_hyperliquid_liquidations_full("BTC")
    hl = hl[hl["method"] == "market"].copy()
    hl["ts"] = hl.time_exchange_us.astype(np.int64)
    hl["notional"] = hl.price.astype(float) * hl["size"].astype(float)
    buy = hl[hl["dir"] == "Close Short"].sort_values("ts")    # short liq -> forced BUY (bullish)
    sell = hl[hl["dir"] == "Close Long"].sort_values("ts")    # long liq  -> forced SELL (bearish)
    return (buy.ts.values, buy.notional.values, sell.ts.values, sell.notional.values)


def rollsum(ts, val, lo_us, hi_us):
    cs = np.concatenate([[0.0], np.cumsum(val)])
    hi = np.searchsorted(ts, hi_us, side="right")
    lo = np.searchsorted(ts, lo_us, side="right")
    return cs[hi] - cs[lo]


def main():
    d = pd.read_parquet(PHYS)
    d = d[d.valid & (d.fire_us <= HI_HL_US)].copy()
    bt, bv, st, sv = liq_streams()

    # liq_net over trailing W ending at fire_us, for a few W
    for W in [300, 900]:
        lo = d.fire_us.values - W * 1_000_000
        hi = d.fire_us.values
        b = np.array([rollsum(bt, bv, lo[i], hi[i]) for i in range(len(d))])
        s = np.array([rollsum(st, sv, lo[i], hi[i]) for i in range(len(d))])
        d[f"liqbuy_{W}"] = b; d[f"liqsell_{W}"] = s; d[f"liqnet_{W}"] = b - s

    d["week"] = pd.to_datetime(d.slot_start_us, unit="us", utc=True).dt.isocalendar().week.astype(int)
    pocket = (d.dist_abs >= 40) & (d.entry_vwap < 0.95) & (d.spread <= 0.02)
    POCK = d[pocket].copy()

    def report(df, label):
        m, t, n = tstat(df.pnl_legacy.values)
        mc, tc, _ = tstat(df.pnl_curve.values)
        wr = df.won.mean(); imp = df.implied.mean()
        return dict(set=label, n=n, wr=round(100 * wr, 1), implied=round(100 * imp, 1),
                    gap_pp=round(100 * (wr - imp), 2),
                    legacy_pf=round(m, 3), legacy_t=round(t, 2),
                    curve_pf=round(mc, 3), curve_t=round(tc, 2))

    rows = [report(POCK, "POCKET (all, <=May27)")]
    # split by liq confirmation
    for W in [300, 900]:
        ln = POCK[f"liqnet_{W}"].values
        side = POCK.side.values
        for T in [0, 1000, 5000, 25000]:
            conf = (np.sign(ln) == side) & (np.abs(ln) >= max(T, 1e-9))
            cont = (np.sign(ln) == -side) & (np.abs(ln) >= max(T, 1e-9))
            if conf.sum() >= 15:
                rows.append(report(POCK[conf], f"  +confirmed W{W} |net|>={T}"))
            if cont.sum() >= 15:
                rows.append(report(POCK[cont], f"  -contradicted W{W} |net|>={T}"))
        # any liq activity at all in trailing window
        any_liq = (POCK[f"liqbuy_{W}"] + POCK[f"liqsell_{W}"]) > 0
        rows.append(report(POCK[any_liq], f"  pocket & any-liq W{W}"))
        rows.append(report(POCK[~any_liq], f"  pocket & NO-liq W{W}"))

    R = pd.DataFrame(rows)
    R.to_csv(OUT / "physics_x_liqcascade_2026_06_01.csv", index=False)
    pd.set_option("display.width", 200); pd.set_option("display.max_rows", 100)
    print("=" * 100)
    print("PHYSICS POCKET x HL LIQ-CASCADE confirmation (BTC, <=May27). gap_pp = WR - implied; t on $/fire")
    print("=" * 100)
    print(R.to_string(index=False))

    # weekly breakdown: does liq-confirmation remove the bad weeks?
    print("\n--- WEEKLY: pocket vs pocket&confirmed(W300,|net|>=1000) ---")
    conf300 = (np.sign(POCK["liqnet_300"].values) == POCK.side.values) & (np.abs(POCK["liqnet_300"].values) >= 1000)
    POCK["confirmed300"] = conf300
    wk = []
    for w, g in POCK.groupby("week"):
        gc = g[g.confirmed300]
        wk.append(dict(week=w, n=len(g), wr=round(100 * g.won.mean(), 1),
                       legacy_pf=round(g.pnl_legacy.mean(), 3),
                       conf_n=len(gc), conf_wr=round(100 * gc.won.mean(), 1) if len(gc) else np.nan,
                       conf_pf=round(gc.pnl_legacy.mean(), 3) if len(gc) else np.nan))
    print(pd.DataFrame(wk).to_string(index=False))

    # also: does liq-confirmation help the FULL physics universe (not just pocket)?
    print("\n--- FULL physics universe split by liq-confirm (W300, |net|>=5000) ---")
    full = d
    lnf = full["liqnet_300"].values; sidef = full.side.values
    confF = (np.sign(lnf) == sidef) & (np.abs(lnf) >= 5000)
    contF = (np.sign(lnf) == -sidef) & (np.abs(lnf) >= 5000)
    print(pd.DataFrame([report(full, "ALL physics"),
                        report(full[confF], " +confirmed"),
                        report(full[contF], " -contradicted")]).to_string(index=False))
    print(f"\nwrote {OUT/'physics_x_liqcascade_2026_06_01.csv'}")


if __name__ == "__main__":
    main()
