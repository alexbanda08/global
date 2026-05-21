"""Decode the WALLET's side-picking strategy + compute realized PnL using CLOB winners.

Hypothesis tested:
  H1: He buys whichever side matches binance price momentum at slot_start
  H2: He buys whichever side has higher Polymarket mid at first trade
  H3: Picks Up/Down randomly (null)

PnL = sum over legs of:
   leftover_shares × payoff   where payoff = $1 if his outcome won else $0
   MINUS the cost basis (avg_buy_px × leftover_shares).
"""
from __future__ import annotations
import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_klines_asof, asof_strict  # noqa: E402
from fees import poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    args = ap.parse_args()
    short = args.wallet.lower()[:10]

    per_leg = pd.read_parquet(CACHE / f"{short}_per_leg.parquet")
    trades  = pd.read_parquet(CACHE / f"{short}_trades.parquet")
    print(f"=== {len(per_leg)} legs to analyze")

    # 1) Resolve winners — try CLOB cache first, fall back to canonical chainlink
    try:
        canon = load_resolutions(source="upstream", with_clob_winner=True,
                                  assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
        win_col = "clob_winner" if "clob_winner" in canon.columns else "outcome"
        winners = canon.set_index("market_id")[win_col].to_dict()
        truth_label = win_col
        print(f"=== Using {truth_label} from canonical (rows={len(winners):,})")
    except Exception as e:
        print(f"  canonical load failed: {e}")
        winners = {}
        truth_label = "none"

    # 2) Map each leg's conditionId to winner
    per_leg["winner"] = per_leg.conditionId.map(winners)
    per_leg["resolved"] = per_leg.winner.notna()
    per_leg["won"] = per_leg.resolved & (per_leg.winner == per_leg.outcome)
    n_res = per_leg.resolved.sum()
    print(f"=== {n_res}/{len(per_leg)} legs have a resolved winner ({100*n_res/len(per_leg):.1f}%)")

    # 3) Compute PnL per leg
    #    Cost = buy_shares × avg_buy_px      (already paid)
    #    Settlement value = leftover_shares × (1 if won else 0)
    #    Realized so far = (sells_px - buys_px) × matched_shares  (already in per_leg)
    #    Plus fee. Note he's a TAKER on every fill.
    per_leg["leftover_value_at_settle"] = np.where(
        per_leg.resolved,
        per_leg.leftover_shares * np.where(per_leg.won, 1.0, 0.0),
        np.nan,   # unresolved → mark-to-market separately
    )
    per_leg["leftover_cost_basis"] = per_leg.avg_buy_px * per_leg.leftover_shares
    per_leg["leftover_pnl_at_settle"] = per_leg.leftover_value_at_settle - per_leg.leftover_cost_basis

    # Real polymarket fees on every fill: shares × 0.07 × p × (1-p)
    # Approximation: at avg_buy_px → fee = buy_shares × 0.07 × p × (1-p)
    per_leg["entry_fees"] = per_leg.buy_shares * per_leg.avg_buy_px.apply(
        lambda p: poly_taker_fee_per_share(p, FEE_RATE) if pd.notna(p) else 0
    )
    per_leg["total_pnl_net"] = per_leg.realized_pnl + per_leg.leftover_pnl_at_settle - per_leg.entry_fees

    print(f"\n=== Per-leg PnL summary (resolved markets only) ===")
    res = per_leg[per_leg.resolved]
    print(f"  legs:           {len(res)}")
    print(f"  won legs:       {res.won.sum()} ({100*res.won.mean():.1f}%)")
    print(f"  cost basis (leftover):    ${res.leftover_cost_basis.sum():>10.2f}")
    print(f"  settlement value:         ${res.leftover_value_at_settle.sum():>10.2f}")
    print(f"  leftover PnL (gross):     ${res.leftover_pnl_at_settle.sum():>10.2f}")
    print(f"  entry fees (poly curve):  ${res.entry_fees.sum():>10.2f}")
    print(f"  net PnL after fees:       ${(res.leftover_pnl_at_settle - res.entry_fees).sum():>10.2f}")
    print(f"  mean PnL per leg:         ${(res.leftover_pnl_at_settle - res.entry_fees).mean():.4f}")
    print()
    print("=== PnL by market_class ===")
    for tf in ("updown_5m", "updown_15m"):
        sub = res[res.market_class == tf]
        if len(sub) == 0: continue
        pnl_total = (sub.leftover_pnl_at_settle - sub.entry_fees).sum()
        print(f"  {tf}: n={len(sub)} won%={sub.won.mean()*100:.1f}  "
              f"pnl=${pnl_total:.2f}  pnl/leg=${pnl_total/len(sub):.4f}")
    print()
    print("=== PnL by asset ===")
    for a in ("BTC", "ETH", "SOL"):
        sub = res[res.mkt_asset == a]
        if len(sub) == 0: continue
        pnl_total = (sub.leftover_pnl_at_settle - sub.entry_fees).sum()
        print(f"  {a}: n={len(sub)} won%={sub.won.mean()*100:.1f}  "
              f"pnl=${pnl_total:.2f}")
    print()

    # 4) Side-picking strategy decode — H1 binance momentum
    klines = {a: load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
              for a in ("BTC", "ETH", "SOL")}
    res = res.copy()
    res["px_at_slot_start"] = res.apply(
        lambda r: asof_strict(*klines[r.mkt_asset], int(r.slot_start_s) * 1_000_000),
        axis=1,
    )
    res["px_2m_before"] = res.apply(
        lambda r: asof_strict(*klines[r.mkt_asset], (int(r.slot_start_s) - 120) * 1_000_000),
        axis=1,
    )
    res["ret_2m_pre"] = np.log(res.px_at_slot_start / res.px_2m_before)
    res["binance_says"] = np.where(res.ret_2m_pre > 0, "Up", "Down")
    res["matches_binance"] = res.outcome == res.binance_says

    # Same anchor as our momo (using slot_start as anchor for a 5m window)
    # but here we want pre-window momentum: ret over [slot_start - 120, slot_start]
    # which is what production uses (ws_s = slot_start - window_s would give us prev slot)
    # For analysis, let's compare both anchors:
    print("=== H1: does he buy the side that binance momentum predicted? ===")
    valid = res.dropna(subset=["binance_says"])
    print(f"  legs evaluable: {len(valid)}")
    print(f"  he picked Up:   {(valid.outcome == 'Up').sum()}")
    print(f"  he picked Down: {(valid.outcome == 'Down').sum()}")
    print(f"  binance up:     {(valid.binance_says == 'Up').sum()}")
    print(f"  binance down:   {(valid.binance_says == 'Down').sum()}")
    print(f"  match binance:  {valid.matches_binance.sum()}/{len(valid)} "
          f"({100*valid.matches_binance.mean():.1f}%)")
    print()
    # WR by match status
    for label, mask in [("his pick matches binance", valid.matches_binance),
                         ("his pick contradicts binance", ~valid.matches_binance)]:
        sub = valid[mask]
        if len(sub):
            print(f"  WR when {label}: {sub.won.mean()*100:.1f}% ({sub.won.sum()}/{len(sub)})")
    print()

    # 5) Per-side trade timing (do early or late trades win more?)
    # offset distribution split by won/lost
    print("=== Average trade offset per leg, by outcome ===")
    avg_off = trades.groupby("conditionId").apply(
        lambda g: (g.timestamp - g.timestamp.min()).mean()
    ).to_dict()
    res["avg_offset_into_window"] = res.conditionId.map(avg_off)
    for w in (True, False):
        sub = res[res.won == w]
        if len(sub):
            tag = "WON" if w else "LOST"
            print(f"  {tag}: legs={len(sub)} avg_offset={sub.avg_offset_into_window.mean():.0f}s "
                  f"(first_offset mean={sub.first_offset.mean():.0f}s, "
                  f"last_offset mean={sub.last_offset.mean():.0f}s)")

    # Save annotated per-leg
    res.to_parquet(CACHE / f"{short}_per_leg_resolved.parquet", index=False)
    print(f"\n--> annotated per-leg saved: {CACHE / f'{short}_per_leg_resolved.parquet'}")


if __name__ == "__main__":
    main()
