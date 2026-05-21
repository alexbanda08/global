"""Policy comparison v2 — runs on v2 scanner output at $2.5 notional.

Reads `mint_and_sell_v2_<cell>_<date>/opportunities.parquet`, samples N
fires per cell, computes HOLD/MARKET_EXIT/HYBRID PnL with corrected fee
model, extrapolates $/day using full opportunity count.

Key difference from v1 policy compare:
  - reads v2 directory (corrected fee math, sum_asks >= 1.005, cooldown 1s)
  - default notional $2.5
  - extrapolates $/day = (sample_total / sample_n) * total_n / window_days
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from fees import (  # noqa: E402
    poly_taker_fee_per_share,
    poly_maker_rebate_per_share,
    bps_to_rate,
    DEFAULT_CRYPTO_FEE_BPS,
)

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
FILL_WAIT_S = 60
HYBRID_BID_ASK_THRESH = 0.97


def fill_status_and_exit_bid(ts_arr, ap_arr, bp_arr,
                              target_ask: float,
                              start_us: int,
                              wait_s: int = FILL_WAIT_S):
    target_us = start_us + wait_s * 1_000_000
    mask = (ts_arr >= start_us) & (ts_arr <= target_us)
    if not mask.any():
        return False, float("nan")
    idx = np.where(mask)[0]
    filled = False
    exit_bid = float("nan")
    for i in idx:
        if len(bp_arr[i]) == 0:
            continue
        bb = float(bp_arr[i][0])
        if not np.isfinite(bb):
            continue
        exit_bid = bb
        if bb >= target_ask:
            filled = True
    return filled, exit_bid


def evaluate_opportunity(row, fill_up, fill_dn, exit_bid_up, exit_bid_dn,
                          outcome: str, notional: float,
                          hybrid_thresh: float = HYBRID_BID_ASK_THRESH):
    n = notional
    au = float(row.ask_up); ad = float(row.ask_dn)
    mint_cost = n * 1.0

    reb_u = n * poly_maker_rebate_per_share(au, FEE_RATE) if fill_up else 0.0
    reb_d = n * poly_maker_rebate_per_share(ad, FEE_RATE) if fill_dn else 0.0
    cash_from_filled = (n * au if fill_up else 0.0) + (n * ad if fill_dn else 0.0)

    if fill_up and fill_dn:
        pnl = cash_from_filled + reb_u + reb_d - mint_cost
        return dict(
            scenario="BOTH", pnl_hold=pnl, pnl_market_exit=pnl, pnl_hybrid=pnl,
            held_won=None, exit_bid=float("nan"), exit_ratio=float("nan"),
        )

    if not fill_up and not fill_dn:
        return dict(
            scenario="NEITHER", pnl_hold=0.0, pnl_market_exit=0.0, pnl_hybrid=0.0,
            held_won=None, exit_bid=float("nan"), exit_ratio=float("nan"),
        )

    if fill_up:
        held_side = "Down"; held_ask = ad; held_bid = exit_bid_dn
    else:
        held_side = "Up"; held_ask = au; held_bid = exit_bid_up
    held_won = (outcome == held_side)

    held_redeem = n * (1.0 if held_won else 0.0)
    pnl_hold = cash_from_filled + reb_u + reb_d + held_redeem - mint_cost

    if np.isfinite(held_bid) and held_bid > 0:
        exit_cash = n * held_bid
        exit_fee = n * poly_taker_fee_per_share(held_bid, FEE_RATE)
        pnl_market_exit = cash_from_filled + reb_u + reb_d + exit_cash - exit_fee - mint_cost
        exit_ratio = held_bid / held_ask if held_ask > 0 else float("nan")
    else:
        pnl_market_exit = pnl_hold
        exit_ratio = float("nan")

    if np.isfinite(exit_ratio) and exit_ratio >= hybrid_thresh:
        pnl_hybrid = pnl_market_exit
    else:
        pnl_hybrid = pnl_hold

    return dict(
        scenario=f"{held_side}_HELD", pnl_hold=pnl_hold,
        pnl_market_exit=pnl_market_exit, pnl_hybrid=pnl_hybrid,
        held_won=held_won,
        exit_bid=float(held_bid) if np.isfinite(held_bid) else float("nan"),
        exit_ratio=float(exit_ratio) if np.isfinite(exit_ratio) else float("nan"),
    )


def run_cell(asset: str, timeframe: str, notional: float,
             sample: int, wait_s: int, tag: str, window_days: float) -> dict:
    cell = f"{asset.lower()}_{timeframe}"
    cell_dir = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_{tag}_{cell}_2026_05_16"
    ops_p = cell_dir / "opportunities.parquet"
    if not ops_p.exists():
        print(f"SKIP {cell}: missing {ops_p}")
        return None
    ops = pd.read_parquet(ops_p)
    n_total = len(ops)
    print(f"\n[{cell}] total opportunities: {n_total:,}", flush=True)

    if n_total > sample:
        ops = ops.sample(n=sample, random_state=42).sort_values("ts").reset_index(drop=True)
    n_sample = len(ops)
    print(f"[{cell}] sampled: {n_sample:,}", flush=True)

    res = load_resolutions(assets=[asset.upper()], timeframes=[timeframe])
    res = res[["slug", "outcome"]].drop_duplicates(subset="slug")
    ops = ops.merge(res, on="slug", how="inner")
    n_with_outcome = len(ops)
    print(f"[{cell}] with outcome: {n_with_outcome:,}", flush=True)

    slugs = sorted(ops.slug.unique().astype(str))
    print(f"[{cell}] loading L25 books for {len(slugs)} slugs...", flush=True)
    bi = load_orderbook_l25_streaming(asset.lower(), slugs=set(slugs), subsample_1hz=True)

    rows = []
    for i, r in enumerate(ops.itertuples(index=False)):
        slug = r.slug
        start_us = int(r.ts)
        up_rec = bi.get((slug, "Up"))
        dn_rec = bi.get((slug, "Down"))
        if up_rec is None or dn_rec is None:
            continue
        ts_up, ap_up, asz_up, bp_up, bsz_up = up_rec
        ts_dn, ap_dn, asz_dn, bp_dn, bsz_dn = dn_rec
        fill_u, exit_bid_u = fill_status_and_exit_bid(ts_up, ap_up, bp_up, float(r.ask_up), start_us, wait_s)
        fill_d, exit_bid_d = fill_status_and_exit_bid(ts_dn, ap_dn, bp_dn, float(r.ask_dn), start_us, wait_s)
        ev = evaluate_opportunity(r, fill_u, fill_d, exit_bid_u, exit_bid_d,
                                    outcome=str(r.outcome), notional=notional)
        ev.update(dict(
            slug=slug, ts=start_us, ask_up=float(r.ask_up), ask_dn=float(r.ask_dn),
            sum_asks=float(r.sum_asks), up_filled=fill_u, dn_filled=fill_d,
            outcome=str(r.outcome),
        ))
        rows.append(ev)
        if (i + 1) % 500 == 0:
            print(f"  [{cell}] {i+1}/{len(ops)}", flush=True)

    df = pd.DataFrame(rows)
    out_dir = cell_dir
    df.to_parquet(out_dir / "policy_compare.parquet", index=False)

    # Summarize
    n_eval = len(df)
    sample_pnl_hold = float(df.pnl_hold.sum())
    sample_pnl_mkt = float(df.pnl_market_exit.sum())
    sample_pnl_hyb = float(df.pnl_hybrid.sum())

    # Extrapolate to full opportunity count
    scale_factor = n_total / max(n_eval, 1)
    total_pnl_hold_extrap = sample_pnl_hold * scale_factor
    total_pnl_mkt_extrap = sample_pnl_mkt * scale_factor
    total_pnl_hyb_extrap = sample_pnl_hyb * scale_factor

    pct_both = 100 * (df.scenario == "BOTH").mean()
    pct_one = 100 * df.scenario.isin(["Up_HELD", "Down_HELD"]).mean()
    pct_neither = 100 * (df.scenario == "NEITHER").mean()
    partial = df[df.scenario.isin(["Up_HELD", "Down_HELD"])]
    held_wr = partial.held_won.mean() if len(partial) else float("nan")

    s = dict(
        cell=cell, notional=notional, n_total=n_total, n_sample=n_eval,
        pct_both=pct_both, pct_one=pct_one, pct_neither=pct_neither,
        held_wr=held_wr,
        sample_pnl_hold=sample_pnl_hold,
        sample_pnl_mkt=sample_pnl_mkt,
        sample_pnl_hyb=sample_pnl_hyb,
        mean_pnl_hold=float(df.pnl_hold.mean()),
        mean_pnl_mkt=float(df.pnl_market_exit.mean()),
        mean_pnl_hyb=float(df.pnl_hybrid.mean()),
        total_pnl_hold_extrap=total_pnl_hold_extrap,
        total_pnl_mkt_extrap=total_pnl_mkt_extrap,
        total_pnl_hyb_extrap=total_pnl_hyb_extrap,
        per_day_hold=total_pnl_hold_extrap / window_days,
        per_day_mkt=total_pnl_mkt_extrap / window_days,
        per_day_hyb=total_pnl_hyb_extrap / window_days,
    )
    pd.DataFrame([s]).to_csv(out_dir / "policy_compare_summary.csv", index=False)
    return s


def print_summary(s):
    print(f"\n=== {s['cell']}  notional=${s['notional']:.2f}  n_sample={s['n_sample']:,}/{s['n_total']:,} ===")
    print(f"  scenario mix: BOTH={s['pct_both']:.1f}% ONE={s['pct_one']:.1f}% NEITHER={s['pct_neither']:.1f}%")
    if not np.isnan(s["held_wr"]):
        print(f"  held_win_rate (partial fills): {s['held_wr']*100:.1f}%")
    print(f"  Policy      Mean/op       Total(extrap)    $/day(extrap)")
    print(f"  HOLD        ${s['mean_pnl_hold']:>7.5f}    ${s['total_pnl_hold_extrap']:>12.2f}   ${s['per_day_hold']:>10.2f}")
    print(f"  MKT_EXIT    ${s['mean_pnl_mkt']:>7.5f}    ${s['total_pnl_mkt_extrap']:>12.2f}   ${s['per_day_mkt']:>10.2f}")
    print(f"  HYBRID      ${s['mean_pnl_hyb']:>7.5f}    ${s['total_pnl_hyb_extrap']:>12.2f}   ${s['per_day_hyb']:>10.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("BTC", "ETH", "SOL", "ALL"), default="ALL")
    ap.add_argument("--timeframe", choices=("5m", "15m", "ALL"), default="ALL")
    ap.add_argument("--notional", type=float, default=2.5)
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--wait-s", type=int, default=FILL_WAIT_S)
    ap.add_argument("--window-days", type=float, default=21.0)
    ap.add_argument("--tag", default="v2")
    args = ap.parse_args()

    assets = ["BTC", "ETH", "SOL"] if args.asset == "ALL" else [args.asset]
    tfs = ["5m", "15m"] if args.timeframe == "ALL" else [args.timeframe]

    all_summaries = []
    for asset in assets:
        for tf in tfs:
            try:
                s = run_cell(asset, tf, args.notional, sample=args.sample,
                             wait_s=args.wait_s, tag=args.tag, window_days=args.window_days)
            except FileNotFoundError as e:
                print(f"SKIP: {e}")
                continue
            if s is None:
                continue
            all_summaries.append(s)
            print_summary(s)

    if len(all_summaries) > 0:
        consolidated_p = ROOT / "data" / "v4" / "canonical" / "_results" / "_policy_compare_v2_consolidated.csv"
        pd.DataFrame(all_summaries).to_csv(consolidated_p, index=False)
        print(f"\n=========== CONSOLIDATED ===========")
        print(f"  notional=${args.notional:.2f}  window={args.window_days:.1f}d")
        tot_n = sum(s["n_total"] for s in all_summaries)
        tot_hold = sum(s["total_pnl_hold_extrap"] for s in all_summaries)
        tot_mkt = sum(s["total_pnl_mkt_extrap"] for s in all_summaries)
        tot_hyb = sum(s["total_pnl_hyb_extrap"] for s in all_summaries)
        print(f"  total opportunities: {tot_n:,}")
        print(f"  Policy      Total PnL        $/day(extrap)")
        print(f"  HOLD        ${tot_hold:>12,.2f}    ${tot_hold/args.window_days:>10,.2f}")
        print(f"  MKT_EXIT    ${tot_mkt:>12,.2f}    ${tot_mkt/args.window_days:>10,.2f}")
        print(f"  HYBRID      ${tot_hyb:>12,.2f}    ${tot_hyb/args.window_days:>10,.2f}")
        print(f"\nwritten to {consolidated_p}")


if __name__ == "__main__":
    main()
