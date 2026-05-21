"""Find the actual FIRST inbound USDC transfer for each wallet — going all
the way back to the wallet's birth on Polygon.

Uses Alchemy `getAssetTransfers` with `order: "asc"` and `fromBlock: 0x0`
so the FIRST page contains the earliest 1000 transfers ever — the very
first inbound USDC is in there.

Output: cache/_first_deposit.csv
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ALCHEMY_KEY = os.environ.get("ALCHEMY_POLYGON_KEY", "CkcB0ru1bUfColNdPoTLO")
ALCHEMY_URL = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"
UA = {"User-Agent": "global-strategy-lab/1.0",
      "Content-Type": "application/json"}

CACHE = Path(__file__).resolve().parent / "cache"

# Same exchange map as cash_pnl.py
EXCHANGE_ADDRS = {
    "0xe111180000d2663c0091e4f400237545b87b996b",  # NegRisk matcher
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTFExchange (old)
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # NegRiskCtfExchange
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # CTF / Conditional Tokens
    "0x0000000000000000000000000000000000000000",  # mint/burn → trading flow
}
USDC_ASSETS = {"USDC", "USDCE", "USDC.E", "PUSD", "USDT"}  # uppercase

# Wallets to scan. Keep aligned with cache/0x*/ folders.
WALLETS_FULL = {
    # Previously analyzed
    "0x04b6d7e9": "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
    "0x7cde1da9": "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
    "0x89b5cdaa": "0x89b5cdaaa4866c1e738406712012a630b4078beb",
    "0xce25e214": "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    "0xcfb103c3": "0xcfb103c37c0234f524c632d964ed31f117b5f694",
    "0xeebde7a0": "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xf247584e": "0xf247584e41117bbbe4cc06e4d2c95741792a5216",
    "0xf7f0b0b1": "0xf7f0b0b1e9c0fe02ccad926916ee31aef74b912c",
    # Round 2 — operator-provided 2026-05-17
    "0x7f599984": "0x7f59998477864871448e312011fa5cc6b210b636",
    "0xb27bc932": "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
    "0xa0a50783": "0xa0a5078359dad63993a868f6d2db82d3a7b3606f",
    "0x3e6bfd2f": "0x3e6bfd2f791a10cf2404e09542c2a82e3e7b6d63",
    "0xeefe46de": "0xeefe46deee8da83bf67dc95b6bc8b8f73e77be43",
    "0x0fe40e88": "0x0fe40e887acbd0022f89d996acce26ab428501b7",
    "0x9dae874a": "0x9dae874a2e804349e3004ccc98107799f15f97a2",
}


def rpc(method: str, params: list, timeout: float = 60.0):
    req = urllib.request.Request(
        ALCHEMY_URL, headers=UA, method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": 1,
                         "method": method, "params": params}).encode(),
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_inbound_from_genesis(wallet: str, max_pages: int = 5,
                                 retries: int = 3) -> list:
    """Pull inbound (toAddress=wallet) transfers in ASC order from block 0.

    Categories: erc20 only — we only need USDC for the first deposit.
    Retries each page on transient errors.
    """
    transfers = []
    page_key = None
    for page in range(max_pages):
        params = {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "toAddress": wallet,
            "category": ["erc20"],
            "maxCount": "0x3e8",   # 1000
            "order": "asc",        # OLDEST first
            "withMetadata": True,
        }
        if page_key:
            params["pageKey"] = page_key

        # Retry loop for transient errors (IncompleteRead, timeouts)
        d = None
        for attempt in range(retries):
            try:
                d = rpc("alchemy_getAssetTransfers", [params])
                break
            except urllib.error.HTTPError as e:
                print(f"  HTTP {e.code} page {page+1} attempt {attempt+1}: "
                      f"{e.read()[:200].decode()}")
                if attempt == retries - 1:
                    return transfers
                time.sleep(2.0)
            except Exception as e:
                print(f"  ERR page {page+1} attempt {attempt+1}: {str(e)[:120]}")
                if attempt == retries - 1:
                    return transfers
                time.sleep(2.0)
        if d is None:
            break

        if "error" in d:
            print(f"  RPC error: {d['error']}")
            break

        chunk = d.get("result", {}).get("transfers", [])
        transfers.extend(chunk)
        page_key = d.get("result", {}).get("pageKey")
        if not page_key:
            break
        time.sleep(0.2)

    return transfers


def first_external_deposit(transfers: list) -> dict | None:
    """Return the first USDC inbound from a non-exchange counterparty."""
    for t in transfers:
        asset = (t.get("asset") or "").upper()
        if asset not in USDC_ASSETS:
            continue
        frm = (t.get("from") or "").lower()
        if frm in EXCHANGE_ADDRS:
            continue
        return {
            "ts": t.get("metadata", {}).get("blockTimestamp"),
            "block": int(t.get("blockNum", "0x0"), 16),
            "value": float(t.get("value") or 0),
            "asset": asset,
            "from": frm,
            "tx_hash": t.get("hash"),
        }
    return None


def first_any_deposit(transfers: list) -> dict | None:
    """Return the very first inbound erc20 transfer (any source)."""
    if not transfers:
        return None
    t = transfers[0]
    return {
        "ts": t.get("metadata", {}).get("blockTimestamp"),
        "block": int(t.get("blockNum", "0x0"), 16),
        "value": float(t.get("value") or 0),
        "asset": (t.get("asset") or "").upper(),
        "from": (t.get("from") or "").lower(),
        "tx_hash": t.get("hash"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", action="append",
                    help="full address; defaults to all in WALLETS_FULL")
    ap.add_argument("--max-pages", type=int, default=5,
                    help="how many 1000-row pages to walk forward")
    args = ap.parse_args()

    wallets = args.wallet or list(WALLETS_FULL.values())
    rows = []
    for w in wallets:
        short = w[:10].lower()
        print(f"\n=== {short} ({w}) ===")
        trs = fetch_inbound_from_genesis(w, max_pages=args.max_pages)
        print(f"  fetched {len(trs)} inbound erc20 transfers (oldest first)")
        first_ext = first_external_deposit(trs)
        first_any = first_any_deposit(trs)
        if first_ext:
            print(f"  FIRST external USDC: ${first_ext['value']:.2f} "
                  f"at {first_ext['ts']} from {first_ext['from']}")
        if first_any:
            print(f"  FIRST any erc20    : ${first_any['value']:.2f} "
                  f"{first_any['asset']} at {first_any['ts']} from {first_any['from']}")
        rows.append({
            "short": short, "full": w,
            "n_inbound_erc20_seen": len(trs),
            "first_external_ts": first_ext["ts"] if first_ext else None,
            "first_external_usd": first_ext["value"] if first_ext else None,
            "first_external_from": first_ext["from"] if first_ext else None,
            "first_external_tx": first_ext["tx_hash"] if first_ext else None,
            "first_any_ts": first_any["ts"] if first_any else None,
            "first_any_usd": first_any["value"] if first_any else None,
            "first_any_asset": first_any["asset"] if first_any else None,
            "first_any_from": first_any["from"] if first_any else None,
        })
    df = pd.DataFrame(rows)
    out = CACHE / "_first_deposit.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved -> {out}")
    print()
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
