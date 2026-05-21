"""Pull full Polymarket trade history for a wallet directly from Polygon.

Scans the NegRisk OrderFilled events emitted by:
  0xe111180000d2663c0091e4f400237545b87b996b (Polymarket NegRiskCtfExchange)

Event signature (verified via openchain.xyz):
  OrderFilled(
    bytes32 indexed orderHash,
    address indexed maker,
    address indexed taker,
    uint8 side,                       # 0 = BUY (from signer/maker POV)
    uint256 makerAssetId,             # the outcome token id the maker holds/sells
                                       # (USDC trades go through the matcher
                                       # which is the contract itself)
    uint256 takerAssetId,             # price × 1e7 (yes, this field is overloaded)
    uint256 makerAmount,              # shares in 1e6 scale
    uint256 takerAmount,              # fee or partial-fill amount
    bytes32 _unused1,
    bytes32 _unused2,
  )

Cross-checked vs data-api row at tx 0x19f0952df04d17680588e0805100bc8a711c5964fb75d858af89f3e323b189c5:
  Data-api: BUY 10 shares @ $0.41 → $4.10
  Chain log 2: makerAssetId=115228638... (asset)
               takerAssetId=4100000 (= price × 1e7 = 0.41)
               makerAmount=10000000 (= 10 shares × 1e6)

Output: cache/<short>/trades_chain.parquet — schema compatible with data-api.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
from eth_abi import decode
from eth_utils import keccak, to_checksum_address

CACHE = Path(__file__).resolve().parent / "cache"

# Polymarket NegRiskCtfExchange (the "matcher" contract that emits the fills)
EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"

# Verified via openchain.xyz lookup
ORDER_FILLED_TOPIC0 = "0x" + keccak(text=(
    "OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
)).hex()

# Polygon RPCs ranked by getLogs limit. Alchemy first (archive + 10k blocks per call).
import os as _os
_ALCHEMY_KEY = _os.environ.get("ALCHEMY_POLYGON_KEY", "CkcB0ru1bUfColNdPoTLO")
RPCS = [
    # Tenderly accepts 50k-block getLogs ranges (verified 2026-05-18); use 10k
    # chunks to stay below max-results-per-request cap (~39661 logs/request).
    "https://polygon.gateway.tenderly.co",
    # drpc.org fallback — 10k block max per free-tier
    "https://polygon.drpc.org",
    # Alchemy fallback — free-tier downgraded to 10 blocks/eth_getLogs in 2026-05.
    # Keep last so we can detect it's been re-upgraded if it ever stops 400'ing.
    f"https://polygon-mainnet.g.alchemy.com/v2/{_ALCHEMY_KEY}",
]

POLYGON_BLOCK_TIME_S = 2.0
CHUNK_BLOCKS = 9999  # tenderly/drpc free-tier max range

UA = {"User-Agent": "global-strategy-lab/1.0",
      "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

def rpc(method: str, params: list, rpcs: list = RPCS, timeout: float = 25.0):
    last_err = None
    for url in rpcs:
        try:
            req = urllib.request.Request(
                url, headers=UA, method="POST",
                data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode())
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                last_err = f"non-JSON response: {raw[:120]}"
                continue
            # Bare-string error body that happened to be valid JSON (e.g. "Backend error...")
            if isinstance(d, str):
                last_err = f"bare-string response: {d[:120]}"
                continue
            if isinstance(d, dict) and "error" in d:
                last_err = d["error"]
                continue
            # Some RPCs return a dict whose result is a string error
            if isinstance(d, dict) and isinstance(d.get("result"), str) and method != "eth_blockNumber" and not d["result"].startswith("0x"):
                last_err = d["result"]
                continue
            return d
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"all RPCs failed: {last_err}")


def get_block_number() -> int:
    return int(rpc("eth_blockNumber", [])["result"], 16)


def pad_address(addr: str) -> str:
    return "0x000000000000000000000000" + addr.lower().replace("0x", "")


def get_logs(from_block: int, to_block: int, address: str, topics: list) -> list:
    return rpc("eth_getLogs", [{
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "address": address,
        "topics": topics,
    }]).get("result", [])


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def decode_log(log: dict) -> dict:
    topics = log["topics"]
    data = bytes.fromhex(log["data"][2:])
    if len(data) < 7 * 32:
        return {}
    # Last 64 bytes are two bytes32s that empirically are zero / unused.
    side, maker_asset_id, taker_asset_id, maker_amount, taker_amount, _, _ = decode(
        ["uint8","uint256","uint256","uint256","uint256","bytes32","bytes32"], data[:7*32])
    return {
        "block":         int(log["blockNumber"], 16),
        "log_index":     int(log["logIndex"], 16),
        "tx_hash":       log["transactionHash"],
        "order_hash":    topics[1],
        "maker":         "0x" + topics[2][-40:].lower(),
        "taker":         "0x" + topics[3][-40:].lower(),
        "side_uint":     side,
        "maker_asset_id": str(maker_asset_id),
        "taker_asset_id_raw": str(taker_asset_id),
        "maker_amount_raw":  str(maker_amount),
        "taker_amount_raw":  str(taker_amount),
    }


def derive_trade_view(df: pd.DataFrame, wallet: str) -> pd.DataFrame:
    """Convert raw fills to wallet-POV BUY/SELL with size + price."""
    if df.empty:
        return df
    w = wallet.lower()
    df = df.copy()
    df["wallet_is_maker"] = df.maker == w
    df["wallet_is_taker"] = df.taker == w

    # Determine which side held the asset vs which provided USDC.
    # Asset IDs of CTF outcome tokens are huge uint256s; the "exchange contract"
    # often shows as taker with a small `takerAssetId` value = price × 1e7.
    df["maker_asset_is_token"] = df.maker_asset_id.astype(str).str.len() > 18
    df["taker_asset_is_token"] = df.taker_asset_id_raw.astype(str).str.len() > 18

    def parse_row(r):
        # Common pattern observed empirically:
        #   Either (maker has token, taker provides USDC) or vice-versa.
        # We compute price = USDC_paid / shares_received and infer wallet's side.
        try:
            mid = int(r.maker_asset_id)
            tid = int(r.taker_asset_id_raw)
            m_amt = int(r.maker_amount_raw) / 1e6
            t_amt = int(r.taker_amount_raw) / 1e6
        except Exception:
            return pd.Series({"side": None, "asset": None, "size": None,
                              "price": None, "usdc_notional": None})

        if r.maker_asset_is_token:
            # Maker holds token → maker is the seller. takerAssetId is overloaded
            # to encode price (× 1e7).
            shares = m_amt
            asset = str(mid)
            price = tid / 1e7
            usdc_notional = shares * price
        elif r.taker_asset_is_token:
            shares = t_amt
            asset = str(tid)
            price = int(r.maker_asset_id) / 1e7
            usdc_notional = shares * price
        else:
            return pd.Series({"side": None, "asset": None, "size": None,
                              "price": None, "usdc_notional": None})

        # Wallet's side: if wallet is the BUYER (received shares, paid USDC).
        # Maker sells, taker buys when maker has token; vice-versa otherwise.
        if r.wallet_is_taker and r.maker_asset_is_token:
            side = "BUY"
        elif r.wallet_is_maker and r.taker_asset_is_token:
            side = "BUY"
        else:
            side = "SELL"

        return pd.Series({"side": side, "asset": asset, "size": shares,
                          "price": price, "usdc_notional": usdc_notional})

    derived = df.apply(parse_row, axis=1)
    out = pd.concat([df, derived], axis=1)
    keep = ["block"]
    if "timestamp" in out.columns:
        keep.append("timestamp")
    keep += ["tx_hash", "log_index", "order_hash",
             "side", "asset", "size", "price", "usdc_notional",
             "maker", "taker", "wallet_is_maker", "wallet_is_taker",
             "side_uint", "maker_asset_id", "taker_asset_id_raw",
             "maker_amount_raw", "taker_amount_raw"]
    return out[keep]


# ---------------------------------------------------------------------------
# Main pull
# ---------------------------------------------------------------------------

def fetch_wallet_chain(wallet: str, days: int = 30,
                        chunk_blocks: int = CHUNK_BLOCKS) -> pd.DataFrame:
    head = get_block_number()
    blocks_to_scan = int(days * 86400 / POLYGON_BLOCK_TIME_S)
    start_block = head - blocks_to_scan
    print(f"  head: {head:,}")
    print(f"  scanning {blocks_to_scan:,} blocks ({days} days), "
          f"chunks of {chunk_blocks} blocks")
    wallet_topic = pad_address(wallet.lower())
    exchange_cs = to_checksum_address(EXCHANGE)

    all_logs = []
    n_chunks = (blocks_to_scan + chunk_blocks - 1) // chunk_blocks
    n_errors = 0
    for chunk_i in range(n_chunks):
        chunk_start = start_block + chunk_i * chunk_blocks
        chunk_end = min(chunk_start + chunk_blocks - 1, head)
        for role_idx in (0, 1):   # 0=maker, 1=taker
            topics = [ORDER_FILLED_TOPIC0, None, None, None]
            topics[2 + role_idx] = wallet_topic
            try:
                logs = get_logs(chunk_start, chunk_end, exchange_cs, topics)
                if logs:
                    all_logs.extend(logs)
            except Exception as e:
                n_errors += 1
                if n_errors < 5:
                    print(f"    err chunk {chunk_i+1}: {str(e)[:60]}", flush=True)
        if (chunk_i + 1) % 20 == 0 or chunk_i == n_chunks - 1:
            print(f"  chunk {chunk_i+1}/{n_chunks}: cum_logs={len(all_logs):,} "
                  f"errs={n_errors}", flush=True)

    # Dedup
    seen = set(); unique = []
    for l in all_logs:
        k = (l["transactionHash"], l["logIndex"])
        if k in seen: continue
        seen.add(k); unique.append(l)
    print(f"  decoded {len(unique)} unique fills (from {len(all_logs)} returned)")

    return pd.DataFrame([decode_log(l) for l in unique]).dropna(how="all")


def join_block_timestamps(df: pd.DataFrame, exact_anchors: int = 8) -> pd.DataFrame:
    """Add `timestamp` (unix seconds) by anchoring `exact_anchors` block→ts
    pairs across the range and linearly interpolating using ~2s block time.

    A full per-block fetch would be 1 RPC call per unique block (~20k calls
    for a 30d wallet pull). Linear interpolation gives ~2s accuracy and ~10
    RPC calls total — good enough for fingerprint/PnL.
    """
    if df.empty:
        return df
    blocks_sorted = sorted(df.block.unique())
    if len(blocks_sorted) == 0:
        return df

    # Pick `exact_anchors` evenly-spaced anchor blocks
    if len(blocks_sorted) <= exact_anchors:
        anchors = blocks_sorted
    else:
        step = len(blocks_sorted) // (exact_anchors - 1)
        anchors = [blocks_sorted[i * step] for i in range(exact_anchors - 1)]
        anchors.append(blocks_sorted[-1])

    print(f"  anchoring {len(anchors)} blocks for timestamp interpolation...")
    anchor_ts = {}
    for b in anchors:
        try:
            d = rpc("eth_getBlockByNumber", [hex(int(b)), False])
            if d.get("result"):
                anchor_ts[int(b)] = int(d["result"]["timestamp"], 16)
        except Exception as e:
            print(f"    anchor block {b} failed: {str(e)[:50]}")
    if not anchor_ts:
        print("  WARNING: no anchors fetched; timestamps will be missing")
        df = df.copy(); df["timestamp"] = pd.NA
        return df

    # Linear interpolation: for any block B, find its surrounding anchors
    anchor_blocks = sorted(anchor_ts.keys())
    anchor_ts_arr = [anchor_ts[b] for b in anchor_blocks]
    import numpy as _np

    def ts_for(block):
        block = int(block)
        # Before all anchors → extrapolate backwards
        if block <= anchor_blocks[0]:
            return anchor_ts_arr[0] - (anchor_blocks[0] - block) * 2
        if block >= anchor_blocks[-1]:
            return anchor_ts_arr[-1] + (block - anchor_blocks[-1]) * 2
        # Between two anchors → linear interpolate
        idx = _np.searchsorted(anchor_blocks, block, side="right") - 1
        b0, b1 = anchor_blocks[idx], anchor_blocks[idx+1]
        t0, t1 = anchor_ts_arr[idx], anchor_ts_arr[idx+1]
        return int(t0 + (t1 - t0) * (block - b0) / max(b1 - b0, 1))

    df = df.copy()
    df["timestamp"] = df.block.map(ts_for).astype("int64")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    ap.add_argument("--days", type=float, default=30)
    args = ap.parse_args()

    w = args.wallet.lower()
    short = w[:10]
    odir = CACHE / short
    odir.mkdir(parents=True, exist_ok=True)

    print(f"=== chain pull: {w} ({args.days} days)")
    raw = fetch_wallet_chain(w, days=args.days)
    if raw.empty:
        print("=== no fills found")
        return
    raw.to_parquet(odir / "trades_chain_raw.parquet", index=False)
    print(f"  raw fills -> {odir / 'trades_chain_raw.parquet'}")

    raw = join_block_timestamps(raw)
    view = derive_trade_view(raw, w)
    view.to_parquet(odir / "trades_chain.parquet", index=False)

    if "timestamp" in view.columns:
        ts = pd.to_datetime(view.timestamp.astype("Int64"), unit="s", utc=True)
    else:
        ts = pd.Series([], dtype="datetime64[ns, UTC]")
    print(f"\n=== summary ===")
    print(f"  fills: {len(view)}")
    if "timestamp" in view.columns and ts.notna().any():
        print(f"  window: {ts.min()} → {ts.max()} "
              f"({(ts.max()-ts.min()).total_seconds()/86400:.1f} days)")
    print(f"  side: {view.side.value_counts().to_dict()}")
    print(f"  liquidity: maker={view.wallet_is_maker.sum()} taker={view.wallet_is_taker.sum()}")
    valid_prices = view.dropna(subset=["price"])
    if len(valid_prices):
        print(f"  price range: ${valid_prices.price.min():.4f} – ${valid_prices.price.max():.4f}")
        print(f"  total USDC notional: ${valid_prices.usdc_notional.sum():,.2f}")
    print(f"  unique tokens (asset_ids): {view.asset.nunique()}")


if __name__ == "__main__":
    main()
