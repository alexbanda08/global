"""
Canonical LB-API workflow:
  1. Hardcode resolved address map for all 17 known wallets
  2. Parallel-fetch /profit and /volume across windows for each
  3. Pull top-50 leaderboard for each window/type combo (8 leaderboards)
  4. Find new wallets in leaderboards not in our catalog
  5. Cross-reference + write reconciliation report

Outputs (all under strategy_lab/wallet_hunt/cache/):
  _addr_map.json
  _lb_known_wallets_table.csv
  _lb_top50_combined.csv  (deduplicated leaderboard union)
  _lb_new_candidates.csv  (top wallets we haven't decoded)
  _lb_leaderboards_raw.json
"""
from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
BASE = "http://lb-api.polymarket.com"

ADDR_MAP = {
    "0x04b6d7e9": "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
    "0x0fe40e88": "0x0fe40e887acbd0022f89d996acce26ab428501b7",
    "0x3e6bfd2f": "0x3e6bfd2f791a10cf2404e09542c2a82e3e7b6d63",
    "0x7dfc8aa2": "0x7dfc8aa22f2d4d6f9cbf55cf86682a4d2477f54e",
    "0x7f599984": "0x7f59998477864871448e312011fa5cc6b210b636",
    "0x89b5cdaa": "0x89b5cdaaa4866c1e738406712012a630b4078beb",
    "0x9dae874a": "0x9dae874a2e804349e3004ccc98107799f15f97a2",
    "0xa0a50783": "0xa0a5078359dad63993a868f6d2db82d3a7b3606f",
    "0xb27bc932": "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
    "0xce25e214": "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    "0xcfb103c3": "0xcfb103c37c0234f524c632d964ed31f117b5f694",
    "0xeebde7a0": "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xeefe46de": "0xeefe46deee8da83bf67dc95b6bc8b8f73e77be43",
    "0xf247584e": "0xf247584e41117bbbe4cc06e4d2c95741792a5216",
    "0xf3cfb6a6": "0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0",
    "0xf7f0b0b1": "0xf7f0b0b1e9c0fe02ccad926916ee31aef74b912c",
}

EXPECTED_CHAIN_PER_DAY = {
    "0x04b6d7e9": 212_000,
    "0x0fe40e88": 19_000,
    "0x3e6bfd2f": 166_000,
    "0x7dfc8aa2": -7_900,
    "0x7f599984": 6_300,
    "0x89b5cdaa": 10_000,
    "0x9dae874a": 5_900,
    "0xa0a50783": 6_000,
    "0xb27bc932": 254_000,
    "0xce25e214": -295_000,
    "0xcfb103c3": -39,
    "0xeebde7a0": 344_000,
    "0xeefe46de": 94,
    "0xf7f0b0b1": 30_000,
}

WINDOWS = ["all", "30d", "7d", "1d"]
TYPES = ["profit", "volume"]


def session() -> requests.Session:
    s = requests.Session()
    s.headers["accept"] = "application/json"
    return s


