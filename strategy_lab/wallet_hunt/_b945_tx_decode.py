"""
On-chain transaction decoder for 0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68.

Reads alchemy_transfers.parquet, classifies every tx by composition,
fetches calldata/receipt samples per class, builds tx_taxonomy.parquet.

Key analysis functions (run independently):
    merge_timing()            -- maps 1,307 MERGE txs to slug windows; confirms 100% post-resolution
    orderfilled_maker_split() -- parses OrderFilled receipt logs; true maker/taker split (~63% maker)

Usage:
    py -3 strategy_lab/wallet_hunt/_b945_tx_decode.py

Outputs:
    cache/0xb945945d/{tx_taxonomy,merge_timing,orderfilled_sample,orderfilled_sample_early}.parquet
"""
import os
import sys
import requests
import pandas as pd

ALCHEMY_KEY = os.environ.get("ALCHEMY_POLYGON_KEY", "CkcB0ru1bUfColNdPoTLO")
ALCHEMY_URL = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"
UA = {"Content-Type": "application/json"}
W = "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68"

PARQUET_IN  = "strategy_lab/wallet_hunt/cache/0xb945945d/alchemy_transfers.parquet"
PARQUET_OUT = "strategy_lab/wallet_hunt/cache/0xb945945d/tx_taxonomy.parquet"

# Known selectors (keccak-verified or 4byte-directory-confirmed)
SELECTORS = {
    "0x765e827f": "handleOps (ERC-4337 EntryPoint)",
    "0x6a761202": "execTransaction (Gnosis Safe)",
    "0x3c2b4399": "matchOrders (NegRisk CTF Exchange, pUSD era)",
    "0x2287e350": "matchOrders (NegRiskAdapter, USDC.e era)",
    "0x72ce4275": "splitPosition (CTF ConditionalTokens)",
    "0x9e7212ad": "mergePositions (CTF ConditionalTokens)",
    "0x01b7037c": "redeemPositions (CTF ConditionalTokens)",
    "0xa22cb465": "setApprovalForAll (ERC1155)",
    "0x095ea7b3": "approve (ERC20)",
}

# Key contract addresses
CONTRACTS = {
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045": "CTF ConditionalTokens",
    "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb": "pUSD token",
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC.e",
    "0xe111180000d2663c0091e4f400237545b87b996b": "NegRisk CTF Exchange",
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e": "CTF Exchange",
    "0xe3f18acc55091e2c48d883fc8c8413319d4ab7b0": "NegRiskAdapter",
    "0x84ba896235059fe27727eaa2695a9f99220d9a7e": "Custom EntryPoint / AccountFactory",
    "0x0000000071727De22E5E9d8BAf0edAc6f37da032": "ERC-4337 EntryPoint v0.6 (canonical)",
    "0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0": "Polymarket merge/relay contract",
    "0xada100874d00e3331d00f2007a9c336a65009718": "Polymarket merge helper v2",
}


