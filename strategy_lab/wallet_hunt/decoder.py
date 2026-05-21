"""Unified wallet-strategy decoder.

INPUT: raw chain logs from `fetch_chain.py` (trades_chain_raw.parquet)
OUTPUT (per wallet):
    fills.parquet         — one row per OrderFilled, with L25-anchored
                            price, correct BUY/SELL, real fees, signals
    legs.parquet          — aggregated per (slug, outcome) leg
    markets.parquet       — aggregated per market (pairs Up+Down legs)
    pnl.parquet           — per-market realized PnL with CLOB winners

This is the SINGLE source-of-truth pipeline. All downstream analysis,
backtest replication, and shadow tracking should consume these parquets.

Key fixes vs prior:
  - Uses L25 book as ground truth for fill price (chain decoder was 80% wrong)
  - Pairs Up + Down legs PER MARKET (mint-and-sell strategies bet across both)
  - Real Polymarket fee curve with maker-rebate credit
  - Detects strategy archetype per wallet automatically
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_chainlink_asof,
    load_orderbook_l25_streaming, asof_strict,
)
from fees import (  # noqa: E402
    poly_taker_fee_per_share, bps_to_rate,
    DEFAULT_CRYPTO_FEE_BPS, CRYPTO_MAKER_REBATE_SHARE,
)

CACHE = Path(__file__).resolve().parent / "cache"
LOOKUP_PATH = CACHE / "_token_lookup.parquet"
SLUG_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")
FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
MATCHER = "0xe111180000d2663c0091e4f400237545b87b996b"


# ===========================================================================
# Strategy archetype classifier
# ===========================================================================

@dataclass
class StrategyClassification:
    archetype: str          # e.g. "MARKET_MAKER", "MINT_AND_SELL", "TAKER_PYRAMID"
    confidence: float       # 0-1
    notes: str


def classify_strategy(legs: pd.DataFrame, markets: pd.DataFrame) -> StrategyClassification:
    """Classify based on observed leg behavior."""
    if legs.empty:
        return StrategyClassification("UNKNOWN", 0.0, "no legs")

    only_sell_pct = (legs.n_buys == 0).mean()
    only_buy_pct = (legs.n_sells == 0).mean()
    both_sides_pct = ((legs.n_buys > 0) & (legs.n_sells > 0)).mean()

    # In markets where Up + Down BOTH have legs and BOTH are sells-only =
    # classic mint-and-sell signature
    if not markets.empty:
        ms = markets[markets.up_n_sells > 0]
        mint_signal_pct = ((ms.up_n_buys == 0) & (ms.down_n_buys == 0)).mean() if len(ms) else 0
    else:
        mint_signal_pct = 0

    # 1. MINT_AND_SELL: dominantly only-sell legs, paired Up+Down
    if only_sell_pct > 0.5 and mint_signal_pct > 0.3:
        return StrategyClassification(
            "MINT_AND_SELL",
            min(only_sell_pct + mint_signal_pct / 2, 1.0),
            f"only_sell_legs={100*only_sell_pct:.0f}%  paired_mint_signal={100*mint_signal_pct:.0f}%",
        )

    # 2. MARKET_MAKER: dominantly both-sides legs AND positive captured spread
    if both_sides_pct > 0.4:
        captured = (legs[legs.n_buys > 0]
                    .assign(sp=lambda x: x.avg_sell_px - x.avg_buy_px)
                    .sp.median())
        if pd.notna(captured) and captured > 0.005:
            return StrategyClassification(
                "MARKET_MAKER",
                min(both_sides_pct + 0.2, 1.0),
                f"both_sides_legs={100*both_sides_pct:.0f}%  med_spread_captured=${captured:+.4f}",
            )
        return StrategyClassification(
            "ACTIVE_CHURNER",
            both_sides_pct,
            f"both_sides_legs={100*both_sides_pct:.0f}%  med_captured_spread=${captured:+.4f}  (no clear spread edge)",
        )

    # 3. TAKER_PYRAMID: dominantly only-buy
    if only_buy_pct > 0.5:
        return StrategyClassification(
            "TAKER_PYRAMID",
            only_buy_pct,
            f"only_buy_legs={100*only_buy_pct:.0f}%",
        )

    return StrategyClassification(
        "MIXED",
        0.5,
        f"only_sell={100*only_sell_pct:.0f}% only_buy={100*only_buy_pct:.0f}% both={100*both_sides_pct:.0f}%",
    )


# ===========================================================================
# Decoding pipeline
# ===========================================================================

def _parse_slug(slug):
    if not isinstance(slug, str): return (None, None, None)
    m = SLUG_UD.match(slug)
    if m: return (f"updown_{m.group(2)}", m.group(1).upper(), int(m.group(3)))
    return (None, None, None)


def _load_books(slugs: set, asset_sym: str) -> dict:
    """Load L25 book indexes for the given slugs of one asset."""
    if not slugs:
        return {}
    return load_orderbook_l25_streaming(asset_sym.lower(), slugs=slugs, subsample_1hz=True)


def _book_at(book_indexes: dict, asset_sym: str, slug: str, outcome: str, ts_us: int):
    bi = book_indexes.get(asset_sym, {})
    rec = bi.get((slug, outcome))
    if rec is None: return None
    ts_arr, ap, asz, bp, bsz = rec
    pos = int(np.searchsorted(ts_arr, ts_us, side="right")) - 1
    if pos < 0: return None
    ba = float(ap[pos][0]) if (len(ap[pos]) and np.isfinite(ap[pos][0])) else None
    bb = float(bp[pos][0]) if (len(bp[pos]) and np.isfinite(bp[pos][0])) else None
    return {
        "ask": ba, "bid": bb,
        "ask_sz": float(asz[pos][0]) if len(asz[pos]) else 0,
        "bid_sz": float(bsz[pos][0]) if len(bsz[pos]) else 0,
        "dt_us": int(ts_us - ts_arr[pos]),
    }


def decode_fills(wallet: str, max_slugs_per_asset: int | None = None) -> pd.DataFrame:
    """Decode wallet's chain fills using L25 as ground truth.

    Returns one row per fill with normalized columns. Drops fills with no
    book match, no clean asset_id mapping, or invalid price.
    """
    w = wallet.lower()
    short = w[:10]
    # Prefer trades_chain.parquet (has timestamp + wallet_is_maker/taker flags)
    chain_p = CACHE / short / "trades_chain.parquet"
    raw_p = CACHE / short / "trades_chain_raw.parquet"
    if chain_p.exists():
        raw_p = chain_p
    if not raw_p.exists():
        return pd.DataFrame()

    raw = pd.read_parquet(raw_p)
    # If raw lacks timestamp/wallet flags (loaded raw-only parquet), backfill
    if "timestamp" not in raw.columns:
        from fetch_chain import join_block_timestamps  # noqa
        raw = join_block_timestamps(raw)
    if "wallet_is_maker" not in raw.columns:
        raw["wallet_is_maker"] = raw.maker.str.lower() == w
        raw["wallet_is_taker"] = raw.taker.str.lower() == w
    if raw.empty:
        return raw
    lookup = pd.read_parquet(LOOKUP_PATH)

    # Join to slug metadata
    merged = raw.merge(
        lookup[["asset_id", "slug", "outcome"]].rename(columns={"asset_id": "_aid"}),
        left_on="maker_asset_id", right_on="_aid", how="left",
    ).rename(columns={"slug": "slug_via_maker", "outcome": "outcome_via_maker"}).drop(columns="_aid")
    merged = merged.merge(
        lookup[["asset_id", "slug", "outcome"]].rename(columns={"asset_id": "_aid"}),
        left_on="taker_asset_id_raw", right_on="_aid", how="left",
    ).rename(columns={"slug": "slug_via_taker", "outcome": "outcome_via_taker"}).drop(columns="_aid")
    merged["slug"] = merged.slug_via_maker.fillna(merged.slug_via_taker)
    merged["outcome"] = merged.outcome_via_maker.fillna(merged.outcome_via_taker)
    merged["maker_holds_token"] = merged.slug_via_maker.notna()
    merged["taker_holds_token"] = merged.slug_via_taker.notna()

    # Filter to up-down
    cls = merged.slug.map(_parse_slug)
    merged["mc"] = cls.map(lambda x: x[0])
    merged["asset_sym"] = cls.map(lambda x: x[1])
    merged["slot_start_s"] = cls.map(lambda x: x[2])
    ud = merged[
        merged.mc.fillna("").str.startswith("updown_")
        & merged.timestamp.notna()
        & merged.outcome.notna()
    ].copy()

    # Load L25 books for the asset/slug sets
    by_asset = {a: set() for a in ("BTC", "ETH", "SOL")}
    slug_counts = ud.slug.value_counts()
    for s in slug_counts.index:
        m = SLUG_UD.match(s)
        if not m: continue
        a = m.group(1).upper()
        if max_slugs_per_asset and len(by_asset[a]) >= max_slugs_per_asset:
            continue
        by_asset[a].add(s)

    print(f"  loading L25 for {sum(len(s) for s in by_asset.values())} slugs "
          f"(BTC={len(by_asset['BTC'])} ETH={len(by_asset['ETH'])} SOL={len(by_asset['SOL'])})...")
    book_indexes = {}
    for a, sl in by_asset.items():
        if sl:
            book_indexes[a] = _load_books(sl, a)

    # Decode each fill
    print(f"  decoding {len(ud)} fills (filtered to top slugs)...")
    ud = ud[ud.slug.isin({s for slugs in by_asset.values() for s in slugs})]

    rows = []
    skipped = {"no_book": 0, "no_role": 0, "bad_price": 0, "bad_size": 0}
    for r in ud.itertuples(index=False):
        ts_us = int(r.timestamp) * 1_000_000
        book = _book_at(book_indexes, r.asset_sym, r.slug, r.outcome, ts_us)
        if book is None or book["ask"] is None or book["bid"] is None:
            skipped["no_book"] += 1; continue

        # Determine wallet's role + side
        if r.wallet_is_maker:
            if r.maker_holds_token:
                side, price = "SELL", book["ask"]  # the maker is selling outcome; fills at posted ask
            else:
                side, price = "BUY", book["bid"]   # maker buying outcome; passive bid that takers hit
        elif r.wallet_is_taker:
            if r.maker_holds_token:
                side, price = "BUY", book["ask"]   # taker bought at maker's ask
            elif r.taker_holds_token:
                side, price = "SELL", book["bid"]  # taker sold at maker's bid
            else:
                skipped["no_role"] += 1; continue
        else:
            skipped["no_role"] += 1; continue

        if not (0 < price < 1):
            skipped["bad_price"] += 1; continue

        # Size = the token-side raw amount
        try:
            if r.maker_holds_token:
                size = int(r.maker_amount_raw) / 1e6
            elif r.taker_holds_token:
                size = int(r.taker_amount_raw) / 1e6
            else:
                skipped["no_role"] += 1; continue
        except Exception:
            skipped["bad_size"] += 1; continue
        if size <= 0:
            skipped["bad_size"] += 1; continue

        rows.append({
            "ts_s": int(r.timestamp),
            "block": int(r.block),
            "tx_hash": r.tx_hash,
            "log_index": int(r.log_index),
            "slug": r.slug,
            "mc": r.mc,
            "asset_sym": r.asset_sym,
            "outcome": r.outcome,
            "slot_start_s": int(r.slot_start_s),
            "side": side,
            "price": price,
            "size": size,
            "usd": size * price,
            "is_maker": bool(r.wallet_is_maker),
            "book_ask": book["ask"],
            "book_bid": book["bid"],
            "book_spread": book["ask"] - book["bid"],
            "ask_size_top": book["ask_sz"],
            "bid_size_top": book["bid_sz"],
            "book_dt_us": book["dt_us"],
            "offset_from_slot_start_s": int(r.timestamp) - int(r.slot_start_s),
            "counterparty": r.taker.lower() if r.wallet_is_maker else r.maker.lower(),
        })
    print(f"  decoded {len(rows)}/{len(ud)} fills  (skipped: {skipped})")
    return pd.DataFrame(rows)


def aggregate_legs(fills: pd.DataFrame) -> pd.DataFrame:
    """One row per (slug, outcome) — the 'leg' on a single side of one market."""
    if fills.empty: return fills
    grp = fills.groupby(["slug", "outcome"], as_index=False)
    legs = grp.agg(
        mc=("mc", "first"),
        asset_sym=("asset_sym", "first"),
        slot_start_s=("slot_start_s", "first"),
        n=("side", "size"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        buy_sz=("size", lambda s: fills.loc[s.index].loc[fills.side == "BUY", "size"].sum()),
        sell_sz=("size", lambda s: fills.loc[s.index].loc[fills.side == "SELL", "size"].sum()),
        avg_buy_px=("price", lambda s: fills.loc[s.index].loc[fills.side == "BUY", "price"].mean()),
        avg_sell_px=("price", lambda s: fills.loc[s.index].loc[fills.side == "SELL", "price"].mean()),
        buy_maker_sz=("size", lambda s: fills.loc[s.index].loc[(fills.side == "BUY") & fills.is_maker, "size"].sum()),
        sell_maker_sz=("size", lambda s: fills.loc[s.index].loc[(fills.side == "SELL") & fills.is_maker, "size"].sum()),
        first_offset=("offset_from_slot_start_s", "min"),
        last_offset=("offset_from_slot_start_s", "max"),
        first_ts=("ts_s", "min"),
        last_ts=("ts_s", "max"),
    )
    legs["leftover"] = legs.buy_sz - legs.sell_sz
    legs["cash_realized"] = legs.sell_sz.fillna(0) * legs.avg_sell_px.fillna(0) - \
                            legs.buy_sz.fillna(0) * legs.avg_buy_px.fillna(0)
    return legs


def aggregate_markets(legs: pd.DataFrame) -> pd.DataFrame:
    """Pair Up + Down legs per market. Captures mint-and-sell behavior."""
    if legs.empty: return legs
    rows = []
    for slug, sub in legs.groupby("slug"):
        up = sub[sub.outcome == "Up"]
        dn = sub[sub.outcome == "Down"]
        up_row = up.iloc[0] if len(up) else None
        dn_row = dn.iloc[0] if len(dn) else None
        ref_row = up_row if up_row is not None else dn_row
        def g(r, c, default=0):
            return float(r[c]) if (r is not None and pd.notna(r[c])) else default
        # Polymarket binary tokens cannot be naked-shorted. If our visible
        # leftover (buys - sells) is negative, they MUST have minted CTF pairs
        # to source the extra inventory. They had to mint AT LEAST max(-up_lo,
        # -dn_lo, 0) pairs — minting creates equal Up+Down balances, so the
        # larger short side bounds it from below.
        #
        # Each mint adds 1 to BOTH actual balances:
        #   actual_up_balance = up_leftover + minted
        #   actual_dn_balance = dn_leftover + minted
        up_lo = g(up_row, "leftover")
        dn_lo = g(dn_row, "leftover")
        minted = max(0, -up_lo, -dn_lo)
        rows.append({
            "slug": slug,
            "mc": ref_row.mc if ref_row is not None else None,
            "asset_sym": ref_row.asset_sym if ref_row is not None else None,
            "slot_start_s": int(ref_row.slot_start_s) if ref_row is not None else 0,
            "up_n_trades": int(g(up_row, "n")),
            "up_n_buys": int(g(up_row, "n_buys")),
            "up_n_sells": int(g(up_row, "n_sells")),
            "up_buy_sz": g(up_row, "buy_sz"),
            "up_sell_sz": g(up_row, "sell_sz"),
            "up_buy_maker_sz": g(up_row, "buy_maker_sz"),
            "up_sell_maker_sz": g(up_row, "sell_maker_sz"),
            "up_avg_buy_px": g(up_row, "avg_buy_px", default=float("nan")),
            "up_avg_sell_px": g(up_row, "avg_sell_px", default=float("nan")),
            "up_leftover": up_lo,
            "down_n_trades": int(g(dn_row, "n")),
            "down_n_buys": int(g(dn_row, "n_buys")),
            "down_n_sells": int(g(dn_row, "n_sells")),
            "down_buy_sz": g(dn_row, "buy_sz"),
            "down_sell_sz": g(dn_row, "sell_sz"),
            "down_buy_maker_sz": g(dn_row, "buy_maker_sz"),
            "down_sell_maker_sz": g(dn_row, "sell_maker_sz"),
            "down_avg_buy_px": g(dn_row, "avg_buy_px", default=float("nan")),
            "down_avg_sell_px": g(dn_row, "avg_sell_px", default=float("nan")),
            "down_leftover": dn_lo,
            "cash_total": g(up_row, "cash_realized") + g(dn_row, "cash_realized"),
            "minted_pairs": minted,
        })
    return pd.DataFrame(rows)


def compute_market_pnl(markets: pd.DataFrame, winners: dict) -> pd.DataFrame:
    """Per-market realized PnL combining Up+Down + minting cost."""
    if markets.empty: return markets
    out = markets.copy()
    out["winner"] = out.slug.map(winners)
    out["resolved"] = out.winner.notna()

    def market_pnl(r):
        if not r.resolved: return None
        # Actual balance held at end = visible leftover + minted pairs.
        # Mints add 1 to BOTH Up and Down balances per pair.
        actual_up = r.up_leftover + r.minted_pairs
        actual_dn = r.down_leftover + r.minted_pairs
        # Both balances should now be ≥ 0 (we can't be naked short)
        up_payoff = max(actual_up, 0) * (1.0 if r.winner == "Up" else 0.0)
        dn_payoff = max(actual_dn, 0) * (1.0 if r.winner == "Down" else 0.0)
        mint_cost = r.minted_pairs * 1.0
        # Net = cash_realized (sells - buys) + redemption value - mint cost
        return r.cash_total + up_payoff + dn_payoff - mint_cost

    def market_fees(r):
        # Maker fills get 20% rebate, taker fills pay full fee. We track
        # maker_sz per side in the legs aggregator. Need to look those up.
        fees = 0.0
        for sd_px, sz, mk_col in [
            (r.up_avg_buy_px,   r.up_buy_sz,   "up_buy_maker_sz"),
            (r.up_avg_sell_px,  r.up_sell_sz,  "up_sell_maker_sz"),
            (r.down_avg_buy_px, r.down_buy_sz, "down_buy_maker_sz"),
            (r.down_avg_sell_px,r.down_sell_sz,"down_sell_maker_sz"),
        ]:
            if pd.notna(sd_px) and sz > 0:
                full_fee = sz * poly_taker_fee_per_share(sd_px, FEE_RATE)
                # Maker share gets 20% off
                mk_sz = float(getattr(r, mk_col, 0) or 0)
                maker_frac = (mk_sz / sz) if sz > 0 else 0
                # Rebate of 20% of fee on maker portion
                fees += full_fee * (1 - maker_frac * CRYPTO_MAKER_REBATE_SHARE)
        return fees

    out["pnl_gross"] = out.apply(market_pnl, axis=1)
    out["fees"] = out.apply(market_fees, axis=1)
    out["pnl_net"] = out.pnl_gross - out.fees
    return out


# ===========================================================================
# Main
# ===========================================================================

def run(wallet: str, max_slugs_per_asset: int | None) -> dict:
    w = wallet.lower()
    short = w[:10]
    print(f"\n=== {short}")
    fills = decode_fills(w, max_slugs_per_asset=max_slugs_per_asset)
    if fills.empty:
        return {"short": short, "n_fills": 0, "error": "no fills decoded"}
    odir = CACHE / short
    odir.mkdir(parents=True, exist_ok=True)
    fills.to_parquet(odir / "fills.parquet", index=False)

    legs = aggregate_legs(fills)
    legs.to_parquet(odir / "legs.parquet", index=False)

    markets = aggregate_markets(legs)
    markets.to_parquet(odir / "markets.parquet", index=False)

    cls = classify_strategy(legs, markets)

    return {
        "short": short,
        "n_fills": len(fills),
        "n_legs": len(legs),
        "n_markets": len(markets),
        "n_5m": int((legs.mc == "updown_5m").sum()),
        "n_15m": int((legs.mc == "updown_15m").sum()),
        "maker_pct": round(100 * fills.is_maker.mean(), 1),
        "buy_pct": round(100 * (fills.side == "BUY").mean(), 1),
        "med_offset": int(fills.offset_from_slot_start_s.median()),
        "archetype": cls.archetype,
        "confidence": round(cls.confidence, 3),
        "notes": cls.notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", action="append", help="repeat for multi-wallet")
    ap.add_argument("--all", action="store_true", help="process all wallets with chain data")
    ap.add_argument("--max-slugs-per-asset", type=int, default=None,
                    help="limit slugs per asset to cap L25 memory (default: no limit)")
    args = ap.parse_args()

    if args.all:
        wallets = [d.name for d in CACHE.glob("0x*") if d.is_dir() and (d / "trades_chain_raw.parquet").exists()]
        # Expand short to full address from any trades.parquet
        full_wallets = []
        for short in wallets:
            tp = CACHE / short / "trades.parquet"
            if tp.exists():
                t = pd.read_parquet(tp)
                if "proxyWallet" in t.columns and len(t):
                    full_wallets.append(str(t.iloc[0].proxyWallet))
            else:
                # No data-api file; the short IS the prefix
                full_wallets.append(short)
        wallets = full_wallets
    elif args.wallet:
        wallets = args.wallet
    else:
        print("--wallet or --all required")
        return 1

    # Load CLOB winners once
    print("Loading CLOB winners...")
    canon = load_resolutions(source="upstream", with_clob_winner=True)
    win_col = "clob_winner" if "clob_winner" in canon.columns else "outcome"
    if win_col == "clob_winner":
        canon[win_col] = canon[win_col].fillna(canon["outcome"])
    winners = canon.set_index("slug")[win_col].to_dict()
    print(f"  {len(winners):,} resolved markets")

    summary = []
    for w in wallets:
        try:
            row = run(w, max_slugs_per_asset=args.max_slugs_per_asset)
            # Compute PnL with winners
            short = w.lower()[:10]
            mp = CACHE / short / "markets.parquet"
            if mp.exists():
                m = pd.read_parquet(mp)
                m_pnl = compute_market_pnl(m, winners)
                m_pnl.to_parquet(CACHE / short / "pnl.parquet", index=False)
                resolved = m_pnl[m_pnl.resolved]
                row["n_resolved_markets"] = len(resolved)
                row["pnl_net_total"] = round(resolved.pnl_net.sum(), 2) if len(resolved) else 0
                row["pnl_net_per_market"] = round(resolved.pnl_net.mean(), 4) if len(resolved) else 0
        except Exception as e:
            import traceback; traceback.print_exc()
            row = {"short": w.lower()[:10], "error": str(e)[:80]}
        summary.append(row)

    df = pd.DataFrame(summary)
    df.to_csv(CACHE / "_decoder_summary.csv", index=False)
    print(f"\n{'='*100}")
    print(df.to_string(index=False))
    print(f"\nsaved -> cache/_decoder_summary.csv")


if __name__ == "__main__":
    main()
