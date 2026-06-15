"""
POLY x KALSHI cross-venue arbitrage — BTC/ETH/SOL 15m up/down (Jun 2-4 overlap).
Both venues have the SAME contract: "<asset> price up in next 15 min?" (Kalshi KX{A}15M / Poly {a}-updown-15m).
Kalshi Yes = up = Poly Up token. Cross-venue complete set:
  A = buy Poly Up (ask) + Kalshi No (ask)   -> pays ~$1 (one leg wins)
  B = buy Kalshi Yes (ask) + Poly Down (ask)
If cost < 1 - fees -> positive-EV locked-ish set. RISK = settlement disagreement (Poly=Chainlink vs Kalshi=its
index): if venues disagree the set pays $0 or $2 (symmetric -> ~0 bias, adds variance). We MEASURE the
disagreement rate (basis risk) and the realized PnL.
Fees: Poly winner-only 0.07*p*(1-p); Kalshi ~0.07*p*(1-p) on the winning leg (approx).
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_resolutions, load_orderbook_l25_streaming
CANON = ROOT / "data/v4/canonical"

km = pd.read_parquet(CANON / "kalshi_markets.parquet")
ko = pd.read_parquet(CANON / "kalshi_orderbook.parquet").dropna(subset=["yes_ask", "no_ask"])
km = km[km.status == "finalized"].copy()
km["A"] = km.asset
# Poly resolutions 15m
res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["15m"])
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
res["min_key"] = (res.slot_start_us // 60_000_000)

def kal_fee(p):  return 0.07 * p * (1 - p)
def poly_fee(p): return 0.07 * p * (1 - p)

print("=== MATCH windows (asset + slot_start==kalshi open_time) ===")
rows = []
for a in ["BTC", "ETH", "SOL"]:
    kma = km[km.A == a].copy(); kma["min_key"] = (kma.open_time_us // 60_000_000)
    rr = res[res.ticker == a]
    mg = kma.merge(rr[["slug", "slot_start_us", "slot_end_us", "outcome", "min_key"]], on="min_key", how="inner")
    print(f"  {a}: kalshi {len(kma)} x poly {len(rr)} -> matched {len(mg)}")
    rows.append(mg)
M = pd.concat(rows, ignore_index=True)
M["kal_up"] = (M.result == "yes"); M["poly_up"] = (M.outcome == "Up")
print(f"\ntotal matched finalized windows: {len(M)}")
print("=== SETTLEMENT AGREEMENT (basis risk) Poly(chainlink) vs Kalshi(index) ===")
ag = (M.kal_up == M.poly_up).mean()
print(f"  outcome agreement = {ag:.4f}  (disagree {1-ag:.4f}) on n={len(M)}")
for a in ["BTC", "ETH", "SOL"]:
    s = M[M.A == a]; print(f"  {a}: agree {(s.kal_up==s.poly_up).mean():.4f} (n={len(s)})")

# ---- price arb scan ----
# kalshi quotes indexed by market_ticker; poly best-ask from L25 per slug
print("\n=== CROSS-VENUE COST SCAN ===", flush=True)
ko = ko.sort_values("time_us")
kidx = {mt: g for mt, g in ko.groupby("market_ticker")}
recs = []
for a in ["BTC", "ETH", "SOL"]:
    Ma = M[M.A == a]
    slugs = set(Ma.slug)
    if not slugs: continue
    books = load_orderbook_l25_streaming(a.lower(), slugs=slugs, subsample_1hz=True)  # 1Hz ok for arb scan
    for _, r in Ma.iterrows():
        kq = kidx.get(r.market_ticker)
        if kq is None or not len(kq): continue
        bu = books.get((r.slug, "Up")); bd = books.get((r.slug, "Down"))
        if bu is None or bd is None: continue
        ut, uap = bu[0], bu[1][:, 0]; dt, dap = bd[0], bd[1][:, 0]   # poly best ask up/down
        kt = kq.time_us.values; kya = kq.yes_ask.values; kna = kq.no_ask.values
        # window mask: only quotes within [slot_start, slot_end]
        in_win = (kt >= r.slot_start_us) & (kt <= r.slot_end_us)
        kt, kya, kna = kt[in_win], kya[in_win], kna[in_win]
        if not len(kt): continue
        # poly asks asof each kalshi quote time
        iu = np.searchsorted(ut, kt, "right") - 1; idn = np.searchsorted(dt, kt, "right") - 1
        ok = (iu >= 0) & (idn >= 0)
        if not ok.any(): continue
        pu = np.where(ok, uap[np.clip(iu, 0, len(uap)-1)], np.nan)
        pd_ = np.where(ok, dap[np.clip(idn, 0, len(dap)-1)], np.nan)
        costA = pu + kna[:len(pu)]            # poly up + kalshi no
        costB = kya[:len(pu)] + pd_           # kalshi yes + poly down
        valid = np.isfinite(costA) | np.isfinite(costB)
        if not valid.any(): continue
        cbest = np.minimum(np.where(np.isfinite(costA), costA, 9.0), np.where(np.isfinite(costB), costB, 9.0))
        cbest = cbest[cbest < 9.0]
        if not len(cbest): continue
        # EXECUTABLE entry: first timestamp where best cost < 0.98 (not the cherry-picked min)
        thr_entry = 0.98
        below = np.where(cbest < thr_entry)[0]
        ent_cost = float(cbest[below[0]]) if len(below) else np.nan
        ent_useA = None
        if len(below):
            j = below[0]
            ent_useA = bool((np.where(np.isfinite(costA), costA, 9.0)[j]) <= (np.where(np.isfinite(costB), costB, 9.0)[j]))
        recs.append(dict(asset=a, slug=r.slug, mt=r.market_ticker, poly_up=bool(r.poly_up), kal_up=bool(r.kal_up),
                         min_cost=float(cbest.min()), median_cost=float(np.median(cbest)),
                         frac_lt_098=float((cbest < 0.98).mean()), frac_lt_100=float((cbest < 1.0).mean()),
                         ent_cost=ent_cost, ent_useA=ent_useA, n_quotes=int(len(cbest))))
    del books
D = pd.DataFrame(recs)
D.to_parquet(ROOT / "strategy_lab/directional/_results/poly_kalshi_arb_2026_06_05.parquet")
print(f"windows with both books+quotes: {len(D)}")
print(f"  TIME-AVG cost per window: median-of-medians={D.median_cost.median():.3f}  (>=1 => no persistent arb)")
print(f"  frac of in-window time cost<1.00: mean={D.frac_lt_100.mean():.3f} ; cost<0.98: mean={D.frac_lt_098.mean():.3f}")
print(f"  windows whose MEDIAN cost < 1.00: {(D.median_cost<1).sum()} ({(D.median_cost<1).mean():.1%}) ; <0.98: {(D.median_cost<0.98).mean():.1%}")
print(f"  (min-over-window cost median={D.min_cost.median():.3f} = optimistic blip, ignore)")

# REALIZED: enter at FIRST executable crossing (cost<0.98), pay that cost, payout from outcomes, minus fee
def realized(d):
    sub = d[d.ent_cost.notna()].copy()
    if not len(sub): return None
    useA = sub.ent_useA.values.astype(bool); cost = sub.ent_cost.values
    pa = sub.poly_up.values.astype(int) + (~sub.kal_up.values).astype(int)
    pb = sub.kal_up.values.astype(int) + (~sub.poly_up.values).astype(int)
    payout = np.where(useA, pa, pb).astype(float)
    g = payout - cost; net = payout - cost - 0.05
    def boot(v,nb=4000):
        v=np.asarray(v); i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
    return len(sub), g.mean(), net.mean(), boot(net), (payout==0).mean(), (payout==2).mean()
print("\n=== REALIZED arb (enter at FIRST moment cost<0.98, executable) ===")
r = realized(D)
if r:
    print(f"  n={r[0]} (windows that ever crossed 0.98)  gross/set={r[1]:+.4f}  net(-$0.05)/set={r[2]:+.4f}  CI={tuple(round(x,3) for x in r[3])}")
    print(f"  disagree-loss(payout0)={r[4]:.3f}  bonus(payout2)={r[5]:.3f}")
print("\nREAD: real persistent arb needs MEDIAN cost<1 and high frac_lt time. If only transient crossings,")
print("the first-crossing realized PnL shows whether catching a dip is genuinely +EV net of fees+disagreement.")
