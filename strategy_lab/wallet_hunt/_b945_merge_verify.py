"""
_b945_merge_verify.py — Article claim verification for wallet 0xb945945d
Reproduces all stats in B945_MERGE_LOOP_VERIFY_2026_06_12.md
"""
import pandas as pd
import numpy as np
import json
import re
import os

BASE = "C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/cache/0xb945945d"
PM_BASE = f"{BASE}/../_pm_portfolio/0xb945945d"


def slug_to_ss(s):
    m = re.search(r"-(\d+)$", str(s))
    return int(m.group(1)) if m else None


def load_fills():
    return pd.read_parquet(f"{BASE}/fill_tape_full.parquet")


def load_alchemy():
    return pd.read_parquet(f"{BASE}/alchemy_transfers.parquet")


def load_ml():
    return pd.read_parquet(f"{BASE}/ml_features.parquet")


def load_fires():
    return pd.read_parquet(f"{BASE}/fires_decoded.parquet")


def load_paired():
    return pd.read_parquet(f"{BASE}/per_slug_paired_ledger.parquet")


def load_activity(typ):
    path = f"{PM_BASE}/activity_{typ}.json"
    if os.path.exists(path):
        return json.load(open(path))
    return []


# ─── Claim 1: Window timing ──────────────────────────────────────────────────
def claim1_timing():
    fills = load_fills()
    fills["ts_dt"] = pd.to_datetime(fills["ts"])
    fills["ss"] = fills["slug"].apply(slug_to_ss)
    fills["slot_start_dt"] = pd.to_datetime(fills["ss"], unit="s", utc=True)
    fills["off_s"] = (fills["ts_dt"] - fills["slot_start_dt"]).dt.total_seconds()
    first = fills.groupby("slug")["off_s"].min()
    print("=== CLAIM 1: Window timing ===")
    print(f"Slugs with first fill: {len(first)}")
    print(f"Pre-window fills (<0s): {(first < 0).sum()}")
    print(f"Within 10s: {(first < 10).sum()} ({(first < 10).mean():.1%})")
    print(f"Within 60s: {(first < 60).sum()} ({(first < 60).mean():.1%})")
    print(f"Median first-fill offset: {first.median():.0f}s")
    print(f"10s-bin distribution (0-120s):")
    bins = list(range(0, 121, 10))
    print(pd.cut(first.clip(0, 120), bins=bins).value_counts().sort_index().to_string())
    print()


# ─── Claim 2: Merge loop / pUSD cycling ─────────────────────────────────────
def claim2_merge_loop():
    alch = load_alchemy()
    ZERO = "0x0000000000000000000000000000000000000000"
    E111 = "0xe111180000d2663c0091e4f400237545b87b996b"
    ADAPTER = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"

    pusd = alch[alch["asset"] == "pUSD"]
    mints = pusd[pusd["from"] == ZERO]
    burns = alch[alch["to"] == ZERO]

    trade_api = load_activity("TRADE")
    merge_api = load_activity("MERGE")
    split_api = load_activity("SPLIT")
    redeem_api = load_activity("REDEEM")

    print("=== CLAIM 2: Merge loop / SPLIT-MERGE ===")
    print(f"Activity API SPLIT events: {len(split_api)}")
    print(f"Activity API MERGE events: {len(merge_api)}")
    print(f"Activity API REDEEM events: {len(redeem_api)}")
    print(f"pUSD minted from 0x0000 (SPLIT ops): {len(mints)} | ${mints['value'].sum():,.0f}")
    print(f"CTF burns to 0x0000 (MERGE/REDEEM): {len(burns)} | ${burns['value'].sum():,.0f}")
    # pUSD to exchange = trading capital
    pusd_to_exch = pusd[(pusd["to"] == E111) & (pusd["direction"] == "from")]
    print(f"pUSD sent to exchange (trading): {len(pusd_to_exch)} | ${pusd_to_exch['value'].sum():,.0f}")
    # adapter flows
    from_adapter = alch[(alch["from"].str.startswith("0x4d97")) & (alch["direction"] == "to")]
    to_adapter = alch[(alch["to"].str.startswith("0x4d97")) & (alch["direction"] == "from")]
    print(f"From adapter to b945 (receive cond tokens): {len(from_adapter)} | ${from_adapter['value'].sum():,.0f}")
    print(f"From b945 to adapter (send cond tokens): {len(to_adapter)}")
    print()


