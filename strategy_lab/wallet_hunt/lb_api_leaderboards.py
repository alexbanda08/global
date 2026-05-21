"""
Pull all 8 leaderboards (profit/volume × all/30d/7d/1d) serially with retries.
Find new wallets not already in our 16-wallet catalog. Show top 25 candidates.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
BASE = "http://lb-api.polymarket.com"
WINDOWS = ["all", "30d", "7d", "1d"]
TYPES = ["profit", "volume"]


def fetch_with_retry(ep: str, window: str, retries: int = 3) -> list[dict]:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/{ep}", params={"window": window}, timeout=15)
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, list):
                    return j
            last = f"status={r.status_code} text={r.text[:80]}"
        except Exception as e:
            last = str(e)
            time.sleep(0.5 * (attempt + 1))
    print(f"  FAILED {ep}/{window}: {last}")
    return []


def main():
    known = json.loads((CACHE / "_addr_map.json").read_text())
    known_full = {v.lower() for v in known.values()}

    raw = {}
    rows = []
    for ep in TYPES:
        for w in WINDOWS:
            t0 = time.time()
            arr = fetch_with_retry(ep, w)
            dt = (time.time() - t0) * 1000
            raw[f"{ep}_{w}"] = arr
            print(f"  [{len(arr):>3}] {ep}/{w}  {dt:.0f}ms")
            for rank, entry in enumerate(arr, 1):
                rows.append({
                    "type": ep,
                    "window": w,
                    "rank": rank,
                    "proxy_wallet": (entry.get("proxyWallet") or "").lower(),
                    "pseudonym": entry.get("pseudonym"),
                    "amount": entry.get("amount"),
                    "name": entry.get("name"),
                })

    (CACHE / "_lb_leaderboards_raw.json").write_text(json.dumps(raw, indent=2, default=str))
    lb_df = pd.DataFrame(rows)
    lb_df.to_csv(CACHE / "_lb_top50_combined.csv", index=False)

    print()
    print("=" * 80)
    print(f"TOTAL leaderboard rows: {len(lb_df)}, unique wallets: {lb_df['proxy_wallet'].nunique()}")
    print("=" * 80)

    # Show top 10 per window/type
    for (ep, w), grp in lb_df.groupby(["type", "window"]):
        print(f"\n--- TOP 10 {ep} / {w} ---")
        top = grp.sort_values("rank").head(10)[["rank", "pseudonym", "proxy_wallet", "amount"]]
        print(top.to_string(index=False))

    # New candidates
    new = lb_df[~lb_df["proxy_wallet"].isin(known_full)].copy()
    print()
    print("=" * 80)
    print(f"NEW WALLETS not in our catalog: {new['proxy_wallet'].nunique()}")
    print("=" * 80)

    pivot = new.pivot_table(
        index=["proxy_wallet", "pseudonym"],
        columns=["type", "window"],
        values="amount",
        aggfunc="first",
    )
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
    appear = new.groupby(["proxy_wallet", "pseudonym"]).agg(
        appearances=("rank", "count"),
        best_rank=("rank", "min"),
    ).reset_index()
    cand = appear.merge(pivot.reset_index(), on=["proxy_wallet", "pseudonym"])
    # Score: best by profit_all desc, fall back to profit_30d
    cand["score_all"] = cand.get("profit_all", 0).fillna(0) if "profit_all" in cand else 0
    cand["score_30d"] = cand.get("profit_30d", 0).fillna(0) if "profit_30d" in cand else 0
    cand = cand.sort_values(["appearances", "score_all"], ascending=[False, False])

    cand.to_csv(CACHE / "_lb_new_candidates.csv", index=False)
    show_cols = [
        "proxy_wallet", "pseudonym", "appearances", "best_rank",
        "profit_all", "profit_30d", "profit_7d", "profit_1d", "volume_all",
    ]
    show_cols = [c for c in show_cols if c in cand.columns]
    print(cand.head(25)[show_cols].to_string(index=False))


if __name__ == "__main__":
    main()
