"""Indirect counterparty search — find target wallets in OTHER wallets' trades_chain.

When direct chain fetch fails (contract wallet, rate-limited RPC, etc.), we can
still recover partial trade data by scanning every existing trades_chain.parquet
for rows where `taker` or `maker` matches the target wallet.

Output: cache/<short>/indirect_trades_chain.parquet (concatenated from all sources)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"

TARGETS = [
    "0x7dfc8aa22f2d4d6f9cbf55cf86682a4d2477f54e",
    "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
    "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
]

def main():
    sources = []
    for d in CACHE.iterdir():
        if not d.is_dir():
            continue
        tc = d / "trades_chain.parquet"
        if tc.exists():
            sources.append((d.name, tc))
    print(f"scanning {len(sources)} source wallets")

    for target in TARGETS:
        tlow = target.lower()
        short = tlow[:10]
        odir = CACHE / short
        odir.mkdir(parents=True, exist_ok=True)
        out = odir / "indirect_trades_chain.parquet"

        hits = []
        for src_name, src_path in sources:
            df = pd.read_parquet(src_path)
            cols = ["maker", "taker"]
            if not all(c in df.columns for c in cols):
                continue
            m = df[(df.maker == tlow) | (df.taker == tlow)].copy()
            if len(m):
                m["_source_wallet"] = src_name
                hits.append(m)
                print(f"  {target[:10]} found {len(m)} fills in {src_name}'s trades_chain")
        if hits:
            combined = pd.concat(hits, ignore_index=True)
            combined = combined.drop_duplicates(subset=["tx_hash", "log_index"]).reset_index(drop=True)
            combined.to_parquet(out, index=False)
            print(f"  -> {target[:10]}: {len(combined):,} unique fills -> {out}")
        else:
            print(f"  -> {target[:10]}: NO indirect hits")


if __name__ == "__main__":
    main()
