"""Cross-check live ent_px vs cache/{asset}_orderbook_L25.parquet at same (slug, outcome, ~timestamp).

If REST-lag is the alpha source: parquet ask0 > prod ent_px (parquet WS book has absorbed move).
If microstructure: parquet ask0 ≈ prod ent_px within ~$0.05.
"""
import pandas as pd
from pathlib import Path
import pyarrow.parquet as pq
import pyarrow.compute as pc

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "data/v4/refresh_2026_05_06/cache"

# Production trades + slug (via condition_id join)
t = pd.read_csv(ROOT / "data/v4/shadow_trades_2026_05_06/momo_trades_full.csv")
t = t[t.entry_phase.notna()].copy()
m = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv")[["slug","condition_id"]]
prod = t.merge(m, on="condition_id").dropna(subset=["slug"]).copy()
prod["at_us"] = (pd.to_datetime(prod.at_utc, utc=True).astype("int64") // 1_000)
prod["held"] = prod.signal.apply(lambda s: "Up" if s == "UP" else "Down")
prod["asset_lower"] = prod.asset.str.lower()
print(f"production trades: {len(prod)}, distinct slugs: {prod.slug.nunique()}")

# Inspect parquet schema first
pf = pq.ParquetFile(CACHE / "btc_orderbook_L25.parquet")
print(f"\nbtc_orderbook_L25.parquet schema (first 8 cols): {pf.schema_arrow.names[:8]}")
print(f"  total cols: {len(pf.schema_arrow.names)}, total rows: {pf.metadata.num_rows:,}")

results = []
for asset in ("btc","eth","sol"):
    sub = prod[prod.asset_lower == asset]
    if len(sub) == 0:
        continue
    target_slugs = sub.slug.unique().tolist()
    print(f"\n[{asset}] {len(sub)} prod trades / {len(target_slugs)} unique slugs")
    # Load only rows for our slugs (predicate pushdown if available)
    pf = pq.ParquetFile(CACHE / f"{asset}_orderbook_L25.parquet")
    cols = ["timestamp_us","slug","outcome","bid_price_0","bid_size_0","ask_price_0","ask_size_0"]
    # Read in chunks, filter
    chunks = []
    for batch in pf.iter_batches(batch_size=500_000, columns=cols):
        df_batch = batch.to_pandas()
        flt = df_batch[df_batch.slug.isin(target_slugs)]
        if len(flt):
            chunks.append(flt)
    raw = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=cols)
    print(f"  raw rows for our slugs: {len(raw)}")
    if len(raw) == 0:
        for r in sub.itertuples(index=False):
            results.append(dict(asset=asset, slug=r.slug, held=r.held, prod_at_utc=r.at_utc,
                                prod_entry_price=r.entry_price, raw_ask0=None, raw_bid0=None,
                                dt_ms=None, divergence=None))
        continue
    # For each prod trade, find closest snapshot in (slug, held, ±2s window)
    for r in sub.itertuples(index=False):
        cand = raw[(raw.slug == r.slug) & (raw.outcome == r.held)].copy()
        if len(cand) == 0:
            results.append(dict(asset=asset, slug=r.slug, held=r.held, signal=r.signal, tf=r.tf,
                                prod_at_utc=r.at_utc, prod_entry_price=r.entry_price,
                                prod_pnl=r.pnl_usd, raw_ask0=None, raw_bid0=None,
                                dt_ms=None, divergence=None, n_in_window=0))
            continue
        cand = cand.reset_index(drop=True).copy()
        cand["dt_us"] = cand.timestamp_us - r.at_us
        # Window ±5s from production fire time
        win = cand[cand.dt_us.abs() <= 5_000_000]
        if len(win) == 0:
            cl = cand.iloc[cand.dt_us.abs().values.argmin()]
        else:
            cl = win.iloc[win.dt_us.abs().values.argmin()]
        if True:
            results.append(dict(
                asset=asset, slug=r.slug, held=r.held, signal=r.signal, tf=r.tf,
                exit_pol=r.exit, prod_at_utc=r.at_utc,
                prod_entry_price=float(r.entry_price), prod_pnl=float(r.pnl_usd),
                raw_ask0=float(cl.ask_price_0) if pd.notna(cl.ask_price_0) else None,
                raw_bid0=float(cl.bid_price_0) if pd.notna(cl.bid_price_0) else None,
                raw_ask_size_0=float(cl.ask_size_0) if pd.notna(cl.ask_size_0) else None,
                dt_ms=int(cl.dt_us // 1000),
                divergence=(float(cl.ask_price_0) - float(r.entry_price)) if pd.notna(cl.ask_price_0) else None,
                n_in_window=int(len(win)),
                n_total_for_slug=int(len(cand)),
            ))

out = pd.DataFrame(results)
out.to_csv(ROOT / "data/v4/shadow_trades_2026_05_06/xref_live_vs_parquet.csv", index=False)

ok = out.dropna(subset=["divergence"])
print(f"\n=== Cross-reference: prod ent_px vs parquet ask0 (within ±5s window) ===")
print(f"total prod trades: {len(out)}, matched within ±5s: {len(ok)}")
print(f"matched rate: {len(ok)/len(out)*100:.1f}%\n")

if len(ok):
    print(out[["asset","tf","exit_pol","signal","held","prod_at_utc","prod_entry_price","raw_ask0","raw_bid0","divergence","dt_ms","n_in_window"]].to_string(index=False, max_rows=80))

    print(f"\n=== Divergence summary (parquet ask0 - production ent_px) ===")
    print(f"  n matched:           {len(ok)}")
    print(f"  mean divergence:     {ok.divergence.mean():+.4f}")
    print(f"  median divergence:   {ok.divergence.median():+.4f}")
    print(f"  std divergence:      {ok.divergence.std():.4f}")
    print(f"  p05 / p95:           {ok.divergence.quantile(0.05):+.4f}  /  {ok.divergence.quantile(0.95):+.4f}")
    print(f"  min / max:           {ok.divergence.min():+.4f}  /  {ok.divergence.max():+.4f}")
    print(f"  |div|<$0.05 count:   {(ok.divergence.abs()<0.05).sum()} / {len(ok)}  (matches REST)")
    print(f"  |div|>$0.20 count:   {(ok.divergence.abs()>0.20).sum()} / {len(ok)}  (REST-lag alpha)")

    print(f"\n=== By asset ===")
    print(ok.groupby("asset").divergence.describe()[["count","mean","50%","std","min","max"]])
