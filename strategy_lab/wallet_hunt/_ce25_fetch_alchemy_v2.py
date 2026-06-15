"""
_ce25_fetch_alchemy_v2.py — Full Alchemy history pull for 0xce25e214.
v2 changes vs v1:
- Checkpoint JSON written to D:/tmp_ce25/ (not C:) to avoid filling C: with 700k-row JSON
- Final parquet written to D: tmp first, then atomic swap to C: canonical path
- Corrected chain-true PnL (b945 method): deposits_in - withdrawals_out + current_balance
- May 15-16 window exact redemption income computed separately
- Restart-safe: will resume from checkpoint on D: if it exists

Output:
  D:/tmp_ce25/_alchemy_checkpoint.json  (temp, deleted on success)
  cache/0xce25e214/alchemy_transfers_full.parquet  (final, overwrites old partial)
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
SINCE_BLOCK = 0x523bccf  # Apr 30 2026 wallet inception (~block 86,228,175)

CACHE = Path(__file__).resolve().parent / "cache" / "0xce25e214"
CACHE.mkdir(parents=True, exist_ok=True)

# Final output on C: (canonical location)
OUT_PARQUET_FINAL = CACHE / "alchemy_transfers_full.parquet"
# Old partial (preserve until new pull is done)
OUT_PARQUET_OLD   = CACHE / "alchemy_transfers.parquet"

# Intermediates on D: (avoids filling C: with 700k-row JSON checkpoint)
TMP_DIR = Path("D:/tmp_ce25")
TMP_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET_TMP = TMP_DIR / "alchemy_transfers_tmp.parquet"
CHECKPOINT      = TMP_DIR / "_alchemy_checkpoint.json"

PUSED_DEPOSIT = "0xf70da97812cb96acdf810712aa562db8dfa3dbef"  # pUSD deposit contract
CONV_CONTRACT = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"   # USDCE->pUSD conversion
CTF_ZERO      = "0x0000000000000000000000000000000000000000"   # CTF mint/burn


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
    ck_key = f"page_key_{direction}"
    checkpoint = {}
    if CHECKPOINT.exists():
        try:
            checkpoint = json.loads(CHECKPOINT.read_text())
        except Exception as e:
            print(f"  WARN: checkpoint parse error ({e}), starting fresh")
            checkpoint = {}

    all_t = checkpoint.get(f"rows_{direction}", [])
    page_key = checkpoint.get(ck_key)
    start_page = len(all_t) // 1000

    if all_t:
        print(f"  [{direction}] Resuming from checkpoint: {len(all_t):,} rows, page ~{start_page}")
    else:
        print(f"  [{direction}] Starting fresh from block {SINCE_BLOCK:,}")

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
        print(f"  [{direction}] page {page+1}: +{len(t)} (cum {len(all_t):,})", flush=True)

        # Checkpoint every 50 pages — written to D: to avoid filling C:
        if (page + 1) % 50 == 0:
            checkpoint[f"rows_{direction}"] = all_t
            checkpoint[ck_key] = page_key
            CHECKPOINT.write_text(json.dumps(checkpoint))
            print(f"  [{direction}] CHECKPOINT saved at {len(all_t):,} rows (D:{TMP_DIR})")

        if not page_key or not t:
            break
        time.sleep(0.03)

    # Final checkpoint save
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
    """
    Chain-true PnL using the b945 method:
      PnL = total_deposited_in - total_withdrawn_out + current_wallet_balance

    Here we compute from transfers:
      deposits_in   = USDC/pUSD arriving FROM pUSD deposit contract (0xf70da) = user funds going IN
      withdrawals_out = USDC/pUSD leaving TO pUSD deposit contract = user funds going OUT
      current_balance = not directly available from transfers alone; approximated as net_cash below

    Transfer classification (USDC/pUSD only):
      TO wallet:
        - from 0xf70da  = external deposit (user funding)
        - from 0x0      = CTF redemption income (winner token resolved at $1)
        - from others   = trading income / CLOB fills
      FROM wallet:
        - to 0xf70da    = external withdrawal (user pulling funds)
        - to 0x0        = CTF mint cost (buying new token sets from Polymarket CLOB)
        - to others     = trading outflow / CLOB fills

    Net chain PnL = (all_in - deposits) - (all_out - withdrawals)
                  = trading_in + redemptions - trading_costs - mint_costs
    NOTE: deposits and withdrawals cancel — they are capital movements, not earnings.

    Separately:
      redemption_income = USDC from 0x0 (CTF resolves winner token -> sends USDC back)
      mint_cost         = USDC to 0x0 (buying CTF token sets = trading cost)
    """
    usdc = df[df.asset.isin(["pUSD", "USDCE", "USDC"])].copy()
    usdc["from_lc"] = usdc["from"].str.lower().fillna("")
    usdc["to_lc"] = usdc["to"].str.lower().fillna("")
    usdc["rc_lc"] = usdc["raw_contract"].str.lower().fillna("")

    # External capital flows (user moving money in/out of Polymarket)
    deposits = usdc[(usdc.direction == "to") & (usdc["from_lc"] == PUSED_DEPOSIT)].value.sum()
    withdrawals = usdc[(usdc.direction == "from") & (usdc["to_lc"] == PUSED_DEPOSIT)].value.sum()

    # CTF operations (internal to Polymarket trading)
    redemption_income = usdc[(usdc.direction == "to") & (usdc["from_lc"] == CTF_ZERO)].value.sum()
    mint_costs = usdc[(usdc.direction == "from") & (usdc["to_lc"] == CTF_ZERO)].value.sum()

    # CLOB trading flows (excluding deposit contract and conversion contract)
    is_conv = usdc["rc_lc"] == CONV_CONTRACT.lower()
    clob_in = usdc[
        (usdc.direction == "to") &
        (usdc["from_lc"] != PUSED_DEPOSIT) &
        (usdc["from_lc"] != CTF_ZERO) &
        (~is_conv)
    ].value.sum()
    clob_out = usdc[
        (usdc.direction == "from") &
        (usdc["to_lc"] != PUSED_DEPOSIT) &
        (usdc["to_lc"] != CTF_ZERO) &
        (~is_conv)
    ].value.sum()

    # Total gross flows
    total_in = usdc[usdc.direction == "to"].value.sum()
    total_out = usdc[usdc.direction == "from"].value.sum()
    net_cash = total_in - total_out  # current balance if wallet started at 0

    # Chain-true trading PnL (excludes capital deposits/withdrawals)
    # = redemption income + clob_in - mint_costs - clob_out
    chain_pnl = redemption_income + clob_in - mint_costs - clob_out

    # b945 method: deposits - withdrawals + net_cash = PnL if starting balance was 0
    # This should equal chain_pnl if accounting is correct
    b945_pnl = net_cash - deposits + withdrawals  # net earned = total_net minus capital in + capital out

    ts = pd.to_datetime(df.ts, errors="coerce", utc=True)
    first_ts = ts.min()
    last_ts = ts.max()
    wallet_age_days = (last_ts - first_ts).total_seconds() / 86400 if pd.notna(first_ts) else 0

    # May 15-16 exact redemption window
    ts_ser = ts
    may15_mask = (ts_ser >= "2026-05-15") & (ts_ser < "2026-05-17")
    may15_usdc = usdc[may15_mask]
    may15_redemptions = may15_usdc[(may15_usdc.direction == "to") & (may15_usdc["from_lc"] == CTF_ZERO)].value.sum()
    may15_mint = may15_usdc[(may15_usdc.direction == "from") & (may15_usdc["to_lc"] == CTF_ZERO)].value.sum()
    may15_clob_in = may15_usdc[
        (may15_usdc.direction == "to") &
        (may15_usdc["from_lc"] != PUSED_DEPOSIT) &
        (may15_usdc["from_lc"] != CTF_ZERO)
    ].value.sum()
    may15_clob_out = may15_usdc[
        (may15_usdc.direction == "from") &
        (may15_usdc["to_lc"] != PUSED_DEPOSIT) &
        (may15_usdc["to_lc"] != CTF_ZERO)
    ].value.sum()
    may15_net = may15_redemptions + may15_clob_in - may15_mint - may15_clob_out

    return {
        "method": "b945_chain_true",
        # Core numbers
        "chain_pnl": float(chain_pnl),
        "b945_pnl_check": float(b945_pnl),
        "deposits_in": float(deposits),
        "withdrawals_out": float(withdrawals),
        "net_cash_in_wallet": float(net_cash),
        # Components
        "redemption_income_total": float(redemption_income),
        "mint_costs_total": float(mint_costs),
        "clob_sell_income": float(clob_in),
        "clob_buy_costs": float(clob_out),
        # Per-day
        "wallet_age_days": float(wallet_age_days),
        "pnl_per_day": float(chain_pnl / wallet_age_days) if wallet_age_days > 0 else 0,
        # May 15-16 window exact
        "may1516_redemption_income": float(may15_redemptions),
        "may1516_mint_costs": float(may15_mint),
        "may1516_clob_in": float(may15_clob_in),
        "may1516_clob_out": float(may15_clob_out),
        "may1516_net_pnl": float(may15_net),
        # Metadata
        "time_start": str(first_ts),
        "time_end": str(last_ts),
        "n_rows": len(df),
        "n_usdc_rows": len(usdc),
        "n_erc1155_rows": int((df.category == "erc1155").sum()),
    }


if __name__ == "__main__":
    import shutil
    t0 = time.time()
    print(f"=== Fetching 0xce25e214 full Alchemy history (v2) ===")
    print(f"Since block: {SINCE_BLOCK:,} (~2026-04-30)")
    print(f"Checkpoint dir: {TMP_DIR}")
    c_free = shutil.disk_usage("C:/").free / 1e9
    d_free = shutil.disk_usage("D:/").free / 1e9
    print(f"Disk: C: {c_free:.1f}GB free, D: {d_free:.1f}GB free")

    print("\nFetching FROM transfers...")
    from_t = fetch_direction("from", max_pages=1000)
    print(f"FROM done: {len(from_t):,} transfers")

    print("\nFetching TO transfers...")
    to_t = fetch_direction("to", max_pages=1000)
    print(f"TO done: {len(to_t):,} transfers")

    print(f"\nParsing {len(from_t)+len(to_t):,} total transfer events...")
    df = parse_transfers(from_t, to_t)
    print(f"Parsed: {len(df):,} unique rows")

    # Write to D: first (tmp), then atomic swap to C:
    print(f"\nWriting parquet to tmp: {OUT_PARQUET_TMP}")
    df.to_parquet(OUT_PARQUET_TMP, index=False)
    print(f"Swap to final: {OUT_PARQUET_FINAL}")
    if OUT_PARQUET_FINAL.exists():
        OUT_PARQUET_FINAL.unlink()
    shutil.copy2(str(OUT_PARQUET_TMP), str(OUT_PARQUET_FINAL))
    OUT_PARQUET_TMP.unlink()
    print(f"Saved -> {OUT_PARQUET_FINAL}")

    pnl = compute_chain_pnl(df)
    pnl_path = CACHE / "chain_pnl_summary.json"
    pnl_path.write_text(json.dumps(pnl, indent=2))
    print("\n=== Chain PnL Summary (b945 method) ===")
    for k, v in pnl.items():
        print(f"  {k}: {v}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")

    # Clean up checkpoint from D:
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()
    print("Checkpoint cleaned up. Done.")
