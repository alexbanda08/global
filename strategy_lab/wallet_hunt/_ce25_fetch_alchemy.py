"""
_ce25_fetch_alchemy.py — Pull full Alchemy history for 0xce25e214.

Wallet started Apr 30 2026 (block ~86,261,839 = 0x523bccf).
Expected ~300k-500k transfers total (very active HF wallet).

Output: cache/0xce25e214/alchemy_transfers_full.parquet
        cache/0xce25e214/chain_pnl_summary.json
"""
from __future__ import annotations
import json, time, urllib.request, urllib.error
from pathlib import Path
import pandas as pd
import numpy as np

ALCHEMY_URL = "https://polygon-mainnet.g.alchemy.com/v2/CkcB0ru1bUfColNdPoTLO"
UA = {"User-Agent": "global-strategy-lab/1.0", "Content-Type": "application/json"}
WALLET = "0xce25e214d5cfe4f459cf67f08df581885aae7fdc"
SINCE_BLOCK = 0x523bccf  # Apr 30 2026 wallet inception

CACHE = Path(__file__).resolve().parent / "cache" / "0xce25e214"
CACHE.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = CACHE / "alchemy_transfers_full.parquet"
CHECKPOINT = CACHE / "_alchemy_checkpoint.json"

PUSED_DEPOSIT = "0xf70da97812cb96acdf810712aa562db8dfa3dbef"  # pUSD deposit contract - NOT treasury
CONV_CONTRACT = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"   # USDCE->pUSD conversion

def rpc(method, params, retries=6):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(ALCHEMY_URL, headers=UA, method="POST",
                data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode())
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}: {e.read()[:200]}")
            return None
        except Exception as e:
            wait = 2.0 * (attempt + 1)
            print(f"  ERR attempt {attempt+1}: {str(e)[:80]} -> retry {wait:.0f}s")
            time.sleep(wait)
    return None

def fetch_direction(direction: str, max_pages: int = 1000) -> list:
    # Load checkpoint if exists
    ck_key = f"page_key_{direction}"
    ck_cum = f"cum_{direction}"
    checkpoint = {}
    if CHECKPOINT.exists():
        checkpoint = json.loads(CHECKPOINT.read_text())

    all_t = checkpoint.get(f"rows_{direction}", [])
    page_key = checkpoint.get(ck_key)
    start_page = len(all_t) // 1000

    if all_t:
        print(f"  [{direction}] Resuming from checkpoint: {len(all_t)} rows, page ~{start_page}")

    for page in range(start_page, max_pages):
        params = {
            "fromBlock": hex(SINCE_BLOCK),
            "toBlock": "latest",
            "category": ["erc20", "erc1155"],
            "maxCount": "0x3e8",
            "order": "asc",
            "withMetadata": True,
        }
        if direction == "from":
            params["fromAddress"] = WALLET
        else:
            params["toAddress"] = WALLET
        if page_key:
            params["pageKey"] = page_key

        d = rpc("alchemy_getAssetTransfers", [params])
        if d is None:
            print(f"  [{direction}] RPC returned None at page {page+1} — stopping")
            break

        result = d.get("result") or {}
        t = result.get("transfers", [])
        all_t.extend(t)
        page_key = result.get("pageKey")
        print(f"  [{direction}] page {page+1}: +{len(t)} (cum {len(all_t)})", flush=True)

        # Checkpoint every 50 pages
        if (page + 1) % 50 == 0:
            checkpoint[f"rows_{direction}"] = all_t
            checkpoint[ck_key] = page_key
            CHECKPOINT.write_text(json.dumps(checkpoint))
            print(f"  [{direction}] CHECKPOINT saved at {len(all_t)} rows")

        if not page_key or not t:
            break
        time.sleep(0.03)

    # Save final state
    checkpoint[f"rows_{direction}"] = all_t
    checkpoint[ck_key] = None
    CHECKPOINT.write_text(json.dumps(checkpoint))
    return all_t


