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


def _enrich_with_pm_portfolio(fp: pd.DataFrame) -> pd.DataFrame:
    """Fix #6 — add lb-api / data-api columns as canonical lifetime PnL.

    For each wallet, pulls:
        pm_lifetime_profit / pm_30d_profit / pm_7d_profit  — lb-api/profit
        pm_30d_volume                                       — lb-api/volume
        pm_current_value, pm_n_open_positions               — data-api
        pm_maker_rebate_share                               — activity tape

    Responses are cached under cache/_pm_portfolio/<short>/.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from polymarket_api import (
            fetch_lb_profit, fetch_lb_volume,
            fetch_value, fetch_positions, fetch_activity,
            activity_to_df, lb_amount, value_amount,
        )
        from cash_pnl import maker_rebate_share
    except Exception as e:
        print(f"  (skipping pm_portfolio enrichment: {e})")
        return fp

    # Map short -> full address from lb_api_canonical
    try:
        from lb_api_canonical import ADDR_MAP
    except Exception:
        ADDR_MAP = {}

    pm_rows = []
    for short in fp.index:
        full = ADDR_MAP.get(short)
        if not full:
            # fall back to trades.parquet
            tp = CACHE / short / "trades.parquet"
            if tp.exists():
                try:
                    t = pd.read_parquet(tp)
                    if "proxyWallet" in t.columns and len(t):
                        full = str(t.iloc[0].proxyWallet).lower()
                except Exception:
                    pass
        if not full:
            pm_rows.append({"short": short})
            continue
        try:
            lb = fetch_lb_profit(full)
            vol = fetch_lb_volume(full)
            val = fetch_value(full)
            pos = fetch_positions(full)
            act_dict = fetch_activity(full)
            df_act = activity_to_df(act_dict)
            pm_rows.append({
                "short": short,
                "pm_lifetime_profit": lb_amount(lb, "all"),
                "pm_30d_profit": lb_amount(lb, "30d"),
                "pm_7d_profit": lb_amount(lb, "7d"),
                "pm_30d_volume": lb_amount(vol, "30d"),
                "pm_current_value": value_amount(val),
                "pm_n_open_positions": len(pos) if isinstance(pos, list) else 0,
                "pm_maker_rebate_share": round(maker_rebate_share(df_act), 4),
            })
        except Exception as e:
            print(f"  pm-portfolio fetch failed for {short}: {e}")
            pm_rows.append({"short": short})

    pm_df = pd.DataFrame(pm_rows).set_index("short")
    return fp.join(pm_df, how="left")


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
        try:
            pn_full = pd.read_csv(pnl_csv).set_index("short")
            wanted = ["span_days", "trading_in", "trading_out", "net_trading_pnl",
                      "capital_in", "capital_out", "net_capital", "net_cash_pnl",
                      "total_pnl", "total_pnl_per_day", "n_days_positive",
                      "n_days_negative", "n_open_positions", "open_position_value"]
            keep = [c for c in wanted if c in pn_full.columns]
            if keep:
                fp = fp.join(pn_full[keep], how="left")
        except Exception as e:
            print(f"  (legacy cash_pnl_summary skip: {e})")

    # 3. Classify
    fp["strategy"] = fp.apply(lambda r: classify(r.to_dict()), axis=1)

    # 3b. Fix #6 — enrich with Polymarket-official PnL from lb-api and
    # activity-tape rebate share. Truth column for lifetime PnL.
    fp = _enrich_with_pm_portfolio(fp)

    # 4. Reorder columns — `pm_lifetime_profit` is the canonical truth.
    col_order = [
        "strategy",
        # Polymarket OFFICIAL — these are the truth columns (Fix #6).
        "pm_lifetime_profit", "pm_30d_profit", "pm_7d_profit",
        "pm_30d_volume",
        "pm_maker_rebate_share",
        "pm_current_value", "pm_n_open_positions",
        # Legacy Alchemy decoder columns (under-report; kept for back-compat).
        "total_pnl", "total_pnl_per_day", "span_days",
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
    print("Strategy classification summary (using OFFICIAL pm_lifetime_profit)")
    print("=" * 80)
    for strat, sub in fp.groupby("strategy"):
        # Prefer pm_lifetime_profit when available; fall back to legacy total_pnl
        pm_col = (sub.get("pm_lifetime_profit")
                  if "pm_lifetime_profit" in sub.columns else None)
        truth = pm_col if pm_col is not None else sub.get("total_pnl")
        total_pnl = pd.to_numeric(truth, errors="coerce").sum()
        n_wallets = len(sub)
        print(f"\n[{strat}]  n={n_wallets}  pm_lifetime_profit_sum=${total_pnl:,.0f}")
        for s, r in sub.iterrows():
            pm_lt = r.get("pm_lifetime_profit", float("nan"))
            pm_30d = r.get("pm_30d_profit", float("nan"))
            rebate = r.get("pm_maker_rebate_share", float("nan"))
            print(f"  {s}  pm_lifetime=${pm_lt:,.0f}  "
                  f"pm_30d=${pm_30d:,.0f}  "
                  f"rebate_share={rebate:.4f}  "
                  f"buy_pct={r.get('buy_pct', 0):.2f}  "
                  f"sum_asks={r.get('sum_asks_mean', 0):.4f}")

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
