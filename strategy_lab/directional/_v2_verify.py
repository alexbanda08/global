"""Verify the V2 oscillation-harvest DEPLOY floor on CORRECTED (de-corrupted) L25.
The deploy engine (_sumpair_signal_oscillation_harvest.harvest_slug) fills LEVEL-0 only (entry_fill on
ap[:,0]; exit on bp[:,0]) — level 0 was never corrupted, so the floor should be UNCHANGED (~+0.52).
The workflow's -0.70 was a DIFFERENT model (realdepth walk, _sumpair_v2_upside) — that only bears on
multi-clip/deep sizing, not the 1-clip level-0 deploy. This settles whether the V2 sleeve spec stands.
Bounded + hang-proof (harvest_slug advances t internally)."""
import sys, os, time, importlib.util
sys.path.insert(0, "data/v4/canonical"); sys.path.insert(0, "strategy_lab/directional")
import numpy as np, pandas as pd
_p = "strategy_lab/directional/_sumpair_signal_oscillation_harvest.py"
spec = importlib.util.spec_from_file_location("osc", _p); OSC = importlib.util.module_from_spec(spec); spec.loader.exec_module(OSC)
THR = 3.0; IS_CUT = int(pd.Timestamp("2026-05-21", tz="UTC").timestamp()*1e6)
NPC = int(sys.argv[1]) if len(sys.argv) > 1 else 150
t0 = time.time()

def boot(v, nb=3000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) < 5: return (np.nan, np.nan)
    rng = np.random.default_rng(0); bs = rng.choice(v, (nb, len(v)), replace=True).mean(1)
    return tuple(np.percentile(bs, [2.5, 97.5]))

res = OSC.load_resolutions(); res = res[(res.timeframe == "5m") & res.ticker.isin(["BTC", "ETH"])].drop_duplicates("slug")
rows = []
for coin in ["BTC", "ETH"]:
    d = res[res.ticker == coin]
    if len(d) == 0: continue
    _, ends, close = OSC.unified_1s(coin)
    slot = dict(zip(d.slug, d.slot_start_us)); out = dict(zip(d.slug, d.outcome))
    oos_slugs = sorted([s for s in d.slug if int(slot[s]) >= IS_CUT])
    samp = oos_slugs[::max(1, len(oos_slugs)//NPC)][:NPC]
    print(f"{coin}: {len(samp)} OOS 5m slugs (of {len(oos_slugs)}) t={time.time()-t0:.0f}s", flush=True)
    CH = 150
    for i in range(0, len(samp), CH):
        ch = samp[i:i+CH]
        bks = OSC.load_orderbook_l25_streaming(coin.lower(), slugs=set(ch), subsample_1hz=False)
        for sl in ch:
            ru = bks.get((sl, "Up")); rd = bks.get((sl, "Down"))
            if ru is None or rd is None: continue
            ss = int(slot[sl]); se = ss + 300_000_000
            r = OSC.harvest_slug(ends, close, ru, rd, ss, se, out[sl], THR)
            r["slug"] = sl; r["coin"] = coin; r["fired"] = (r["nclip_up"] + r["nclip_dn"]) > 0
            rows.append(r)
        print(f"  {coin} {i+len(ch)}/{len(samp)} t={time.time()-t0:.0f}s", flush=True)
R = pd.DataFrame(rows); F = R[R.fired]
print("="*64)
print(f"FIRED slugs: {len(F)} of {len(R)} | corrected-depth, level-0 fills, OOS 5m BTC+ETH")
a = F.arm_a_pnl.to_numpy(); lo, hi = boot(a)
print(f"ARM A (hold) net/slug = {a.mean():+.3f}  CI95[{lo:+.3f},{hi:+.3f}]  med={np.median(a):+.2f}  %pos={100*(a>0).mean():.0f}%   (prior corrupted-era: +0.52)")
diff = (F.arm_a_pnl - F.ctrl).to_numpy(); dlo, dhi = boot(diff)
print(f"ARM A vs CTRL(+60s sell) paired diff = {diff.mean():+.3f} CI95[{dlo:+.3f},{dhi:+.3f}]  (>0 = beats deployed scalp)")
for coin in ["BTC", "ETH"]:
    g = F[F.coin == coin].arm_a_pnl.to_numpy()
    if len(g): clo, chi = boot(g); print(f"  {coin}: net/slug {g.mean():+.3f} CI[{clo:+.3f},{chi:+.3f}] n={len(g)}")
print(f"\nVERDICT: V2 deploy floor (level-0, 1-clip) on CORRECTED depth = {a.mean():+.3f} "
      f"{'STANDS (corruption never touched level-0 — workflow -0.70 was the realdepth model)' if lo>0 else 'IN QUESTION (CI crosses 0)'}")
print(f"t={time.time()-t0:.0f}s")
