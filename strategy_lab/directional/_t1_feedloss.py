"""T1 — FEED-LOSS AUDIT (the decisive test).
Question: what fraction of REAL taker fills execute at price levels our 10Hz L25 feed NEVER showed?
If high -> our offline fill model is structurally blind to the edge (b945 fills at fresh levels) -> infra build justified.

Method (per taker print at price P, side, collector-time t = local_timestamp_us):
  - take L25 snapshots for (slug, outcome) within +/- W us of t,
  - relevant side (buy -> ask ladder, sell -> bid ladder), levels with size>0, prices rounded to 1c grid,
  - VISIBLE if P appears in that set in ANY snapshot in the window (generous to the feed),
  - INVISIBLE otherwise = a level that existed long enough to be traded but our 10Hz never sampled it.
Report count-frac + volume-frac at W=100ms and W=300ms; buy/sell; inside-spread (price better than best visible).
HANG-PROOF: no while loops; all bounded over finite arrays. Memory-safe: trades streamed+filtered; L25 by slug set.
"""
import sys, os, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from load import load_resolutions, load_orderbook_l25_streaming, CANON

TF = "15m"; COIN = "BTC"
SAMPLE_N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
WINDOWS = [100_000, 300_000]  # us tolerance (+-1 snap, +-3 snaps at 10Hz)
t0 = time.time()

def asof_round(x):  # 1c grid
    return np.round(x.astype(float), 2)