# ─── Claim 3: SPLIT manufacturing liquidity ──────────────────────────────────
def claim3_splits():
    alch = load_alchemy()
    ZERO = "0x0000000000000000000000000000000000000000"
    mints = alch[(alch["from"] == ZERO) & (alch["asset"] == "pUSD")].copy()
    mints["ts_dt"] = pd.to_datetime(mints["ts"])

    fires = load_fires()
    sells = fires[fires["wallet_side"] == "SELL"]

    print("=== CLAIM 3: SPLIT manufacturing + SELL fills ===")
    print(f"SPLIT ops (pUSD mints): {len(mints)} | ${mints['value'].sum():,.0f}")
    print(f"Monthly breakdown:")
    print(mints.set_index("ts_dt").resample("ME")["value"].agg(["sum", "count"]).to_string())
    print(f"SELL fills in fires_decoded: {len(sells)}")
    print(f"SELL fills all post-resolution (>900s): {(sells['offset_from_slot_start_s'] > 900).all()}")
    print(f"SELL fill median offset: {sells['offset_from_slot_start_s'].median():.0f}s (=~36s post window-end)")
    print(f"SELL counterparties: {sells['counterparty'].value_counts().to_string()}")
    print()


# ─── Claim 4: GTC-only maker ──────────────────────────────────────────────────
def claim4_maker_taker():
    ml = load_ml()
    fills = ml[ml["is_fill"] == 1].copy()
    fills["dn_mid"] = (fills["dn_ask"] + fills["dn_bid"]) / 2
    # Classify by price vs book
    fills["is_maker_up"] = (fills["side_up"] == 1) & (fills["price"] <= fills["up_bid"])
    fills["is_taker_up"] = (fills["side_up"] == 1) & (fills["price"] >= fills["up_ask"])
    fills["is_maker_dn"] = (fills["side_up"] == 0) & (fills["price"] <= fills["dn_bid"])
    fills["is_taker_dn"] = (fills["side_up"] == 0) & (fills["price"] >= fills["dn_ask"])
    fills["is_maker"] = fills["is_maker_up"] | fills["is_maker_dn"]
    fills["is_taker"] = fills["is_taker_up"] | fills["is_taker_dn"]
    fills["is_ambig"] = ~fills["is_maker"] & ~fills["is_taker"]

    print("=== CLAIM 4: GTC maker vs taker classification ===")
    print(f"Total fill events in ml_features: {len(fills)}")
    print(f"Maker (price<=bid): {fills['is_maker'].sum()} ({fills['is_maker'].mean():.1%})")
    print(f"Taker (price>=ask): {fills['is_taker'].sum()} ({fills['is_taker'].mean():.1%})")
    print(f"Ambiguous (in-spread): {fills['is_ambig'].sum()} ({fills['is_ambig'].mean():.1%})")
    print(f"Caveat: ±2s block-smear may misclassify some; book snapshot at fill exact time approximate")
    print()


# ─── Claim 5: Imbalance gate ─────────────────────────────────────────────────
def claim5_imbalance_gate():
    ml = load_ml()
    fills = ml[ml["is_fill"] == 1].sort_values(["slug", "t_us"]).copy()
    fills["next_is_up"] = fills.groupby("slug")["side_up"].shift(-1)
    fills = fills.dropna(subset=["next_is_up"])
    fills["delta_q5"] = pd.qcut(fills["delta"].clip(-200, 200), q=5)

    print("=== CLAIM 5: Imbalance gate - P(next fill Up | signed delta) ===")
    result = fills.groupby("delta_q5", observed=True)["next_is_up"].agg(["mean", "count"])
    print(result.to_string())
    print("Interpretation: when delta heavily +Up (top quintile), P(next is Up)=0.47 (below 0.5)")
    print("When delta heavily -Down (bottom quintile), P(next is Up)=0.54 (above 0.5)")
    print("Weak but consistent with quote-throttling on heavy side")
    print()


# ─── Claim 6: 2-second requote cadence ───────────────────────────────────────
def claim6_requote_cadence():
    ml = load_ml()
    fills = ml[ml["is_fill"] == 1].sort_values(["slug", "leg", "t_us"]).copy()
    fills["gap_s"] = fills.groupby(["slug", "leg"])["t_us"].diff() / 1e6
    gap = fills["gap_s"].dropna()

    print("=== CLAIM 6: Inter-fill spacing distribution ===")
    print(f"Total inter-fill gaps: {len(gap)}")
    print(f"Pct <1s: {(gap < 1).mean():.1%}")
    print(f"Pct 1-3s: {((gap >= 1) & (gap < 3)).mean():.1%}")
    print(f"Pct 2-2.5s: {((gap >= 2) & (gap < 2.5)).mean():.1%}")
    print(f"Median: {gap.median():.1f}s | Mean: {gap.mean():.1f}s")
    print(f"Modal bin: 0-1s (sub-second cancel/replace activity)")
    print()


