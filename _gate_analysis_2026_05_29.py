"""
_gate_analysis_2026_05_29.py — conditional gate analysis + stacking for the lag taker.
Reads the enriched fire parquet, computes per-gate True/False metrics (WR,$tr,t,n,maxDD),
IS/OOS stability, builds best gate stacks, and saves the gated fire subset.
Run: C:/Python314/python.exe _gate_analysis_2026_05_29.py
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
ENR = ROOT / "strategy_lab" / "lag_taker_fires_enriched_2026_05_29.parquet"
GATED_OUT = ROOT / "strategy_lab" / "lag_taker_fires_gated_2026_05_29.parquet"
print("ANALYSIS_V1_MARKER", flush=True)

F = pd.read_parquet(ENR)
DAYS = (1778800000 - 1778198400) / 86400.0  # ~ window length used for tr/day (approx 21d)
# recompute window days precisely from base slot_start
base_all = F[F.is_base]
DAYS = (base_all.slot_start.max() - base_all.slot_start.min()) / 86400.0


def stat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return np.nan, np.nan
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def max_dd(p):
    if len(p) == 0:
        return 0.0
    cum = np.cumsum(p); peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def metr(g):
    p = g.pnl.to_numpy(); m, t = stat(p)
    return dict(n=len(g), WR=round(100 * g.won.mean(), 1), dtr=round(m, 3),
                t=round(t, 2), tot=round(p.sum(), 0), maxDD=round(max_dd(p), 0))


def oos_t(g):
    o = g[g.period == "OOS"]
    if len(o) < 10:
        return np.nan, len(o), np.nan
    p = o.pnl.to_numpy(); m, t = stat(p)
    return round(t, 2), len(o), round(m, 3)


# ---------- BASE ----------
B = F[F.is_base].copy()
bm = metr(B)
ot, on, odt = oos_t(B)
print(f"\nBASE BTC+ETH d>=3: n={bm['n']} WR={bm['WR']} $tr={bm['dtr']} t={bm['t']} maxDD={bm['maxDD']} | OOS n={on} t={ot} $tr={odt}", flush=True)

# ---------- gate definition helpers ----------
def report_gate(name, mask):
    gt = B[mask]; gf = B[~mask]
    mt = metr(gt); mf = metr(gf)
    ott, otn, otd = oos_t(gt)
    lift = round(mt['dtr'] - bm['dtr'], 3)
    print(f"\n[{name}]", flush=True)
    print(f"  TRUE : n={mt['n']:4d} WR={mt['WR']:5} $tr={mt['dtr']:+.3f} t={mt['t']:+.2f} maxDD={mt['maxDD']} | OOS n={otn} t={ott} $tr={otd}", flush=True)
    print(f"  FALSE: n={mf['n']:4d} WR={mf['WR']:5} $tr={mf['dtr']:+.3f} t={mf['t']:+.2f}", flush=True)
    print(f"  lift vs base $tr={lift:+.3f}", flush=True)
    return dict(name=name, **{f"true_{k}": v for k, v in mt.items()},
                **{f"false_{k}": v for k, v in mf.items()},
                lift=lift, oos_t=ott, oos_n=otn, oos_dtr=otd)


rows = []
# 1. magnitude tiers
print("\n===== GATE 1: magnitude tiers =====", flush=True)
for thr in [3, 5, 8, 12]:
    g = B[B.delta_bps >= thr]; m = metr(g); ott, otn, otd = oos_t(g)
    print(f"  d>={thr:2d}: n={m['n']:4d} WR={m['WR']:5} $tr={m['dtr']:+.3f} t={m['t']:+.2f} maxDD={m['maxDD']} | OOS n={otn} t={ott}", flush=True)
    rows.append(dict(gate=f"delta>={thr}", **m, oos_t=ott, oos_n=otn))

# 2. persistence
rows.append(report_gate("persist3 (last3 1s same sign)", B.persist3 == 1.0))
# also persistence AND direction-consistent already implied by sign of move; test pure persistence
# 3. vol regime: low vs high rv30
rv_med = B.rv30_bps.median()
rows.append(report_gate(f"rv30 LOW (<med {rv_med:.3g}bps)", B.rv30_bps < rv_med))
rows.append(report_gate("rv30 HIGH (>=med)", B.rv30_bps >= rv_med))
for q in [0.33, 0.66]:
    pass
# tertiles
qa, qb = B.rv30_bps.quantile([1/3, 2/3])
print("\n  rv30 tertiles:", flush=True)
for lab, mask in [("low", B.rv30_bps < qa), ("mid", (B.rv30_bps >= qa) & (B.rv30_bps < qb)), ("high", B.rv30_bps >= qb)]:
    m = metr(B[mask]); print(f"    {lab}: n={m['n']} WR={m['WR']} $tr={m['dtr']:+.3f} t={m['t']:+.2f}", flush=True)

# 4. book depth / spread
dep_med = B.topdepth_usd.median()
rows.append(report_gate(f"topdepth HIGH (>=med {dep_med:.3g}$)", B.topdepth_usd >= dep_med))
rows.append(report_gate("spread tight (<=0.02)", B.spread_eff <= 0.02))
rows.append(report_gate("spread tight (<=0.01)", B.spread_eff <= 0.01))

# 6. time-of-day
print("\n===== GATE 6: time-of-day =====", flush=True)
B["hb"] = pd.cut(B.hour, bins=[-1, 5, 11, 17, 23], labels=["00-05", "06-11", "12-17", "18-23"])
for hb in ["00-05", "06-11", "12-17", "18-23"]:
    g = B[B.hb == hb]; m = metr(g); ott, otn, _ = oos_t(g)
    print(f"  {hb}: n={m['n']:4d} WR={m['WR']:5} $tr={m['dtr']:+.3f} t={m['t']:+.2f} | OOS t={ott}", flush=True)
rows.append(report_gate("ex 18-23 UTC", B.hour < 18))
rows.append(report_gate("00-11 UTC (best block)", B.hour < 12))

# 7. entry price band
print("\n===== GATE 7: entry vwap band =====", flush=True)
for lo, hi in [(0.0, 0.45), (0.45, 0.55), (0.45, 0.70), (0.55, 0.70), (0.70, 1.0)]:
    g = B[(B.entry_vwap >= lo) & (B.entry_vwap < hi)]
    if len(g) < 10:
        continue
    m = metr(g); print(f"  vwap[{lo},{hi}): n={m['n']:4d} WR={m['WR']:5} $tr={m['dtr']:+.3f} t={m['t']:+.2f}", flush=True)
rows.append(report_gate("vwap in [0.45,0.70)", (B.entry_vwap >= 0.45) & (B.entry_vwap < 0.70)))
rows.append(report_gate("vwap < 0.62", B.entry_vwap < 0.62))

# 8. microstructure ta alignment with direction
# RSI: for Up fires want rsi not overbought / momentum supportive; test alignment
up = B.direction == "Up"
# "ta agrees" = (Up & macd_hist>0) or (Down & macd_hist<0)
macd_agree = ((up) & (B.macd_hist > 0)) | ((~up) & (B.macd_hist < 0))
rows.append(report_gate("macd_hist agrees w/ dir", macd_agree))
cci_agree = ((up) & (B.cci20 > 0)) | ((~up) & (B.cci20 < 0))
rows.append(report_gate("cci20 agrees w/ dir", cci_agree))
rsi_agree = ((up) & (B.rsi14 > 50)) | ((~up) & (B.rsi14 < 50))
rows.append(report_gate("rsi14 agrees w/ dir (>50 up)", rsi_agree))
# contrarian variant: ta DISAGREES (mean reversion into oracle settle)
rows.append(report_gate("macd_hist DISagrees w/ dir", ~macd_agree))

# 5. cross-asset confluence: BTC & ETH agree on direction in overlapping slot windows
print("\n===== GATE 5: cross-asset confluence (BTC&ETH same dir, overlapping time) =====", flush=True)
# For each fire, look for an opposite-asset fire whose [slot_start, slot_start+window] overlaps
# fire time and shares direction. Use ALL fires F (any delta) of the other asset as evidence.
WINSEC = {"5m": 300, "15m": 900}
other = {"BTC": "ETH", "ETH": "BTC"}
allf = F[F.asset.isin(["BTC", "ETH"])].copy()
allf["win_s"] = allf.tf.map(WINSEC)
conf = pd.Series(index=B.index, data=False)
# build per-asset arrays for quick overlap test
oa = {a: allf[allf.asset == a].sort_values("slot_start") for a in ["BTC", "ETH"]}
for idx, row in B.iterrows():
    oth = oa[other[row.asset]]
    # opposite-asset fire active at row.fire_us with same direction (delta>=3 to be a real lead)
    ft = row.fire_us
    cand = oth[(oth.slot_start * 1_000_000 <= ft) &
               ((oth.slot_start + oth.win_s) * 1_000_000 >= ft) &
               (oth.delta_bps >= 3.0) & (oth.direction == row.direction)]
    conf.loc[idx] = len(cand) > 0
rows.append(report_gate("cross-asset confluence (>=3bps same dir)", conf))
B["xconf"] = conf

# ---------- STACK building ----------
print("\n" + "=" * 80, flush=True)
print("STACKS", flush=True)
print("=" * 80, flush=True)
B["macd_agree"] = macd_agree
B["rsi_agree"] = rsi_agree
B["cci_agree"] = cci_agree
B["macd_dis"] = ~macd_agree

stacks = {
    "S0 base (d>=3)": pd.Series(True, index=B.index),
    "S1 ex18-23": B.hour < 18,
    "S2 ex18-23 + d>=5": (B.hour < 18) & (B.delta_bps >= 5),
    "S3 ex18-23 + vwap<0.70": (B.hour < 18) & (B.entry_vwap < 0.70),
    "S4 ex18-23 + macd_dis": (B.hour < 18) & B.macd_dis,
    "S5 ex18-23 + macd_dis + vwap<0.70": (B.hour < 18) & B.macd_dis & (B.entry_vwap < 0.70),
    "S6 ex18-23 + d>=5 + macd_dis": (B.hour < 18) & (B.delta_bps >= 5) & B.macd_dis,
    "S7 xconf + ex18-23": B.xconf & (B.hour < 18),
    "S8 macd_dis only": B.macd_dis,
    "S9 ex18-23 + vwap<0.62": (B.hour < 18) & (B.entry_vwap < 0.62),
    "S10 ex18-23 + macd_dis + d>=5": (B.hour < 18) & B.macd_dis & (B.delta_bps >= 5),
}
srows = []
for nm, mk in stacks.items():
    g = B[mk]; m = metr(g); ott, otn, otd = oos_t(g)
    ist = metr(g[g.period == "IS"]) if (g.period == "IS").sum() >= 10 else {}
    perday = round(m['n'] / DAYS, 1)
    print(f"{nm:38s} n={m['n']:4d} WR={m['WR']:5} $tr={m['dtr']:+.3f} t={m['t']:+.2f} maxDD={m['maxDD']:>6} /day={perday:5} | IS t={ist.get('t','-')} | OOS n={otn} t={ott} $tr={otd}", flush=True)
    srows.append(dict(stack=nm, **m, perday=perday, IS_t=ist.get('t'), oos_n=otn, oos_t=ott, oos_dtr=otd))

# pick best by OOS t with adequate n
SR = pd.DataFrame(srows)
SR.to_csv(ROOT / "strategy_lab" / "directional" / "_results" / "lag_taker_gate_stacks.csv", index=False)
pd.DataFrame(rows).to_csv(ROOT / "strategy_lab" / "directional" / "_results" / "lag_taker_gate_singles.csv", index=False)

# save the recommended gated subset = best stack chosen below (set after reading output)
BEST = (B.hour < 18) & B.macd_dis  # S4 as default; may revise
gated = B[BEST].copy()
gated.to_parquet(GATED_OUT, index=False)
print(f"\nSAVED gated subset (S4 default) n={len(gated)} -> {GATED_OUT}", flush=True)
print("window days:", round(DAYS, 1), flush=True)
print("DONE", flush=True)
