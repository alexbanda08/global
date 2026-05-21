"""
Wallet profiler — per-slug behavior for every reference wallet.

For each (wallet, slug) compute:
  - n_fills, n_buys, n_sells
  - n_maker_fills, n_taker_fills
  - buy/sell shares, USDC paid/received
  - avg buy price, avg sell price
  - first_offset_s, last_offset_s (timing of activity in slug)
  - n_fires_per_minute density
  - leftover at slug close
  - paired_pct, paired_side, single-outcome focus
  - book_spread at fill time (median)

Outputs:
  strategy_lab/backtests/_wallet_profile_per_slug.csv   — one row per (wallet, slug, outcome)
  strategy_lab/backtests/_wallet_profile_per_slug_agg.csv — one row per (wallet, slug) aggregated
  strategy_lab/backtests/_wallet_profile_summary.csv     — one row per wallet
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WALLET_CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
OUT_DIR = ROOT / "strategy_lab" / "backtests"
OUT_DIR.mkdir(exist_ok=True)

WALLETS = {
    "0x04b6d7e9": "ACC-M-ref (PURE_PAIR_ARB)",
    "0xb27bc932": "ACC-M-scale-ref",
    "0xeebde7a0": "ACC-H-ref (HYBRID)",
    "0x89b5cdaa": "DIRECTIONAL-ref",
    "0xcfb103c3": "xuanxuan008 (+$2.5k/d)",
    "0xce25e214": "+$4.6k/d (originally LOSER)",
    "0x7dfc8aa2": "CramSchoolClub01 (+$2.2k/d)",
}


def load_fills(wallet_short: str) -> pd.DataFrame:
    p = WALLET_CACHE / wallet_short / "fills.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    return df


def per_slug_per_outcome(wallet_short: str, df: pd.DataFrame) -> pd.DataFrame:
    """One row per (slug, outcome) for this wallet."""
    if df.empty:
        return df
    # Filter to updown only
    df = df[df["mc"].isin(["updown_5m", "updown_15m"])].copy()
    if df.empty:
        return df
    df["side_upper"] = df["side"].str.upper()
    df["is_buy"] = df["side_upper"] == "BUY"
    df["is_sell"] = df["side_upper"] == "SELL"

    grp = df.groupby(["slug", "outcome"], observed=True).agg(
        n_fills=("side", "count"),
        n_buys=("is_buy", "sum"),
        n_sells=("is_sell", "sum"),
        n_maker=("is_maker", "sum"),
        n_taker=("is_maker", lambda s: (~s).sum()),
        buy_shares=("size", lambda s: df.loc[s.index, "size"][df.loc[s.index, "is_buy"]].sum()),
        sell_shares=("size", lambda s: df.loc[s.index, "size"][df.loc[s.index, "is_sell"]].sum()),
        buy_usd=("usd", lambda s: df.loc[s.index, "usd"][df.loc[s.index, "is_buy"]].sum()),
        sell_usd=("usd", lambda s: df.loc[s.index, "usd"][df.loc[s.index, "is_sell"]].sum()),
        avg_buy_px=("price", lambda s: df.loc[s.index, "price"][df.loc[s.index, "is_buy"]].mean()),
        avg_sell_px=("price", lambda s: df.loc[s.index, "price"][df.loc[s.index, "is_sell"]].mean()),
        size_p50=("size", "median"),
        size_p90=("size", lambda s: s.quantile(0.90)),
        first_offset=("offset_from_slot_start_s", "min"),
        last_offset=("offset_from_slot_start_s", "max"),
        median_offset=("offset_from_slot_start_s", "median"),
        n_unique_offsets=("offset_from_slot_start_s", "nunique"),
        mc=("mc", "first"),
        asset_sym=("asset_sym", "first"),
        slot_start_s=("slot_start_s", "first"),
        median_book_spread=("book_spread", "median"),
    ).reset_index()
    grp["wallet"] = wallet_short
    grp["span_s"] = grp["last_offset"] - grp["first_offset"]
    grp["fires_per_min"] = grp["n_fills"] / (grp["span_s"].clip(lower=1) / 60.0)
    grp["maker_pct"] = grp["n_maker"] / grp["n_fills"] * 100
    grp["sell_pct"] = grp["n_sells"] / grp["n_fills"] * 100
    return grp


def per_slug_agg(per_so: pd.DataFrame) -> pd.DataFrame:
    """Aggregate across outcomes into one row per (wallet, slug)."""
    if per_so.empty:
        return per_so
    agg = per_so.groupby(["wallet", "slug"], observed=True).agg(
        n_outcomes_touched=("outcome", "nunique"),
        total_fills=("n_fills", "sum"),
        total_buys=("n_buys", "sum"),
        total_sells=("n_sells", "sum"),
        total_maker=("n_maker", "sum"),
        total_taker=("n_taker", "sum"),
        total_buy_shares=("buy_shares", "sum"),
        total_sell_shares=("sell_shares", "sum"),
        total_buy_usd=("buy_usd", "sum"),
        total_sell_usd=("sell_usd", "sum"),
        min_first_offset=("first_offset", "min"),
        max_last_offset=("last_offset", "max"),
        mc=("mc", "first"),
        asset_sym=("asset_sym", "first"),
        slot_start_s=("slot_start_s", "first"),
        avg_buy_px=("avg_buy_px", "mean"),
        avg_sell_px=("avg_sell_px", "mean"),
    ).reset_index()
    agg["span_s"] = agg["max_last_offset"] - agg["min_first_offset"]
    agg["fires_per_min"] = agg["total_fills"] / (agg["span_s"].clip(lower=1) / 60.0)
    agg["maker_pct"] = agg["total_maker"] / agg["total_fills"] * 100
    agg["paired_full"] = agg["n_outcomes_touched"] == 2
    agg["is_buy_heavy"] = agg["total_buys"] > agg["total_sells"] * 2
    agg["is_sell_heavy"] = agg["total_sells"] > agg["total_buys"] * 2
    return agg


def wallet_summary(wallet_short: str, df_per_so: pd.DataFrame,
                    df_per_slug: pd.DataFrame) -> dict:
    """Cross-slug summary for the wallet."""
    if df_per_so.empty:
        return {"wallet": wallet_short, "n_slugs": 0}
    return {
        "wallet": wallet_short,
        "label": WALLETS.get(wallet_short, ""),
        "n_slugs_total": int(df_per_slug["slug"].nunique()),
        "n_5m_slugs": int((df_per_slug["mc"] == "updown_5m").sum()),
        "n_15m_slugs": int((df_per_slug["mc"] == "updown_15m").sum()),
        "n_btc_slugs": int((df_per_slug["asset_sym"] == "BTC").sum()),
        "n_eth_slugs": int((df_per_slug["asset_sym"] == "ETH").sum()),
        "n_sol_slugs": int((df_per_slug["asset_sym"] == "SOL").sum()),
        "total_fills": int(df_per_so["n_fills"].sum()),
        "total_maker": int(df_per_so["n_maker"].sum()),
        "total_taker": int(df_per_so["n_taker"].sum()),
        "maker_pct": float(df_per_so["n_maker"].sum() / df_per_so["n_fills"].sum() * 100),
        "total_buys": int(df_per_so["n_buys"].sum()),
        "total_sells": int(df_per_so["n_sells"].sum()),
        "median_fills_per_slug_per_outcome": float(df_per_so["n_fills"].median()),
        "p90_fills_per_slug_per_outcome": float(df_per_so["n_fills"].quantile(0.90)),
        "median_size": float(df_per_so["size_p50"].median()),
        "p90_size": float(df_per_so["size_p90"].median()),
        "median_first_offset_s": float(df_per_so["first_offset"].median()),
        "median_last_offset_s": float(df_per_so["last_offset"].median()),
        "median_span_s": float(df_per_so["span_s"].median()),
        "median_fires_per_min": float(df_per_so["fires_per_min"].median()),
        "median_book_spread": float(df_per_so["median_book_spread"].median()),
        "pct_slugs_paired_full": float(df_per_slug["paired_full"].mean() * 100),
        "pct_slugs_buy_heavy": float(df_per_slug["is_buy_heavy"].mean() * 100),
        "pct_slugs_sell_heavy": float(df_per_slug["is_sell_heavy"].mean() * 100),
        "slug_window_start_s": int(df_per_slug["slot_start_s"].min()),
        "slug_window_end_s": int(df_per_slug["slot_start_s"].max()),
    }


def main():
    all_per_so = []
    all_per_slug = []
    summaries = []
    for wshort, label in WALLETS.items():
        print(f"  loading {wshort} ({label})...", flush=True)
        df = load_fills(wshort)
        if df.empty:
            print(f"    no fills.parquet")
            continue
        per_so = per_slug_per_outcome(wshort, df)
        per_slug = per_slug_agg(per_so)
        all_per_so.append(per_so)
        all_per_slug.append(per_slug)
        s = wallet_summary(wshort, per_so, per_slug)
        summaries.append(s)
        print(f"    {s['n_slugs_total']} slugs, "
              f"{s['total_fills']} fills, "
              f"maker_pct={s['maker_pct']:.0f}%, "
              f"med_fills/slug={s['median_fills_per_slug_per_outcome']:.0f}, "
              f"med_size={s['median_size']:.1f}, "
              f"first_offset_med={s['median_first_offset_s']:.0f}s")

    if all_per_so:
        pd.concat(all_per_so, ignore_index=True).to_csv(
            OUT_DIR / "_wallet_profile_per_slug.csv", index=False
        )
    if all_per_slug:
        pd.concat(all_per_slug, ignore_index=True).to_csv(
            OUT_DIR / "_wallet_profile_per_slug_agg.csv", index=False
        )
    if summaries:
        pd.DataFrame(summaries).to_csv(
            OUT_DIR / "_wallet_profile_summary.csv", index=False
        )

    print()
    print("=" * 80)
    print("SUMMARY (all wallets)")
    print("=" * 80)
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    main()
