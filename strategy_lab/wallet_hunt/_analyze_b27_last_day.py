"""Deep-dive analysis of 0xb27bc932 last 24h activity.

Identify the strategy signature: mint-and-sell, sell-and-redeem,
pair-accumulator, or NEW.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

WALLET = "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82".lower()
CACHE = Path("strategy_lab/wallet_hunt/cache/0xb27bc932")

# Known Polymarket contracts
MATCHER = "0xe111180000d2663c0091e4f400237545b87b996b"
CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
CTF_EXCHANGE = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
NEGRISK_EXCHANGE = "0xc5d563a36ae78145c45a50134d48a1215220f80a"
NEGRISK_ADAPTER = "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296"
ZERO = "0x0000000000000000000000000000000000000000"
USDC_PROXY_DEPOSIT = "0xaaaa1f4aaff7d5e8a96cf21d59648c3a4f4e3e6c"  # common
EXCHANGE_LIKE = {MATCHER, CTF, CTF_EXCHANGE, NEGRISK_EXCHANGE, NEGRISK_ADAPTER}

t = pd.read_parquet(CACHE / "alchemy_transfers.parquet")
t["ts"] = pd.to_datetime(t.ts, utc=True, errors="coerce")
t["value"] = pd.to_numeric(t.value, errors="coerce")
t["from"] = t["from"].astype(str).str.lower()
t["to"] = t["to"].astype(str).str.lower()
print(f"=== 0xb27bc932 — last 24h chain activity ===")
print(f"  total transfers: {len(t):,}")
span_h = (t.ts.max() - t.ts.min()).total_seconds() / 3600
print(f"  span: {span_h:.2f}h  ({t.ts.min()} → {t.ts.max()})")

# Categorize transfers
usdc = t[t.category == "erc20"].copy()
erc1155 = t[t.category == "erc1155"].copy()
print(f"\n  USDC (erc20) transfers: {len(usdc):,}")
print(f"  ERC1155 token transfers: {len(erc1155):,}")

# === Direction breakdown ===
print(f"\n--- Direction breakdown ---")
print(f"  USDC:    IN={len(usdc[usdc.direction=='in']):>6,}  OUT={len(usdc[usdc.direction=='out']):>6,}")
print(f"  ERC1155: IN={len(erc1155[erc1155.direction=='in']):>6,}  OUT={len(erc1155[erc1155.direction=='out']):>6,}")

# === Top USDC counterparties ===
print(f"\n--- Top USDC counterparties ---")
usdc_in = usdc[usdc.direction == "in"]
usdc_out = usdc[usdc.direction == "out"]
print("  USDC RECEIVED FROM (top 10):")
top_in = usdc_in.groupby("from").agg(n=("value","count"), total=("value","sum")).sort_values("total", ascending=False).head(10)
print(top_in.to_string())
print("\n  USDC SENT TO (top 10):")
top_out = usdc_out.groupby("to").agg(n=("value","count"), total=("value","sum")).sort_values("total", ascending=False).head(10)
print(top_out.to_string())

# === ERC1155 counterparties ===
print(f"\n--- Top ERC1155 counterparties ---")
erc_in = erc1155[erc1155.direction == "in"]
erc_out = erc1155[erc1155.direction == "out"]
print(f"  ERC1155 RECEIVED FROM (top 5):")
print(erc_in["from"].value_counts().head(5).to_string())
print(f"\n  ERC1155 SENT TO (top 5):")
print(erc_out["to"].value_counts().head(5).to_string())

# === Mint/Burn detection ===
n_mints = len(erc1155[(erc1155.direction=="to") & (erc1155["from"].str.lower()==ZERO)])
n_burns = len(erc1155[(erc1155.direction=="from") & (erc1155["to"].str.lower()==ZERO)])
print(f"\n--- Mint/Burn (splitPosition / mergePositions / redeemPositions) ---")
print(f"  ERC1155 mints (from 0x0):  {n_mints:>6,}")
print(f"  ERC1155 burns (to 0x0):    {n_burns:>6,}")

# Mint TXs (unique tx_hash)
mint_txs = erc1155[(erc1155.direction=="to") & (erc1155["from"].str.lower()==ZERO)]
n_mint_txs = mint_txs.tx_hash.nunique() if len(mint_txs) else 0
burn_txs = erc1155[(erc1155.direction=="from") & (erc1155["to"].str.lower()==ZERO)]
n_burn_txs = burn_txs.tx_hash.nunique() if len(burn_txs) else 0
print(f"  unique mint TXs:           {n_mint_txs:>6,}")
print(f"  unique burn TXs:           {n_burn_txs:>6,}")

# === Trade fills via matcher ===
n_filled_via_matcher = len(usdc[(usdc.direction=="to") & (usdc["from"].str.lower()==MATCHER)])
n_paid_to_matcher = len(usdc[(usdc.direction=="from") & (usdc["to"].str.lower()==MATCHER)])
total_in_matcher = usdc[(usdc.direction=="to") & (usdc["from"].str.lower()==MATCHER)].value.sum()
total_out_matcher = usdc[(usdc.direction=="from") & (usdc["to"].str.lower()==MATCHER)].value.sum()
print(f"\n--- Matcher contract (CLOB fills) ---")
print(f"  USDC IN  via matcher: {n_filled_via_matcher:>6,} fills  total=${total_in_matcher:,.2f}")
print(f"  USDC OUT via matcher: {n_paid_to_matcher:>6,} fills  total=${total_out_matcher:,.2f}")

# === Fingerprint inference ===
print(f"\n--- Strategy fingerprint inference ---")
ratio_in_out = total_in_matcher / total_out_matcher if total_out_matcher else float('inf')
print(f"  IN/OUT via matcher ratio: {ratio_in_out:.4f}")
if n_mint_txs > 0:
    fills_per_mint = (n_filled_via_matcher + n_paid_to_matcher) / max(n_mint_txs, 1)
    print(f"  fills per mint TX: {fills_per_mint:.1f}")
print(f"  burn/mint ratio: {n_burns/max(n_mints,1):.2f}")
print(f"  USDC OUT > IN by: ${total_out_matcher - total_in_matcher:,.2f}")

# === Tx-level grouping ===
print(f"\n--- Tx-level activity ---")
all_tx = t.tx_hash.value_counts()
print(f"  unique TXs:           {len(all_tx):,}")
print(f"  transfers per TX:     median={all_tx.median():.0f}  p95={all_tx.quantile(0.95):.0f}  max={all_tx.max()}")

# === Side classification: are they buying or selling? ===
# Mint-and-sell signature: many SELL fills (USDC IN from matcher), few BUYs
# Pure taker buyer: USDC OUT to matcher (BUY)
# Hybrid: both
print(f"\n--- BUY vs SELL classification ---")
total_fills = n_filled_via_matcher + n_paid_to_matcher
if total_fills > 0:
    print(f"  SELL fills (USDC IN from matcher):  {n_filled_via_matcher} ({n_filled_via_matcher/total_fills*100:.1f}%)")
    print(f"  BUY  fills (USDC OUT to matcher):   {n_paid_to_matcher} ({n_paid_to_matcher/total_fills*100:.1f}%)")
else:
    print("  (no fills via main matcher; check other counterparties below)")

# === Decompose by counterparty type for USDC + ERC1155 ===
print(f"\n--- USDC flow by counterparty (any direction) ---")
# Wallet SENT pUSD (FROM wallet):
print("  pUSD SENT (FROM wallet) — top 10 destinations:")
sent = usdc[usdc.direction == "from"].groupby("to").agg(n=("value","count"), total=("value","sum"))
print(sent.sort_values("total", ascending=False).head(10).to_string())
print("\n  pUSD RECEIVED (TO wallet) — top 10 sources:")
recv = usdc[usdc.direction == "to"].groupby("from").agg(n=("value","count"), total=("value","sum"))
print(recv.sort_values("total", ascending=False).head(10).to_string())

print(f"\n--- ERC1155 flow by counterparty (any direction) ---")
print("  ERC1155 SENT (FROM wallet) — top 5:")
print(erc1155[erc1155.direction == "from"].groupby("to").size().sort_values(ascending=False).head(5).to_string())
print("\n  ERC1155 RECEIVED (TO wallet) — top 5:")
print(erc1155[erc1155.direction == "to"].groupby("from").size().sort_values(ascending=False).head(5).to_string())

# === Trade pattern: at TX level, is this BUY or SELL? ===
# BUY signature in a TX: wallet sends pUSD + receives ERC1155
# SELL signature in a TX: wallet sends ERC1155 + receives pUSD
# Mint signature: wallet sends pUSD to CTF + receives ERC1155 from 0x0 (or matcher)
print(f"\n--- TX-level pattern classification ---")
tx_stats = []
for tx, g in t.groupby("tx_hash"):
    pusd_sent = g[(g.direction=="from") & (g.category=="erc20")].value.sum()
    pusd_recv = g[(g.direction=="to") & (g.category=="erc20")].value.sum()
    erc_sent = (g[(g.direction=="from") & (g.category=="erc1155")]).shape[0]
    erc_recv = (g[(g.direction=="to") & (g.category=="erc1155")]).shape[0]
    tx_stats.append({"tx": tx, "pusd_sent": pusd_sent, "pusd_recv": pusd_recv,
                     "erc_sent": erc_sent, "erc_recv": erc_recv})
txs = pd.DataFrame(tx_stats)
txs["pattern"] = "OTHER"
txs.loc[(txs.pusd_sent > 0) & (txs.erc_recv > 0) & (txs.erc_sent == 0), "pattern"] = "BUY"
txs.loc[(txs.pusd_recv > 0) & (txs.erc_sent > 0) & (txs.erc_recv == 0), "pattern"] = "SELL"
txs.loc[(txs.pusd_sent > 0) & (txs.erc_recv >= 2) & (txs.erc_sent == 0), "pattern"] = "MINT (split)"
txs.loc[(txs.pusd_recv > 0) & (txs.erc_sent >= 2), "pattern"] = "MERGE/REDEEM"
print(txs.pattern.value_counts().to_string())
print()
print("Aggregate by pattern:")
agg = txs.groupby("pattern").agg(
    n_tx=("tx","count"),
    pusd_sent=("pusd_sent","sum"),
    pusd_recv=("pusd_recv","sum"),
    erc_sent=("erc_sent","sum"),
    erc_recv=("erc_recv","sum"),
)
agg["net_pusd"] = agg.pusd_recv - agg.pusd_sent
print(agg.round(2).to_string())

# === Unique tokens (markets) ===
if len(erc1155):
    print(f"\n--- Markets touched ---")
    print(f"  unique ERC1155 asset_ids: {erc1155.raw_contract.nunique() if 'raw_contract' in erc1155.columns else 'N/A'}")
    # If asset_id is in the data as 'asset' or similar
    cols_for_token = [c for c in erc1155.columns if 'asset' in c.lower() or 'contract' in c.lower() or 'token' in c.lower()]
    print(f"  token-related cols: {cols_for_token}")

# === Hourly activity rhythm ===
print(f"\n--- Hourly activity ---")
t["hour"] = t.ts.dt.hour
hourly = t.groupby("hour").size()
print(hourly.to_string())
