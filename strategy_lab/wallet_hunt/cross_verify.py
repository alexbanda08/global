"""Cross-verify wallet chain fills against our local data.

For each wallet trade on a BTC/ETH/SOL up-down 5m/15m market:
  1. Look up L25 book at the fill timestamp → verify the chain decoder's
     side + price match the actual ask/bid the wallet hit.
  2. Look up binance kline at fire time → compute the ret_2m signal we'd
     see, check if wallet's side correlates with momentum.
  3. Look up chainlink RTDS at fire time + resolution → see if the wallet
     "picked the side that won" relative to the oracle.

Produces per-wallet enrichment + a cross-validation summary.

Usage:
  py -3 strategy_lab/wallet_hunt/cross_verify.py --wallet 0x...
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_chainlink_asof,
    load_orderbook_l25_streaming, asof_strict, slug_to_ws_s,
)

CACHE = Path(__file__).resolve().parent / "cache"

SLUG_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")


def _classify(slug):
    if not isinstance(slug, str):
        return (None, None, None)
    m = SLUG_UD.match(slug)
    if m:
        return (f"updown_{m.group(2)}", m.group(1).upper(), int(m.group(3)))
    return (None, None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    ap.add_argument("--max-slugs", type=int, default=80,
                    help="cap unique slugs to look up (book loading is heavy)")
    args = ap.parse_args()
    w = args.wallet.lower()
    short = w[:10]

    enriched_p = CACHE / short / "trades_chain_enriched.parquet"
    if not enriched_p.exists():
        print(f"missing {enriched_p}; run analyze_chain.py first")
        return 1
    trades = pd.read_parquet(enriched_p)

    # Filter to UD markets with valid decode
    cls = trades.slug.map(_classify)
    trades["mc"] = cls.map(lambda x: x[0])
    trades["asset_sym"] = cls.map(lambda x: x[1])
    trades["slot_start_s"] = cls.map(lambda x: x[2])

    ud = trades[
        trades.mc.fillna("").str.startswith("updown_")
        & trades.side_clean.notna()
        & trades.price_clean.between(0, 1, inclusive="neither")
        & trades.timestamp.notna()
    ].copy()
    print(f"=== {short}: {len(ud):,} valid up-down fills after decode filter")

    # Choose top-N slugs by trade count for deep cross-verify (book load is heavy)
    slug_counts = ud.slug.value_counts()
    top_slugs = list(slug_counts.head(args.max_slugs).index)
    sub = ud[ud.slug.isin(top_slugs)].copy()
    print(f"  cross-verify focusing on top {len(top_slugs)} slugs ({len(sub)} fills)")

    # ---- 1. Load L25 books for these slugs (one stream per asset) ----
    by_asset = {a: set() for a in ("BTC", "ETH", "SOL")}
    for s in top_slugs:
        m = SLUG_UD.match(s)
        if m:
            by_asset[m.group(1).upper()].add(s)
    print(f"  L25 lookup: BTC={len(by_asset['BTC'])} "
          f"ETH={len(by_asset['ETH'])} SOL={len(by_asset['SOL'])} slugs")

    book_indexes = {}
    for asset_sym, slugs in by_asset.items():
        if not slugs:
            continue
        print(f"  loading {asset_sym} L25 books...")
        bi = load_orderbook_l25_streaming(asset_sym.lower(), slugs=slugs, subsample_1hz=True)
        book_indexes[asset_sym] = bi
        print(f"    -> {len(bi)} (slug, outcome) streams")

    # ---- 2. Load binance klines + chainlink RTDS once per asset ----
    print("  loading binance klines + chainlink RTDS...")
    klines = {a: load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
              for a in ("BTC", "ETH", "SOL")}
    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}

    # ---- 3. Per-fill enrichment ----
    def find_book_at(asset_sym, slug, outcome, ts_us):
        bi = book_indexes.get(asset_sym, {})
        rec = bi.get((slug, outcome))
        if rec is None:
            return None
        ts_arr, ap, asz, bp, bsz = rec
        pos = int(np.searchsorted(ts_arr, ts_us, side="right")) - 1
        if pos < 0:
            return None
        return {
            "book_ts_us":  int(ts_arr[pos]),
            "dt_us":       int(ts_us - ts_arr[pos]),
            "best_ask":    float(ap[pos][0]) if np.isfinite(ap[pos][0]) else float("nan"),
            "best_bid":    float(bp[pos][0]) if np.isfinite(bp[pos][0]) else float("nan"),
            "ask_sz_0":    float(asz[pos][0]),
            "bid_sz_0":    float(bsz[pos][0]),
        }

    rows = []
    n_no_book = 0
    for r in sub.itertuples(index=False):
        ts_s = int(r.timestamp)
        ts_us = ts_s * 1_000_000
        slot_start = int(r.slot_start_s)
        asset_sym = r.asset_sym
        outcome = r.outcome  # Up / Down

        # Production-anchor ret_2m at fire (use OUR canonical ws_s convention)
        tf = "5m" if r.mc == "updown_5m" else "15m"
        try:
            ws_s = slug_to_ws_s(r.slug, tf)
        except Exception:
            ws_s = None

        # Binance prices
        end_us, prices = klines[asset_sym]
        px_at_fire = asof_strict(end_us, prices, ts_us)
        px_at_slot_start = asof_strict(end_us, prices, slot_start * 1_000_000)
        px_2m_pre = asof_strict(end_us, prices, (slot_start - 120) * 1_000_000)
        ret_2m_pre = float("nan")
        if px_at_slot_start and px_2m_pre and px_at_slot_start > 0 and px_2m_pre > 0:
            ret_2m_pre = float(np.log(px_at_slot_start / px_2m_pre))

        # RTDS oracle at fire
        rt_ts, rt_px = rtds[asset_sym]
        rtds_at_fire = asof_strict(rt_ts, rt_px, ts_us)

        # Book lookup
        book = find_book_at(asset_sym, r.slug, outcome, ts_us)
        if book is None:
            n_no_book += 1
            book = {"book_ts_us": None, "dt_us": None,
                    "best_ask": float("nan"), "best_bid": float("nan"),
                    "ask_sz_0": 0.0, "bid_sz_0": 0.0}

        # Decoder verification: did the wallet's reported fill price match the
        # book ask/bid at that moment?
        fp = float(r.price_clean)
        mid = (book["best_ask"] + book["best_bid"]) / 2 if (
            np.isfinite(book["best_ask"]) and np.isfinite(book["best_bid"])) else float("nan")
        side = r.side_clean
        if side == "BUY":
            # Should fill at/near best_ask
            decoder_diff = fp - book["best_ask"] if np.isfinite(book["best_ask"]) else float("nan")
        else:
            # Should fill at/near best_bid
            decoder_diff = fp - book["best_bid"] if np.isfinite(book["best_bid"]) else float("nan")

        # Signal alignment: did wallet pick side that matched binance momentum?
        binance_says = None
        if not np.isnan(ret_2m_pre):
            binance_says = "Up" if ret_2m_pre > 0 else "Down"
        matches_binance = (binance_says == outcome) if binance_says else None

        rows.append({
            "ts_s":          ts_s,
            "slug":          r.slug,
            "asset_sym":     asset_sym,
            "mc":            r.mc,
            "outcome":       outcome,
            "side":          side,
            "fill_price":    fp,
            "fill_size":     float(r.size_clean),
            "fill_usd":      float(r.usd_clean),
            "wallet_maker":  bool(r.wallet_is_maker),
            "book_ask":      book["best_ask"],
            "book_bid":      book["best_bid"],
            "book_mid":      mid,
            "book_spread":   (book["best_ask"] - book["best_bid"]) if (
                              np.isfinite(book["best_ask"]) and np.isfinite(book["best_bid"])) else float("nan"),
            "book_dt_us":    book["dt_us"],
            "decoder_diff":  decoder_diff,
            "offset_from_slot_start_s": ts_s - slot_start,
            "ret_2m_pre":    ret_2m_pre,
            "binance_says":  binance_says,
            "matches_binance": matches_binance,
            "binance_px_fire": px_at_fire,
            "rtds_px_fire":    rtds_at_fire,
        })
    print(f"  fills with no book match: {n_no_book}/{len(sub)}")

    enr = pd.DataFrame(rows)
    out_path = CACHE / short / "fills_cross_verified.parquet"
    enr.to_parquet(out_path, index=False)
    print(f"  saved -> {out_path}")

    # ---- 4. Cross-verify report ----
    print(f"\n=== Decoder validation (fills with valid book lookup) ===")
    valid = enr[enr.book_ask.notna()].copy()
    print(f"  valid fills:          {len(valid)} / {len(enr)}")
    print(f"  abs(decoder_diff) stats:")
    print(f"    p50 = {valid.decoder_diff.abs().median():.4f}")
    print(f"    p90 = {valid.decoder_diff.abs().quantile(0.90):.4f}")
    print(f"    p99 = {valid.decoder_diff.abs().quantile(0.99):.4f}")
    print(f"  fills within ±$0.01 of book: {(valid.decoder_diff.abs() <= 0.01).mean()*100:.1f}%")
    print(f"  fills within ±$0.05 of book: {(valid.decoder_diff.abs() <= 0.05).mean()*100:.1f}%")

    print(f"\n=== Maker vs Taker (from wallet_is_maker flag) ===")
    print(f"  maker_pct: {100 * valid.wallet_maker.mean():.1f}%")
    print(f"  maker fills' fill_price vs mid: avg = {(valid[valid.wallet_maker].fill_price - valid[valid.wallet_maker].book_mid).mean():.4f}")
    print(f"  taker fills' fill_price vs ask (BUYs) or bid (SELLs): see decoder_diff above")

    print(f"\n=== Spread observed at fill time ===")
    sp = valid.book_spread.dropna()
    if len(sp):
        print(f"  spread p25={sp.quantile(0.25):.4f}  med={sp.median():.4f}  "
              f"p75={sp.quantile(0.75):.4f}  p95={sp.quantile(0.95):.4f}")

    print(f"\n=== Signal alignment (binance ret_2m_pre vs wallet side) ===")
    valid_sig = enr.dropna(subset=["matches_binance"])
    if len(valid_sig):
        print(f"  evaluable fills: {len(valid_sig)}")
        wb = valid_sig[valid_sig.matches_binance == True]
        cb = valid_sig[valid_sig.matches_binance == False]
        print(f"  picks MATCHING binance momentum:   {len(wb)} ({100*len(wb)/len(valid_sig):.1f}%)")
        print(f"  picks CONTRADICTING binance momentum: {len(cb)} ({100*len(cb)/len(valid_sig):.1f}%)")
        # Also split by side (BUY = bullish on outcome, SELL = bearish)
        for side in ("BUY", "SELL"):
            s = valid_sig[valid_sig.side == side]
            if len(s):
                pct_match = 100 * s.matches_binance.mean()
                print(f"    {side}s: {len(s)} fills, {pct_match:.1f}% match binance")

    print(f"\n=== Per market_class breakdown ===")
    for mc in ("updown_5m", "updown_15m"):
        sub = valid[valid.mc == mc]
        if len(sub) == 0: continue
        print(f"  {mc}: n={len(sub)} maker_pct={100*sub.wallet_maker.mean():.1f}% "
              f"med_spread={sub.book_spread.median():.4f} "
              f"med_offset_from_slot_start={int(sub.offset_from_slot_start_s.median())}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
