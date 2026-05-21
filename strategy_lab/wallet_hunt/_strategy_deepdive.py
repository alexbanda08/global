"""Per-wallet strategy deep-dive.

For each wallet, joins fires_decoded.parquet to canonical resolutions to
compute the wallet's actual edge:
  - WR by side (Up vs Dn picks)
  - WR vs implied probability (was their ask cheaper than realized prob?)
  - Realized PnL per fire (using HOLD-to-settlement assumption)
  - Correlation of side picked with binance / RTDS direction at fire
  - Time-of-day pattern
  - Trade size distribution

Strategy fingerprint output: cache/<short>/strategy_deepdive.json

Usage:  py -3 -X utf8 strategy_lab/wallet_hunt/_strategy_deepdive.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import (  # noqa: E402
    load_resolutions, add_ws_s, load_chainlink_asof, asof_strict,
)

import re as _re

SLUG_RE = _re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")
WINDOW_S = {"5m": 300, "15m": 900}


def derive_outcome_from_chainlink(slug: str, rtds_cache: dict) -> str | None:
    """Compute Up/Down outcome from chainlink RTDS for slugs not in canonical
    resolutions yet (recent markets)."""
    m = SLUG_RE.match(slug)
    if not m:
        return None
    asset = m.group(1).upper()
    tf = m.group(2)
    slot_start = int(m.group(3))
    slot_end = slot_start + WINDOW_S[tf]

    ts_arr, px_arr = rtds_cache.get(asset, (None, None))
    if ts_arr is None or len(ts_arr) == 0:
        return None
    strike = asof_strict(ts_arr, px_arr, slot_start * 1_000_000)
    settle = asof_strict(ts_arr, px_arr, slot_end * 1_000_000)
    if not (strike > 0 and settle > 0):
        return None
    return "Up" if settle > strike else "Down"

CACHE = Path(__file__).resolve().parent / "cache"

# 9 user-provided wallets
TARGETS = [
    "0x7f599984", "0xb27bc932", "0xa0a50783", "0x3e6bfd2f",
    "0xeefe46de", "0x0fe40e88", "0x9dae874a", "0xcfb103c3", "0x89b5cdaa",
]

# Real Polymarket fee curve (per strategy_lab/fees.py)
FEE_RATE = 0.07  # crypto markets


def real_taker_fee_per_share(p: float) -> float:
    if not (0 < p < 1):
        return 0.0
    return FEE_RATE * p * (1.0 - p)


def hold_pnl_per_share(entry_px: float, won: bool) -> float:
    """Per-share PnL assuming buy at ask, hold to chainlink resolution.

    Win:  receive $1 - entry_px - fee(entry)
    Loss: -entry_px - fee(entry)
    """
    fee = real_taker_fee_per_share(entry_px)
    if won:
        return 1.0 - entry_px - fee
    return -entry_px - fee


def load_universe_outcomes():
    """slug → outcome (Up/Down chainlink-derived). Pre-loads canonical
    resolutions; falls back to chainlink RTDS for newer slugs."""
    res = load_resolutions()
    res = add_ws_s(res)
    canon_outcomes = dict(zip(res["slug"], res["outcome"]))
    rtds_cache = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}
    return canon_outcomes, rtds_cache


def lookup_outcome(slug: str, canon: dict, rtds: dict) -> str | None:
    """First check canonical, fallback to chainlink-derived."""
    o = canon.get(slug)
    if o is not None:
        return o
    return derive_outcome_from_chainlink(slug, rtds)


def deepdive(short: str, canon_outcomes: dict, rtds_cache: dict) -> dict:
    p = CACHE / short / "fires_decoded.parquet"
    if not p.exists():
        return {"short": short, "error": "no fires_decoded"}
    fd = pd.read_parquet(p)
    if fd.empty:
        return {"short": short, "error": "empty"}

    fd = fd.copy()
    # Determine wallet's actual entry price + execution side
    # If wallet_side == "BUY"  → they paid own_ask (taker on ask)
    # If wallet_side == "SELL" → they got own_bid (taker on bid)
    fd["entry_px"] = np.where(
        fd["wallet_side"] == "BUY", fd["own_ask"], fd["own_bid"]
    )
    fd["is_taker_on_ask"] = (fd["wallet_side"] == "BUY") & fd["own_ask"].notna()
    fd["is_taker_on_bid"] = (fd["wallet_side"] == "SELL") & fd["own_bid"].notna()

    # Drop rows where entry_px is NaN (settlement / redeem events)
    fd = fd[fd["entry_px"].notna() & (fd["entry_px"] > 0) & (fd["entry_px"] < 1)].copy()
    if fd.empty:
        return {"short": short, "error": "no valid taker entries"}

    # Join to outcomes (canonical first, chainlink fallback)
    fd["winner"] = fd["slug"].apply(
        lambda s: lookup_outcome(s, canon_outcomes, rtds_cache)
    )
    fd = fd[fd["winner"].notna()].copy()
    if fd.empty:
        return {"short": short, "error": "no resolved slugs in sample"}

    # Compute won for BUY events (where they bought a side and held)
    fd["won"] = (fd["outcome"] == fd["winner"])

    # PnL per share (HOLD policy: buy, hold to settlement, eat fee on entry)
    fd["pnl_per_share"] = fd.apply(
        lambda r: hold_pnl_per_share(r["entry_px"], bool(r["won"])), axis=1
    )
    fd["pnl_usd"] = fd["pnl_per_share"] * fd["shares"]

    # Restrict to BUY-side fires for the directional analysis
    buys = fd[fd["wallet_side"] == "BUY"].copy()
    sells = fd[fd["wallet_side"] == "SELL"].copy()

    def _pct(b: bool) -> float:
        return 100.0 * float(b)

    # Per-side WR
    by_side = {}
    for side_name in ("Up", "Down"):
        sub = buys[buys["outcome"] == side_name]
        if not sub.empty:
            by_side[side_name] = {
                "n": int(len(sub)),
                "wr": round(float(sub["won"].mean()), 4),
                "mean_entry_px": round(float(sub["entry_px"].mean()), 4),
                "mean_shares": round(float(sub["shares"].mean()), 2),
                "total_usd_in": round(float((sub["entry_px"] * sub["shares"]).sum()), 2),
                "realized_pnl_hold": round(float(sub["pnl_usd"].sum()), 2),
            }

    # By entry price bucket
    bins = [0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.01]
    buys["px_bin"] = pd.cut(buys["entry_px"], bins, include_lowest=True)
    by_px = buys.groupby("px_bin", observed=True).agg(
        n=("won", "size"),
        wr=("won", "mean"),
        breakeven_px=("entry_px", "mean"),
        edge_pp=("won", lambda x: 0.0),  # placeholder
        mean_shares=("shares", "mean"),
        pnl_hold=("pnl_usd", "sum"),
    )
    by_px["edge_pp"] = (by_px["wr"] - by_px["breakeven_px"]) * 100
    by_px_summary = {
        str(k): {
            "n": int(v["n"]),
            "wr": round(float(v["wr"]), 4),
            "mean_entry": round(float(v["breakeven_px"]), 4),
            "edge_pp": round(float(v["edge_pp"]), 2),
            "pnl_hold": round(float(v["pnl_hold"]), 2),
        } for k, v in by_px.iterrows()
    }

    # Binance signal correlation
    # Does the wallet pick the side that matches binance momentum?
    has_sig = buys["binance_ret_60s"].notna()
    sig_sub = buys[has_sig].copy()
    if not sig_sub.empty:
        # Did they pick Up when ret_60s > 0?
        sig_sub["binance_up"] = sig_sub["binance_ret_60s"] > 0
        sig_sub["picked_up"] = sig_sub["outcome"] == "Up"
        sig_sub["matches_binance"] = sig_sub["binance_up"] == sig_sub["picked_up"]
        binance_match_pct = round(float(sig_sub["matches_binance"].mean()), 4)
        # WR when they match vs not
        matched = sig_sub[sig_sub["matches_binance"]]
        contrary = sig_sub[~sig_sub["matches_binance"]]
        binance_signal = {
            "n_with_binance": int(len(sig_sub)),
            "matches_binance_pct": binance_match_pct,
            "wr_when_match": round(float(matched["won"].mean()), 4) if not matched.empty else None,
            "wr_when_contrary": round(float(contrary["won"].mean()), 4) if not contrary.empty else None,
        }
    else:
        binance_signal = {}

    # Offset distribution (when in the slug do they fire?)
    offset_stats = {
        "mean": round(float(buys["offset_from_slot_start_s"].mean()), 1),
        "median": round(float(buys["offset_from_slot_start_s"].median()), 1),
        "p10": round(float(buys["offset_from_slot_start_s"].quantile(0.1)), 1),
        "p90": round(float(buys["offset_from_slot_start_s"].quantile(0.9)), 1),
    }

    # Per-slug aggregation
    per_slug = buys.groupby("slug").agg(
        n_fires=("won", "size"),
        n_distinct_sides=("outcome", "nunique"),
    )
    slug_stats = {
        "n_slugs": int(len(per_slug)),
        "median_fires_per_slug": int(per_slug["n_fires"].median()),
        "p90_fires_per_slug": int(per_slug["n_fires"].quantile(0.9)),
        "frac_slugs_both_sides": round(float((per_slug["n_distinct_sides"] >= 2).mean()), 4),
    }

    # Counterparty distribution
    top_ctr = (
        buys["counterparty"]
        .value_counts(normalize=True)
        .head(5)
        .round(3)
        .to_dict()
    )

    # Aggregate summary
    total_in_usd = float((buys["entry_px"] * buys["shares"]).sum())
    total_pnl_hold = float(buys["pnl_usd"].sum())
    overall = {
        "short": short,
        "n_buys": int(len(buys)),
        "n_sells": int(len(sells)),
        "n_resolved_slugs_in_sample": int(buys["slug"].nunique()),
        "buy_wr": round(float(buys["won"].mean()), 4),
        "mean_entry_px": round(float(buys["entry_px"].mean()), 4),
        "median_entry_px": round(float(buys["entry_px"].median()), 4),
        "mean_shares": round(float(buys["shares"].mean()), 2),
        "median_shares": round(float(buys["shares"].median()), 2),
        "total_usd_deployed_in_sample": round(total_in_usd, 2),
        "realized_pnl_hold_in_sample": round(total_pnl_hold, 2),
        "pnl_per_$_deployed": round(total_pnl_hold / total_in_usd, 4) if total_in_usd > 0 else 0,
        "side_breakdown": by_side,
        "by_entry_price_bucket": by_px_summary,
        "binance_signal_correlation": binance_signal,
        "fire_offset_seconds": offset_stats,
        "slug_density": slug_stats,
        "top_counterparties": top_ctr,
    }
    return overall


def main():
    print("Loading canonical resolutions + chainlink RTDS...")
    canon, rtds = load_universe_outcomes()
    print(f"  {len(canon)} resolved slugs in canonical")
    for a in ("BTC", "ETH", "SOL"):
        print(f"  chainlink {a}: {len(rtds[a][0])} ticks")

    results = {}
    for s in TARGETS:
        print(f"\n=== {s} ===")
        r = deepdive(s, canon, rtds)
        if "error" in r:
            print(f"  SKIP: {r['error']}")
            results[s] = r
            continue

        # Save individual deepdive
        out_path = CACHE / s / "strategy_deepdive.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(r, indent=2, default=str))

        # Print compact summary
        print(f"  n_buys={r['n_buys']}  buy_WR={r['buy_wr']*100:.2f}%  "
              f"mean_entry=${r['mean_entry_px']:.3f}  "
              f"mean_shares={r['mean_shares']:.1f}")
        print(f"  total_USD_in=${r['total_usd_deployed_in_sample']:.0f}  "
              f"realized_PnL(HOLD)=${r['realized_pnl_hold_in_sample']:+.2f}  "
              f"PnL/$=${r['pnl_per_$_deployed']:+.4f}")
        if r['binance_signal_correlation']:
            bsc = r['binance_signal_correlation']
            print(f"  binance signal: match_pct={bsc['matches_binance_pct']*100:.1f}%  "
                  f"WR(match)={bsc.get('wr_when_match', 0):.2f}  "
                  f"WR(contrary)={bsc.get('wr_when_contrary', 0):.2f}")
        for side, ss in r['side_breakdown'].items():
            print(f"  {side:5s}: n={ss['n']:4d}  WR={ss['wr']*100:.2f}%  "
                  f"mean_entry=${ss['mean_entry_px']:.3f}  "
                  f"pnl=${ss['realized_pnl_hold']:+.2f}")
        offs = r['fire_offset_seconds']
        print(f"  offset_s: median={offs['median']}  p10={offs['p10']}  p90={offs['p90']}")
        ss = r['slug_density']
        print(f"  slugs: n={ss['n_slugs']}  med_fires/slug={ss['median_fires_per_slug']}  "
              f"p90={ss['p90_fires_per_slug']}  both_sides_pct={ss['frac_slugs_both_sides']*100:.1f}%")
        results[s] = r

    # Save combined
    combined_path = CACHE / "_strategy_deepdive_all.json"
    combined_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nsaved -> {combined_path}")


if __name__ == "__main__":
    main()
