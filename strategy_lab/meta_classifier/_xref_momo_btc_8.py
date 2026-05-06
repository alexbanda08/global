"""Cross-check 8 random momo BTC trades vs parquet ask0 at fill time = slug_ws+120s."""
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "data/v4/refresh_2026_05_06/cache"
SAMPLE_TSV = ROOT / "data/v4/shadow_trades_2026_05_06/momo_btc_sample.tsv"

cols = ["sleeve_id","at","condition_id","symbol","tf","signal","outcome","pnl_usd","entry_price"]
sample = pd.read_csv(SAMPLE_TSV, sep="\t", names=cols, dtype={"pnl_usd": float, "entry_price": float})
m = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv")[["slug","condition_id"]]
sample = sample.merge(m, on="condition_id", how="left").dropna(subset=["slug"])
sample["ws"] = sample.slug.str.extract(r"-(\d+)$")[0].astype("int64")
sample["fill_us"] = (sample.ws + 120) * 1_000_000
sample["held"] = sample.signal.apply(lambda s: "Up" if s == "UP" else "Down")
print(f"sampled {len(sample)} momo BTC trades\n")

# Stream parquet for these slugs
target_slugs = sample.slug.unique().tolist()
pf = pq.ParquetFile(CACHE / "btc_orderbook_L25.parquet")
chunks = []
for batch in pf.iter_batches(batch_size=500_000, columns=["timestamp_us","slug","outcome","bid_price_0","ask_price_0","bid_size_0","ask_size_0"]):
    df = batch.to_pandas()
    flt = df[df.slug.isin(target_slugs)]
    if len(flt):
        chunks.append(flt)
raw = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
print(f"parquet rows for these slugs: {len(raw)}\n")

results = []
for r in sample.itertuples(index=False):
    cand = raw[(raw.slug == r.slug) & (raw.outcome == r.held)].copy()
    if len(cand) == 0:
        results.append(dict(slug=r.slug, signal=r.signal, held=r.held, outcome=r.outcome, won=(r.pnl_usd > 0),
                            prod_entry_price=r.entry_price, prod_pnl=r.pnl_usd, parquet_ask0=None,
                            divergence=None, dt_ms=None, n_in_window=0))
        continue
    cand = cand.reset_index(drop=True)
    cand["dt_us"] = cand.timestamp_us - r.fill_us
    win = cand[cand.dt_us.abs() <= 5_000_000]
    if len(win):
        cl = win.iloc[win.dt_us.abs().values.argmin()]
        n_in = len(win)
    else:
        cl = cand.iloc[cand.dt_us.abs().values.argmin()]
        n_in = 0
    results.append(dict(
        slug=r.slug, signal=r.signal, held=r.held, outcome=r.outcome, won=(r.pnl_usd > 0),
        prod_entry_price=r.entry_price, prod_pnl=r.pnl_usd,
        parquet_ask0=float(cl.ask_price_0) if pd.notna(cl.ask_price_0) else None,
        parquet_bid0=float(cl.bid_price_0) if pd.notna(cl.bid_price_0) else None,
        divergence=(float(cl.ask_price_0) - r.entry_price) if pd.notna(cl.ask_price_0) else None,
        dt_ms=int(cl.dt_us // 1000), n_in_window=n_in,
    ))

out = pd.DataFrame(results)
print(out.to_string(index=False))

ok = out.dropna(subset=["divergence"])
in_win = ok[ok.n_in_window > 0]
print(f"\n=== momo BTC sample (n={len(out)}) ===")
print(f"  matched (any dt):       {len(ok)}/{len(out)}")
print(f"  matched within ±5s:     {len(in_win)}/{len(out)}")
if len(in_win):
    print(f"  in-window mean div:     {in_win.divergence.mean():+.4f}")
    print(f"  in-window median div:   {in_win.divergence.median():+.4f}")
    print(f"  in-window max(|div|):   {in_win.divergence.abs().max():.4f}")
