"""
s4_faithful.py — FAITHFUL S4 ALL_15m_S4_prewindow backtest, matching the LIVE engine.

Fixes the 3 fidelity bugs in the first attempt (s4_backtest_2026_06_03/backtest.py):
  1. strike = CHAINLINK (load_chainlink_asof), not binance.
  2. fill = engine_v2.fill_at_book LegacyConfig + spread_filter (like the original sweep),
     and the fair_edge gate uses the $25 WALK vwap (not best-ask).
  3. Runs THREE strike modes to expose the lookahead:
       - live_causal   : strike = chainlink @ fire_us  (what LIVE actually does; signal evt
                         showed strike≈s_now @ fire, fair_up≈0.51)
       - orig_lookahead: strike = chainlink @ slot_start (reproduces the n=229 original sweep)
Plus the Kalshi in-window re-fill (slot+60) on the SAME fire set, and the full regression
battery + a by-week comparison to the LIVE ground truth (May25 WR80%/+267 ; Jun1 WR31%/-160).

Window Apr 24 -> Jun 1 09:00 UTC. 15m only, BTC/ETH/SOL. $25 notional. 2%-on-profit fee
(LegacyConfig) = the live shadow fill model; 0.07-curve reported alongside.
Run: C:/Python314/python.exe strategy_lab/s4_backtest_2026_06_03/s4_faithful.py
"""
import sys, math, gc
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm, binomtest
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_klines_1s, load_chainlink_asof, load_orderbook_l25_streaming
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl

