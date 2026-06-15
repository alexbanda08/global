"""
POLY x KALSHI arb — TREASURY / venue-balance simulation.
Each arb set returns $1 to ONE venue at resolution (the winning leg's venue). Question: does the capital
drift to one venue (forcing slow cross-venue transfers), or self-balance? And can a balance-aware policy
hold both venues funded (preferring Poly-accumulation) with minimal edge loss?
Per set ($1 notional), entry pays leg prices, settle returns $1 to winner's venue. We track running per-venue cash.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_resolutions, load_orderbook_l25_streaming, load_kalshi_markets, load_kalshi_orderbook
THR = 0.95   # take arb when complete-set cost first dips below this

km = load_kalshi_markets(); km = km[km.status == "finalized"]
ko = load_kalshi_orderbook().dropna(subset=["yes_ask", "no_ask"]).sort_values("time_us")
res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["15m"])
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug"); res["min_key"] = res.slot_start_us // 60_000_000
M = []
for a in ["BTC", "ETH", "SOL"]:
    kma = km[km.asset == a].copy(); kma["min_key"] = kma.open_time_us // 60_000_000
    M.append(kma.merge(res[res.ticker == a][["slug", "slot_start_us", "slot_end_us", "outcome", "min_key"]], on="min_key"))
M = pd.concat(M, ignore_index=True); M["poly_up"] = M.outcome == "Up"; M["kal_up"] = M.result == "yes"
kfee = lambda p: np.ceil(0.07 * p * (1 - p) * 100) / 100
pfee = lambda p: 0.07 * p * (1 - p)
kidx = {mt: g for mt, g in ko.groupby("market_ticker")}
recs = []
for a in ["BTC", "ETH", "SOL"]:
    Ma = M[M.asset == a]; books = load_orderbook_l25_streaming(a.lower(), slugs=set(Ma.slug), subsample_1hz=True)
    for _, r in Ma.iterrows():
        kq = kidx.get(r.market_ticker); bu = books.get((r.slug, "Up")); bd = books.get((r.slug, "Down"))
        if kq is None or bu is None or bd is None: continue
        ut, uap = bu[0], bu[1][:, 0]; dt, dap = bd[0], bd[1][:, 0]
        m = (kq.time_us.values >= r.slot_start_us) & (kq.time_us.values <= r.slot_end_us)
        kt, kya, kna = kq.time_us.values[m], kq.yes_ask.values[m], kq.no_ask.values[m]
        if not len(kt): continue
        iu = np.clip(np.searchsorted(ut, kt, "right") - 1, 0, len(uap) - 1); idn = np.clip(np.searchsorted(dt, kt, "right") - 1, 0, len(dap) - 1)
        ok = (np.searchsorted(ut, kt, "right") > 0) & (np.searchsorted(dt, kt, "right") > 0)
        costA = np.where(ok, uap[iu] + kna, 9.0); costB = np.where(ok, kya + dap[idn], 9.0)
        cb = np.minimum(costA, costB); bl = np.where(cb < THR)[0]
        if not len(bl): continue
        j = bl[0]; ua = costA[j] <= costB[j]
        if ua:  # dir A: Poly Up (p=uap), Kalshi No (k=kna)
            pleg, kleg = uap[iu][j], kna[j]; poly_win = bool(r.poly_up); kal_win = bool(not r.kal_up)
        else:   # dir B: Poly Down, Kalshi Yes
            pleg, kleg = dap[idn][j], kya[j]; poly_win = bool(not r.poly_up); kal_win = bool(r.kal_up)
        dPoly = -pleg + (1 - (pfee(pleg)) if poly_win else 0.0)       # entry out + (win - winnerfee)
        dKal = -kleg + (1 - 0.0 if kal_win else 0.0) - kfee(kleg)      # kalshi entry fee always (on trade)
        recs.append(dict(t=int(r.slot_end_us), asset=a, dirA=bool(ua), poly_win=poly_win, kal_win=kal_win,
                         dPoly=float(dPoly), dKal=float(dKal), pleg=float(pleg), kleg=float(kleg),
                         net=float(dPoly + dKal), exp_poly=float(pleg if ua else (1 - pleg))))  # ~P(win lands on poly)
    del books
D = pd.DataFrame(recs).sort_values("t").reset_index(drop=True)
days = (M.slot_end_us.max() - M.slot_start_us.min()) / 1e6 / 86400
print(f"=== TREASURY SIM (arb cost<{THR}, $1/set, {len(D)} sets over {days:.1f}d) ===")
print(f"net profit/set (both venues): {D.net.mean():+.4f}  total=${D.net.sum():+.2f}")

def sim(d, label):
    cp = d.dPoly.cumsum().values; ck = d.dKal.cumsum().values
    imb = cp - ck                      # poly-minus-kalshi running cash drift
    # capital needed per venue = -min(running cumulative) (worst depletion below start)
    poly_need = -min(0, cp.min()); kal_need = -min(0, ck.min())
    print(f"\n[{label}] n={len(d)}")
    print(f"  final cum: Poly={cp[-1]:+.2f}  Kalshi={ck[-1]:+.2f}  (profit split)")
    print(f"  win-venue counts: Poly-wins={d.poly_win.sum()} Kalshi-wins={d.kal_win.sum()}")
    print(f"  running imbalance (Poly-Kalshi cash): max={imb.max():+.2f} min={imb.min():+.2f} -> peak gap=${abs(imb).max():.2f}")
    print(f"  working capital needed: Poly>=${poly_need:.2f}  Kalshi>=${kal_need:.2f} (per $1 set; scale by stake)")
    return abs(imb).max(), d.net.sum()

# 1) take-everything (forced direction)
g0 = sim(D, "TAKE ALL arbs (forced direction)")
# 2) balance-aware: skip a set if it would push the current imbalance further from 0 beyond a band
def balance_aware(d, band=3.0, prefer_poly=0.0):
    cp = ck = 0.0; taken = []
    for _, r in d.iterrows():
        imb = cp - ck                      # >0 = poly ahead
        # this set's expected drift to poly vs kalshi ~ exp_poly (win prob to poly)
        # skip if imbalance already > band in the SAME direction this set would worsen
        worsen_poly = r.exp_poly > 0.5     # set likely sends win to poly
        if imb > band + prefer_poly and worsen_poly: continue
        if imb < -band + prefer_poly and (not worsen_poly): continue
        cp += r.dPoly; ck += r.dKal; taken.append(r)
    td = pd.DataFrame(taken)
    return td
for band in [5.0, 3.0, 2.0]:
    td = balance_aware(D, band=band)
    if len(td) < 5: continue
    g = sim(td, f"BALANCE-AWARE band=${band} (skip sets that worsen imbalance)")
    print(f"  edge kept: ${td.net.sum():+.2f} of ${D.net.sum():+.2f} ({td.net.sum()/D.net.sum():.0%}) on {len(td)}/{len(D)} sets")
print("\nREAD: if TAKE-ALL peak gap is small -> auto-balances, no rebalancing needed. If large, balance-aware")
print("holds the gap within band at the cost of skipped sets (edge kept %). prefer_poly>0 biases accumulation to Poly.")
