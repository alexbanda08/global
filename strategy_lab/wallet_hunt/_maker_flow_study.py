"""
_maker_flow_study.py — offline feasibility for the b945-style maker probe.

Q1: how much taker-SELL flow hits resting bids per btc-15m window? (upper bound on fills)
Q2: markout after bid-side prints (adverse selection -> breakeven spread)
Q3: queue-ahead at best bid (what a $1 join faces)
Sample: 400 random btc-15m slugs Apr 22+ with L25 books.
"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RNG = np.random.default_rng(11)

t0 = time.time()
# slug universe from resolutions (btc 15m, Apr22+)
res = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "resolutions.parquet",
                      columns=["slug", "slot_start_us"])
res = res[res.slug.str.contains("btc-updown-15m", na=False, regex=False)]
res = res[res.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
slugs_all = sorted(res.slug.unique())
sample = set(RNG.choice(slugs_all, size=min(400, len(slugs_all)), replace=False))
print(f"sampled {len(sample)} slugs of {len(slugs_all)}", flush=True)

# trades for sampled slugs
f = pq.ParquetFile(TR)
parts = []
for i in range(f.num_row_groups):
    df = f.read_row_group(i, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"]).to_pandas()
    df = df[df.slug.isin(sample)]
    if len(df):
        parts.append(df)
T = pd.concat(parts, ignore_index=True)
print(f"trades rows: {len(T)}  sides: {T.side.value_counts().to_dict()}  t={time.time()-t0:.0f}s", flush=True)

# L25 top-of-book for sampled slugs
cols = ["timestamp_us", "slug", "outcome", "bid_price_0", "bid_size_0", "ask_price_0"]
f2 = pq.ParquetFile(L25)
parts = []
for i in range(f2.num_row_groups):
    df = f2.read_row_group(i, columns=cols).to_pandas()
    df = df[df.slug.isin(sample)]
    if len(df):
        parts.append(df)
B = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
tob = {}
for k, g in B.groupby(["slug", "outcome"], sort=False, observed=True):
    tob[k] = (g.timestamp_us.to_numpy(np.int64), g.bid_price_0.to_numpy(np.float64),
              g.bid_size_0.to_numpy(np.float64), g.ask_price_0.to_numpy(np.float64))
print(f"tob series: {len(tob)}  t={time.time()-t0:.0f}s", flush=True)

ss_of = {s: int(s.rsplit("-", 1)[1]) for s in sample}
sell_side = "sell" if "sell" in set(T.side.str.lower().unique()) else sorted(T.side.unique())[1]
S = T[T.side.str.lower() == "sell"].copy() if "sell" in set(T.side.str.lower().unique()) else T[T.side == sell_side].copy()
S["off"] = S.timestamp_us / 1e6 - S.slug.map(ss_of)
S = S[(S.off >= 0) & (S.off <= 900)]
S["usd"] = S.price * S["size"]

rows = []
for r in S.itertuples():
    rec = tob.get((r.slug, r.outcome))
    if rec is None:
        continue
    ts, bp, bsz, ap = rec
    j = np.searchsorted(ts, r.timestamp_us, "right") - 1
    if j < 0 or (r.timestamp_us - ts[j]) > 30_000_000:
        continue
    at_bid = r.price <= bp[j] + 0.0001
    # markout 30s / 60s: mid drift after the print, same outcome token
    mo30 = mo60 = np.nan
    for dt, name in ((30, "30"), (60, "60")):
        k = np.searchsorted(ts, r.timestamp_us + dt * 1_000_000, "right") - 1
        if k > j and np.isfinite(bp[k]) and np.isfinite(ap[k]):
            mid_k = (bp[k] + ap[k]) / 2
            if dt == 30:
                mo30 = mid_k - r.price
            else:
                mo60 = mid_k - r.price
    rows.append((r.slug, r.outcome, r.off, r.price, r.usd, at_bid,
                 bp[j], bsz[j] if np.isfinite(bsz[j]) else np.nan, mo30, mo60))

D = pd.DataFrame(rows, columns=["slug", "outcome", "off", "price", "usd", "at_bid",
                                "bid", "bidsz", "mo30", "mo60"])
print(f"classified prints: {len(D)} ({D.at_bid.mean():.0%} at/below bid)  t={time.time()-t0:.0f}s", flush=True)

AB = D[D.at_bid]
nwin = D.slug.nunique()
print(f"\n=== Q1: taker-sell flow hitting bids (n={nwin} windows) ===")
per_win = AB.groupby("slug").usd.sum()
per_win = per_win.reindex(list(sample & set(D.slug.unique())), fill_value=0.0)
print(f"sell-$-at-bid per window: p25 ${per_win.quantile(.25):.0f}  med ${per_win.median():.0f}  "
      f"p75 ${per_win.quantile(.75):.0f}  mean ${per_win.mean():.0f}")
print(f"windows with ZERO bid-side flow: {(per_win==0).mean():.0%}")
print("\nby time-in-window (sell-$-at-bid per window):")
AB2 = AB.copy(); AB2["bucket"] = pd.cut(AB2.off, [0, 180, 420, 660, 870, 900])
print((AB2.groupby("bucket", observed=True).usd.sum() / nwin).round(1).to_string())
print("\nby price band:")
AB2["pband"] = pd.cut(AB2.price, [0, .1, .3, .55, .8, .97, 1.0])
print((AB2.groupby("pband", observed=True).usd.sum() / nwin).round(1).to_string())

print(f"\n=== Q2: markout after bid-side prints (cents, negative = adverse) ===")
for c in ["mo30", "mo60"]:
    v = AB[c].dropna()
    print(f"{c}: med {v.median()*100:+.2f}c  mean {v.mean()*100:+.2f}c  p25 {v.quantile(.25)*100:+.2f}c  "
          f"p75 {v.quantile(.75)*100:+.2f}c  (n={len(v)})")
# markout by price band
print("mo60 by price band (cents):")
print((AB2.groupby("pband", observed=True).mo60.median() * 100).round(2).to_string())

print(f"\n=== Q3: queue at best bid when sells arrive ===")
q = AB.bidsz.dropna()
print(f"best-bid size (shares): p10 {q.quantile(.1):.0f}  med {q.median():.0f}  p90 {q.quantile(.9):.0f}")
print(f"-> a $1 join (~2-10 sh) is negligible vs queue; fill needs the LEVEL to trade through "
      f"or queue ahead to cancel.")
print(f"\nsell prints per window at/below bid: med {AB.groupby('slug').size().median():.0f}")
print(f"done t={time.time()-t0:.0f}s")
