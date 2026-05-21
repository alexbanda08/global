"""Pull wallet's complete USDC + ERC1155 transfer history via Alchemy.

Bypasses OrderFilled parsing entirely. The cash-PnL = USDC_in - USDC_out
is what Polymarket UI shows users. We need ONLY two streams per wallet:

  1. ERC20 USDC transfers in/out  → cash flow
  2. ERC1155 token transfers in/out → outstanding inventory

Output: cache/<short>/alchemy_transfers.parquet (one row per transfer).

Per-wallet PnL = net USDC delta + value of outstanding ERC1155 holdings at
settlement (or current market mid for unresolved).

Usage:
    py -3 strategy_lab/wallet_hunt/fetch_alchemy.py --wallet 0x...
    py -3 strategy_lab/wallet_hunt/fetch_alchemy.py --all
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd

ALCHEMY_KEY = os.environ.get("ALCHEMY_POLYGON_KEY", "CkcB0ru1bUfColNdPoTLO")
ALCHEMY_URL = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"
UA = {"User-Agent": "global-strategy-lab/1.0",
      "Content-Type": "application/json"}

CACHE = Path(__file__).resolve().parent / "cache"

WALLETS = [
    "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    "0x89b5cdaaa4866c1e738406712012a630b4078beb",
    "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
    "0xcfb103c37c0234f524c632d964ed31f117b5f694",
    "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
]


def rpc(method: str, params: list, timeout: float = 60.0):
    req = urllib.request.Request(
        ALCHEMY_URL, headers=UA, method="POST",
        data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_transfers_one_direction(wallet: str, direction: str,
                                    categories: list, max_pages: int = 500,
                                    sleep_s: float = 0.1,
                                    since_block: int | None = None) -> list:
    """direction = 'from' or 'to'. Pages descending (newest first), stops
    when reaching `since_block` or running out of pages."""
    all_t = []
    page_key = None
    for page in range(max_pages):
        params = {
            "fromBlock": hex(since_block) if since_block else "0x0",
            "toBlock": "latest",
            "category": categories,
            "maxCount": "0x3e8",   # 1000
            "order": "desc",       # newest first
            "withMetadata": True,
        }
        if direction == "from":
            params["fromAddress"] = wallet
        else:
            params["toAddress"] = wallet
        if page_key:
            params["pageKey"] = page_key
        try:
            d = rpc("alchemy_getAssetTransfers", [params])
        except urllib.error.HTTPError as e:
            print(f"    [{direction}] page {page+1} HTTP {e.code}: {e.read()[:200].decode()}")
            break
        except Exception as e:
            print(f"    [{direction}] page {page+1} ERR: {str(e)[:80]}")
            break
        if "error" in d:
            print(f"    [{direction}] page {page+1} ERR: {d['error']}")
            break
        result = d.get("result") or {}
        t = result.get("transfers", [])
        all_t.extend(t)
        page_key = result.get("pageKey")
        print(f"    [{direction}] page {page+1}: +{len(t)} (cum {len(all_t)})", flush=True)
        if not page_key or not t:
            break
        time.sleep(sleep_s)
    return all_t


def fetch_wallet_transfers(wallet: str, days: float = 7.0,
                              max_pages: int = 200) -> pd.DataFrame:
    """Pull both incoming and outgoing transfers (ERC20 + ERC1155).

    Pages descending (newest first), stops after `max_pages` per direction
    (1000 transfers/page → up to 200,000 transfers per direction = 400k total).
    """
    w = wallet.lower()
    print(f"\n=== {w[:10]} (target: last {days}d, max {max_pages} pages/direction)")
    # Compute since_block from days
    head = int(rpc("eth_blockNumber", [])["result"], 16)
    since_block = head - int(days * 86400 / 2)  # ~2s blocks
    print(f"  head={head:,}  since_block={since_block:,}")
    rows = []
    for direction in ("from", "to"):
        print(f"  [{direction}] fetching...")
        t = fetch_transfers_one_direction(w, direction, ["erc20", "erc1155"],
                                            max_pages=max_pages,
                                            since_block=since_block)
        for r in t:
            mt = r.get("metadata") or {}
            erc1155_md = r.get("erc1155Metadata") or []
            # ERC1155 may have multiple tokens per transfer event — split into rows
            if erc1155_md:
                for md in erc1155_md:
                    rows.append({
                        "block": int(r.get("blockNum", "0x0"), 16),
                        "ts": mt.get("blockTimestamp"),
                        "tx_hash": r.get("hash"),
                        "log_index": r.get("uniqueId"),
                        "direction": direction,  # from this wallet, or to this wallet
                        "category": r.get("category"),
                        "asset": str(md.get("tokenId", "")),
                        "value": float(int(md.get("value", "0x0"), 16)) / 1e6,
                        "from": r.get("from"),
                        "to": r.get("to"),
                        "raw_contract": (r.get("rawContract") or {}).get("address"),
                    })
            else:
                rows.append({
                    "block": int(r.get("blockNum", "0x0"), 16),
                    "ts": mt.get("blockTimestamp"),
                    "tx_hash": r.get("hash"),
                    "log_index": r.get("uniqueId"),
                    "direction": direction,
                    "category": r.get("category"),
                    "asset": r.get("asset"),  # symbol for erc20 (pUSD)
                    "value": float(r.get("value") or 0),
                    "from": r.get("from"),
                    "to": r.get("to"),
                    "raw_contract": (r.get("rawContract") or {}).get("address"),
                })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["tx_hash", "log_index", "direction", "asset"]).reset_index(drop=True)
    df = df.sort_values("block").reset_index(drop=True)
    return df


def save_and_summarize(wallet: str, df: pd.DataFrame):
    w = wallet.lower(); short = w[:10]
    odir = CACHE / short
    odir.mkdir(parents=True, exist_ok=True)
    out = odir / "alchemy_transfers.parquet"
    df.to_parquet(out, index=False)
    print(f"  -> saved {len(df):,} transfers to {out}")
    if df.empty:
        return
    # Cash PnL
    usdc = df[df.asset == "pUSD"]
    cash_in = usdc[usdc.direction == "to"].value.sum()
    cash_out = usdc[usdc.direction == "from"].value.sum()
    print(f"  USDC in:    ${cash_in:>12,.2f}")
    print(f"  USDC out:   ${cash_out:>12,.2f}")
    print(f"  NET CASH:   ${cash_in - cash_out:>+12,.2f}")

    erc = df[df.category == "erc1155"]
    print(f"  ERC1155 transfers: {len(erc):,}  ({(erc.direction=='from').sum()} sent, {(erc.direction=='to').sum()} received)")
    if not df.ts.isna().all():
        ts_dt = pd.to_datetime(df.ts, errors="coerce", utc=True)
        valid = ts_dt.dropna()
        if len(valid):
            print(f"  time range: {valid.min()} → {valid.max()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--max-pages", type=int, default=100)
    args = ap.parse_args()
    wallets = WALLETS if args.all else (args.wallet or [])
    if not wallets:
        print("--wallet or --all required"); return 1

    for w in wallets:
        try:
            df = fetch_wallet_transfers(w, days=args.days, max_pages=args.max_pages)
            save_and_summarize(w, df)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"ERROR on {w}: {e}")


if __name__ == "__main__":
    main()
