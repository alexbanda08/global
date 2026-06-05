"""
clbasis_signal_wr.py — does the binance->chainlink-lag signal predict the
chainlink outcome across the BROAD up-down universe? (Pass 1: direction WR.)

The decoded wallet edge (DECODE_SYNTHESIS_2026_05_28): Polymarket up-down resolves
on Chainlink Data Streams which LAGS Binance spot. Buy the side Binance is moving
toward. Signals (all measured causally at fire_us = slot_start + offset, on
binance-spot-ws 1MIN closes + chainlink RTDS):
  ema9_slope_bps>0 -> Up   (short-term binance trend)
  ret_3m>0 -> Up           (3-min binance return)
  cl_basis_bps>0 -> Up     (binance above lagging chainlink)
  px_vs_strike_bps>0 -> Up (binance above the slot strike)

We fire on EVERY resolved slug (synthesis: slug selection ~indiscriminate) and
check direction == chainlink outcome. Pure causal: only binance/chainlink data
up to fire_us. No entry price / fills here (that's Pass 2 / PnL).

Usage: py -X utf8 strategy_lab/directional/clbasis_signal_wr.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_klines_asof, load_chainlink_asof  # noqa: E402

OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"5m": 300, "15m": 900}
OFFSETS = [30, 60, 120]


def asof_idx(sorted_us: np.ndarray, targets: np.ndarray) -> np.ndarray:
    return np.searchsorted(sorted_us, targets.astype(np.int64), side="right") - 1


def signals_for_asset(asset: str):
    e, c = load_klines_asof(asset, source="binance-spot-ws", period_id="1MIN")
    e = e.astype(np.int64); c = c.astype(float)
    s = pd.Series(c, index=e)
    ema9 = s.ewm(span=9, adjust=False).mean().to_numpy()
    ema9_3 = np.r_[np.full(3, np.nan), ema9[:-3]]
    slope = np.where(ema9_3 > 0, (ema9 - ema9_3) / ema9_3 * 1e4, np.nan)
    ret3 = np.full_like(c, np.nan)
    ret3[3:] = (c[3:] / c[:-3] - 1) * 1e4
    ce, cc = load_chainlink_asof(asset)
    ce = ce.astype(np.int64); cc = cc.astype(float)
    return e, c, slope, ret3, ce, cc


def run():
    res = load_resolutions()
    res["slug"] = res["slug"].astype(str)
    rows = []
    detail = []
    for asset in ["BTC", "ETH", "SOL"]:
        e, c, slope, ret3, ce, cc = signals_for_asset(asset)
        ra = res[res.ticker == asset].copy()
        for tf in ["5m", "15m"]:
            sub = ra[ra.timeframe == tf].copy()
            if sub.empty:
                continue
            ss = sub.slot_start_us.to_numpy().astype(np.int64)
            up = (sub.outcome.str.lower() == "up").to_numpy()
            strike = pd.to_numeric(sub.strike_price, errors="coerce").to_numpy()
            for off in OFFSETS:
                tgt = ss + off * 1_000_000
                # only fire if fire_us strictly inside the window (< slot_end)
                inwin = (off < WIN[tf])
                ki = asof_idx(e, tgt)
                cli = asof_idx(ce, tgt)
                ok = (ki >= 3) & (cli >= 0) & inwin
                px = np.where(ki >= 0, c[ki], np.nan)
                slp = np.where(ki >= 0, slope[ki], np.nan)
                r3 = np.where(ki >= 0, ret3[ki], np.nan)
                clpx = np.where(cli >= 0, cc[cli], np.nan)
                clb = (px - clpx) / clpx * 1e4
                pvs = (px - strike) / strike * 1e4
                sigs = {
                    "ema9_slope": slp, "ret_3m": r3,
                    "cl_basis": clb, "px_vs_strike": pvs,
                }
                for name, sig in sigs.items():
                    m = ok & np.isfinite(sig) & (np.abs(sig) > 1e-9)
                    if m.sum() < 20:
                        continue
                    direction_up = sig[m] > 0
                    won = direction_up == up[m]
                    rows.append(dict(asset=asset, tf=tf, offset=off, signal=name,
                                     n=int(m.sum()), wr=round(100 * won.mean(), 1),
                                     up_rate=round(100 * direction_up.mean(), 1)))
            # magnitude stratification for cl_basis at offset=60
            off = 60
            tgt = ss + off * 1_000_000
            ki = asof_idx(e, tgt); cli = asof_idx(ce, tgt)
            ok = (ki >= 3) & (cli >= 0) & (off < WIN[tf])
            px = np.where(ki >= 0, c[ki], np.nan)
            clpx = np.where(cli >= 0, cc[cli], np.nan)
            clb = (px - clpx) / clpx * 1e4
            for lo, hi in [(0, 5), (5, 10), (10, 20), (20, 1e9)]:
                m = ok & np.isfinite(clb) & (np.abs(clb) >= lo) & (np.abs(clb) < hi)
                if m.sum() < 20:
                    continue
                d_up = clb[m] > 0
                won = d_up == up[m]
                detail.append(dict(asset=asset, tf=tf, signal="cl_basis", off=off,
                                   absbucket=f"[{lo},{hi})", n=int(m.sum()),
                                   wr=round(100 * won.mean(), 1)))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "signal_wr.csv", index=False)
    dd = pd.DataFrame(detail)
    dd.to_csv(OUT / "clbasis_magnitude_wr.csv", index=False)

    pd.set_option("display.width", 200)
    print("=" * 90)
    print("SIGNAL DIRECTION WR vs chainlink outcome (fire @ slot_start+offset, broad universe)")
    print("=" * 90)
    piv = df.pivot_table(index=["asset", "tf", "signal"], columns="offset",
                         values="wr", aggfunc="first")
    ncol = df.pivot_table(index=["asset", "tf", "signal"], columns="offset",
                          values="n", aggfunc="first")
    print("WR% by offset (30/60/120s):")
    print(piv.to_string())
    print("\nsample n by offset:")
    print(ncol.to_string())
    print("\ncl_basis WR by |basis| magnitude bucket (offset=60):")
    if not dd.empty:
        print(dd.pivot_table(index=["asset", "tf"], columns="absbucket",
                             values="wr", aggfunc="first").to_string())
    print(f"\nwrote {OUT/'signal_wr.csv'} + clbasis_magnitude_wr.csv")
    # headline: best signal per asset/tf at offset 60
    h = df[df.offset == 60].sort_values("wr", ascending=False).head(12)
    print("\nTop direction-WR cells @60s:")
    print(h.to_string(index=False))


if __name__ == "__main__":
    run()
