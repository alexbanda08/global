"""
polymarket_hedge_fallback.py — Test countermeasure policies for failed hedges.

CONTEXT
-------
Production deploy of hedge-hold rev_bp=5 has 4 verified bugs (TV cache rot +
stale-snapshot tolerance) causing near-100% hedge failure: every reversal
trigger logs `hedge_skipped_no_asks` and the position rides to natural
resolution unhedged. If the signal was wrong, we lose 100% of the entry stake.

Even AFTER the TV bugs are fixed, hedge can still fail on thin moments — and
losing 100% on a hedge-that-couldn't-fire is unacceptable. We need a
countermeasure that caps downside without depending on opposite-side liquidity.

POLICIES
--------
  HEDGE_HOLD       Current locked: buy-opposite-ask. If fails, hold to resolution.
  SELL_OWN_BID     At reversal trigger, sell held side into ITS OWN bid.
                   Bid liquidity is generally good (winning-side bids attract
                   buyers wanting to take a near-$1 outcome cheap).
  HYBRID           Try hedge first; if hedge fills < 95% of target shares OR
                   asks are empty/synthetically-failed → fall back to sell-own-bid.
  STOPLOSS_20      Independent of reversal trigger. At entry, set stop at
                   entry_price - 0.20. If held bid ever drops to stop, exit.
                   Caps loss at $0.20 / share (= 80% recovery on $0.55 entry).

Each policy is run across:
  - hedge_fail_rate ∈ {0.0, 0.5, 1.0}  — synthetic prob that a hedge attempt
                                          is forced to "no asks" (mimics prod
                                          cache rot at variable severity)
  - deployed cells: q10 × 5m × ALL, q20 × 15m × ALL, q10 × 15m × ALL
  - $25 stake (matches production config)

Outputs:
  results/polymarket/hedge_fallback.csv
  reports/polymarket/02_analysis/POLYMARKET_HEDGE_FALLBACK.md

Run:
  py polymarket_hedge_fallback.py
  PMK_FAIL_SEED=7 py polymarket_hedge_fallback.py   # change rng seed
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd

from book_walk import book_walk_fill
from polymarket_stats import equity_curve_stats
from polymarket_signal_grid_realfills import (
    load_features, load_trajectories, load_book_depth, load_klines_1m,
    asof_close, add_q10_signal, add_q20_signal,
)

HERE = Path(__file__).resolve().parent
RNG_SEED = int(os.environ.get("PMK_FAIL_SEED", "42"))
ASSETS = ["btc", "eth", "sol"]
LEVELS = 10
NOTIONAL = 25.0
REV_BP = 5
FEE_RATE = 0.02

POLICIES = ["HEDGE_HOLD", "SELL_OWN_BID", "HYBRID", "STOPLOSS_20"]
HEDGE_FAIL_RATES = [0.0, 0.5, 1.0]
STOPLOSS_DELTA = 0.20  # held bid <= entry_vwap - 0.20 → exit

# Cells to test (deployed)
CELLS = [
    ("q10", "5m",  "ALL"),
    ("q20", "15m", "ALL"),
    ("q10", "15m", "ALL"),
    # per-asset breakdowns for the locked 5m cell (most concentrated risk)
    ("q10", "5m",  "btc"),
    ("q10", "5m",  "eth"),
    ("q10", "5m",  "sol"),
]


def _resolve_pnl(usd_e: float, shares_e: float, entry_vwap: float,
                 hedge: tuple | None, exit_bid: tuple | None,
                 sig_won: bool) -> float:
    """Compute final PnL given the trade's exit state.

    Args:
        usd_e        cost paid at entry (USD)
        shares_e     shares acquired at entry
        entry_vwap   weighted-avg entry price
        hedge        (vwap_h, shares_h, usd_h) if hedged, else None
        exit_bid     (vwap_x, shares_x, usd_x) if early-exited via own bid, else None
        sig_won      True iff the held side won at resolution

    Exactly one of hedge / exit_bid is non-None, OR both are None (held to
    resolution unhedged).
    """
    if exit_bid is not None:
        # Early exit via own bid: realized PnL = (sell USD received) - (entry USD paid)
        _, shares_x, usd_x = exit_bid
        # Edge case: partial close — treat as we exit min(shares_e, shares_x).
        # Realfills bid-walk targets shares_e exactly, so usually shares_x ≈ shares_e.
        return float(usd_x - usd_e)

    if hedge is not None:
        vwap_h, shares_h, usd_h = hedge
        # Both legs to resolution. Total cost = usd_e + usd_h.
        # Both sides combined → exactly $1 per matched-share-pair pays out
        # (winning leg pays $1 minus 2% fee on its profit; losing leg pays $0).
        matched = min(shares_e, shares_h)
        if sig_won:
            # Held side wins matched pairs. Profit per matched share = (1 - entry_vwap).
            payout = matched * (1.0 - (1.0 - entry_vwap) * FEE_RATE)
        else:
            # Hedge side wins matched pairs. Profit per matched share = (1 - vwap_h).
            payout = matched * (1.0 - (1.0 - vwap_h) * FEE_RATE)
        # Any unmatched shares on the held side resolve normally
        unmatched_held = shares_e - matched
        if unmatched_held > 0:
            if sig_won:
                payout += unmatched_held * (1.0 - (1.0 - entry_vwap) * FEE_RATE)
            # else: 0 payout on unmatched losing side
        return float(payout - usd_e - usd_h)

    # Hold to resolution unhedged
    if sig_won:
        gross = shares_e * 1.0
        profit_pre_fee = gross - usd_e
        fee = profit_pre_fee * FEE_RATE if profit_pre_fee > 0 else 0.0
        return float(profit_pre_fee - fee)
    return float(-usd_e)


def simulate_with_policy(
    row: pd.Series, traj_g: pd.DataFrame, k1m: pd.DataFrame, book: dict,
    policy: str, rev_bp: int, notional_usd: float,
    hedge_fail_p: float, rng: np.random.Generator,
) -> dict | None:
    """Run a single trade under the chosen policy. Returns metrics dict or None."""
    sig = int(row.signal)
    held_outcome = "Up" if sig == 1 else "Down"
    other_outcome = "Down" if sig == 1 else "Up"

    # 1) Entry: walk held-side asks at bucket 0
    entry_key = (0, held_outcome)
    if entry_key not in book:
        return None
    ask_p, ask_s, bid_p, bid_s = book[entry_key]
    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, notional_usd)
    if shares_e <= 0:
        return None
    if under_e and usd_e < notional_usd * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)

    # Stop threshold (only used by STOPLOSS_*)
    stop_bid_threshold = vwap_e - STOPLOSS_DELTA  # absolute price level on held side

    hedge: tuple | None = None
    exit_bid: tuple | None = None
    hedge_attempted = False
    hedge_failed = False
    stop_triggered = False
    stop_via_what = None  # "stop" | "reversal" | None

    # 2) Walk buckets, applying policy logic
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        ts_in_bucket = ws + bucket * 10

        # --- Stop-loss check (STOPLOSS_20 policy only) — independent of reversal ---
        if policy == "STOPLOSS_20":
            held_bid_key = (bucket, held_outcome)
            if held_bid_key in book:
                _, _, h_bid_p, h_bid_s = book[held_bid_key]
                # Worst-case: lowest bid_min in this bucket. We use level-0 bid as proxy.
                top_bid = h_bid_p[0] if len(h_bid_p) and np.isfinite(h_bid_p[0]) else None
                if top_bid is not None and top_bid > 0 and top_bid <= stop_bid_threshold:
                    # Sell into our own bid at this bucket
                    target_x = shares_e * top_bid  # USD we'd receive walking the bid
                    vwap_x, shares_x, usd_x, lvls_x, under_x = book_walk_fill(
                        h_bid_p, h_bid_s, target_x
                    )
                    if shares_x > 0:
                        exit_bid = (vwap_x, shares_x, usd_x)
                        stop_triggered = True
                        stop_via_what = "stop"
                        break

        # --- Reversal trigger ---
        if rev_bp is None or not np.isfinite(btc_at_ws):
            continue
        btc_now = asof_close(k1m, ts_in_bucket)
        if not np.isfinite(btc_now):
            continue
        bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
        reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
        if not reverted:
            continue

        # --- Apply policy ---
        if policy == "HEDGE_HOLD":
            hedge_attempted = True
            # Synthetic failure: with prob hedge_fail_p, treat as no asks
            if rng.random() < hedge_fail_p:
                hedge_failed = True
                # Hold to resolution (per current locked behaviour)
                break
            hedge = _try_hedge(book, bucket, other_outcome, shares_e)
            if hedge is None:
                hedge_failed = True
                break
            stop_via_what = "reversal_hedge"
            break

        elif policy == "SELL_OWN_BID":
            # Never hedge. Just sell held side into bid.
            held_bid_key = (bucket, held_outcome)
            if held_bid_key not in book:
                break  # ride to resolution
            _, _, h_bid_p, h_bid_s = book[held_bid_key]
            top_bid = h_bid_p[0] if len(h_bid_p) and np.isfinite(h_bid_p[0]) else None
            if top_bid is None or top_bid <= 0:
                break
            target_x = shares_e * top_bid
            vwap_x, shares_x, usd_x, _, _ = book_walk_fill(h_bid_p, h_bid_s, target_x)
            if shares_x > 0:
                exit_bid = (vwap_x, shares_x, usd_x)
                stop_via_what = "reversal_sell"
            break

        elif policy == "HYBRID":
            hedge_attempted = True
            # First try hedge
            hedge_local = None
            if rng.random() >= hedge_fail_p:
                hedge_local = _try_hedge(book, bucket, other_outcome, shares_e)
            if hedge_local is not None:
                hedge = hedge_local
                stop_via_what = "reversal_hedge"
                break
            # Hedge failed → fall back to sell own bid
            hedge_failed = True
            held_bid_key = (bucket, held_outcome)
            if held_bid_key in book:
                _, _, h_bid_p, h_bid_s = book[held_bid_key]
                top_bid = h_bid_p[0] if len(h_bid_p) and np.isfinite(h_bid_p[0]) else None
                if top_bid is not None and top_bid > 0:
                    target_x = shares_e * top_bid
                    vwap_x, shares_x, usd_x, _, _ = book_walk_fill(h_bid_p, h_bid_s, target_x)
                    if shares_x > 0:
                        exit_bid = (vwap_x, shares_x, usd_x)
                        stop_via_what = "reversal_fallback_sell"
            # If even bid fallback failed, ride to resolution
            break

        elif policy == "STOPLOSS_20":
            # Reversal under stoploss policy: also exit at bid (no hedge attempt)
            held_bid_key = (bucket, held_outcome)
            if held_bid_key not in book:
                break
            _, _, h_bid_p, h_bid_s = book[held_bid_key]
            top_bid = h_bid_p[0] if len(h_bid_p) and np.isfinite(h_bid_p[0]) else None
            if top_bid is None or top_bid <= 0:
                break
            target_x = shares_e * top_bid
            vwap_x, shares_x, usd_x, _, _ = book_walk_fill(h_bid_p, h_bid_s, target_x)
            if shares_x > 0:
                exit_bid = (vwap_x, shares_x, usd_x)
                stop_via_what = "reversal_sell"
            break

    # 3) Resolve
    outcome_up = int(row.outcome_up)
    sig_won = (sig == outcome_up)
    pnl = _resolve_pnl(usd_e, shares_e, vwap_e, hedge, exit_bid, sig_won)

    return {
        "skipped_thin": False,
        "pnl": pnl,
        "cost": float(usd_e),
        "shares_e": shares_e,
        "vwap_e": vwap_e,
        "sig_won": sig_won,
        "hedge_attempted": hedge_attempted,
        "hedge_failed": hedge_failed,
        "hedged": hedge is not None,
        "exited_at_bid": exit_bid is not None,
        "rode_to_resolution": (hedge is None and exit_bid is None),
        "stop_triggered": stop_triggered,
        "stop_via": stop_via_what,
    }


def _try_hedge(book: dict, bucket: int, other_outcome: str, target_shares: float):
    """Attempt to walk opposite-side asks at this bucket. Returns (vwap, shares, usd) or None."""
    hedge_key = (bucket, other_outcome)
    if hedge_key not in book:
        return None
    h_ask_p, h_ask_s, _, _ = book[hedge_key]
    top = h_ask_p[0] if len(h_ask_p) and np.isfinite(h_ask_p[0]) else None
    if not (top is not None and 0 < top < 1):
        return None
    target_h = target_shares * float(top)
    vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target_h)
    if shares_h <= 0:
        return None
    # Bump if we got too few shares (price walked higher than expected)
    if shares_h < target_shares * 0.95 and not under_h:
        bump = target_shares * vwap_h
        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, bump)
        if shares_h <= 0:
            return None
    return (vwap_h, shares_h, usd_h)


def run_cell(df: pd.DataFrame, traj_by_asset: dict, k1m_by_asset: dict, book_by_asset: dict,
             policy: str, hedge_fail_p: float, rng: np.random.Generator) -> dict:
    pnls, ws_list, costs = [], [], []
    n_attempted = n_failed = n_hedged = n_exited = n_rode = n_stop = 0
    skipped_thin = skipped_no_book = 0
    wins = 0

    for _, row in df.iterrows():
        slug = row.slug
        asset = row.asset
        traj_g = traj_by_asset[asset].get(slug)
        if traj_g is None or traj_g.empty:
            skipped_no_book += 1; continue
        book = book_by_asset[asset].get(slug)
        if book is None:
            skipped_no_book += 1; continue
        k1m = k1m_by_asset[asset]
        r = simulate_with_policy(row, traj_g, k1m, book, policy, REV_BP, NOTIONAL,
                                  hedge_fail_p, rng)
        if r is None:
            skipped_no_book += 1; continue
        if r.get("skipped_thin"):
            skipped_thin += 1; continue
        pnls.append(r["pnl"])
        costs.append(r["cost"])
        ws_list.append(int(row.window_start_unix))
        if r["sig_won"]: wins += 1
        if r["hedge_attempted"]: n_attempted += 1
        if r["hedge_failed"]: n_failed += 1
        if r["hedged"]: n_hedged += 1
        if r["exited_at_bid"]: n_exited += 1
        if r["rode_to_resolution"]: n_rode += 1
        if r["stop_triggered"]: n_stop += 1

    pnls_arr = np.array(pnls)
    costs_arr = np.array(costs)
    ws_arr = np.array(ws_list, dtype=float) if ws_list else None
    n = len(pnls_arr)
    if n == 0:
        return {"n": 0}
    eq = equity_curve_stats(pnls_arr, trade_timestamps=ws_arr)
    roi = pnls_arr / np.where(costs_arr > 0, costs_arr, 1.0) * 100
    boot = rng.choice(pnls_arr, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "pnl_total": float(pnls_arr.sum()),
        "pnl_mean": float(pnls_arr.mean()),
        "roi_pct": float(roi.mean()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls_arr > 0).mean()),
        "wins": wins,
        "hedge_attempted": n_attempted,
        "hedge_failed": n_failed,
        "hedged_pct": float(n_hedged / n * 100),
        "exited_at_bid_pct": float(n_exited / n * 100),
        "rode_to_resolution_pct": float(n_rode / n * 100),
        "stop_triggered": n_stop,
        "skipped_thin": skipped_thin,
        "sharpe": eq["sharpe"],
        "sortino": eq["sortino"],
        "max_dd": eq["max_dd"],
        "longest_dd_run": eq["longest_dd_run"],
        "total_capital": float(costs_arr.sum()),
    }


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    book_by_asset = {a: load_book_depth(a) for a in ASSETS}
    k1m_by_asset = {a: load_klines_1m(a) for a in ASSETS}

    feats_q10 = add_q10_signal(feats)
    feats_q20 = add_q20_signal(feats)
    sig_dfs = {"q10": feats_q10, "q20": feats_q20}

    rng = np.random.default_rng(RNG_SEED)
    rows_out = []
    for sig_label, tf, asset_lbl in CELLS:
        feats_sig = sig_dfs[sig_label]
        sub = feats_sig if asset_lbl == "ALL" else feats_sig[feats_sig.asset == asset_lbl]
        sub = sub[sub.timeframe == tf]
        if len(sub) == 0:
            continue
        for policy in POLICIES:
            for fail_p in HEDGE_FAIL_RATES:
                # Reset rng per cell to make policies comparable across same trades
                local_rng = np.random.default_rng(RNG_SEED)
                r = run_cell(sub, traj_by_asset, k1m_by_asset, book_by_asset,
                             policy, fail_p, local_rng)
                r.update({"signal": sig_label, "timeframe": tf, "asset": asset_lbl,
                          "policy": policy, "hedge_fail_p": fail_p})
                rows_out.append(r)
                print(f"sig={sig_label:3s} tf={tf:3s} asset={asset_lbl:3s} "
                      f"policy={policy:13s} fail={fail_p:.0%} → "
                      f"n={r.get('n', 0):4d} pnl_mean=${r.get('pnl_mean', 0):+.3f} "
                      f"roi={r.get('roi_pct', 0):+6.2f}% hit={r.get('hit', 0)*100:5.1f}% "
                      f"sharpe={r.get('sharpe', 0):+6.1f} maxDD=${r.get('max_dd', 0):+.0f} "
                      f"hedged={r.get('hedged_pct', 0):.0f}% bid_exit={r.get('exited_at_bid_pct', 0):.0f}% "
                      f"rode={r.get('rode_to_resolution_pct', 0):.0f}%")

    df_out = pd.DataFrame(rows_out)
    out_csv = HERE / "results" / "polymarket" / "hedge_fallback.csv"
    out_md = HERE / "reports" / "polymarket" / "02_analysis" / "POLYMARKET_HEDGE_FALLBACK.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    cols = ["signal","timeframe","asset","policy","hedge_fail_p","n","pnl_total","pnl_mean",
            "roi_pct","ci_lo","ci_hi","hit","wins","sharpe","sortino","max_dd","longest_dd_run",
            "hedge_attempted","hedge_failed","hedged_pct","exited_at_bid_pct",
            "rode_to_resolution_pct","stop_triggered","skipped_thin","total_capital"]
    df_out = df_out[cols]
    df_out.to_csv(out_csv, index=False)

    # Markdown report — pivot by policy × fail_rate per cell
    md = ["# Polymarket Hedge-Fallback Policies — Realfills Backtest\n",
          f"Stake: ${NOTIONAL:.0f}. rev_bp={REV_BP}. Realistic L10 book-walked entries + hedge attempts. "
          f"`hedge_fail_p` synthetically forces hedge attempts to fail with given probability "
          f"(simulates production cache+staleness bug chain). Seed={RNG_SEED}.\n"]
    md.append("## Policies\n")
    md.append("- **HEDGE_HOLD** — current locked: buy-opposite-ask. If fails → ride to resolution.")
    md.append("- **SELL_OWN_BID** — at reversal trigger, sell held side into ITS OWN bid. Never hedges.")
    md.append("- **HYBRID** — try hedge first; if fails → fall back to sell own bid.")
    md.append(f"- **STOPLOSS_20** — exit at own bid if held bid drops by ${STOPLOSS_DELTA:.2f} from entry, OR on reversal.\n")

    for sig_label, tf, asset_lbl in CELLS:
        cell_df = df_out[(df_out.signal == sig_label) & (df_out.timeframe == tf) & (df_out.asset == asset_lbl)]
        if cell_df.empty:
            continue
        md.append(f"\n## {sig_label} × {tf} × {asset_lbl}\n")
        md.append("| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |")
        md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in cell_df.sort_values(["policy", "hedge_fail_p"]).iterrows():
            md.append(
                f"| {r['policy']} | {r['hedge_fail_p']:.0%} | {int(r['n'])} | "
                f"{r['roi_pct']:+.2f}% | {r['hit']*100:.1f}% | {r['sharpe']:+.1f} | "
                f"${r['max_dd']:+.0f} | {r['hedged_pct']:.0f}% | {r['exited_at_bid_pct']:.0f}% | "
                f"{r['rode_to_resolution_pct']:.0f}% | {int(r['stop_triggered'])} |"
            )

    md.append("\n## Reading the table")
    md.append("- **Fail%** = probability we synthetically force the hedge attempt to fail. 0% = clean book; 100% = hedge always fails (current production reality due to bugs).")
    md.append("- **Hedged%** = fraction of trades that ended up hedged (target outcome of HEDGE_HOLD when book is healthy).")
    md.append("- **BidExit%** = fraction that closed via own-bid sell (the countermeasure path).")
    md.append("- **Rode%** = fraction that rode to natural resolution (no hedge, no exit). Under HEDGE_HOLD at fail=100%, this catches ALL the failed hedges → loses on every wrong-direction signal.")
    md.append("- **StopTrig** = trades where the STOPLOSS_20 stop fired before any reversal trigger.\n")

    md.append("## Headline comparison — q10 × 5m × ALL\n")
    md.append("| Policy | ROI@0% | ROI@50% | ROI@100% | Δ@100% vs HEDGE_HOLD@100% |")
    md.append("|---|---:|---:|---:|---:|")
    base = df_out[(df_out.signal == "q10") & (df_out.timeframe == "5m") & (df_out.asset == "ALL") & (df_out.policy == "HEDGE_HOLD") & (df_out.hedge_fail_p == 1.0)]
    base_roi = float(base.iloc[0]["roi_pct"]) if len(base) else float("nan")
    for policy in POLICIES:
        rois = {}
        for fail_p in HEDGE_FAIL_RATES:
            row = df_out[(df_out.signal == "q10") & (df_out.timeframe == "5m") & (df_out.asset == "ALL") & (df_out.policy == policy) & (df_out.hedge_fail_p == fail_p)]
            rois[fail_p] = float(row.iloc[0]["roi_pct"]) if len(row) else float("nan")
        delta = rois[1.0] - base_roi if base_roi == base_roi else float("nan")
        md.append(f"| {policy} | {rois[0.0]:+.2f}% | {rois[0.5]:+.2f}% | {rois[1.0]:+.2f}% | {delta:+.2f} pp |")

    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {out_csv} and {out_md}")


if __name__ == "__main__":
    main()
