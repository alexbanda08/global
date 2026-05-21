"""Per-fire trigger decoder — enrich every wallet trade with full context.

For each fill in alchemy_transfers (USDC + ERC1155 events) on an up-down
market, joins:
  - L25 book state at fill_ts (best ask, best bid, mid, spread, top-of-book sizes)
  - Binance 1MIN price at fill_ts + 30s/60s/120s before (rolling returns)
  - Chainlink RTDS oracle at fill_ts
  - Offset from slot_start (where in the market lifecycle)
  - Wallet's own side / price / size / maker-or-taker

Then computes per-wallet stats:
  - Distribution of "ask sum at fire" — confirms mint-and-sell trigger
  - Distribution of "offset from slot_start" — when do they fire?
  - Distribution of "binance ret_2m at fire" — momentum signal?
  - Counterparties — who do they trade against?

Output: cache/<short>/fires_decoded.parquet + per-wallet trigger report.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "wallet_hunt"))

from load import (  # noqa: E402
    load_klines_asof, load_chainlink_asof,
    load_orderbook_l25_streaming, asof_strict,
)

CACHE = Path(__file__).resolve().parents[1] / "cache"
LOOKUP = CACHE / "_token_lookup.parquet"
SLUG_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")
MATCHER = "0xe111180000d2663c0091e4f400237545b87b996b"
CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
ZERO = "0x0000000000000000000000000000000000000000"
USDCE_ADDR = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"


def parse_slug(slug):
    if not isinstance(slug, str): return (None, None, None)
    m = SLUG_UD.match(slug)
    if m: return (f"updown_{m.group(2)}", m.group(1).upper(), int(m.group(3)))
    return (None, None, None)


def decode_wallet(wallet: str, max_fires: int = 5000) -> pd.DataFrame:
    short = wallet.lower()[:10]
    tp = CACHE / short / "alchemy_transfers.parquet"
    if not tp.exists():
        print(f"missing {tp}")
        return pd.DataFrame()

    raw = pd.read_parquet(tp)

    # Focus on ERC1155 (outcome token transfers) — these ARE the trades
    # Each ERC1155 row = a token movement; combined with USDC TX-mate = trade
    erc = raw[raw.category == "erc1155"].copy()
    erc["ts_dt"] = pd.to_datetime(erc.ts, errors="coerce", utc=True)
    erc["ts_us"] = (erc.ts_dt.astype("int64") // 1000)  # ns -> us

    # Join asset → slug. Alchemy returns asset as HEX (0x...), lookup has decimal uint256.
    def to_dec(x):
        try:
            return str(int(x, 16)) if isinstance(x, str) and x.startswith("0x") else str(x)
        except Exception:
            return str(x)
    erc["asset_dec"] = erc.asset.map(to_dec)
    lookup = pd.read_parquet(LOOKUP)
    erc = erc.merge(
        lookup[["asset_id", "slug", "outcome"]].rename(columns={"asset_id": "_aid"}),
        left_on="asset_dec", right_on="_aid", how="left",
    ).drop(columns="_aid")

    # Filter to up-down markets
    cls = erc.slug.map(parse_slug)
    erc["mc"] = cls.map(lambda x: x[0])
    erc["asset_sym"] = cls.map(lambda x: x[1])
    erc["slot_start_s"] = cls.map(lambda x: x[2])
    erc = erc[erc.mc.fillna("").str.startswith("updown_")].copy()
    print(f"  {short}: {len(erc):,} ERC1155 up-down transfers")

    # Wallet's side: 'to' = received tokens (BUY/MINT), 'from' = sent tokens (SELL)
    # Determine if MINT/REDEEM (counterparty = 0x0 or CTF) vs trade (counterparty = matcher)
    erc["counterparty"] = erc.apply(
        lambda r: r["to"] if r.direction == "from" else r["from"], axis=1).str.lower()
    erc["is_mint"] = ((erc.direction == "to") &
                     (erc.counterparty.isin([ZERO, CTF]))).astype(bool)
    erc["is_redeem"] = ((erc.direction == "from") &
                       (erc.counterparty.isin([ZERO, CTF]))).astype(bool)
    erc["is_trade"] = ~(erc.is_mint | erc.is_redeem)
    erc["wallet_side"] = erc.direction.map({"to": "BUY", "from": "SELL"})

    print(f"    trades:   {int(erc.is_trade.sum()):>6}  ({100*erc.is_trade.mean():.1f}%)")
    print(f"    mints:    {int(erc.is_mint.sum()):>6}  ({100*erc.is_mint.mean():.1f}%)")
    print(f"    redeems:  {int(erc.is_redeem.sum()):>6}  ({100*erc.is_redeem.mean():.1f}%)")

    # Cap at max_fires (most recent) for speed
    trades = erc[erc.is_trade].sort_values("ts_us", ascending=False).head(max_fires).copy()
    print(f"    sampling top {len(trades)} most-recent trades for enrichment...")

    # Group slugs by asset for L25 loading
    by_asset = {a: set() for a in ("BTC", "ETH", "SOL")}
    for s in trades.slug.unique():
        m = SLUG_UD.match(s)
        if m: by_asset[m.group(1).upper()].add(s)

    print(f"    loading L25 for BTC={len(by_asset['BTC'])} ETH={len(by_asset['ETH'])} SOL={len(by_asset['SOL'])} slugs")
    bi = {}
    for a, sl in by_asset.items():
        if sl:
            bi[a] = load_orderbook_l25_streaming(a.lower(), slugs=sl, subsample_1hz=True)

    print("    loading binance + chainlink RTDS...")
    klines = {a: load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
              for a in ("BTC", "ETH", "SOL")}
    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}

    print(f"    enriching {len(trades)} trades...")
    rows = []
    for r in trades.itertuples(index=False):
        ts_us = int(r.ts_us)
        slug = r.slug
        outcome = r.outcome
        a = r.asset_sym

        # L25 book at fire time
        book_up = bi.get(a, {}).get((slug, "Up"))
        book_dn = bi.get(a, {}).get((slug, "Down"))
        def look(rec, t):
            if rec is None: return None
            ts_arr, ap, asz, bp, bsz = rec
            pos = int(np.searchsorted(ts_arr, t, side="right")) - 1
            if pos < 0: return None
            try:
                return {"ask": float(ap[pos][0]), "bid": float(bp[pos][0]),
                        "asz": float(asz[pos][0]), "bsz": float(bsz[pos][0]),
                        "dt_us": int(t - ts_arr[pos])}
            except (IndexError, ValueError, TypeError):
                return None
        bu = look(book_up, ts_us); bd = look(book_dn, ts_us)

        # Binance momentum at fire
        end_us, prices = klines[a]
        px_fire = asof_strict(end_us, prices, ts_us)
        px_30s  = asof_strict(end_us, prices, ts_us -  30_000_000)
        px_60s  = asof_strict(end_us, prices, ts_us -  60_000_000)
        px_120s = asof_strict(end_us, prices, ts_us - 120_000_000)
        def safelog(a, b):
            if a and b and a > 0 and b > 0:
                return float(np.log(a / b))
            return float("nan")
        ret_30s  = safelog(px_fire, px_30s)
        ret_60s  = safelog(px_fire, px_60s)
        ret_120s = safelog(px_fire, px_120s)

        # Chainlink RTDS
        rt_ts, rt_px = rtds[a]
        rtds_at_fire = asof_strict(rt_ts, rt_px, ts_us)
        rtds_60s = asof_strict(rt_ts, rt_px, ts_us - 60_000_000)
        rtds_ret_60s = safelog(rtds_at_fire, rtds_60s)

        # Sum of asks (mint-and-sell trigger metric)
        sum_asks = (bu["ask"] + bd["ask"]) if (bu and bd) else float("nan")

        rows.append({
            "ts_us": ts_us,
            "slug": slug,
            "outcome": outcome,
            "asset_sym": a,
            "mc": r.mc,
            "wallet_side": r.wallet_side,
            "tx_hash": r.tx_hash,
            "counterparty": r.counterparty,
            "shares": float(r.value),
            "offset_from_slot_start_s": (ts_us // 1_000_000) - int(r.slot_start_s),
            # Book state
            "own_ask": bu["ask"] if (bu and r.outcome == "Up")  else (bd["ask"] if bd else None),
            "own_bid": bu["bid"] if (bu and r.outcome == "Up")  else (bd["bid"] if bd else None),
            "own_asz": bu["asz"] if (bu and r.outcome == "Up")  else (bd["asz"] if bd else None),
            "own_bsz": bu["bsz"] if (bu and r.outcome == "Up")  else (bd["bsz"] if bd else None),
            "opp_ask": bd["ask"] if (bd and r.outcome == "Up")  else (bu["ask"] if bu else None),
            "opp_bid": bd["bid"] if (bd and r.outcome == "Up")  else (bu["bid"] if bu else None),
            "sum_asks": sum_asks,
            "sum_bids": (bu["bid"] + bd["bid"]) if (bu and bd) else float("nan"),
            "spread_own": (bu["ask"] - bu["bid"]) if (bu and r.outcome == "Up") else
                          ((bd["ask"] - bd["bid"]) if bd else float("nan")),
            # Signals
            "binance_px": px_fire,
            "binance_ret_30s":  ret_30s,
            "binance_ret_60s":  ret_60s,
            "binance_ret_120s": ret_120s,
            "rtds_px": rtds_at_fire,
            "rtds_ret_60s": rtds_ret_60s,
            "binance_vs_rtds_bp": (px_fire - rtds_at_fire) / rtds_at_fire * 10_000 if
                                    (px_fire and rtds_at_fire and rtds_at_fire > 0) else float("nan"),
        })
    df = pd.DataFrame(rows)
    out = CACHE / short / "fires_decoded.parquet"
    df.to_parquet(out, index=False)
    print(f"    saved -> {out}")
    return df


def trigger_report(df: pd.DataFrame, short: str):
    """Print summary stats per wallet — what conditions are present at fire?"""
    print(f"\n{'=' * 60}")
    print(f"=== {short} — trigger-condition signature ===")
    print(f"{'=' * 60}")
    if df.empty: return

    # Side breakdown
    print(f"\nside split (BUY = received tokens, SELL = sent tokens):")
    print(df.wallet_side.value_counts().to_string())

    # Counterparty breakdown (filter to most common)
    cp = df.counterparty.value_counts()
    print(f"\nTop 5 counterparties:")
    print(cp.head(5).to_string())

    # Sum of asks (mint-and-sell trigger condition)
    print(f"\nSum of asks (ask_up + ask_down) at fire:")
    print(df.sum_asks.describe(percentiles=[.1,.25,.5,.75,.9]).round(4).to_string())
    n_above_1 = (df.sum_asks > 1.0).sum()
    print(f"  fires when sum > $1.00: {n_above_1} ({100*n_above_1/len(df):.1f}%)")

    # Own side ask / bid
    print(f"\nOwn-side ASK at fire:")
    print(df.own_ask.describe(percentiles=[.1,.25,.5,.75,.9]).round(4).to_string())
    print(f"\nOwn-side BID at fire:")
    print(df.own_bid.describe(percentiles=[.1,.25,.5,.75,.9]).round(4).to_string())
    print(f"\nOwn-side SPREAD at fire:")
    print(df.spread_own.describe(percentiles=[.1,.25,.5,.75,.9]).round(4).to_string())

    # Offset from slot_start
    print(f"\nOffset from slot_start (seconds):")
    print(df.offset_from_slot_start_s.describe(percentiles=[.1,.25,.5,.75,.9]).round(0).to_string())
    # By tf
    for tf in ("updown_5m", "updown_15m"):
        sub = df[df.mc == tf]
        if len(sub) > 0:
            print(f"  {tf}: p25={sub.offset_from_slot_start_s.quantile(.25):.0f}s "
                  f"med={sub.offset_from_slot_start_s.median():.0f}s "
                  f"p75={sub.offset_from_slot_start_s.quantile(.75):.0f}s")

    # Binance signal
    print(f"\nBinance ret_2m_pre_fire (×10000, basis points):")
    bp = (df.binance_ret_120s * 10_000).dropna()
    if len(bp):
        print(bp.describe(percentiles=[.1,.25,.5,.75,.9]).round(2).to_string())
        # Side-conditional
        for s in ("BUY", "SELL"):
            sub = df[df.wallet_side == s]
            br = (sub.binance_ret_120s * 10_000).dropna()
            if len(br):
                print(f"  {s} fires: med ret_2m = {br.median():+.2f} bp")

    # Binance vs RTDS basis
    print(f"\nBinance-vs-RTDS basis at fire (bp):")
    basis = df.binance_vs_rtds_bp.dropna()
    if len(basis):
        print(basis.describe(percentiles=[.1,.25,.5,.75,.9]).round(2).to_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-fires", type=int, default=3000)
    args = ap.parse_args()

    WALLETS = {
        "0xeebde7a0": "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
        "0xce25e214": "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
        "0x89b5cdaa": "0x89b5cdaaa4866c1e738406712012a630b4078beb",
        "0xcfb103c3": "0xcfb103c37c0234f524c632d964ed31f117b5f694",
        "0x04b6d7e9": "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
    }
    targets = WALLETS.values() if args.all else (args.wallet or [])
    for w in targets:
        try:
            df = decode_wallet(w, max_fires=args.max_fires)
            if not df.empty:
                trigger_report(df, w.lower()[:10])
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"ERROR on {w}: {e}")


if __name__ == "__main__":
    main()