# 1) sample slugs spread across the trade range
res = load_resolutions(assets=[COIN], timeframes=[TF]).drop_duplicates("slug")
res = res.sort_values("slot_start_us")
# trade tape covers ~Apr26->Jun15; keep slugs whose window is inside that
lo = int(pd.Timestamp("2026-04-27", tz="UTC").timestamp()*1e6)
hi = int(pd.Timestamp("2026-06-15", tz="UTC").timestamp()*1e6)
res = res[(res.slot_start_us >= lo) & (res.slot_start_us <= hi)]
slugs_all = res.slug.tolist()
step = max(1, len(slugs_all)//SAMPLE_N)
sample = set(slugs_all[::step][:SAMPLE_N])
print(f"T1 feed-loss: {COIN} {TF}, sampling {len(sample)} slugs across {len(slugs_all)} (step {step})", flush=True)

# 2) stream trades once, keep only sample slugs + needed cols
p = CANON / "trades_polymarket" / f"{COIN.lower()}.parquet"
cols = ["timestamp_us","local_timestamp_us","slug","outcome","price","size","side"]
parts = []
pf = pq.ParquetFile(p)
for i, bt in enumerate(pf.iter_batches(columns=cols, batch_size=500_000)):
    d = bt.to_pandas()
    d = d[d.slug.isin(sample)]
    if len(d): parts.append(d)
    if i % 20 == 0: print(f"  trades rg {i}/{pf.num_row_groups} kept={sum(len(x) for x in parts)} t={time.time()-t0:.0f}s", flush=True)
tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
# collector clock; fallback to exchange ts if local missing
tr["t"] = pd.to_numeric(tr.local_timestamp_us, errors="coerce")
tr.loc[~np.isfinite(tr.t), "t"] = pd.to_numeric(tr.timestamp_us, errors="coerce")
tr = tr[np.isfinite(tr.t)]
tr["price"] = asof_round(tr.price); tr["t"] = tr.t.astype(np.int64)
print(f"trades kept: {len(tr)} prints across {tr.slug.nunique()} slugs t={time.time()-t0:.0f}s", flush=True)

# 3) load L25 for sample slugs (NATIVE 10Hz — mandatory)
bks = load_orderbook_l25_streaming(COIN.lower(), slugs=sample, subsample_1hz=False)
print(f"L25 loaded: {len(bks)} (slug,outcome) series t={time.time()-t0:.0f}s", flush=True)

# 4) per-print visibility (3 metrics: cadence-independent bracket, time-window, both-sides union)
rows = []
gap_pct = []
n_unsorted = 0
for (slug, oc), g in tr.groupby(["slug","outcome"]):
    rec = bks.get((slug, oc))
    if rec is None: continue
    ts, ap, asz, bp, bsz = rec
    if len(ts) < 2: continue
    if np.any(np.diff(ts) < 0):   # defensive: ensure sorted (searchsorted + gaps depend on it)
        n_unsorted += 1
        o = np.argsort(ts, kind="stable"); ts = ts[o]; ap = ap[o]; asz = asz[o]; bp = bp[o]; bsz = bsz[o]
    apr = asof_round(ap); bpr = asof_round(bp)
    gap_pct.append(np.percentile(np.diff(ts), [50,90,99]))
    tarr = g.t.to_numpy(); parr = g.price.to_numpy(); sarr = g["size"].to_numpy(); sides = g.side.to_numpy()
    for k in range(len(tarr)):
        t = tarr[k]; P = round(float(parr[k]),2); sz = sarr[k]; buy = (sides[k] == "buy")
        relP = apr if buy else bpr; relS = asz if buy else bsz   # buy lifts ask, sell hits bid
        rowk = {"slug":slug,"size":sz,"buy":buy}
        j = int(np.searchsorted(ts, t, "right")) - 1            # snap just before t
        # (a) BRACKET visibility (cadence-independent): relevant side, snaps [j, j+1]
        idx = [i for i in (j, j+1) if 0 <= i < len(ts)]
        vis_b = False; best = np.nan
        if idx:
            pr = relP[idx][relS[idx] > 0]
            vis_b = bool(P in set(np.round(pr,2)))
            if 0 <= j < len(ts):
                pj = relP[j][relS[j] > 0]
                if pj.size: best = (pj.min() if buy else pj.max())
        rowk["vis_bracket"] = vis_b
        # local feed health = gap between the two bracketing snaps (tight => feed was ~healthy here)
        rowk["bracket_gap_us"] = float(ts[j+1]-ts[j]) if (0 <= j and j+1 < len(ts)) else np.inf
        rowk["inside_spread"] = bool(np.isfinite(best) and ((P < best-1e-9) if buy else (P > best+1e-9)))
        # (b) TIME-WINDOW visibility (relevant side) + (c) BOTH-SIDES union @300ms
        for W in WINDOWS:
            m = np.abs(ts - t) <= W
            rowk[f"vis_{W}"] = bool(m.any() and P in set(np.round(relP[m][relS[m] > 0],2)))
        m3 = np.abs(ts - t) <= 300_000
        anyp = set()
        if m3.any():
            anyp |= set(np.round(apr[m3][asz[m3] > 0],2)); anyp |= set(np.round(bpr[m3][bsz[m3] > 0],2))
        rowk["vis_anyside"] = bool(P in anyp)
        rows.append(rowk)

R = pd.DataFrame(rows)
print("="*70)
if len(R) == 0:
    print("NO joined prints — check overlap"); sys.exit(0)
gp = np.mean(gap_pct, axis=0)
def line(name, mask):
    inv = ~mask; return f"{name}: INVISIBLE count={100*inv.mean():.1f}%  volume={100*R.loc[inv,'size'].sum()/R['size'].sum():.1f}%"
print(f"JOINED PRINTS: {len(R)} across {R.slug.nunique()} slugs | snap gap p50={gp[0]/1000:.0f}ms p90={gp[1]/1000:.0f}ms p99={gp[2]/1000:.0f}ms | unsorted series fixed: {n_unsorted}")
print("  [PRIMARY, cadence-indep] "+line("bracket(rel-side, +-1 snap)", R["vis_bracket"]))
print("  [robust, side-indep]     "+line("anyside(both ladders +-300ms)", R["vis_anyside"]))
for W in WINDOWS:
    print(f"  [time-window]            "+line(f"rel-side +-{W//1000}ms", R[f"vis_{W}"]))
for buy in (True, False):
    sub = R[R.buy == buy]
    if len(sub):
        inv = ~sub["vis_bracket"]
        print(f"    {'BUY ' if buy else 'SELL'}: n={len(sub)} bracket-invisible count={100*inv.mean():.1f}% vol={100*sub.loc[inv,'size'].sum()/sub['size'].sum():.1f}%")
print(f"  INSIDE-SPREAD (taken cheaper/richer than our best visible): {100*R['inside_spread'].mean():.1f}% count")
# DECOMPOSE: tight bracket (feed locally healthy, gap<=300ms) = genuine sub-snapshot churn (racer-addressable)
#            vs loose (feed had a hole >300ms) = missing-data
tight = R[R.bracket_gap_us <= 300_000]; loose = R[(R.bracket_gap_us > 300_000) & np.isfinite(R.bracket_gap_us)]
print(f"  --- decomposition by local feed health ---")
print(f"  TIGHT (gap<=300ms, {100*len(tight)/len(R):.0f}% of prints): bracket-invisible count={100*(1-tight['vis_bracket'].mean()):.1f}%  <- genuine churn, racer-addressable")
if len(loose):
    print(f"  LOOSE (gap>300ms,  {100*len(loose)/len(R):.0f}% of prints): bracket-invisible count={100*(1-loose['vis_bracket'].mean()):.1f}%  <- feed-hole / missing-data (also racer-fixable if conn-stall)")
vb = 1 - R["vis_bracket"].mean(); va = 1 - R["vis_anyside"].mean()
verdict = "FEED BLIND -> infra build JUSTIFIED" if vb>=0.20 else ("FEED FINE -> offline stands" if vb<0.05 else "AMBIGUOUS")
print(f"\nPRE-REGISTERED VERDICT (bracket-invisible count = {100*vb:.1f}%; anyside = {100*va:.1f}%): {verdict}")
print(f"total t={time.time()-t0:.0f}s")