def parse_transfers(transfers_from: list, transfers_to: list) -> pd.DataFrame:
    rows = []
    for direction, transfers in [("from", transfers_from), ("to", transfers_to)]:
        for r in transfers:
            mt = r.get("metadata") or {}
            erc1155_md = r.get("erc1155Metadata") or []
            if erc1155_md:
                for md in erc1155_md:
                    rows.append({
                        "block": int(r.get("blockNum", "0x0"), 16),
                        "ts": mt.get("blockTimestamp"),
                        "tx_hash": r.get("hash"),
                        "log_index": r.get("uniqueId"),
                        "direction": direction,
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
                    "asset": r.get("asset"),
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


def compute_chain_pnl(df: pd.DataFrame) -> dict:
    """Chain-true PnL:
    - pUSD/USDCE TO wallet = deposits/credits (except from 0x0 = CTF redemption = income)
    - pUSD/USDCE FROM wallet = outflows (except to 0x0 = mint cost = trading expense)
    - USDC from conversion contract = neutral (USDCE->pUSD swap, nets to 0)

    Actual formula: PnL = redemptions (from 0x0) + external USDC in - deposits - USDC costs
    Simpler: net USDC balance = cash_in_total - cash_out_total
             BUT need to exclude deposit contract (0xf70da) as it's just pUSD wrapper, not income

    Ground truth: cash_in (from counterparties) - cash_out (to counterparties) - deposits + withdrawals
    """
    usdc = df[df.asset.isin(["pUSD", "USDCE"])].copy()

    # Deposits = USDC arriving from pUSD deposit contract (0xf70da) - user funding the wallet
    deposits = usdc[(usdc.direction == "to") & (usdc["from"].str.lower() == PUSED_DEPOSIT)].value.sum()

    # Withdrawals = USDC sent to pUSD deposit contract (user withdrawing)
    withdrawals = usdc[(usdc.direction == "from") & (usdc["to"].str.lower() == PUSED_DEPOSIT)].value.sum()

    # Trading cash flows: USDC to/from trading counterparties (excluding deposit contract and conversion)
    trading_out = usdc[
        (usdc.direction == "from") &
        (usdc["to"].str.lower() != PUSED_DEPOSIT) &
        (usdc.raw_contract.str.lower().fillna("") != CONV_CONTRACT)
    ].value.sum()

    trading_in = usdc[
        (usdc.direction == "to") &
        (usdc["from"].str.lower() != PUSED_DEPOSIT) &
        (usdc.raw_contract.str.lower().fillna("") != CONV_CONTRACT)
    ].value.sum()

    # Simple chain PnL
    total_cash_in = usdc[usdc.direction == "to"].value.sum()
    total_cash_out = usdc[usdc.direction == "from"].value.sum()
    net_cash = total_cash_in - total_cash_out

    # Deposit-adjusted PnL (what the wallet actually earned from trading)
    trading_pnl = trading_in - trading_out

    ts = pd.to_datetime(df.ts, errors="coerce", utc=True)

    return {
        "total_usdc_in": float(total_cash_in),
        "total_usdc_out": float(total_cash_out),
        "net_cash_usdc": float(net_cash),
        "deposits": float(deposits),
        "withdrawals": float(withdrawals),
        "trading_in": float(trading_in),
        "trading_out": float(trading_out),
        "trading_pnl": float(trading_pnl),
        "deposit_adjusted_pnl": float(net_cash + deposits - withdrawals),
        "time_start": str(ts.min()),
        "time_end": str(ts.max()),
        "n_rows": len(df),
        "n_usdc_rows": len(usdc),
        "n_erc1155_rows": int((df.category == "erc1155").sum()),
    }


if __name__ == "__main__":
    t0 = time.time()
    print(f"=== Fetching 0xce25e214 full Alchemy history ===")
    print(f"Since block: {SINCE_BLOCK:,} (~2026-04-30)")

    print("\nFetching FROM transfers...")
    from_t = fetch_direction("from", max_pages=1000)
    print(f"FROM done: {len(from_t):,} transfers")

    print("\nFetching TO transfers...")
    to_t = fetch_direction("to", max_pages=1000)
    print(f"TO done: {len(to_t):,} transfers")

    print(f"\nParsing {len(from_t)+len(to_t):,} total transfer events...")
    df = parse_transfers(from_t, to_t)
    print(f"Parsed: {len(df):,} unique rows")

    df.to_parquet(OUT_PARQUET, index=False)
    print(f"Saved -> {OUT_PARQUET}")

    pnl = compute_chain_pnl(df)
    (CACHE / "chain_pnl_summary.json").write_text(json.dumps(pnl, indent=2))
    print("\n=== Chain PnL Summary ===")
    for k, v in pnl.items():
        print(f"  {k}: {v}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")

    # Clean up checkpoint
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()