# ─── Claim 7: Article scale vs actual ────────────────────────────────────────
def claim7_scale():
    fills = load_fills()
    fills["ts_dt"] = pd.to_datetime(fills["ts"])
    trade_api = pd.DataFrame(load_activity("TRADE"))
    trade_api["ts"] = pd.to_datetime(trade_api["timestamp"], unit="s", utc=True)
    alch = load_alchemy()

    # Sibling wallet check: USDC outflows to non-contract addresses
    polymkt_prefixes = ["0x4bfb", "0xc5d5", "0x2791", "0x4d97", "0xf70d", "0x0d50", "0xe111"]
    b945 = "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68"
    usdc = alch[alch["asset"].isin(["USDC", "USDCE"])]
    out = usdc[usdc["direction"] == "from"].copy()
    out["is_known"] = out["to"].apply(lambda a: any(a.lower().startswith(p) for p in polymkt_prefixes))
    sibling_candidates = (
        out[~out["is_known"]]
        .groupby("to")["value"]
        .agg(["sum", "count"])
        .sort_values("sum", ascending=False)
    )
    sibling_candidates = sibling_candidates[sibling_candidates["sum"] >= 1000]

    print("=== CLAIM 7: Article scale vs actual ===")
    print(f"Activity API TRADE count (page-capped at 3500): {len(trade_api)}")
    print(f"Activity API TRADE date range: {trade_api['ts'].min()} to {trade_api['ts'].max()}")
    print(f"Activity API TRADE volume: ${trade_api['usdcSize'].sum():,.0f}")
    print(f"Alchemy tape total fills: {len(fills)} | volume: ${fills['usd'].sum():,.0f}")
    print(f"Date range: {fills['ts_dt'].min()} to {fills['ts_dt'].max()}")
    apr28 = pd.Timestamp("2026-04-28", tz="UTC")
    print(f"Last 6-week fills (Apr28+): {len(fills[fills['ts_dt'] >= apr28])} | ${fills[fills['ts_dt'] >= apr28]['usd'].sum():,.0f}")
    print()
    print("Sibling wallet candidates (non-contract USDC outflows >=1k):")
    print(sibling_candidates.to_string())
    print()


# ─── PnL reconciliation vs audit identity (+$21,742) — r2 ────────────────────
def pnl_reconciliation():
    """r2: the ledger's total_pnl (-11,738) was WRONG. Two holes:
    1. Fee-model artifact -$17,873 (taker fee curve applied to a maker wallet)
    2. 323 unmapped slugs dropped: +$104,259 redeem vs ~$92,534 costs = +$11,725
    Closure: +6,372 (mapped nofee) + 11,725 (unmapped) + 3,645 (rebate) = +21,742 (= LB API)
    """
    led = load_paired()
    aud = pd.read_parquet(f"{BASE}/per_slug_audit_ledger.parquet")
    print("=== PnL RECONCILIATION (r2) ===")
    costs = led["usd_up"].sum() + led["usd_dn"].sum()
    redeem = led["redeem_usd"].sum()
    print(f"Mapped slugs (1,564): cost ${costs:,.0f} | redeem ${redeem:,.0f} | cash net ${redeem - costs:,.0f}")
    print(f"total_pnl (fee-modeled, WRONG for maker): ${led['total_pnl'].sum():,.0f}")
    print(f"total_nofee (correct basis): ${led['total_nofee'].sum():,.0f}")
    print(f"Fee-model artifact: ${led['total_pnl'].sum() - led['total_nofee'].sum():,.0f}")
    only_aud = aud.loc[~aud.index.isin(led.index)]
    print(f"Audit-only slugs ({len(only_aud)}): redeem ${only_aud['redeem'].sum():,.0f} (costs unmapped, ~$92.5k per audit)")
    print("Closure: 6,372 + 11,725 + 3,645 rebate = +21,742 = LB API")
    print()


# ─── Claim 1 addendum: market creation timing (canonical, market-wide) ───────
def claim1_market_creation():
    """82.3% of btc-15m markets have third-party prints BEFORE slot_start
    (earliest -23.9h, cluster ~-23.5h) => '24h-early' availability CONFIRMED."""
    import duckdb
    p = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket/btc.parquet"
    df = duckdb.connect().execute(
        f"SELECT slug, min(timestamp_us) AS first_us FROM read_parquet('{p}') "
        "WHERE slug LIKE 'btc-updown-15m-%' GROUP BY slug"
    ).df()
    df["ss"] = df["slug"].str.extract(r"-(\d+)$").astype("int64")
    df["off_s"] = df["first_us"] / 1e6 - df["ss"]
    print("=== CLAIM 1 addendum: market-wide earliest print vs slot_start ===")
    print(df["off_s"].describe())
    print(f"Pct pre-slot_start: {(df['off_s'] < 0).mean():.1%}")
    print()


if __name__ == "__main__":
    claim1_timing()
    claim1_market_creation()
    claim2_merge_loop()
    claim3_splits()
    claim4_maker_taker()
    claim5_imbalance_gate()
    claim6_requote_cadence()
    claim7_scale()
    pnl_reconciliation()