WIN_LO = int(pd.Timestamp("2026-04-24 00:00", tz="UTC").value // 1000)
WIN_HI = int(pd.Timestamp("2026-06-01 09:00", tz="UTC").value // 1000)
# original sweep window (binance_1s_28d) ~ Apr 28 -> May 26; report this sub-window as "baseline"
BASE_LO = int(pd.Timestamp("2026-04-28 00:00", tz="UTC").value // 1000)
BASE_HI = int(pd.Timestamp("2026-05-26 00:00", tz="UTC").value // 1000)
ASSETS = ["BTC", "ETH", "SOL"]
SPREAD = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
OUT = ROOT / "strategy_lab" / "s4_backtest_2026_06_03"

# ---- binance 1s arrays ----
print("loading 1s klines...")
S1 = {}
for a in ASSETS:
    df = load_klines_1s(a)
    df = df[(df.time_period_start_us >= WIN_LO - 1400*1_000_000) & (df.time_period_start_us <= WIN_HI + 300*1_000_000)]
    df = df.drop_duplicates("time_period_start_us").sort_values("time_period_start_us")
    S1[a] = (df.time_period_start_us.values.astype("int64"), df.price_close.values.astype("float64"),
             df.volume_traded.values.astype("float64"), df.taker_buy_quote.values.astype("float64"),
             df.quote_volume.values.astype("float64"))
CK = {a: tuple(np.asarray(x) for x in load_chainlink_asof(a)) for a in ASSETS}

def asof(ts, px, t):
    i = int(np.searchsorted(ts, t, side="right")) - 1
    return float(px[i]) if i >= 0 else float("nan")

def feat(a, fire_us):
    ts, cls, vol, tbq, qv = S1[a]
    i1 = int(np.searchsorted(ts, fire_us, side="right"))
    if i1 == 0: return None
    lo = int(np.searchsorted(ts, fire_us - 900*1_000_000, side="left"))
    tsf, clf, vlf, tbf, qvf = ts[lo:i1], cls[lo:i1], vol[lo:i1], tbq[lo:i1], qv[lo:i1]
    if len(clf) < 31: return None
    s_now = float(clf[-1])
    # sigma over 900s
    cl = clf[np.isfinite(clf) & (clf > 0)]
    rets = np.diff(np.log(cl)); rets = rets[np.isfinite(rets)]
    sigma = math.sqrt(rets.var(ddof=1)) if len(rets) >= 30 and rets.var(ddof=1) > 0 else None
    # cvd 30s
    s30 = tsf >= fire_us - 30*1_000_000
    cvd30 = float(np.sum(2.0*tbf[s30] - qvf[s30])) if s30.sum() > 0 else None
    # dev_bps: 15m UTC-bucket anchored vwap
    bk = (fire_us // (900*1_000_000)) * (900*1_000_000)
    vs = tsf >= bk
    dev = None
    if vs.sum() > 0 and vlf[vs].sum() > 0:
        vwap = float((clf[vs]*vlf[vs]).sum()/vlf[vs].sum())
        if vwap > 0 and s_now > 0: dev = 10000.0*math.log(s_now/vwap)
    return dict(s_now=s_now, sigma=sigma, cvd30=cvd30, dev=dev)

def fair_up(s_now, strike, sigma, tau):
    if not all(x and math.isfinite(x) for x in (s_now, strike, sigma, tau)): return None
    if s_now<=0 or strike<=0 or sigma<=0 or tau<=0: return None
    return float(norm.cdf(math.log(s_now/strike)/(sigma*math.sqrt(tau))))

def pnl07(vwap, sh, won): return (1-vwap)*sh*(1-0.07*vwap) if won else -vwap*sh
def pnlkal(vwap, sh, won):
    f = 0.07*vwap*(1-vwap)
    return sh*((1-vwap)-f) if won else -sh*(vwap+f)

cfg = LegacyConfig()
res = load_resolutions(assets=ASSETS, timeframes=["15m"])
res = res[(res.slot_start_us >= WIN_LO) & (res.slot_start_us <= WIN_HI)].copy()
print(f"15m slots: {len(res)}")

recs = []
for a in ASSETS:
    ra = res[res.ticker == a]
    slugs = set(ra.slug)
    print(f"{a}: {len(ra)} slots, loading L25...")
    books = load_orderbook_l25_streaming(a.lower(), slugs=slugs, subsample_1hz=True,
                                         min_ts_us=WIN_LO-200*1_000_000, max_ts_us=WIN_HI+1100*1_000_000)
    ck_ts, ck_px = CK[a]
    for _, r in ra.iterrows():
        ss, se = int(r.slot_start_us), int(r.slot_end_us)
        fire = ss - 120*1_000_000
        f = feat(a, fire)
        if f is None or f["dev"] is None or f["sigma"] is None or f["cvd30"] is None: continue
        dev = f["dev"]
        if abs(dev) < 8: continue
        direction = "UP" if dev > 0 else "DOWN"; leg = "Up" if dev > 0 else "Down"
        tau = (se - fire)/1_000_000.0
        won = (leg == r.outcome)
        wk = pd.to_datetime(ss/1e6, unit="s", utc=True).isocalendar()
        # fills: pre-window (A), in-window slot+60 (B)
        fa = fill_at_book(books, r.slug, leg, fire, cfg=cfg, spread_filter=SPREAD[a])
        if fa is None: continue   # spread/staleness/coverage drop (matches original)
        ev = float(fa["vwap"])
        fb = fill_at_book(books, r.slug, leg, ss + 60*1_000_000, cfg=cfg, spread_filter=SPREAD[a])
        for mode, strike in (("live_causal", asof(ck_ts, ck_px, fire)),
                             ("orig_lookahead", asof(ck_ts, ck_px, ss))):
            fu = fair_up(f["s_now"], strike, f["sigma"], tau)
            if fu is None: continue
            fe = (fu - ev)*1e4 if direction == "UP" else ((1-fu) - ev)*1e4
            cvd_ok = (f["cvd30"] > 0) if direction == "UP" else (f["cvd30"] < 0)
            if not (fe > 500 and cvd_ok): continue
            recs.append(dict(mode=mode, fill="A_poly_prewin", asset=a, slug=r.slug, direction=direction,
                             slot_start_us=ss, won=won, entry_vwap=ev, fe=fe, dev=dev, fair_up=fu,
                             pnl=hold_pnl(fa, won=won, cfg=cfg), pnl07=pnl07(ev, float(fa["shares"]), won),
                             iso=f"{wk.year}-W{wk.week:02d}", in_base=(BASE_LO <= ss <= BASE_HI)))
            if fb is not None:
                evb = float(fb["vwap"])
                recs.append(dict(mode=mode, fill="B_kalshi_inwin60", asset=a, slug=r.slug, direction=direction,
                                 slot_start_us=ss, won=won, entry_vwap=evb, fe=fe, dev=dev, fair_up=fu,
                                 pnl=hold_pnl(fb, won=won, cfg=cfg), pnl07=pnlkal(evb, float(fb["shares"]), won),
                                 iso=f"{wk.year}-W{wk.week:02d}", in_base=(BASE_LO <= ss <= BASE_HI)))
    del books; gc.collect()

bt = pd.DataFrame(recs)
bt.to_csv(OUT / "s4_faithful_fires.csv", index=False)

def stats(d, col="pnl"):
    if len(d) == 0: return "n=0"
    n=len(d); w=int(d.won.sum()); wr=w/n; pt=d[col].mean(); tot=d[col].sum()
    p=binomtest(w, n, 0.5, alternative="greater").pvalue
    cum=np.cumsum(d.sort_values("slot_start_us")[col].values); dd=float((np.maximum.accumulate(cum)-cum).max()) if n else 0
    return f"n={n:4d} WR={wr*100:5.1f}% $/tr={pt:+6.3f} tot={tot:+8.1f} p={p:.3f} maxDD={dd:7.1f} impl={d.entry_vwap.mean():.3f}"

print("\n================= FAITHFUL S4 RESULTS (LegacyConfig 2%-on-profit) =================")
for mode in ("live_causal", "orig_lookahead"):
    A = bt[(bt["mode"]==mode)&(bt.fill=="A_poly_prewin")]
    print(f"\n--- strike mode = {mode} ---")
    print(f"  FULL  pre-window(A): {stats(A)}")
    print(f"  BASE  pre-window(A): {stats(A[A.in_base])}   [vs original n=229 WR=54.6% +$2.26]")
    B = bt[(bt['mode']==mode)&(bt.fill=='B_kalshi_inwin60')]
    print(f"  FULL  kalshi-inwin60(B): {stats(B)}")
    print(f"  by-week (A):")
    for wk, g in A.groupby("iso"):
        print(f"      {wk}: {stats(g)}")
    print(f"  per-asset (A): " + " | ".join(f"{x}:{stats(A[A.asset==x])}" for x in ASSETS))
    print(f"  per-dir   (A): " + " | ".join(f"{x}:{stats(A[A.direction==x])}" for x in ("UP","DOWN")))
print("\nLIVE GROUND TRUTH (VPS3 resolutions): 2026-W22(May25) n=20 WR80.0% +$266.85 | 2026-W23(Jun1) n=16 WR31.3% -$160.49 | total n=36 WR58.3% +$106")
print(f"\nwrote {OUT/'s4_faithful_fires.csv'}")
