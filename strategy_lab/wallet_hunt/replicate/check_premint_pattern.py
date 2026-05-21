"""Check: do wallets pre-mint inventory at slot_start, or mint per fire?

If pre-minting: we'd see a small number of mints (CTF.splitPosition calls)
per slug, all clustered at slot_start, with many sells throughout the window.
If per-fire: we'd see one mint per sell pair, scattered through the window.

Mint events show up in alchemy_transfers as ERC1155 transfers FROM the zero
address (0x0) — when CTF.splitPosition is called, new tokens are minted to
the wallet's address with `from = 0x0`.

Burns (mergePositions) show as transfers TO 0x0.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

ZERO_ADDR = "0x0000000000000000000000000000000000000000"

WALLETS = ["0xeebde7a0", "0x04b6d7e9", "0x89b5cdaa", "0xf7f0b0b1"]

for w in WALLETS:
    cache = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / w
    transfers_p = cache / "alchemy_transfers.parquet"
    fires_p = cache / "fires_decoded.parquet"
    if not transfers_p.exists() or not fires_p.exists():
        continue

    transfers = pd.read_parquet(transfers_p)
    fires = pd.read_parquet(fires_p)

    # Mints = ERC1155 transfers FROM zero address INTO wallet
    erc1155 = transfers[transfers.category == "erc1155"].copy() if "category" in transfers.columns else transfers
    if "from" not in erc1155.columns:
        print(f"  {w}: missing 'from' column")
        continue
    mints = erc1155[erc1155["from"].str.lower() == ZERO_ADDR]
    burns = erc1155[erc1155["to"].str.lower() == ZERO_ADDR] if "to" in erc1155.columns else pd.DataFrame()

    n_fires = len(fires)
    n_mints = len(mints)
    n_burns = len(burns)

    # Group mints by tx_hash (one splitPosition tx may produce 2 token transfers — one Up + one Down)
    mints_per_tx = mints.groupby("tx_hash").size() if len(mints) else pd.Series(dtype=int)
    n_mint_txs = len(mints_per_tx)

    print(f"\n=== {w}")
    print(f"  fires (CLOB fills): {n_fires:,}")
    print(f"  mint events (token transfers from 0x0): {n_mints:,}")
    print(f"  mint TXs (unique splitPosition calls):  {n_mint_txs:,}")
    print(f"  burn events (token transfers to 0x0): {n_burns:,}")

    if n_fires > 0 and n_mint_txs > 0:
        ratio = n_fires / n_mint_txs
        print(f"  → fires per mint TX: {ratio:.1f}")
        if ratio > 3:
            print(f"  → PATTERN: pre-mint and re-use ({ratio:.0f}× sells per mint)")
        elif ratio < 1.5:
            print(f"  → PATTERN: mint-per-fire (each sell preceded by a mint)")
        else:
            print(f"  → PATTERN: mixed / partial pre-mint")
