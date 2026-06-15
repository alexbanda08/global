"""
POLY x KALSHI 15m arb — full QUANTIFICATION. Captures per-leg entry prices, proper per-venue fees,
realized $ per set, total capturable, per asset, opportunity counts at multiple thresholds + persistence.
Fee model: Poly winner-only 0.07*p*(1-p) on the poly leg IF it wins; Kalshi entry fee 0.07*p*(1-p) on its leg
(rounded up to 1c, Kalshi-style). Set = $1 notional (1 share each leg).
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_resolutions, load_orderbook_l25_streaming, load_kalshi_markets, load_kalshi_orderbook

km = load_kalshi_markets(); km = km[km.status == "finalized"]
ko = load_kalshi_orderbook().dropna(subset=["yes_ask", "no_ask"]).sort_values("time_us")
res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["15m"])
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug"); res["min_key"] = res.slot_start_us // 60_000_000
M = []
for a in ["BTC", "ETH", "SOL"]:
    kma = km[km.asset == a].copy(); kma["min_key"] = kma.open_time_us // 60_000_000
    M.append(kma.merge(res[res.ticker == a][["slug", "slot_start_us", "slot_end_us", "outcome", "min_key"]], on="min_key"))
M = pd.concat(M, ignore_index=True)
M["poly_up"] = M.outcome == "Up"; M["kal_up"] = M.result == "yes"
print(f"WINDOWS: {len(M)} matched finalized 15m windows, {pd.to_datetime(M.slot_start_us.min(),unit='us')} -> {pd.to_datetime(M.slot_end_us.max(),unit='us')}")
print(f"  per asset: {M.asset.value_counts().to_dict()}")
print(f"  settlement agreement (Chainlink vs Kalshi index): {(M.poly_up==M.kal_up).mean():.4f}")

kfee = lambda p: np.ceil(0.07 * p * (1 - p) * 100) / 100      # Kalshi entry fee, round up to cent
pfee = lambda p: 0.07 * p * (1 - p)                            # Poly winner-only

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
        iu = np.clip(np.searchsorted(ut, kt, "right") - 1, 0, len(uap) - 1)
        idn = np.clip(np.searchsorted(dt, kt, "right") - 1, 0, len(dap) - 1)
        ok = (np.searchsorted(ut, kt, "right") > 0) & (np.searchsorted(dt, kt, "right") > 0)
        pu, pdn = uap[iu], dap[idn]
        costA = np.where(ok, pu + kna, 9.0)      # poly Up + kalshi No
        costB = np.where(ok, kya + pdn, 9.0)     # kalshi Yes + poly Down
        cb = np.minimum(costA, costB); useA = costA <= costB
        valid = cb < 9.0
        if not valid.any(): continue
        cb_v = cb[valid]
        # entry at FIRST crossing below each threshold, capture per-leg prices + realized net
        for THR in [0.99, 0.97, 0.95, 0.92, 0.90, 0.85]:
            bl = np.where(cb < THR)[0]
            if not len(bl): continue
            j = bl[0]; ua = bool(useA[j])
            if ua: pl, kl = pu[j], kna[j]; payout = int(r.poly_up) + int(not r.kal_up)
            else:  pl, kl = pdn[j], kya[j]; payout = int(not r.poly_up) + int(r.kal_up)
            cost = pl + kl; poly_wins = (r.poly_up if ua else (not r.poly_up))
            fee = kfee(kl) + (pfee(pl) if poly_wins else 0.0)
            recs.append(dict(thr=THR, asset=a, slug=r.slug, gross=payout - cost, net=payout - cost - fee,
                             cost=cost, payout=payout))
    del books
D = pd.DataFrame(recs)
nwin = len(M); days = (M.slot_end_us.max() - M.slot_start_us.min()) / 1e6 / 86400
def boot(v,nb=5000):
    v=np.asarray(v); i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
print(f"\n=== OPPORTUNITY by ENTRY THRESHOLD (enter at first moment set-cost < thr; {days:.1f}-day sample) ===")
print(f"{'thr':>5} {'n_win':>6} {'/day':>5} {'entryCost':>9} {'GROSS/set':>10} {'NET/set':>9} {'NET 95%CI':>20} {'$0loss':>7} {'@$100 NETtot':>12}")
for thr in [0.99,0.97,0.95,0.92,0.90,0.85]:
    d=D[D.thr==thr]
    if len(d)<5: continue
    lo,hi=boot(d.net.values)
    print(f"{thr:>5.2f} {len(d):>6} {len(d)/days:>5.0f} {d.cost.mean():>9.3f} {d.gross.mean():>+10.4f} {d.net.mean():>+9.4f} "
          f"[{lo:>+7.4f},{hi:>+7.4f}] {(d.payout==0).mean():>7.3f} {d.net.sum()*100:>+12.0f}")
print(f"\nPER ASSET at thr<0.95 (net $/set):")
d95=D[D.thr==0.95]
for a in ["BTC","ETH","SOL"]:
    da=d95[d95.asset==a]; lo,hi=boot(da.net.values) if len(da)>=5 else (np.nan,np.nan)
    print(f"  {a}: n={len(da):3d} net/set={da.net.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] total=${da.net.sum():+.2f}")
print(f"\nHOW MUCH COULD BE ARBITRAGED (net, this {days:.1f}-day sample, by threshold):")
for thr in [0.99,0.95,0.90]:
    d=D[D.thr==thr]
    for stake in [100,500]:
        print(f"  thr<{thr} @ ${stake}/set: n={len(d)} GROSS=${d.gross.sum()*stake:+,.0f} NET=${d.net.sum()*stake:+,.0f} (~${d.net.sum()*stake/days:+,.0f}/day)")
D.to_parquet(ROOT/"strategy_lab/directional/_results/poly_kalshi_arb_numbers_2026_06_05.parquet")
print("\nCAVEATS: first-crossing entry (may be a transient/thin dip); Kalshi ask SIZE unknown (can't confirm fillable");
print("size); requires simultaneous 2-venue fills; 3.96% settlement disagreement adds the $0/$2 tail.")
