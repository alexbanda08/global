"""DIFFERENTIAL: does the L25 de-corruption change the V2 DEPLOY engine (level-0 fills)?
Run harvest_slug on the SAME slugs with corrupted (decorrupt=False) vs de-corrupted (decorrupt=True) L25.
If arm_a_pnl is ~identical per slug -> level-0 untouched -> the +0.52 floor stands (the workflow's -0.70
was the realdepth model, not this). If it differs -> re-sort promoted deeper levels to index 0; quantify."""
import sys, time, importlib.util
sys.path.insert(0, "data/v4/canonical"); sys.path.insert(0, "strategy_lab/directional")
import numpy as np, pandas as pd
spec = importlib.util.spec_from_file_location("osc", "strategy_lab/directional/_sumpair_signal_oscillation_harvest.py")
OSC = importlib.util.module_from_spec(spec); spec.loader.exec_module(OSC)
THR = 3.0; IS_CUT = int(pd.Timestamp("2026-05-21", tz="UTC").timestamp()*1e6)
NPC = int(sys.argv[1]) if len(sys.argv) > 1 else 250
t0 = time.time()
res = OSC.load_resolutions(); res = res[(res.timeframe == "5m") & res.ticker.isin(["BTC", "ETH"])].drop_duplicates("slug")
rows = []
for coin in ["BTC", "ETH"]:
    d = res[res.ticker == coin]
    if len(d) == 0: continue
    _, ends, close = OSC.unified_1s(coin)
    slot = dict(zip(d.slug, d.slot_start_us)); out = dict(zip(d.slug, d.outcome))
    oos = sorted([s for s in d.slug if int(slot[s]) >= IS_CUT])
    samp = oos[::max(1, len(oos)//NPC)][:NPC]
    print(f"{coin}: {len(samp)} OOS slugs t={time.time()-t0:.0f}s", flush=True)
    CH = 250
    for i in range(0, len(samp), CH):
        ch = set(samp[i:i+CH])
        bk_fix = OSC.load_orderbook_l25_streaming(coin.lower(), slugs=ch, subsample_1hz=False, decorrupt=True)
        bk_raw = OSC.load_orderbook_l25_streaming(coin.lower(), slugs=ch, subsample_1hz=False, decorrupt=False)
        for sl in ch:
            ru, rd = bk_fix.get((sl, "Up")), bk_fix.get((sl, "Down"))
            ru0, rd0 = bk_raw.get((sl, "Up")), bk_raw.get((sl, "Down"))
            if ru is None or rd is None or ru0 is None or rd0 is None: continue
            ss = int(slot[sl]); se = ss + 300_000_000; oc = out[sl]
            rf = OSC.harvest_slug(ends, close, ru, rd, ss, se, oc, THR)
            rr = OSC.harvest_slug(ends, close, ru0, rd0, ss, se, oc, THR)
            rows.append(dict(slug=sl, coin=coin, fix=rf["arm_a_pnl"], raw=rr["arm_a_pnl"],
                             fix_fired=(rf["nclip_up"]+rf["nclip_dn"])>0, raw_fired=(rr["nclip_up"]+rr["nclip_dn"])>0))
        print(f"  {coin} {i+len(ch)} t={time.time()-t0:.0f}s", flush=True)
R = pd.DataFrame(rows)
Ff = R[R.fix_fired]; Fr = R[R.raw_fired]
print("="*64)
print(f"slugs={len(R)} | fired: corrected={len(Ff)} raw={len(Fr)}")
print(f"ARM A net/slug (fired): CORRECTED={Ff.fix.mean():+.3f} (n={len(Ff)})  vs  RAW/corrupted={Fr.raw.mean():+.3f} (n={len(Fr)})")
both = R[R.fix_fired & R.raw_fired]
d = (both.fix - both.raw).to_numpy()
print(f"per-slug diff (corrected-raw) on slugs fired in both: mean={d.mean():+.4f} max|diff|={np.abs(d).max():.3f} "
      f"frac|diff|>0.01: {100*np.mean(np.abs(d)>0.01):.1f}%")
print(f"\nVERDICT: {'IDENTICAL → level-0 untouched → +0.52 floor STANDS (de-corruption does not affect the V2 deploy engine)' if np.abs(d).max()<0.01 else 'DIFFERS → re-sort changed level-0 on some slugs; V2 floor must be re-estimated on a large corrected sample'}")
print(f"t={time.time()-t0:.0f}s")