def fetch_one(s: requests.Session, addr: str, endpoint: str, window: str):
    try:
        r = s.get(f"{BASE}/{endpoint}", params={"window": window, "address": addr}, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        if isinstance(j, list) and j:
            return j[0]
        return None
    except Exception as e:
        return {"_err": str(e)}


def fetch_top(s: requests.Session, endpoint: str, window: str):
    try:
        r = s.get(f"{BASE}/{endpoint}", params={"window": window}, timeout=12)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        return {"_err": str(e)}


def main():
    (CACHE / "_addr_map.json").write_text(json.dumps(ADDR_MAP, indent=2))

    s = session()

    # 1. Sweep known wallets — parallel
    tasks: list[tuple[str, str, str]] = []
    for short, full in ADDR_MAP.items():
        for ep in TYPES:
            for w in WINDOWS:
                tasks.append((short, full, ep, w))  # type: ignore[arg-type]

    rows: dict[str, dict] = {short: {"short": short, "full": full} for short, full in ADDR_MAP.items()}
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {
            ex.submit(fetch_one, s, full, ep, w): (short, ep, w)
            for short, full, ep, w in tasks
        }
        for fut in as_completed(futs):
            short, ep, w = futs[fut]
            res = fut.result()
            amt = (res or {}).get("amount") if isinstance(res, dict) else None
            rows[short][f"{ep}_{w}"] = amt
            if ep == "profit" and w == "all" and res:
                rows[short]["pseudonym"] = res.get("pseudonym")

    df = pd.DataFrame(rows.values())
    df["chain_per_day"] = df["short"].map(EXPECTED_CHAIN_PER_DAY)
    df["lb_per_day_30d"] = df["profit_30d"] / 30
    df["lb_per_day_7d"]  = df["profit_7d"] / 7
    df["overestimate_ratio_30d"] = df["chain_per_day"] / df["lb_per_day_30d"].replace(0, pd.NA)
    df = df.sort_values("profit_all", ascending=False, na_position="last")

    out_known = CACHE / "_lb_known_wallets_table.csv"
    df.to_csv(out_known, index=False)
    cols_show = [
        "short", "pseudonym", "profit_all", "profit_30d", "profit_7d", "profit_1d",
        "volume_all", "chain_per_day", "lb_per_day_30d", "overestimate_ratio_30d",
    ]
    print("=" * 80)
    print("KNOWN WALLETS RECONCILIATION (chain-decoded vs LB-API)")
    print("=" * 80)
    print(df[cols_show].to_string(index=False))
    print(f"\nSaved: {out_known}")

    # 2. Leaderboards (8 calls)
    print()
    print("=" * 80)
    print("LEADERBOARDS — top 50 per (type, window)")
    print("=" * 80)
    raw_lb = {}
    leader_rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {
            ex.submit(fetch_top, s, ep, w): (ep, w)
            for ep in TYPES
            for w in WINDOWS
        }
        for fut in as_completed(futs):
            ep, w = futs[fut]
            arr = fut.result()
            if not isinstance(arr, list):
                continue
            raw_lb[f"{ep}_{w}"] = arr
            for rank, entry in enumerate(arr, 1):
                leader_rows.append({
                    "type": ep,
                    "window": w,
                    "rank": rank,
                    "proxy_wallet": entry.get("proxyWallet"),
                    "pseudonym": entry.get("pseudonym"),
                    "amount": entry.get("amount"),
                })

    (CACHE / "_lb_leaderboards_raw.json").write_text(json.dumps(raw_lb, default=str, indent=2))

    lb_df = pd.DataFrame(leader_rows)
    lb_df.to_csv(CACHE / "_lb_top50_combined.csv", index=False)

    # Show top 10 per (type, window)
    for (ep, w), group in lb_df.groupby(["type", "window"]):
        print(f"\n--- TOP 10 {ep} / {w} ---")
        top = group.sort_values("rank").head(10)[["rank", "pseudonym", "proxy_wallet", "amount"]]
        print(top.to_string(index=False))

    # 3. Find NEW wallets — appearing in any leaderboard, not in our catalog
    known_full = {v.lower() for v in ADDR_MAP.values()}
    lb_df["proxy_wallet_lc"] = lb_df["proxy_wallet"].str.lower()
    new = lb_df[~lb_df["proxy_wallet_lc"].isin(known_full)]
    # Aggregate per wallet to find best candidates
    agg = new.groupby(["proxy_wallet_lc", "pseudonym"]).agg(
        appearances=("rank", "count"),
        best_rank=("rank", "min"),
        max_amount=("amount", "max"),
    ).reset_index().sort_values(["best_rank", "max_amount"], ascending=[True, False])

    # Add per-window/type detail for top candidates
    pivot = new.pivot_table(
        index=["proxy_wallet_lc", "pseudonym"],
        columns=["type", "window"],
        values="amount",
        aggfunc="first",
    )
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
    candidates = agg.merge(pivot.reset_index(), on=["proxy_wallet_lc", "pseudonym"])
    candidates.to_csv(CACHE / "_lb_new_candidates.csv", index=False)

    print()
    print("=" * 80)
    print(f"NEW WALLET CANDIDATES (in leaderboards, NOT in our catalog) — {len(candidates)} unique")
    print("=" * 80)
    show_cols = [
        "proxy_wallet_lc", "pseudonym", "appearances", "best_rank",
        "profit_all", "profit_30d", "profit_1d", "volume_all",
    ]
    show_cols = [c for c in show_cols if c in candidates.columns]
    print(candidates.head(25)[show_cols].to_string(index=False))


if __name__ == "__main__":
    main()
