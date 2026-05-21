"""
Compute true per-slug wallet PnL using fills.parquet (has is_maker per fill).

PnL = sum(sells_USD) - sum(buys_USD) - taker_fees + maker_rebates + redemption_at_close - mint_cost

Where:
  - For SELL: usd = size * price (received). If is_maker=True, add rebate. Else subtract taker fee.
  - For BUY: usd = size * price (paid). If is_maker=True, add rebate. Else subtract taker fee.
  - Mint cost = inferred from inventory at slug close (won't have direct visibility unless markets.parquet helps)
  - Redemption = leftover shares on winning side × $1
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WALLET_CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
OUT_DIR = ROOT / "strategy_lab" / "backtests"
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from fees import poly_taker_fee_per_share, poly_maker_rebate_per_share, DEFAULT_CRYPTO_FEE_BPS, bps_to_rate
from load import load_resolutions

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)

WALLETS = ["0x04b6d7e9", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3", "0xce25e214"]


def compute_pnl_per_slug(wallet: str, fills: pd.DataFrame, slug_outcome: dict) -> pd.DataFrame:
    rows = []
    fills = fills[fills["asset_sym"] == "BTC"]
    fills = fills[fills["mc"].isin(["updown_5m", "updown_15m"])]
    fills["side_upper"] = fills["side"].str.upper()
    fills["fee_per_share"] = fills["price"].apply(
        lambda p: poly_taker_fee_per_share(p, fee_rate=FEE_RATE) if 0 < p < 1 else 0
    )
    fills["rebate_per_share"] = fills["price"].apply(
        lambda p: poly_maker_rebate_per_share(p, fee_rate=FEE_RATE) if 0 < p < 1 else 0
    )
    fills["fee_total"] = np.where(fills["is_maker"], 0, fills["size"] * fills["fee_per_share"])
    fills["rebate_total"] = np.where(fills["is_maker"], fills["size"] * fills["rebate_per_share"], 0)
    fills["signed_usd"] = np.where(fills["side_upper"] == "SELL", fills["usd"], -fills["usd"])

    grp = fills.groupby(["slug", "outcome"]).agg(
        signed_usd=("signed_usd", "sum"),
        rebate=("rebate_total", "sum"),
        fee=("fee_total", "sum"),
        net_shares=("size", lambda s: (s * np.where(fills.loc[s.index, "side_upper"] == "BUY", 1, -1)).sum()),
        n_fills=("size", "count"),
        n_maker=("is_maker", "sum"),
        slot_start_s=("slot_start_s", "first"),
        mc=("mc", "first"),
    ).reset_index()

    # Aggregate across outcomes
    slug_agg = grp.groupby("slug").agg(
        total_signed_usd=("signed_usd", "sum"),
        total_rebate=("rebate", "sum"),
        total_fee=("fee", "sum"),
        net_up=("net_shares", lambda s: s.values[grp.loc[s.index, "outcome"] == "Up"].sum() if (grp.loc[s.index, "outcome"] == "Up").any() else 0),
        net_dn=("net_shares", lambda s: s.values[grp.loc[s.index, "outcome"] == "Down"].sum() if (grp.loc[s.index, "outcome"] == "Down").any() else 0),
        total_fills=("n_fills", "sum"),
        total_maker=("n_maker", "sum"),
        slot_start_s=("slot_start_s", "first"),
        mc=("mc", "first"),
    ).reset_index()

    # Per-slug PnL
    out_rows = []
    for _, r in slug_agg.iterrows():
        slug = r["slug"]
        outcome = slug_outcome.get(slug, "?")
        # Trading net cash (sells - buys)
        cash_from_trading = r["total_signed_usd"]
        # Maker rebates and taker fees
        rebate = r["total_rebate"]
        fee = r["total_fee"]
        # Inventory: net_up + net_dn shares (BUY positive, SELL negative)
        net_up = r["net_up"]
        net_dn = r["net_dn"]
        # If they have positive net (bought more than sold), they have leftover inventory
        # If they have negative net (sold more than bought), they MINTED to cover
        # Assume MAS pattern: mint enough to short-sell, leftover = mint - sold + bought
        # mint_cost = |min(net_up, net_dn)| if both negative (they minted both sides)
        if net_up < 0 and net_dn < 0:
            # mint-and-sell pattern: minted ~max(|net_up|, |net_dn|) pairs
            mint_pairs = max(-net_up, -net_dn)
            mint_cost = mint_pairs
        else:
            mint_pairs = 0
            mint_cost = 0
        # Final inventory: net + minted on each side
        inv_up = net_up + mint_pairs
        inv_dn = net_dn + mint_pairs
        # Redemption: winning side gets $1 per share
        redemption = 0
        if outcome == "Up" and inv_up > 0:
            redemption = inv_up
        elif outcome == "Down" and inv_dn > 0:
            redemption = inv_dn

        pnl = cash_from_trading + rebate - fee + redemption - mint_cost

        out_rows.append({
            "wallet": wallet,
            "slug": slug,
            "outcome_truth": outcome,
            "mc": r["mc"],
            "slot_start_s": r["slot_start_s"],
            "total_fills": int(r["total_fills"]),
            "maker_pct": r["total_maker"] / max(r["total_fills"], 1) * 100,
            "cash_from_trading": float(cash_from_trading),
            "rebate": float(rebate),
            "fee": float(fee),
            "net_up": float(net_up),
            "net_dn": float(net_dn),
            "mint_pairs": float(mint_pairs),
            "mint_cost": float(mint_cost),
            "inv_up_final": float(inv_up),
            "inv_dn_final": float(inv_dn),
            "redemption": float(redemption),
            "actual_pnl": float(pnl),
        })
    return pd.DataFrame(out_rows)


def main():
    res = load_resolutions(assets=["BTC", "ETH", "SOL"])
    slug_outcome = dict(zip(res["slug"], res["outcome"]))

    all_dfs = []
    for w in WALLETS:
        p = WALLET_CACHE / w / "fills.parquet"
        if not p.exists():
            continue
        fills = pd.read_parquet(p)
        df = compute_pnl_per_slug(w, fills, slug_outcome)
        if df.empty:
            continue
        all_dfs.append(df)
        print(f"\n{w}: n_slugs={len(df)} "
              f"mean_pnl=${df['actual_pnl'].mean():.2f}/slug "
              f"median=${df['actual_pnl'].median():.2f} "
              f"sum=${df['actual_pnl'].sum():.0f} "
              f"%positive={(df['actual_pnl'] > 0).mean()*100:.0f}%")

    if not all_dfs:
        return
    full = pd.concat(all_dfs, ignore_index=True)
    full.to_csv(OUT_DIR / "_wallet_true_pnl_per_slug.csv", index=False)

    summary = full.groupby("wallet").agg(
        n_slugs=("slug", "count"),
        mean_pnl=("actual_pnl", "mean"),
        median_pnl=("actual_pnl", "median"),
        sum_pnl=("actual_pnl", "sum"),
        pct_positive=("actual_pnl", lambda s: (s > 0).mean() * 100),
        mean_fills=("total_fills", "mean"),
        mean_maker_pct=("maker_pct", "mean"),
        mean_mint_pairs=("mint_pairs", "mean"),
        mean_redemption=("redemption", "mean"),
    ).reset_index()
    summary.to_csv(OUT_DIR / "_wallet_true_pnl_summary.csv", index=False)

    print()
    print("=" * 100)
    print("WALLET TRUE PnL SUMMARY")
    print("=" * 100)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
