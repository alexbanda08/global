"""For 1 profitable trade per strategy bundle, compare prod ent_px vs parquet ask0
at fill time = slug_ws + 120s, for the held outcome side.

Quantifies REST lag PER STRATEGY across all 10 bundles.
"""
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "data/v4/refresh_2026_05_06/cache"
SAMPLE_TSV = ROOT / "data/v4/shadow_trades_2026_05_06/bundle_sample.tsv"

# Read sample (no header, tab-separated, raw psql output)
cols = ["bundle","sleeve_id","at","condition_id","symbol","tf","signal","outcome","pnl_usd","entry_price"]
sample = pd.read_csv(SAMPLE_TSV, sep="\t", names=cols, dtype={"pnl_usd": float, "entry_price": float})
print(f"sample: {len(sample)} bundles\n")

# Join condition_id → slug via markets_full
m = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv")[["slug","condition_id"]]
sample = sample.merge(m, on="condition_id", how="left")
matched = sample[sample.slug.notna()]
print(f"slug-matched: {len(matched)}/{len(sample)}\n")

# Compute fill time = slug_ws + 120s
sample["ws"] = sample.slug.str.extract(r"-(\d+)$")[0].astype("Int64")
# Fill timestamp depends on strategy_mode dispatch (verified in poly_updown_loop.py master scheduler):
#   momo: t+120s phase → fires at slug_ws + 120s
#   all others (sniper/v3*/volume/inverse*/v4): bar-close phase → fires at slug_ws
sample["fill_offset_s"] = sample.bundle.apply(lambda b: 120 if b == "momo" else 0)
sample["fill_us"] = (sample.ws.astype("int64") + sample.fill_offset_s) * 1_000_000
sample["held"] = sample.signal.apply(lambda s: "Up" if s == "UP" else "Down")
sample["asset"] = sample.symbol.str.lower()

# Look up parquet ask0 at fill time for each
results = []
for asset in ("btc","eth","sol"):
    sub = sample[sample.asset == asset].dropna(subset=["slug"])
    if len(sub) == 0:
        continue
    target_slugs = sub.slug.unique().tolist()
    print(f"[{asset}] streaming parquet for {len(target_slugs)} slugs…")
    pf = pq.ParquetFile(CACHE / f"{asset}_orderbook_L25.parquet")
    cols_keep = ["timestamp_us","slug","outcome","bid_price_0","ask_price_0","bid_size_0","ask_size_0"]
    chunks = []
    for batch in pf.iter_batches(batch_size=500_000, columns=cols_keep):
        df = batch.to_pandas()
        flt = df[df.slug.isin(target_slugs)]
        if len(flt):
            chunks.append(flt)
    raw = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=cols_keep)
    print(f"  raw rows for our slugs: {len(raw)}")
    for r in sub.itertuples(index=False):
        cand = raw[(raw.slug == r.slug) & (raw.outcome == r.held)].copy()
        if len(cand) == 0:
            results.append(dict(bundle=r.bundle, sleeve_id=r.sleeve_id, slug=r.slug, asset=asset.upper(),
                                tf=r.tf, signal=r.signal, held=r.held, outcome=r.outcome,
                                fill_at=str(pd.to_datetime(r.fill_us, unit="us", utc=True)),
                                prod_entry_price=r.entry_price, prod_pnl=r.pnl_usd,
                                parquet_ask0=None, parquet_bid0=None, dt_ms=None,
                                divergence=None, n_in_window=0))
            continue
        cand = cand.reset_index(drop=True)
        cand["dt_us"] = cand.timestamp_us - r.fill_us
        win = cand[cand.dt_us.abs() <= 5_000_000]
        if len(win):
            cl = win.iloc[win.dt_us.abs().values.argmin()]
            n_in_window = len(win)
        else:
            cl = cand.iloc[cand.dt_us.abs().values.argmin()]
            n_in_window = 0
        results.append(dict(
            bundle=r.bundle, sleeve_id=r.sleeve_id, slug=r.slug, asset=asset.upper(),
            tf=r.tf, signal=r.signal, held=r.held, outcome=r.outcome,
            fill_at=str(pd.to_datetime(r.fill_us, unit="us", utc=True)),
            prod_entry_price=r.entry_price, prod_pnl=r.pnl_usd,
            parquet_ask0=float(cl.ask_price_0) if pd.notna(cl.ask_price_0) else None,
            parquet_bid0=float(cl.bid_price_0) if pd.notna(cl.bid_price_0) else None,
            parquet_ask_size_0=float(cl.ask_size_0) if pd.notna(cl.ask_size_0) else None,
            dt_ms=int(cl.dt_us // 1000),
            divergence=(float(cl.ask_price_0) - r.entry_price) if pd.notna(cl.ask_price_0) else None,
            n_in_window=n_in_window,
        ))

out = pd.DataFrame(results).sort_values("bundle")
out.to_csv(ROOT / "data/v4/shadow_trades_2026_05_06/xref_bundles_vs_parquet.csv", index=False)

print(f"\n=== PER-BUNDLE: prod ent_px vs parquet ask0 at corrected dispatch time ===")
print(f"   momo fires at slug_ws+120s; everyone else fires at slug_ws (bar-close)\n")
print(out[["bundle","asset","tf","signal","held","outcome","fill_at","prod_entry_price","parquet_ask0","parquet_bid0","divergence","dt_ms","n_in_window","prod_pnl"]].to_string(index=False))

ok = out.dropna(subset=["divergence"])
print(f"\n=== Divergence summary across {len(ok)} bundles (parquet ask0 - prod ent_px) ===")
if len(ok):
    print(f"  mean divergence:    {ok.divergence.mean():+.4f}")
    print(f"  median divergence:  {ok.divergence.median():+.4f}")
    print(f"  min / max:          {ok.divergence.min():+.4f} / {ok.divergence.max():+.4f}")
    print(f"  |div|<$0.05:        {(ok.divergence.abs()<0.05).sum()} / {len(ok)}  (matches REST closely)")
    print(f"  |div|>$0.20:        {(ok.divergence.abs()>0.20).sum()} / {len(ok)}  (REST-lag exploit)")
    print(f"\n=== Direction sanity: divergence has same sign as REST-lag hypothesis? ===")
    rest_lag_consistent = (ok.divergence < 0).sum()
    print(f"  prod < parquet (REST-lag consistent): {rest_lag_consistent} / {len(ok)}")