def rpc(method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(ALCHEMY_URL, headers=UA, json=body, timeout=30)
    return r.json().get("result")


def classify_tx_flags(df):
    """Vectorized tx classification using transfer composition."""
    df2 = df[["tx_hash", "from", "to", "category", "asset"]].copy()
    df2["w_pusd_out"] = ((df2["from"] == W) & (df2["asset"] == "pUSD")).astype(int)
    df2["w_pusd_in"]  = ((df2["to"]   == W) & (df2["asset"] == "pUSD")).astype(int)
    df2["w_1155_in"]  = ((df2["to"]   == W) & (df2["category"] == "erc1155")).astype(int)
    df2["w_1155_out"] = ((df2["from"] == W) & (df2["category"] == "erc1155")).astype(int)
    df2["w_usdc_in"]  = ((df2["to"]   == W) & (df2["asset"] == "USDCE")).astype(int)
    df2["w_usdc_out"] = ((df2["from"] == W) & (df2["asset"] == "USDCE")).astype(int)
    df2["has_mint"]   = (df2["from"] == "0x0000000000000000000000000000000000000000").astype(int)
    df2["has_burn"]   = (df2["to"]   == "0x0000000000000000000000000000000000000000").astype(int)

    flags = df2.groupby("tx_hash")[
        ["w_pusd_out", "w_pusd_in", "w_1155_in", "w_1155_out",
         "w_usdc_in", "w_usdc_out", "has_mint", "has_burn"]
    ].sum()
    flags = (flags > 0).astype(int)

    def classify(row):
        # from 0x0 = ConditionalTokens mints pUSD to wallet = mergePositions result
        if row.has_mint:
            return "MERGE"
        # to 0x0 = wallet burns ERC1155 = redeemPositions
        if row.has_burn:
            return "REDEEM"
        # wallet sends pUSD, receives ERC1155 = CLOB BUY fill (pUSD era).
        # NOTE: composition does NOT determine maker/taker side — OrderFilled
        # receipt logs show ~63% of these are MAKER fills (resting bids).
        if row.w_pusd_out and row.w_1155_in:
            return "CLOB_BUY"
        # wallet sends USDC.e, receives ERC1155 = CLOB BUY fill (USDC.e era, pre-Apr28)
        if row.w_usdc_out and row.w_1155_in:
            return "CLOB_BUY_EARLY"
        # wallet sends ERC1155 OUT + receives USDC.e = NegRisk-era paired
        # redemption (adapter path pays from the 0x05cd9922 vault, no 0x0 burn)
        if row.w_usdc_in and row.w_1155_out:
            return "NEGRISK_REDEEM"
        # wallet receives USDC.e without 1155 = deposit/withdrawal
        if row.w_usdc_in and not row.w_1155_in:
            return "USDC_IN"
        # wallet receives pUSD only = pUSD deposit
        if row.w_pusd_in and not row.w_1155_in and not row.w_1155_out:
            return "PUSD_IN_ONLY"
        return "OTHER"

    flags["cls"] = flags.apply(classify, axis=1)
    return flags


def check_wallet_type():
    """Verify b945 is Gnosis Safe 1.3.0."""
    code = rpc("eth_getCode", [W, "latest"])
    is_contract = bool(code and len(code) > 4)
    impl_slot0 = rpc("eth_getStorageAt", [W, "0x0", "latest"])
    version = rpc("eth_call", [{"to": W, "data": "0xffa1ad74"}, "latest"])
    return {
        "is_contract": is_contract,
        "code_len_bytes": (len(code) - 2) // 2 if code else 0,
        "implementation_addr": impl_slot0,
        "version_raw": version,
    }


def sample_calldata(flags, n=5):
    """Fetch calldata selector for n txs per class."""
    results = {}
    for cls in flags["cls"].unique():
        cls_txs = flags[flags["cls"] == cls].index.tolist()[:n]
        sels = {}
        for tx_hash in cls_txs:
            tx = rpc("eth_getTransactionByHash", [tx_hash])
            if tx:
                inp = tx.get("input", "")
                sel = inp[:10]
                to = tx.get("to", "")
                frm = tx.get("from", "")
                sels[tx_hash] = {"selector": sel, "to": to, "from": frm}
        results[cls] = sels
    return results


def build_taxonomy_table(df, flags):
    """Build summary taxonomy dataframe."""
    df["cls"] = df["tx_hash"].map(flags["cls"])
    df["ts"] = pd.to_datetime(df["ts"])

    rows = []
    for cls in ["CLOB_BUY", "CLOB_BUY_EARLY", "MERGE", "REDEEM", "NEGRISK_REDEEM",
                "USDC_IN", "PUSD_IN_ONLY", "OTHER"]:
        sub = df[df["cls"] == cls]
        n_txs = flags[flags["cls"] == cls].shape[0]

        # Volume
        if cls == "CLOB_BUY":
            vol_spent = sub[(sub["from"] == W) & (sub["asset"] == "pUSD")]["value"].sum()
            vol_rcvd = 0
            shares = sub[(sub["to"] == W) & (sub["category"] == "erc1155")]["value"].sum()
        elif cls == "CLOB_BUY_EARLY":
            vol_spent = sub[(sub["from"] == W) & (sub["asset"] == "USDCE")]["value"].sum()
            vol_rcvd = 0
            shares = sub[(sub["to"] == W) & (sub["category"] == "erc1155")]["value"].sum()
        elif cls == "MERGE":
            vol_spent = 0
            vol_rcvd = sub[(sub["to"] == W) & (sub["asset"] == "pUSD")]["value"].sum()
            shares = sub[(sub["from"] == W) & (sub["category"] == "erc1155")]["value"].sum()
        elif cls in ("REDEEM", "NEGRISK_REDEEM"):
            vol_spent = 0
            vol_rcvd = sub[(sub["to"] == W) & (sub["category"] == "erc20")]["value"].sum()
            shares = sub[(sub["from"] == W) & (sub["category"] == "erc1155")]["value"].sum()
        else:
            vol_spent = 0
            vol_rcvd = sub[sub["to"] == W]["value"].sum()
            shares = 0

        rows.append({
            "class": cls,
            "n_txs": n_txs,
            "n_transfers": len(sub),
            "vol_spent_usd": round(vol_spent, 2),
            "vol_received_usd": round(vol_rcvd, 2),
            "shares": round(shares, 2),
            "date_start": str(sub["ts"].min().date()) if len(sub) else "",
            "date_end": str(sub["ts"].max().date()) if len(sub) else "",
        })

    return pd.DataFrame(rows)


CACHE = "strategy_lab/wallet_hunt/cache/0xb945945d"

# CTFExchange OrderFilled event topic0 (keccak256 of ABI signature)
# NegRisk CTF Exchange (pUSD era, 0xe111): 0xd543adfd... (verified from receipts)
# CTF Exchange (USDC.e era, 0x4bfb):       0xd0a08e8c... (verified from receipts)
TOPIC0_PUSD  = "0xd543adfd9f5fb4a96427e5ebfb1fa3e12fd4e04c97ea1bb01d4bd8e6ce6ddedc"
TOPIC0_USDC  = "0xd0a08e8c9d1d63e1e24a6d9dd5a7badc50a0a41cc45699671562e07af2ffa91e"
NEGR_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
CTF_EXCHANGE  = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"


def merge_timing():
    """Map each MERGE tx to its slug window and compute merge_time - slot_end.

    Method: loads MERGE txs from alchemy_transfers.parquet, joins to
    token_lookup_ext.parquet and fill_tape_full.parquet for token→slug mapping,
    then compares block timestamp to [slot_start, slot_start+900].

    Results show 100% post-resolution (median +43s after slot end).

    Output: cache/0xb945945d/merge_timing.parquet
    """
    import numpy as np

    df = pd.read_parquet(f"{CACHE}/alchemy_transfers.parquet")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # MERGE txs: from=0x0 (CTF minting pUSD from paired ERC1155 burn)
    ZERO = "0x0000000000000000000000000000000000000000"
    merge_txs = set(df[df["from"] == ZERO]["tx_hash"].unique())

    # ERC1155 burned in MERGE (sent OUT from b945 before the pUSD mint)
    burns = df[
        (df["tx_hash"].isin(merge_txs)) &
        (df["category"] == "erc1155") &
        (df["from"] == W)
    ][["tx_hash", "ts", "tokenId", "value"]].copy()
    burns["token_id_dec"] = burns["tokenId"].apply(
        lambda x: int(x, 16) if isinstance(x, str) and x.startswith("0x") else int(x)
    )

    # Token → slug mapping: token_lookup_ext first, then fill_tape_full
    def load_token_map():
        rows = {}
        try:
            tl = pd.read_parquet(f"{CACHE}/token_lookup_ext.parquet")
            id_col = [c for c in tl.columns if "token" in c.lower() and "id" in c.lower()][0]
            slug_col = [c for c in tl.columns if "slug" in c.lower()][0]
            for _, r in tl.iterrows():
                rows[int(r[id_col])] = r[slug_col]
        except Exception:
            pass
        try:
            ft = pd.read_parquet(f"{CACHE}/fill_tape_full.parquet")
            id_col2 = [c for c in ft.columns if "token" in c.lower() and "id" in c.lower()]
            slug_col2 = [c for c in ft.columns if "slug" in c.lower()]
            if id_col2 and slug_col2:
                for _, r in ft[[id_col2[0], slug_col2[0]]].drop_duplicates().iterrows():
                    tid = r[id_col2[0]]
                    if tid and not pd.isna(tid):
                        rows.setdefault(int(tid), r[slug_col2[0]])
        except Exception:
            pass
        return rows

    token_map = load_token_map()
    burns["slug"] = burns["token_id_dec"].map(token_map)
    burns = burns.dropna(subset=["slug"])

    # slot_start = int(slug.rsplit("-", 1)[1])
    burns["slot_start"] = burns["slug"].apply(lambda s: int(s.rsplit("-", 1)[1]))
    burns["win_s"] = 900  # 15m markets
    burns["dt_start"] = (burns["ts"].astype("int64") // 10**9) - burns["slot_start"]
    burns["dt_end"]   = burns["dt_start"] - burns["win_s"]  # lag after slot_END

    out = burns[["tx_hash", "ts", "slug", "value", "slot_start", "win_s", "dt_start", "dt_end"]]
    out.to_parquet(f"{CACHE}/merge_timing.parquet", index=False)

    total = len(out)
    pre  = (out["dt_start"] < 0).sum()
    mid  = ((out["dt_start"] >= 0) & (out["dt_end"] < 0)).sum()
    post = (out["dt_end"] >= 0).sum()
    pcts = [5, 25, 50, 75, 95]
    post_lags = out[out["dt_end"] >= 0]["dt_end"]
    lag_pcts = np.percentile(post_lags, pcts)
    print(f"MERGE timing (n={total} legs mapped / {burns['tx_hash'].nunique()} txs):")
    print(f"  PRE-window:       {pre:4d} ({100*pre/total:.1f}%)")
    print(f"  MID-window:       {mid:4d} ({100*mid/total:.1f}%)")
    print(f"  POST-resolution:  {post:4d} ({100*post/total:.1f}%)")
    for p, v in zip(pcts, lag_pcts):
        print(f"  p{p} lag after slot_end: +{v:.0f}s")
    print(f"  max: +{post_lags.max():.0f}s ({post_lags.max()/86400:.1f}d)")
    print(f"Saved: {CACHE}/merge_timing.parquet")
    return out


def orderfilled_maker_split(n_pusd=600, n_early=100):
    """Parse OrderFilled receipt logs for a stratified sample of CLOB_BUY txs.

    For each sampled fill tx, fetches the tx receipt and scans logs for the
    OrderFilled event. Determines b945's role:
      taker_addr == exchange contract  → b945's order was TAKER (crossed)
      taker_addr != exchange contract  → b945's resting order was hit (MAKER)

    Samples n_pusd txs from CLOB_BUY (pUSD era) and n_early from CLOB_BUY_EARLY
    (USDC.e era), stratified uniformly over time.

    Output: cache/0xb945945d/orderfilled_sample{,_early}.parquet
    Returns: (pusd_df, early_df)
    """
    import math

    df = pd.read_parquet(f"{CACHE}/alchemy_transfers.parquet")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    flags = classify_tx_flags(df)

    def _fetch_receipt_role(tx_hash, expected_topic0, exchange_addr):
        """Fetch receipt, find OrderFilled log, return maker/taker role."""
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        if not receipt:
            return None
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if not topics:
                continue
            if topics[0].lower() != expected_topic0.lower():
                continue
            # OrderFilled(bytes32 orderId, address maker, address taker, ...)
            # topic1=orderId (indexed), topic2=maker (indexed), topic3=taker (indexed)
            if len(topics) < 4:
                continue
            maker_addr = "0x" + topics[2][-40:]
            taker_addr = "0x" + topics[3][-40:]
            data_hex = log.get("data", "0x")[2:]
            # data: makerAssetFilled, takerAssetFilled, makerFee, takerFee, fee (5×uint256)
            vals = [int(data_hex[i*64:(i+1)*64], 16) / 1e6
                    for i in range(min(5, len(data_hex) // 64))]
            maker_asset_is_cash = maker_addr.lower() == W.lower()
            role = "MAKER" if taker_addr.lower() != exchange_addr.lower() else "TAKER"
            return {
                "tx_hash": tx_hash,
                "contract": log.get("address", ""),
                "taker_addr": taker_addr,
                "maker_asset_is_cash": maker_asset_is_cash,
                "maker_amt": vals[0] if len(vals) > 0 else None,
                "taker_amt": vals[1] if len(vals) > 1 else None,
                "fee": vals[4] if len(vals) > 4 else 0.0,
                "b945_role": role,
                "b945_dir": "BUY" if maker_asset_is_cash else "SELL",
                "usd": vals[0] if maker_asset_is_cash else vals[1],
            }
        return None

    def sample_and_fetch(cls_name, topic0, exchange, n):
        cls_hashes = flags[flags["cls"] == cls_name].index.tolist()
        step = max(1, len(cls_hashes) // n)
        sampled = cls_hashes[::step][:n]
        rows = []
        ts_map = df.groupby("tx_hash")["ts"].first()
        for i, tx_hash in enumerate(sampled):
            if i % 50 == 0:
                print(f"  {cls_name}: {i}/{len(sampled)} ...")
            result = _fetch_receipt_role(tx_hash, topic0, exchange)
            if result:
                result["ts"] = ts_map.get(tx_hash)
                result["cls"] = cls_name
                rows.append(result)
        return pd.DataFrame(rows)

    print(f"Fetching pUSD era sample (n={n_pusd} CLOB_BUY)...")
    pusd_df = sample_and_fetch("CLOB_BUY", TOPIC0_PUSD, NEGR_EXCHANGE, n_pusd)
    if len(pusd_df):
        # Reorder columns
        cols = ["tx_hash", "cls", "ts", "contract", "taker_addr",
                "maker_asset_is_cash", "maker_amt", "taker_amt", "fee",
                "b945_role", "b945_dir", "usd"]
        pusd_df = pusd_df[[c for c in cols if c in pusd_df.columns]]
        pusd_df.to_parquet(f"{CACHE}/orderfilled_sample.parquet", index=False)
        n = len(pusd_df)
        maker_n = (pusd_df["b945_role"] == "MAKER").sum()
        taker_n = (pusd_df["b945_role"] == "TAKER").sum()
        import math
        p = maker_n / n
        ci = 1.96 * math.sqrt(p * (1 - p) / n)
        print(f"pUSD MAKER: {maker_n}/{n} = {100*p:.1f}% ± {100*ci:.1f}%")
        print(f"Saved: {CACHE}/orderfilled_sample.parquet")

    print(f"Fetching USDC.e era sample (n={n_early} CLOB_BUY_EARLY)...")
    early_df = sample_and_fetch("CLOB_BUY_EARLY", TOPIC0_USDC, CTF_EXCHANGE, n_early)
    if len(early_df):
        # Early era uses simpler column set
        early_df = early_df.rename(columns={"b945_role": "role", "b945_dir": "dir"})
        early_df = early_df[["tx_hash", "ts", "contract", "taker_addr",
                              "maker_amt", "taker_amt", "fee", "role", "dir", "usd"]].copy()
        early_df.to_parquet(f"{CACHE}/orderfilled_sample_early.parquet", index=False)
        n = len(early_df)
        maker_n = (early_df["role"] == "MAKER").sum()
        taker_n = (early_df["role"] == "TAKER").sum()
        p = maker_n / n
        ci = 1.96 * math.sqrt(p * (1 - p) / n)
        print(f"USDC.e MAKER: {maker_n}/{n} = {100*p:.1f}% ± {100*ci:.1f}%")
        print(f"Saved: {CACHE}/orderfilled_sample_early.parquet")

    return pusd_df, early_df


if __name__ == "__main__":
    print("Loading transfers parquet...")
    df = pd.read_parquet(PARQUET_IN)
    print(f"  {len(df):,} rows, {df['tx_hash'].nunique():,} unique txs")

    print("Classifying txs...")
    flags = classify_tx_flags(df)
    print("Class counts:")
    print(flags["cls"].value_counts().to_string())

    print("\nChecking wallet type...")
    wtype = check_wallet_type()
    print(f"  Is contract: {wtype['is_contract']}")
    print(f"  Code size: {wtype['code_len_bytes']} bytes (Gnosis Safe proxy = ~62 bytes)")
    print(f"  Implementation (slot 0): {wtype['implementation_addr']}")
    print(f"  Version raw: {wtype['version_raw']}")

    print("\nBuilding taxonomy table...")
    taxonomy = build_taxonomy_table(df, flags)
    print(taxonomy.to_string())

    taxonomy.to_parquet(PARQUET_OUT, index=False)
    print(f"\nSaved: {PARQUET_OUT}")
