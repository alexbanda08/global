"""
edge_val_stage3_polyflow_2026_06_01.py — STAGE 3: Polymarket order-flow gates (B1 VPIN, C4 CVD).

CAUSAL ANCHOR FIX: ws_s = slot_start - window is BEFORE the slug's market opens, so the report's
"trades in [ws_s-300,ws_s]" can't read the current slug. We instead read the slug's OWN early flow
over [slot_start, fire_us] (fire_us = slot_start + offset) and predict its chainlink resolution.
Entry would be at fire_us (lag-taker style). Fully causal: flow precedes fire_us; outcome is at slot_end.

Cross-token signed CVD per trade (side = taker side):
  +notional if (outcome==Up & side==buy)  or (outcome==Down & side==sell)   [UP pressure]
  -notional if (outcome==Up & side==sell) or (outcome==Down & side==buy)    [DOWN pressure]

Gates:
  C4_follow      : total CVD over [slot_start,fire] ; predict UP if CVD>+T, DOWN if <-T (follow informed flow)
  C4_reversal    : slow=[0,off-30], fast=(off-30,off] ; exhaustion: slow strongly one way AND fast flips -> contrarian
  B1_vpin        : |CVD| / gross_notional over window (informed-flow fraction) as a CONFIDENCE gate on C4_follow

Metric: directional WR vs chainlink outcome (z vs base rate). PnL/L25 fill = later stage.
Window: Apr26 -> Jun1 (trades coverage). BTC+ETH+SOL.
Usage: C:/Python314/python.exe strategy_lab/directional/edge_val_stage3_polyflow_2026_06_01.py
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_trades  # noqa: E402

OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"5m": 300, "15m": 900}
# offset (seconds into window) at which we'd fire / cut the flow read
OFFSET = {"5m": 120, "15m": 300}
FAST = 30  # last-N seconds = fast bucket


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def z_p(k, n, p0):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    ph = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return (ph, np.nan, np.nan)
    z = (ph - p0) / se
    return (ph, z, 2 * (1 - norm_cdf(abs(z))))


def build(asset):
    res = load_resolutions()
    res = res[(res.ticker == asset) & res.timeframe.isin(["5m", "15m"])].copy()
    res["slot_start_us"] = res.slot_start_us.astype(np.int64)
    res["won_up"] = (res.outcome.astype(str).str.lower() == "up")
    meta = res.set_index("slug")[["slot_start_us", "timeframe", "won_up"]]

    tr = load_trades(asset)
    tr = tr[tr.outcome.isin(["Up", "Down"]) & tr.side.isin(["buy", "sell"])].copy()
    tr = tr.join(meta, on="slug", how="inner")
    tr["t_rel"] = (tr.timestamp_us.astype(np.int64) - tr.slot_start_us) / 1_000_000.0
    tr["off"] = tr.timeframe.map(OFFSET).astype(float)
    tr = tr[(tr.t_rel >= 0) & (tr.t_rel <= tr.off)]
    notional = tr.price.astype(float) * tr["size"].astype(float)
    up = tr.outcome.values == "Up"
    buy = tr.side.values == "buy"
    sign = np.where((up & buy) | (~up & ~buy), 1.0, -1.0)
    tr["sig"] = sign * notional
    tr["gross"] = notional
    tr["is_fast"] = tr.t_rel > (tr.off - FAST)
    g = tr.groupby("slug").agg(
        cvd=("sig", "sum"), gross=("gross", "sum"),
        cvd_fast=("sig", lambda s: s[tr.loc[s.index, "is_fast"]].sum()),
        ntr=("sig", "size"))
    g["cvd_slow"] = g.cvd - g.cvd_fast
    g = g.join(meta[["won_up", "timeframe"]])
    g["asset"] = asset
    return g.reset_index()


def run():
    t0 = time.time()
    parts = []
    for a in ["BTC", "ETH", "SOL"]:
        gg = build(a)
        print(f"[{a}] slugs-with-flow={len(gg)} t={time.time()-t0:.0f}s", flush=True)
        parts.append(gg)
    G = pd.concat(parts, ignore_index=True)
    G.to_parquet(OUT / "edge_val_stage3_polyflow_features_2026_06_01.parquet", index=False)

    def evalset(D, label):
        rows = []
        base_up = float(D.won_up.mean())
        n0 = len(D)
        rows.append(dict(set=label, gate="BASE_rate", param="-", pred="-", n=n0,
                         wr=round(base_up, 4), ref=0.5, lift_pp=round((base_up - .5) * 100, 2), z=np.nan, p=np.nan))
        # C4_follow: predict UP if cvd>+T else DOWN if cvd<-T
        for T in [50, 200, 500, 1000]:
            q = np.abs(D.cvd) > T
            pred_up = D.cvd > 0
            nn = int(q.sum())
            if nn < 20:
                continue
            k = int((pred_up[q] == D.won_up[q]).sum())
            wr, z, p = z_p(k, nn, 0.5)
            rows.append(dict(set=label, gate="C4_cvd_follow", param=f"|cvd|>{T}", pred="flow",
                             n=nn, wr=round(wr, 4), ref=0.5, lift_pp=round((wr - .5) * 100, 2),
                             z=round(z, 2), p=round(p, 4)))
        # C4_reversal: slow strongly one way (|slow|>T) AND fast opposite sign -> contrarian to slow
        for T in [200, 500, 1000]:
            q = (np.abs(D.cvd_slow) > T) & (np.sign(D.cvd_fast) == -np.sign(D.cvd_slow)) & (D.cvd_fast != 0)
            pred_up = D.cvd_slow < 0   # slow was DOWN-pressure exhausting -> bet UP
            nn = int(q.sum())
            if nn < 20:
                continue
            k = int((pred_up[q] == D.won_up[q]).sum())
            wr, z, p = z_p(k, nn, 0.5)
            rows.append(dict(set=label, gate="C4_cvd_reversal", param=f"|slow|>{T}&fastflip", pred="contra",
                             n=nn, wr=round(wr, 4), ref=0.5, lift_pp=round((wr - .5) * 100, 2),
                             z=round(z, 2), p=round(p, 4)))
        # B1_vpin: follow-flow but only when informed fraction high
        D = D.copy()
        D["vpin"] = np.where(D.gross > 0, np.abs(D.cvd) / D.gross, 0.0)
        for vq in [0.5, 0.7, 0.9]:
            thr = D.vpin.quantile(vq)
            q = (D.vpin >= thr) & (np.abs(D.cvd) > 200)
            pred_up = D.cvd > 0
            nn = int(q.sum())
            if nn < 20:
                continue
            k = int((pred_up[q] == D.won_up[q]).sum())
            wr, z, p = z_p(k, nn, 0.5)
            rows.append(dict(set=label, gate="B1_vpin_follow", param=f"vpin>=q{int(vq*100)}", pred="flow",
                             n=nn, wr=round(wr, 4), ref=0.5, lift_pp=round((wr - .5) * 100, 2),
                             z=round(z, 2), p=round(p, 4)))
        return rows

    rows = []
    rows += evalset(G[G.asset.isin(["BTC", "ETH"])], "BTC+ETH")
    rows += evalset(G[G.asset == "SOL"], "SOL")
    for a in ["BTC", "ETH"]:
        rows += evalset(G[G.asset == a], a)
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "edge_val_stage3_polyflow_2026_06_01.csv", index=False)
    pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
    print("\n" + "=" * 92)
    print("STAGE 3 — POLYMARKET ORDER-FLOW GATES (within-slug CVD @ fire=slot_start+offset)")
    print("predict slug's own chainlink outcome ; WR vs 0.5")
    print("=" * 92)
    print(R.to_string(index=False))
    print(f"\ntotal {time.time()-t0:.0f}s ; wrote stage3 csv + features parquet")


if __name__ == "__main__":
    run()
