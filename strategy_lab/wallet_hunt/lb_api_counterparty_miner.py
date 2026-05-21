"""
Mine the most-active counterparties from our deeply-decoded wallets (0xeebde7a0
the hybrid maker+taker, 0x04b6d7e9 the pure pair-arb maker). These are by
definition crypto-updown active traders. Score them by:
  - # trades crossed with our wallet
  - LB-API /profit (all, 30d)
  - LB-API /volume (all, 30d)
  - whether they're a known counterparty in our existing catalog

Output: cache/_lb_counterparties_scored.csv
"""
from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
LB = "http://lb-api.polymarket.com"
DATA = "https://data-api.polymarket.com"


def known_set() -> set[str]:
    amap = json.loads((CACHE / "_addr_map.json").read_text())
    s = {v.lower() for v in amap.values()}
    # Also exclude exchange/relay contracts
    s.add("0xe111180000d2663c0091e4f400237545b87b996b")
    s.add("0xc5d563a36ae78145c45a50134d48a1215220f80a")  # NegRiskCtfExchange
    s.add("0x84ba896235059fe27727eaa2695a9f99220d9a7e")  # batch-merge router
    s.add("0xd91e80cf2e7be2e162c6513ced06f1dd0da35296")  # NegRiskAdapter
    s.add("0x4d97dcd97ec945f40cf65f87097ace5ea0476045")  # CTF
    return {a.lower() for a in s}


def harvest_counterparties() -> pd.DataFrame:
    """Pool counterparties from every decoded wallet's trades_chain.parquet."""
    rows = []
    seen = known_set()
    for wallet_dir in CACHE.iterdir():
        if not wallet_dir.is_dir() or not wallet_dir.name.startswith("0x"):
            continue
        f = wallet_dir / "trades_chain.parquet"
        if not f.exists():
            continue
        try:
            df = pd.read_parquet(f, columns=["maker", "taker", "wallet_is_maker", "wallet_is_taker", "usdc_notional"])
        except Exception:
            continue
        if df.empty:
            continue
        # The counterparty is whichever leg is NOT our wallet
        df["counterparty"] = df.apply(
            lambda r: r["taker"] if r.get("wallet_is_maker") else r["maker"],
            axis=1,
        )
        df["counterparty"] = df["counterparty"].astype(str).str.lower()
        # Aggregate per counterparty for this wallet
        agg = df.groupby("counterparty").agg(
            n_crosses=("counterparty", "count"),
            sum_usdc=("usdc_notional", "sum"),
        ).reset_index()
        agg["our_wallet_short"] = wallet_dir.name
        rows.append(agg)

    if not rows:
        return pd.DataFrame()
    combined = pd.concat(rows, ignore_index=True)
    grand = combined.groupby("counterparty").agg(
        total_crosses=("n_crosses", "sum"),
        total_usdc=("sum_usdc", "sum"),
        n_our_wallets_crossed=("our_wallet_short", "nunique"),
        crossed_with=("our_wallet_short", lambda s: ",".join(sorted(set(s)))),
    ).reset_index()
    grand["in_known_set"] = grand["counterparty"].isin(known_set())
    grand = grand.sort_values("total_crosses", ascending=False)
    return grand


def lb_fetch_one(addr: str, endpoint: str, window: str):
    try:
        r = requests.get(f"{LB}/{endpoint}",
                         params={"window": window, "address": addr}, timeout=8)
        if r.status_code != 200:
            return None
        j = r.json()
        if isinstance(j, list) and j:
            return j[0]
    except Exception:
        return None
    return None


def enrich_lb(top: pd.DataFrame, max_workers: int = 16) -> pd.DataFrame:
    """Hit LB-API for top N counterparties in parallel."""
    work = []
    for _, r in top.iterrows():
        addr = r["counterparty"]
        for ep in ("profit", "volume"):
            for w in ("all", "30d", "7d", "1d"):
                work.append((addr, ep, w))

    results: dict[tuple, dict | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(lb_fetch_one, a, e, w): (a, e, w) for a, e, w in work}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()

    rows = []
    for _, r in top.iterrows():
        addr = r["counterparty"]
        prof_all = results.get((addr, "profit", "all")) or {}
        prof_30d = results.get((addr, "profit", "30d")) or {}
        prof_7d = results.get((addr, "profit", "7d")) or {}
        prof_1d = results.get((addr, "profit", "1d")) or {}
        vol_all = results.get((addr, "volume", "all")) or {}
        vol_30d = results.get((addr, "volume", "30d")) or {}
        rows.append({
            "counterparty": addr,
            "pseudonym": prof_all.get("pseudonym") or prof_30d.get("pseudonym") or "",
            "total_crosses": r["total_crosses"],
            "total_usdc": r["total_usdc"],
            "n_our_wallets_crossed": r["n_our_wallets_crossed"],
            "crossed_with": r["crossed_with"],
            "in_known_set": r["in_known_set"],
            "lb_profit_all": prof_all.get("amount"),
            "lb_profit_30d": prof_30d.get("amount"),
            "lb_profit_7d": prof_7d.get("amount"),
            "lb_profit_1d": prof_1d.get("amount"),
            "lb_volume_all": vol_all.get("amount"),
            "lb_volume_30d": vol_30d.get("amount"),
        })
    return pd.DataFrame(rows)


def main():
    print("Harvesting counterparties from decoded wallets...")
    grand = harvest_counterparties()
    print(f"  unique counterparties: {len(grand)}")
    print(f"  in known set: {grand['in_known_set'].sum()}")
    print()
    print("Top 30 unknown counterparties by # crosses:")
    unknown = grand[~grand["in_known_set"]].head(30)
    print(unknown[["counterparty", "total_crosses", "total_usdc", "n_our_wallets_crossed", "crossed_with"]].to_string(index=False))

    print("\nHitting LB-API for top 100 unknown counterparties...")
    enriched = enrich_lb(grand[~grand["in_known_set"]].head(100))
    enriched = enriched.sort_values("lb_profit_30d", ascending=False, na_position="last")

    enriched.to_csv(CACHE / "_lb_counterparties_scored.csv", index=False)

    show = enriched[enriched["lb_profit_30d"].notna()].head(20)
    print()
    print("=" * 80)
    print("TOP UNKNOWN COUNTERPARTIES with LB-API profit data")
    print("=" * 80)
    cols = ["pseudonym", "counterparty", "total_crosses", "lb_profit_all",
            "lb_profit_30d", "lb_profit_7d", "lb_profit_1d", "lb_volume_30d", "crossed_with"]
    cols = [c for c in cols if c in show.columns]
    print(show[cols].to_string(index=False))

    print()
    print(f"Saved: {CACHE / '_lb_counterparties_scored.csv'}")


if __name__ == "__main__":
    main()
