"""Deep-dive analysis of 0xb27bc932 BUY-only strategy.

Findings so far:
- 1730 BUY fills via matcher (sent $9,185 pUSD)
- 220 MINT splits (sent $3,804 pUSD)
- 13 REDEEM TXs (received $12,485 from 0x0)
- 0 sells
- Activity burst in hour 13 UTC (4695 transfers in 1h)
- NET: -$500 in 13h

Now decompose: BUY price distribution, markets touched, timing.
"""
import pandas as pd
import numpy as np
from pathlib import Path

CACHE = Path("strategy_lab/wallet_hunt/cache/0xb27bc932")
WALLET = "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82".lower()
MATCHER = "0xe111180000d2663c0091e4f400237545b87b996b"
CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
ZERO = "0x0000000000000000000000000000000000000000"

t = pd.read_parquet(CACHE / "alchemy_transfers.parquet")
t["ts"] = pd.to_datetime(t.ts, utc=True, errors="coerce")
t["value"] = pd.to_numeric(t.value, errors="coerce")
t["from"] = t["from"].astype(str).str.lower()
t["to"] = t["to"].astype(str).str.lower()

# Per-TX summary
print("="*80)
print("PER-TX PATTERN ANALYSIS")
print("="*80)
tx_summary = []
for tx, g in t.groupby("tx_hash"):
    pusd_sent = g[(g.direction=="from") & (g.category=="erc20")].value.sum()
    pusd_recv = g[(g.direction=="to") & (g.category=="erc20")].value.sum()
    erc_in_rows = g[(g.direction=="to") & (g.category=="erc1155")]
    erc_out_rows = g[(g.direction=="from") & (g.category=="erc1155")]
    erc_in_size = erc_in_rows.value.sum()
    erc_out_size = erc_out_rows.value.sum()
    # Counterparty for ERC1155 in
    cp_erc_in = erc_in_rows["from"].iloc[0] if len(erc_in_rows) else None
    cp_erc_out = erc_out_rows["to"].iloc[0] if len(erc_out_rows) else None
    cp_pusd_out = g[(g.direction=="from") & (g.category=="erc20")]["to"].iloc[0] if pusd_sent > 0 else None
    # Asset (token_id) — for BUYs, the token they received
    asset = erc_in_rows.asset.iloc[0] if len(erc_in_rows) else (erc_out_rows.asset.iloc[0] if len(erc_out_rows) else None)
    ts = g.ts.min()

    pattern = "OTHER"
    if pusd_sent > 0 and erc_in_size > 0 and erc_out_size == 0:
        if cp_erc_in == MATCHER:
            pattern = "BUY (matcher)"
        elif cp_erc_in == CTF:
            pattern = "MINT (split)"
        else:
            pattern = f"BUY ({cp_erc_in[:10]})"
    elif pusd_recv > 0 and erc_out_size > 0 and erc_in_size == 0:
        if cp_erc_out == ZERO:
            pattern = "REDEEM (0x0)"
        elif cp_erc_out == MATCHER:
            pattern = "SELL (matcher)"
        else:
            pattern = f"OUT ({cp_erc_out[:10]})"

    # implied fill price (BUY: pUSD per token)
    fill_price = (pusd_sent / erc_in_size) if (pusd_sent > 0 and erc_in_size > 0) else (pusd_recv / erc_out_size if erc_out_size > 0 else None)

    tx_summary.append(dict(
        tx=tx, ts=ts, pattern=pattern, pusd_sent=pusd_sent, pusd_recv=pusd_recv,
        erc_in_size=erc_in_size, erc_out_size=erc_out_size, fill_price=fill_price,
        asset=asset, n_erc_in=len(erc_in_rows), n_erc_out=len(erc_out_rows),
    ))

txs = pd.DataFrame(tx_summary)
print(f"\nPattern counts:")
print(txs.pattern.value_counts().to_string())

