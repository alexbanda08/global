"""Master wallet catalog — fuses every analysis output into ONE table.

Per wallet, collects from existing cache artifacts:
  - Genesis: cache/_first_deposit.csv
  - Cash PnL: cache/_cash_pnl_summary.csv
  - Trigger fingerprint: cache/<short>/fires_decoded.parquet
  - Volume: alchemy_transfers.parquet row counts

Then runs a strategy classifier (mint_and_sell / directional_clob_taker /
mixed / unknown) using the trigger fingerprint heuristics.

Writes to cache/_master_catalog.csv + a markdown summary.

Usage:  py -3 -X utf8 strategy_lab/wallet_hunt/_master_catalog.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"

# CTF and exchange contracts
CTF_CONTRACT = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
NEGRISK_MATCHER = "0xe111180000d2663c0091e4f400237545b87b996b"
CTF_EXCHANGE_OLD = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
NEGRISK_CTF_EXCHANGE = "0xc5d563a36ae78145c45a50134d48a1215220f80a"

# Target wallets (operator-provided 2026-05-17, deduped)
TARGET_SHORTS = [
    "0x7f599984",
    "0xb27bc932",
    "0xa0a50783",
    "0x3e6bfd2f",
    "0xeefe46de",
    "0x0fe40e88",
    "0x9dae874a",
    "0xcfb103c3",
    "0x89b5cdaa",
]


def fingerprint(short: str) -> dict:
    """Per-wallet trigger fingerprint from fires_decoded.parquet + alchemy_transfers."""
    out = {"short": short}

    # 1. Transfer-level activity (raw alchemy)
    p_tr = CACHE / short / "alchemy_transfers.parquet"
    if not p_tr.exists():
        out["error"] = "no transfers"
        return out
    tr = pd.read_parquet(p_tr)
    if len(tr) == 0:
        out["error"] = "empty transfers"
        return out

    # On-chain mint counter: ERC1155 transfers FROM 0x0 (= CTF splitPosition mint)
    if "asset" not in tr.columns or "category" not in tr.columns:
        out["error"] = "missing schema"
        return out
    erc1155 = tr[tr["category"] == "erc1155"].copy()
    n_mints_onchain = int(
        ((erc1155["direction"] == "to")
         & (erc1155["from"].str.lower() == "0x0000000000000000000000000000000000000000")
        ).sum()
    )
    n_burns_onchain = int(
        ((erc1155["direction"] == "from")
         & (erc1155["to"].str.lower() == "0x0000000000000000000000000000000000000000")
        ).sum()
    )

    # USDC flow to/from CTF (mint cost / merge recovery)
    usdc = tr[tr.asset.isin({"USDC", "USDCE", "USDC.E", "PUSD", "USDT"})].copy()
    usdc_to_ctf = float(
        usdc[(usdc.direction == "from")
             & (usdc["to"].str.lower() == CTF_CONTRACT)].value.sum()
    )
    usdc_from_ctf = float(
        usdc[(usdc.direction == "to")
             & (usdc["from"].str.lower() == CTF_CONTRACT)].value.sum()
    )

    # Detect non-up-down trader: erc1155 transfers exist but none match up-down lookup
    updown_share = float("nan")
    n_erc1155 = len(erc1155)
    if n_erc1155 > 0:
        lookup_p = CACHE / "_token_lookup.parquet"
        if lookup_p.exists():
            lookup = pd.read_parquet(lookup_p)
            ud_assets = set(
                lookup[lookup.slug.str.contains("updown", na=False)].asset_id.astype(str)
            )
            updown_share = float(
                erc1155.asset.astype(str).isin(ud_assets).sum() / n_erc1155
            )

    out.update({
        "n_transfers": len(tr),
        "n_erc1155": n_erc1155,
        "updown_share_of_erc1155": round(updown_share, 4) if not np.isnan(updown_share) else float("nan"),
        "n_mints_onchain": n_mints_onchain,
        "n_burns_onchain": n_burns_onchain,
        "usdc_to_ctf": round(usdc_to_ctf, 2),
        "usdc_from_ctf": round(usdc_from_ctf, 2),
    })

    # 2. Fires_decoded.parquet
    p_fd = CACHE / short / "fires_decoded.parquet"
    if p_fd.exists():
        fd = pd.read_parquet(p_fd)
        n = len(fd)
        if n > 0:
            n_buy = int((fd["wallet_side"] == "BUY").sum())
            n_sell = int((fd["wallet_side"] == "SELL").sum())
            buy_pct = n_buy / n
            sum_asks_mean = float(fd["sum_asks"].mean()) if "sum_asks" in fd.columns else float("nan")
            sum_asks_med = float(fd["sum_asks"].median()) if "sum_asks" in fd.columns else float("nan")
            own_ask_mean = float(fd["own_ask"].mean()) if "own_ask" in fd.columns else float("nan")
            own_bid_mean = float(fd["own_bid"].mean()) if "own_bid" in fd.columns else float("nan")
            spread_med = float(fd["own_spread"].median()) if "own_spread" in fd.columns else float("nan")
            offset_mean = float(fd["offset_from_slot_start"].mean()) if "offset_from_slot_start" in fd.columns else float("nan")
            # Slug-asset mix
            asset_mix = {}
            if "asset" in fd.columns:
                asset_mix = fd["asset"].value_counts(normalize=True).round(3).to_dict()
            out.update({
                "fires_enriched": n,
                "n_buy": n_buy,
                "n_sell": n_sell,
                "buy_pct": round(buy_pct, 3),
                "sum_asks_mean": round(sum_asks_mean, 4),
                "sum_asks_med": round(sum_asks_med, 4),
                "own_ask_mean": round(own_ask_mean, 4),
                "own_bid_mean": round(own_bid_mean, 4),
                "spread_med": round(spread_med, 4),
                "offset_s_mean": round(offset_mean, 1),
                "asset_mix": str(asset_mix),
            })

    return out


def classify(row: dict) -> str:
    """Apply heuristic strategy labels."""
    if "error" in row:
        return "no_data"

    # Off-market check: if erc1155 trades exist but NONE are up-down tokens,
    # this wallet trades sports/elections/news markets, not up-down crypto.
    # CAVEAT: _token_lookup.parquet can be stale; if decode_triggers ran
    # successfully (fires_enriched > 100), the wallet DOES trade up-down.
    ud_share = row.get("updown_share_of_erc1155", float("nan"))
    n_erc1155 = row.get("n_erc1155", 0) or 0
    fires_enriched_raw = row.get("fires_enriched", 0)
    fires_enriched = (0 if fires_enriched_raw is None or
                      (isinstance(fires_enriched_raw, float) and np.isnan(fires_enriched_raw))
                      else int(fires_enriched_raw))
    if (fires_enriched < 50  # decode_triggers found ≤ a few up-down trades
        and not np.isnan(ud_share) and n_erc1155 > 100 and ud_share < 0.05):
        return "non_updown_polymarket_trader"

    # Did this wallet do on-chain minting?
    minting_ratio = row.get("n_mints_onchain", 0) / max(row.get("n_transfers", 1), 1)
    is_minter = minting_ratio > 0.001 or row.get("usdc_to_ctf", 0) > 100

    buy_pct = row.get("buy_pct", float("nan"))
    sum_asks = row.get("sum_asks_mean", float("nan"))

    if is_minter and not np.isnan(buy_pct) and buy_pct < 0.4:
        # Mints AND sells more than buys → classic mint-and-sell maker
        return "mint_and_sell_maker"

    if is_minter and not np.isnan(buy_pct) and buy_pct < 0.7:
        return "mint_and_sell_hybrid"

    if (not is_minter) and not np.isnan(buy_pct) and buy_pct > 0.7:
        if sum_asks and sum_asks > 1.005:
            return "directional_clob_taker_at_mispricing"
        return "directional_clob_taker"

    if (not is_minter) and not np.isnan(buy_pct) and 0.55 < buy_pct < 0.75:
        return "mixed_clob_taker_seller"

    return "unknown"


def main():
    # 1. Build fingerprint rows
    rows = []
    for s in TARGET_SHORTS:
        rows.append(fingerprint(s))

    # 2. Join with genesis + cash_pnl summaries
    fp = pd.DataFrame(rows).set_index("short")

    genesis_csv = CACHE / "_first_deposit.csv"
    if genesis_csv.exists():
        gn = pd.read_csv(genesis_csv).set_index("short")[
            ["first_external_usd", "first_external_ts", "first_external_from",
             "first_any_usd", "first_any_asset"]
        ]
        fp = fp.join(gn, how="left")

    pnl_csv = CACHE / "_cash_pnl_summary.csv"
    if pnl_csv.exists():
        pn = pd.read_csv(pnl_csv).set_index("short")[
            ["span_days", "trading_in", "trading_out", "net_trading_pnl",
             "capital_in", "capital_out", "net_capital", "net_cash_pnl",
             "total_pnl", "total_pnl_per_day", "n_days_positive",
             "n_days_negative", "n_open_positions", "open_position_value"]
        ]
        fp = fp.join(pn, how="left")

    # 3. Classify
    fp["strategy"] = fp.apply(lambda r: classify(r.to_dict()), axis=1)

    # 4. Reorder columns
    col_order = [
        "strategy", "total_pnl", "total_pnl_per_day", "span_days",
        "first_external_usd", "first_any_usd", "first_any_asset",
        "first_external_from", "first_external_ts",
        "n_transfers", "n_mints_onchain", "n_burns_onchain",
        "usdc_to_ctf", "usdc_from_ctf",
        "fires_enriched", "n_buy", "n_sell", "buy_pct",
        "sum_asks_mean", "sum_asks_med",
        "own_ask_mean", "own_bid_mean", "spread_med", "offset_s_mean",
        "trading_in", "trading_out", "net_trading_pnl",
        "capital_in", "capital_out", "net_capital",
        "n_days_positive", "n_days_negative",
        "n_open_positions", "open_position_value",
        "asset_mix", "error",
    ]
    col_order = [c for c in col_order if c in fp.columns]
    fp = fp[col_order]

    # 5. Write outputs
    out_csv = CACHE / "_master_catalog.csv"
    fp.to_csv(out_csv)
    print(f"saved -> {out_csv}")
    print()
    print(fp.to_string())
    print()

    # 6. Strategy clusters
    print("=" * 80)
    print("Strategy classification summary")
    print("=" * 80)
    for strat, sub in fp.groupby("strategy"):
        total_pnl = sub.total_pnl.sum()
        n_wallets = len(sub)
        print(f"\n[{strat}]  n={n_wallets}  total_pnl=${total_pnl:,.0f}")
        for s, r in sub.iterrows():
            pnl_day = r.get("total_pnl_per_day", float("nan"))
            print(f"  {s}  span={r.get('span_days', '?')}d  "
                  f"pnl=${r.get('total_pnl', 0):,.0f}  "
                  f"$/day=${pnl_day:,.0f}  "
                  f"buy_pct={r.get('buy_pct', 0):.2f}  "
                  f"sum_asks={r.get('sum_asks_mean', 0):.4f}  "
                  f"own_ask={r.get('own_ask_mean', 0):.3f}")

    # 7. Funder clusters
    print("\n" + "=" * 80)
    print("Funder clusters (wallets seeded by same source)")
    print("=" * 80)
    funder_counts = fp["first_external_from"].value_counts()
    for funder, count in funder_counts.items():
        if count >= 2:
            kids = fp[fp.first_external_from == funder].index.tolist()
            print(f"  {funder}  → seeded {count} wallets: {kids}")


if __name__ == "__main__":
    main()
