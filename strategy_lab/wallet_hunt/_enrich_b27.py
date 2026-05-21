"""Quick enrichment for 0xb27bc932 trades_chain → join slug/outcome via clob_token_ids."""
import json
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xb27bc932"

# Build asset_id -> (slug, outcome, market_class, mkt_asset, slot_start_s)
m = pd.read_csv(ROOT / "data" / "v4" / "refresh_2026_05_12" / "markets_full.csv")
# Polymarket convention: clob_token_ids = [YES_token, NO_token]
# For BTC up-down: YES = "Up", NO = "Down" (verified in PMK API docs)

records = []
for _, r in m.iterrows():
    if not isinstance(r.clob_token_ids, str):
        continue
    try:
        toks = json.loads(r.clob_token_ids)
    except Exception:
        continue
    if len(toks) != 2:
        continue
    # Parse slot_start_s from slug suffix
    try:
        slot_start_s = int(str(r.slug).rsplit("-", 1)[1])
    except Exception:
        slot_start_s = None
    # Get market class
    tf = str(r.timeframe).strip() if pd.notna(r.timeframe) else None
    mc = f"updown_{tf}" if tf in ("5m", "15m", "1m") else None
    asset = str(r.ticker).upper() if pd.notna(r.ticker) else None
    records.append({"asset_id": str(toks[0]), "slug": r.slug, "outcome": "Up",
                    "market_class": mc, "mkt_asset": asset, "slot_start_s": slot_start_s,
                    "condition_id": r.condition_id})
    records.append({"asset_id": str(toks[1]), "slug": r.slug, "outcome": "Down",
                    "market_class": mc, "mkt_asset": asset, "slot_start_s": slot_start_s,
                    "condition_id": r.condition_id})

mp = pd.DataFrame(records)
print(f"asset_id mapping rows: {len(mp):,} ({mp.asset_id.nunique():,} unique)")

# Now load 0xb27bc932 trades_chain and enrich
df = pd.read_parquet(CACHE / "trades_chain.parquet")
print(f"trades_chain: {len(df):,}")
# Determine asset_id per row (= maker_asset_id if maker_asset is token, else taker_asset_id_raw)
def get_asset_id(r):
    mid = str(r.maker_asset_id)
    tid = str(r.taker_asset_id_raw)
    if len(mid) > 18:
        return mid
    if len(tid) > 18:
        return tid
    return None
df["asset_id"] = df.apply(get_asset_id, axis=1)
df = df.merge(mp, on="asset_id", how="left")
print(f"after join: {len(df):,}, with slug: {df.slug.notna().sum():,}")
# Compute price_clean / size_clean / side_clean as in trades_chain_enriched
df["price_clean"] = df["price"]
df["size_clean"] = df["size"]
df["side_clean"] = df["side"]
df.to_parquet(CACHE / "trades_chain_enriched.parquet", index=False)
print(f"-> {CACHE / 'trades_chain_enriched.parquet'}")
print(f"  unique slugs (maker-side): {df[df.wallet_is_maker].slug.nunique()}")
print(f"  BTC maker rows: {(df.wallet_is_maker & (df.mkt_asset == 'BTC')).sum()}")