# === BUY trades analysis ===
print()
print("="*80)
print("BUY TRADES (matcher fills) — price distribution")
print("="*80)
buys = txs[txs.pattern == "BUY (matcher)"]
print(f"  count: {len(buys)}")
print(f"  total pUSD spent: ${buys.pusd_sent.sum():,.2f}")
print(f"  total tokens received: {buys.erc_in_size.sum():,.0f}")
print(f"  fill price stats:")
print(f"    median: ${buys.fill_price.median():.4f}")
print(f"    mean:   ${buys.fill_price.mean():.4f}")
print(f"    p10:    ${buys.fill_price.quantile(0.10):.4f}")
print(f"    p25:    ${buys.fill_price.quantile(0.25):.4f}")
print(f"    p75:    ${buys.fill_price.quantile(0.75):.4f}")
print(f"    p90:    ${buys.fill_price.quantile(0.90):.4f}")
print(f"    p99:    ${buys.fill_price.quantile(0.99):.4f}")
print(f"    max:    ${buys.fill_price.max():.4f}")
print(f"  pUSD per trade:")
print(f"    median: ${buys.pusd_sent.median():.2f}")
print(f"    p25:    ${buys.pusd_sent.quantile(0.25):.2f}")
print(f"    p75:    ${buys.pusd_sent.quantile(0.75):.2f}")
print(f"    max:    ${buys.pusd_sent.max():.2f}")

# Bucket fills by price
print(f"\n  BUY fills by price bucket:")
buys["bucket"] = pd.cut(buys.fill_price,
    bins=[0, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00],
    labels=["<0.5¢","0.5-1¢","1-2¢","2-5¢","5-10¢","10-20¢","20-40¢","40-60¢","60-80¢","80-100¢"])
buckets = buys.groupby("bucket", observed=True).agg(
    n=("pusd_sent","count"),
    pusd_spent=("pusd_sent","sum"),
    tokens=("erc_in_size","sum"),
)
buckets["%spent"] = buckets.pusd_spent / buckets.pusd_spent.sum() * 100
print(buckets.round(2).to_string())

# === MINT analysis ===
print()
print("="*80)
print("MINT TRADES (splitPosition)")
print("="*80)
mints = txs[txs.pattern == "MINT (split)"]
print(f"  count: {len(mints)}")
print(f"  total pUSD spent: ${mints.pusd_sent.sum():,.2f}")
# n_erc_in per mint = number of outcomes minted (binary=2, multi-outcome=3+)
print(f"  outcomes per mint distribution:")
print(mints.n_erc_in.value_counts().to_string())
print(f"  median pUSD per mint: ${mints.pusd_sent.median():.2f}")
print(f"  max pUSD per mint:    ${mints.pusd_sent.max():.2f}")

# === REDEEM analysis ===
print()
print("="*80)
print("REDEEM TRADES (CTF burns to 0x0)")
print("="*80)
redeems = txs[txs.pattern == "REDEEM (0x0)"]
print(f"  count: {len(redeems)}")
print(f"  total pUSD recovered: ${redeems.pusd_recv.sum():,.2f}")
print(f"  median per redeem: ${redeems.pusd_recv.median():.2f}")
print(f"  max per redeem: ${redeems.pusd_recv.max():.2f}")

# === Unique markets touched ===
print()
print("="*80)
print("MARKETS / TOKENS TOUCHED")
print("="*80)
unique_assets = t[(t.category == "erc1155") & (t.asset.notna())].asset.unique()
print(f"  unique ERC1155 asset_ids touched: {len(unique_assets)}")
# Distribution of activity per asset
asset_activity = t[t.category == "erc1155"].asset.value_counts()
print(f"  top 10 most-touched assets (by # transfers):")
print(asset_activity.head(10).to_string())

# Burst hour analysis (hour 13)
print()
print("="*80)
print("BURST: Hour 13 UTC (4695 transfers)")
print("="*80)
burst = t[t.ts.dt.hour == 13]
n_burst_txs = burst.tx_hash.nunique()
print(f"  transfers: {len(burst):,}")
print(f"  unique TXs: {n_burst_txs:,}")
print(f"  unique assets: {burst.asset.nunique()}")
print(f"  time range: {burst.ts.min()} → {burst.ts.max()}")
print(f"  → {n_burst_txs / 3600:.1f} txs/sec average for the hour")

# Per-tx pattern within burst
burst_txs = txs[txs.tx.isin(burst.tx_hash.unique())]
print(f"  burst patterns:")
print(burst_txs.pattern.value_counts().to_string())

# === Overall PnL ===
print()
print("="*80)
print("OVERALL PnL (matches cash_pnl)")
print("="*80)
print(f"  pUSD spent (BUY+MINT):  ${buys.pusd_sent.sum() + mints.pusd_sent.sum():,.2f}")
print(f"  pUSD recv (REDEEM):     ${redeems.pusd_recv.sum():,.2f}")
print(f"  NET PnL:                ${redeems.pusd_recv.sum() - buys.pusd_sent.sum() - mints.pusd_sent.sum():,.2f}")
