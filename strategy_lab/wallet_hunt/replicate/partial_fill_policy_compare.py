"""Compare exit policies for mint-and-sell when only ONE leg fills.

Question from session 2026-05-16:
  > In shadow tests >50% of fires get only 1 leg → we're naked on the other
  > side. If we add a market-sell when the second leg doesn't fill within
  > 60s, does that improve PnL or destroy it?

Three policies evaluated per opportunity:
  A. HOLD          — hold the unfilled leg to chainlink resolution
                     (current strategy)
  B. MARKET_EXIT   — at fire+60s, market-sell the unfilled leg at best_bid,
                     paying taker fee on that leg (no held-leg variance)
  C. HYBRID        — market-exit IFF bid_unfilled / ask_unfilled > THRESH
                     (tight book); otherwise hold

For each opportunity we evaluate (using canonical L25 + chainlink-derived
`outcome` column) what the actual realized PnL would be under each policy
at a configurable notional.

Outputs (per cell):
  data/v4/canonical/_results/mint_and_sell_<cell>/policy_compare.parquet
  data/v4/canonical/_results/mint_and_sell_<cell>/policy_compare_summary.csv

Notes
-----
- mint cost = $1 per pair; n_pairs = notional / 1.0
- maker_rebate added as INCOME per the corrected fee model in
  strategy_lab/fees.py (poly_maker_rebate_per_share)
- taker_fee paid on the market-exit leg only
- Outcome truth = canonical `outcome` column (chainlink-derived)
- bid_at_60s = best_bid in [fire_us, fire_us+60s] last observation;
  if missing (sparse book) the policy can't exit → falls back to HOLD
- BOTH-filled and NEITHER-filled outcomes are policy-invariant
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
HYBRID_BID_ASK_THRESH = 0.97  # bid_unfilled / ask_unfilled must exceed this


def fill_status_and_exit_bid(ts_arr, ap_arr, bp_arr,
                              target_ask: float,
                              start_us: int,
                              wait_s: int = FILL_WAIT_S):
    """Returns (filled, exit_bid_at_window_end).

    filled       — True iff best_bid reached target_ask within window
    exit_bid     — last finite best_bid observation in [start_us, start_us+wait]
                   (used for market-exit price); NaN if no book in window
    """
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
        exit_bid = bb  # last finite observation in window
        if bb >= target_ask:
            filled = True
    return filled, exit_bid


def evaluate_opportunity(row, fill_up, fill_dn, exit_bid_up, exit_bid_dn,
                          outcome: str, notional: float,
                          hybrid_thresh: float = HYBRID_BID_ASK_THRESH):
    """Compute PnL under 3 policies for a single opportunity.

    Returns dict with pnl_hold, pnl_market_exit, pnl_hybrid + diagnostics.
    """
    n = notional  # n_pairs since $1/pair mint
    au = float(row.ask_up); ad = float(row.ask_dn)
    mint_cost = n * 1.0

    # Maker rebate on each filled leg
    reb_u = n * poly_maker_rebate_per_share(au, FEE_RATE) if fill_up else 0.0
    reb_d = n * poly_maker_rebate_per_share(ad, FEE_RATE) if fill_dn else 0.0
    cash_from_filled = (n * au if fill_up else 0.0) + (n * ad if fill_dn else 0.0)

    # Case: BOTH filled — policy-invariant
    if fill_up and fill_dn:
        pnl = cash_from_filled + reb_u + reb_d - mint_cost
        return dict(
            scenario="BOTH", pnl_hold=pnl, pnl_market_exit=pnl, pnl_hybrid=pnl,
            held_won=None, exit_bid=float("nan"), exit_ratio=float("nan"),
        )

    # Case: NEITHER filled — assume merge → recover mint, gas negligible
    if not fill_up and not fill_dn:
        return dict(
            scenario="NEITHER", pnl_hold=0.0, pnl_market_exit=0.0, pnl_hybrid=0.0,
            held_won=None, exit_bid=float("nan"), exit_ratio=float("nan"),
        )

    # Case: ONE leg filled — held leg is the unfilled side
    if fill_up:  # held = Down
        held_side = "Down"; held_ask = ad; held_bid = exit_bid_dn
    else:        # held = Up
        held_side = "Up"; held_ask = au; held_bid = exit_bid_up

    held_won = (outcome == held_side)

    # Policy A: HOLD
    held_redeem = n * (1.0 if held_won else 0.0)
    pnl_hold = cash_from_filled + reb_u + reb_d + held_redeem - mint_cost

    # Policy B: MARKET_EXIT — sell unfilled at best_bid, pay taker fee
    if np.isfinite(held_bid) and held_bid > 0:
        exit_cash = n * held_bid
        exit_fee = n * poly_taker_fee_per_share(held_bid, FEE_RATE)
        pnl_market_exit = cash_from_filled + reb_u + reb_d + exit_cash - exit_fee - mint_cost
        exit_ratio = held_bid / held_ask if held_ask > 0 else float("nan")
    else:
        # No book → can't exit; falls back to HOLD
        pnl_market_exit = pnl_hold
        exit_ratio = float("nan")

    # Policy C: HYBRID — exit only if book is tight
    if np.isfinite(exit_ratio) and exit_ratio >= hybrid_thresh:
        pnl_hybrid = pnl_market_exit
    else:
        pnl_hybrid = pnl_hold

    return dict(
        scenario=f"{held_side}_HELD",
        pnl_hold=pnl_hold,
        pnl_market_exit=pnl_market_exit,
        pnl_hybrid=pnl_hybrid,
        held_won=held_won,
        exit_bid=float(held_bid) if np.isfinite(held_bid) else float("nan"),
        exit_ratio=float(exit_ratio) if np.isfinite(exit_ratio) else float("nan"),
    )


def run_cell(asset: str, timeframe: str, notional: float,
             sample: int | None = 2000, wait_s: int = FILL_WAIT_S) -> pd.DataFrame:
    cell = f"{asset.lower()}_{timeframe}"
    cell_dir = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_{cell}_2026_05_16"
    ops_p = cell_dir / "opportunities.parquet"
    if not ops_p.exists():
        raise FileNotFoundError(ops_p)
    ops = pd.read_parquet(ops_p)
    print(f"[{cell}] loaded {len(ops):,} opportunities", flush=True)

    if sample is not None and len(ops) > sample:
        # Sample evenly across slugs so we don't bias toward a few markets
        ops = ops.sample(n=sample, random_state=42).sort_values("ts").reset_index(drop=True)
        print(f"[{cell}] sampled to {len(ops):,}", flush=True)

    # Join with resolutions (chainlink outcome)
    res = load_resolutions(assets=[asset.upper()], timeframes=[timeframe])
    res = res[["slug", "outcome"]].drop_duplicates(subset="slug")
    ops = ops.merge(res, on="slug", how="inner")
    print(f"[{cell}] after resolution join: {len(ops):,}", flush=True)

    # Load L25 books for sampled slugs
    slugs = sorted(ops.slug.unique().astype(str))
    print(f"[{cell}] loading L25 books for {len(slugs)} slugs...", flush=True)
    bi = load_orderbook_l25_streaming(asset.lower(), slugs=set(slugs), subsample_1hz=True)

    rows = []
    for i, r in enumerate(ops.itertuples(index=False)):
        slug = r.slug
        start_us = int(r.ts)
        target_up = float(r.ask_up); target_dn = float(r.ask_dn)
        up_rec = bi.get((slug, "Up"))
        dn_rec = bi.get((slug, "Down"))
        if up_rec is None or dn_rec is None:
            continue
        ts_up, ap_up, asz_up, bp_up, bsz_up = up_rec
        ts_dn, ap_dn, asz_dn, bp_dn, bsz_dn = dn_rec
        fill_u, exit_bid_u = fill_status_and_exit_bid(ts_up, ap_up, bp_up, target_up, start_us, wait_s)
        fill_d, exit_bid_d = fill_status_and_exit_bid(ts_dn, ap_dn, bp_dn, target_dn, start_us, wait_s)
        ev = evaluate_opportunity(r, fill_u, fill_d, exit_bid_u, exit_bid_d,
                                    outcome=str(r.outcome), notional=notional)
        ev.update(dict(
            slug=slug, ts=start_us, ask_up=target_up, ask_dn=target_dn,
            sum_asks=float(r.sum_asks),
            up_filled=fill_u, dn_filled=fill_d, outcome=str(r.outcome),
        ))
        rows.append(ev)
        if (i + 1) % 500 == 0:
            print(f"  [{cell}] {i+1}/{len(ops)}", flush=True)

    out = pd.DataFrame(rows)
    return out


def summarize(df: pd.DataFrame, cell: str, notional: float,
              window_days: float = 21.0) -> dict:
    """Aggregate PnL stats per policy."""
    n = len(df)
    n_both = (df.scenario == "BOTH").sum()
    n_one = df.scenario.isin(["Up_HELD", "Down_HELD"]).sum()
    n_neither = (df.scenario == "NEITHER").sum()

    summary = {"cell": cell, "n_opportunities": n,
               "pct_both": 100 * n_both / n if n else 0,
               "pct_one_leg": 100 * n_one / n if n else 0,
               "pct_neither": 100 * n_neither / n if n else 0,
               "notional_usd": notional, "window_days": window_days}

    for pol in ("hold", "market_exit", "hybrid"):
        col = f"pnl_{pol}"
        summary[f"total_pnl_{pol}"] = float(df[col].sum())
        summary[f"mean_pnl_per_op_{pol}"] = float(df[col].mean())
        summary[f"median_pnl_per_op_{pol}"] = float(df[col].median())
        summary[f"std_pnl_per_op_{pol}"] = float(df[col].std())
        summary[f"per_day_extrap_{pol}"] = float(df[col].sum()) / window_days

    # Win rate of held side (for partial-fill rows)
    partial = df[df.scenario.isin(["Up_HELD", "Down_HELD"])]
    if len(partial):
        summary["held_win_rate"] = float(partial.held_won.mean())
        summary["mean_exit_ratio"] = float(partial.exit_ratio.mean(skipna=True))
        summary["pct_tight_book_exit"] = float(
            (partial.exit_ratio >= HYBRID_BID_ASK_THRESH).mean() * 100
        )
    else:
        summary["held_win_rate"] = float("nan")
        summary["mean_exit_ratio"] = float("nan")
        summary["pct_tight_book_exit"] = float("nan")
    return summary


def print_summary(s: dict, df: pd.DataFrame | None = None):
    print(f"\n=== {s['cell']}  (n={s['n_opportunities']:,}, notional=${s['notional_usd']:.0f}, window={s['window_days']:.1f}d) ===")
    print(f"  scenario mix: BOTH={s['pct_both']:.1f}%  ONE_LEG={s['pct_one_leg']:.1f}%  NEITHER={s['pct_neither']:.1f}%")
    if not np.isnan(s["held_win_rate"]):
        print(f"  partial-fill held_win_rate={s['held_win_rate']*100:.1f}%   "
              f"mean exit_ratio={s['mean_exit_ratio']:.3f}   "
              f"tight-book(>={HYBRID_BID_ASK_THRESH})={s['pct_tight_book_exit']:.1f}%")
    print(f"  {'Policy':<14}  {'Total PnL':>12}  {'Mean/op':>10}  {'Std/op':>10}  {'$/day':>10}")
    for pol in ("hold", "market_exit", "hybrid"):
        print(f"  {pol:<14}  ${s[f'total_pnl_{pol}']:>11.2f}  ${s[f'mean_pnl_per_op_{pol}']:>9.4f}  ${s[f'std_pnl_per_op_{pol}']:>9.4f}  ${s[f'per_day_extrap_{pol}']:>9.2f}")

    # Edge-bucket breakdown
    if df is not None and len(df):
        df = df.copy()
        df["edge_bucket"] = pd.cut(
            df.sum_asks - 1.0,
            bins=[-0.01, 0.005, 0.01, 0.02, 0.05, 1.0],
            labels=["<0.5¢", "0.5-1¢", "1-2¢", "2-5¢", ">5¢"],
        )
        print(f"\n  Mean PnL per op by sum_asks-1 (edge) bucket:")
        print(f"  {'bucket':<8} {'n':>6} {'%both':>7} {'HOLD':>10} {'MKT_EXIT':>10} {'HYBRID':>10}")
        for b, g in df.groupby("edge_bucket", observed=True):
            pct_both = 100 * (g.scenario == "BOTH").mean()
            print(f"  {str(b):<8} {len(g):>6} {pct_both:>6.1f}% "
                  f"${g.pnl_hold.mean():>9.4f} ${g.pnl_market_exit.mean():>9.4f} ${g.pnl_hybrid.mean():>9.4f}")

        # Partial-fill subset: where is HOLD most painful?
        partial = df[df.scenario.isin(["Up_HELD", "Down_HELD"])]
        if len(partial):
            print(f"\n  Partial-fill PnL (n={len(partial):,}):")
            print(f"  HOLD       mean=${partial.pnl_hold.mean():>9.4f} std=${partial.pnl_hold.std():>9.4f}")
            print(f"  MKT_EXIT   mean=${partial.pnl_market_exit.mean():>9.4f} std=${partial.pnl_market_exit.std():>9.4f}")
            print(f"  HYBRID     mean=${partial.pnl_hybrid.mean():>9.4f} std=${partial.pnl_hybrid.std():>9.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("BTC", "ETH", "SOL", "ALL"), default="BTC")
    ap.add_argument("--timeframe", choices=("5m", "15m", "ALL"), default="15m")
    ap.add_argument("--notional", type=float, default=200.0)
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--wait-s", type=int, default=FILL_WAIT_S)
    ap.add_argument("--window-days", type=float, default=21.0)
    args = ap.parse_args()

    assets = ["BTC", "ETH", "SOL"] if args.asset == "ALL" else [args.asset]
    tfs = ["5m", "15m"] if args.timeframe == "ALL" else [args.timeframe]

    all_summaries = []
    for asset in assets:
        for tf in tfs:
            cell = f"{asset.lower()}_{tf}"
            try:
                df = run_cell(asset, tf, args.notional, sample=args.sample, wait_s=args.wait_s)
            except FileNotFoundError as e:
                print(f"SKIP {cell}: {e}")
                continue
            out_dir = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_{cell}_2026_05_16"
            df.to_parquet(out_dir / "policy_compare.parquet", index=False)
            s = summarize(df, cell, args.notional, args.window_days)
            all_summaries.append(s)
            pd.DataFrame([s]).to_csv(out_dir / "policy_compare_summary.csv", index=False)
            print_summary(s, df)

    if len(all_summaries) > 1:
        consolidated_p = ROOT / "data" / "v4" / "canonical" / "_results" / "_policy_compare_consolidated.csv"
        pd.DataFrame(all_summaries).to_csv(consolidated_p, index=False)
        print(f"\n=== CONSOLIDATED ===")
        tot_n = sum(s["n_opportunities"] for s in all_summaries)
        for pol in ("hold", "market_exit", "hybrid"):
            tot_pnl = sum(s[f"total_pnl_{pol}"] for s in all_summaries)
            per_day = sum(s[f"per_day_extrap_{pol}"] for s in all_summaries)
            print(f"  {pol:<14}  total=${tot_pnl:>10,.2f}   mean/op=${tot_pnl/max(tot_n,1):.4f}   $/day(sample-extrap)=${per_day:.2f}")
        print(f"\nwritten to {consolidated_p}")


if __name__ == "__main__":
    main()
