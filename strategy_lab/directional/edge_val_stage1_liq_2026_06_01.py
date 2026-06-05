"""
edge_val_stage1_liq_2026_06_01.py — STAGE 1 of the Tier-1 new-edge validation.
Validates the LIQUIDATION-CASCADE gates from NEW_EDGE_RESEARCH_2026_06_01.md:
  A1  HL short-liq cascade (Close Short + Open Long = forced BUYS -> predict UP), windows {60,120,240,300}
  C6  HL prior-slot Close-Short cascade + directional imbalance (cs vs cl) -> predict UP
  C7  HL ETH Close-Long cascade (forced SELLS) -> predict DOWN, count-based
  A2  Cross-CEX (okx+gate) liq cascade, contrarian exhaustion (sell-liq->UP, buy-liq->DOWN)

Metric (first-pass, no L25 needed): DIRECTIONAL WR vs chainlink outcome on QUALIFYING fires,
with base-rate-adjusted one-sided binomial significance. (PnL fills = a later stage.)

ANCHOR: signal computed causally over [ws_s - W, ws_s], ws_s = slot_start - window_s.
Outcome = the current slug's chainlink resolution. Fully causal (signal ends >= window before settle).

DATA CAVEAT: HL liqs only Apr24->May27 (not refreshed). CEX liqs only May29->Jun1 (2.8d, sparse).

Usage: C:/Python314/python.exe strategy_lab/directional/edge_val_stage1_liq_2026_06_01.py
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import (load_resolutions, load_hyperliquid_liquidations_full,  # noqa: E402
                  load_cex_futures_liquidations)

OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"5m": 300, "15m": 900}


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def prop_z_p(k, n, p0):
    """one-sided z-test: is observed prop k/n > p0? returns (wr, z, p_one_sided)."""
    if n == 0:
        return (np.nan, np.nan, np.nan)
    ph = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return (ph, np.nan, np.nan)
    z = (ph - p0) / se
    return (ph, z, 1.0 - norm_cdf(z))


def base_fires(tickers, lo_s, hi_s):
    """resolutions for tickers, 5m+15m, ws_s in [lo_s,hi_s). returns df w/ asset,tf,ws_s,won_up."""
    r = load_resolutions()
    r = r[r.ticker.isin(tickers) & r.timeframe.isin(["5m", "15m"])].copy()
    r["slot_start"] = (r.slot_start_us // 1_000_000).astype(np.int64)
    r["ws_s"] = r.slot_start - r.timeframe.map(WIN).astype(np.int64)
    r["won_up"] = (r.outcome.astype(str).str.lower() == "up")
    r = r[(r.ws_s >= lo_s) & (r.ws_s < hi_s)]
    return r[["ticker", "timeframe", "slug", "slot_start", "ws_s", "won_up"]].reset_index(drop=True)


def rolling_sum_at(ev_ts, ev_val, anchors, W):
    """sum of ev_val over (anchor-W, anchor], vectorized. ev_ts sorted (seconds)."""
    cs = np.concatenate([[0.0], np.cumsum(ev_val)])
    hi = np.searchsorted(ev_ts, anchors, side="right")
    lo = np.searchsorted(ev_ts, anchors - W, side="right")
    return cs[hi] - cs[lo], (hi - lo)  # (sum, count)


def hl_events(coin, dirs):
    hl = load_hyperliquid_liquidations_full(coin)
    hl = hl[(hl["dir"].isin(dirs)) & (hl["method"] == "market")].copy()
    hl["ts_s"] = (hl.time_exchange_us / 1_000_000.0)
    hl["notional"] = hl.price.astype(float) * hl["size"].astype(float)
    hl = hl.sort_values("ts_s")
    return hl.ts_s.values.astype(float), hl.notional.values.astype(float)


def run():
    t0 = time.time()
    rows = []

    # ---------- universe for HL gates: BTC+ETH, Apr24 -> May27 ----------
    LO = int(pd.Timestamp("2026-04-24", tz="UTC").timestamp())
    HI_HL = int(pd.Timestamp("2026-05-27 13:30", tz="UTC").timestamp())
    F = base_fires(["BTC", "ETH"], LO, HI_HL)
    base_up = float(F.won_up.mean())
    print(f"HL universe: n={len(F)} base P(Up)={base_up:.4f} "
          f"({pd.Timestamp(F.ws_s.min(),unit='s',tz='UTC'):%m-%d} -> {pd.Timestamp(F.ws_s.max(),unit='s',tz='UTC'):%m-%d})", flush=True)

    # pre-load HL event streams per coin
    short_buy = {c: hl_events(c, ["Close Short", "Open Long"]) for c in ["BTC", "ETH"]}   # forced BUYS
    close_short = {c: hl_events(c, ["Close Short"]) for c in ["BTC", "ETH"]}
    close_long = {c: hl_events(c, ["Close Long"]) for c in ["BTC", "ETH"]}
    anchors = {c: F[F.ticker == c].ws_s.values.astype(float) for c in ["BTC", "ETH"]}
    wonup = {c: F[F.ticker == c].won_up.values for c in ["BTC", "ETH"]}

    # ===== A1: short-cascade sum > T -> predict UP =====
    for W in [60, 120, 240, 300]:
        for T in [1e3, 1e4, 5e4, 1e5]:
            k = n = 0
            for c in ["BTC", "ETH"]:
                ts, val = short_buy[c]
                s, _ = rolling_sum_at(ts, val, anchors[c], W)
                q = s > T
                n += int(q.sum()); k += int(wonup[c][q].sum())
            wr, z, p = prop_z_p(k, n, base_up)
            rows.append(dict(gate="A1_hl_shortcascade", param=f"W{W}_T{int(T)}", pred="UP",
                             n=n, wr=round(wr, 4) if n else np.nan, base=round(base_up, 4),
                             lift_pp=round((wr - base_up) * 100, 2) if n else np.nan,
                             z=round(z, 2) if n else np.nan, p_one=round(p, 4) if n else np.nan))

    # ===== C6: close_short 300s sum > T AND imbalance(cs vs cl) > 0.5 -> UP =====
    for T in [5e3, 1e4, 2.5e4, 5e4, 1e5]:
        k = n = 0
        for c in ["BTC", "ETH"]:
            cs_ts, cs_val = close_short[c]; cl_ts, cl_val = close_long[c]
            cs_s, _ = rolling_sum_at(cs_ts, cs_val, anchors[c], 300)
            cl_s, _ = rolling_sum_at(cl_ts, cl_val, anchors[c], 300)
            imb = (cs_s - cl_s) / (cs_s + cl_s + 1e-6)
            q = (cs_s > T) & (imb > 0.5)
            n += int(q.sum()); k += int(wonup[c][q].sum())
        wr, z, p = prop_z_p(k, n, base_up)
        rows.append(dict(gate="C6_hl_priorslot_imb", param=f"T{int(T)}_imb0.5", pred="UP",
                         n=n, wr=round(wr, 4) if n else np.nan, base=round(base_up, 4),
                         lift_pp=round((wr - base_up) * 100, 2) if n else np.nan,
                         z=round(z, 2) if n else np.nan, p_one=round(p, 4) if n else np.nan))

    # ===== C7: ETH close-long COUNT >= thr (300s) -> predict DOWN =====
    eth = F[F.ticker == "ETH"]
    base_dn_eth = float((~eth.won_up).mean())
    a_eth = eth.ws_s.values.astype(float); won_dn_eth = (~eth.won_up).values
    cl_ts, cl_val = close_long["ETH"]
    for thr in [4, 6, 8, 10, 12]:
        _, cnt = rolling_sum_at(cl_ts, cl_val, a_eth, 300)
        q = cnt >= thr
        n = int(q.sum()); k = int(won_dn_eth[q].sum())
        wr, z, p = prop_z_p(k, n, base_dn_eth)
        rows.append(dict(gate="C7_hl_eth_longcascade", param=f"cnt>={thr}", pred="DOWN",
                         n=n, wr=round(wr, 4) if n else np.nan, base=round(base_dn_eth, 4),
                         lift_pp=round((wr - base_dn_eth) * 100, 2) if n else np.nan,
                         z=round(z, 2) if n else np.nan, p_one=round(p, 4) if n else np.nan))

    # ===== A2: cross-CEX okx+gate, contrarian. sell-liq->UP, buy-liq->DOWN. May29->Jun1 =====
    LO2 = int(pd.Timestamp("2026-05-29", tz="UTC").timestamp())
    HI2 = int(pd.Timestamp("2026-06-01 09:00", tz="UTC").timestamp())
    F2 = base_fires(["BTC", "ETH"], LO2, HI2)
    base_up2 = float(F2.won_up.mean())
    cx = load_cex_futures_liquidations()
    cx = cx[cx.exchange.isin(["okx", "gate"])].copy()
    cx["coin"] = cx.symbol_id.str.extract(r"PERP_([A-Z]+)_USD")[0]
    cx = cx[cx.coin.isin(["BTC", "ETH"])]
    cx["ts_s"] = cx.time_exchange_us / 1_000_000.0
    print(f"A2 universe: n={len(F2)} base P(Up)={base_up2:.4f} | cex liq ticks BTC+ETH={len(cx)}", flush=True)
    for T in [1e4, 5e4, 1e5]:
        # sell-side (forced long-liq) -> contrarian UP ; buy-side -> contrarian DOWN
        for side, pred_up, label in [("sell", True, "UP"), ("buy", False, "DOWN")]:
            sub = cx[cx.side == side]
            k = n = 0
            for c in ["BTC", "ETH"]:
                e = sub[sub.coin == c].sort_values("ts_s")
                ets = e.ts_s.values.astype(float); eval_ = e.notional_usd.values.astype(float)
                aa = F2[F2.ticker == c].ws_s.values.astype(float)
                wu = F2[F2.ticker == c].won_up.values
                if len(ets) == 0:
                    continue
                s, _ = rolling_sum_at(ets, eval_, aa, 300)
                q = s > T
                n += int(q.sum())
                k += int(wu[q].sum()) if pred_up else int((~wu[q]).sum())
            base = base_up2 if pred_up else (1 - base_up2)
            wr, z, p = prop_z_p(k, n, base)
            rows.append(dict(gate="A2_cex_liqcascade", param=f"{side}_T{int(T)}", pred=label,
                             n=n, wr=round(wr, 4) if n else np.nan, base=round(base, 4),
                             lift_pp=round((wr - base) * 100, 2) if n else np.nan,
                             z=round(z, 2) if n else np.nan, p_one=round(p, 4) if n else np.nan))

    D = pd.DataFrame(rows)
    D.to_csv(OUT / "edge_val_stage1_liq_2026_06_01.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 90)
    print("STAGE 1 — LIQUIDATION-CASCADE GATE VALIDATION (directional WR vs chainlink outcome)")
    print("lift_pp = WR - base-rate ; p_one = one-sided z vs base rate")
    print("=" * 90)
    print(D.to_string(index=False))
    # headline check on A1 W60 T10k
    a1 = D[(D.gate == "A1_hl_shortcascade") & (D.param == "W60_T10000")]
    print("\nHEADLINE CHECK — report claims A1 W=60 T=10k: WR=57.9% p=0.041")
    print(a1.to_string(index=False))
    print(f"\ntotal {time.time()-t0:.0f}s ; wrote {OUT/'edge_val_stage1_liq_2026_06_01.csv'}")


if __name__ == "__main__":
    run()
