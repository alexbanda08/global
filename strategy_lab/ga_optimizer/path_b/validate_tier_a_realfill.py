"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""
Validate TIER A with REAL L25 fills, NO 1Hz subsample, opposite-side book walk.

For each TIER A event:
  1. Find the exact fire_us timestamp (from production fire record)
  2. Load FULL L25 book on the OPPOSITE-side outcome (since action=INVERT)
  3. searchsorted to find snapshot at-or-before fire_us (causal)
  4. Walk asks for $25 → real vwap
  5. Settle: shares × (won - vwap), 2% fee on profit only
  6. Compare to the approximation
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_orderbook_l25_streaming, load_resolutions, load_trading_events
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events

NOTIONAL = 25.0
FEE_RATE = 0.02


def walk_asks(prices, sizes, dollars=NOTIONAL):
    spent = 0.0
    shares = 0.0
    for p, s in zip(prices, sizes):
        if not np.isfinite(p) or p <= 0 or s <= 0:
            continue
        cost_full = p * s
        if spent + cost_full >= dollars:
            need = (dollars - spent) / p
            shares += need
            spent += need * p
            return spent / shares, shares, spent, False
        shares += s
        spent += cost_full
    if shares <= 0:
        return np.nan, 0.0, 0.0, True
    return spent / shares, shares, spent, spent < dollars * 0.5


def get_book_snapshot_at(books, slug, outcome_side, fire_us):
    """Returns (ap, asz, bp, bsz) at-or-before fire_us, or None."""
    key = (slug, outcome_side)
    if key not in books:
        return None
    ts, ap, asz, bp, bsz = books[key]
    i = int(np.searchsorted(ts, fire_us, side="right") - 1)
    if i < 0:
        return None
    return ap[i], asz[i], bp[i], bsz[i], int(ts[i])


def main():
    print("=== TIER A real-fill validation ===")
    # Load TIER A cell predicate
    tier_a = pd.read_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "TIER_A_DEPLOY.csv")
    print(f"\nTier A cells: {len(tier_a)}")
    print(tier_a[["sleeve_id","signal","hour_bucket","dow_group","action"]].to_string(index=False))

    # Load all events, filter to the TIER A cells
    events = load_path_b_events()
    tier_a_events = events.merge(
        tier_a[["sleeve_id","signal","hour_bucket","dow_group","action"]],
        on=["sleeve_id","signal","hour_bucket","dow_group"], how="inner")
    print(f"\nTier A events to validate: {len(tier_a_events)}")

    # Pull fire_us from trading_events directly (the `at` timestamp)
    # production fires at slot_start_us - window + 120 = ws_s + 120
    # But the `at_ts` of the resolution event is when the market SETTLED, not when it fired
    # Need to compute fire_us from slug:
    # slug = poly_updown_btc_15m_<unix_slot_start_seconds>
    # For 15m: ws_s = slot_start - 900s, fire_us = (ws_s + 120) * 1e6 = (slot_start - 780) * 1e6

    # First, get condition_id → slug mapping from resolutions
    res_univ = load_resolutions()
    cond_to_slug = dict(zip(res_univ.market_id, zip(res_univ.slug, res_univ.timeframe,
                                                     res_univ.slot_start_us, res_univ.slot_end_us)))

    # Augment tier_a_events with slug + fire_us
    def lookup_fire(row):
        # condition_id is in the event data
        cid = row.get("condition_id")
        if cid is None or pd.isna(cid):
            return pd.Series([None, None, None, None])
        info = cond_to_slug.get(cid)
        if info is None:
            return pd.Series([None, None, None, None])
        slug, tf, slot_start_us, slot_end_us = info
        window_s = {"5m": 300, "15m": 900}.get(tf, 900)
        ws_s = slot_start_us - window_s * 1_000_000
        fire_us = ws_s + 120 * 1_000_000
        return pd.Series([slug, tf, fire_us, slot_end_us])

    # Need condition_id field; it's in the event JSON, parse again
    ev_all = load_trading_events()
    res_ev = ev_all[ev_all.kind == "poly_updown_resolution"].copy()
    parsed = res_ev["data"].apply(json.loads).apply(pd.Series)
    res_ev = pd.concat([res_ev, parsed], axis=1)
    # event_id is the link
    cid_map = dict(zip(res_ev.event_id, res_ev.condition_id))
    tier_a_events["condition_id"] = tier_a_events.event_id.map(cid_map)

    fire_info = tier_a_events.apply(lookup_fire, axis=1)
    fire_info.columns = ["slug", "tf", "fire_us", "slot_end_us"]
    tier_a_events = pd.concat([tier_a_events, fire_info], axis=1)
    tier_a_events = tier_a_events.dropna(subset=["slug", "fire_us"])
    tier_a_events["fire_us"] = tier_a_events["fire_us"].astype("int64")
    print(f"Tier A events with slug + fire_us: {len(tier_a_events)}")

    # Load FULL L25 (subsample_1hz=False!) for these slugs on the OPPOSITE side
    # For action=INVERT, signal=UP: we trade DOWN → need Down-side book
    # For action=INVERT, signal=DOWN: we trade UP → need Up-side book
    slugs = set(tier_a_events.slug.unique())
    print(f"\nLoading FULL (no subsample) L25 for {len(slugs)} slugs...")
    import time
    t0 = time.time()
    asset = tier_a_events.asset.iloc[0].lower()
    books_full = load_orderbook_l25_streaming(asset, slugs=slugs, subsample_1hz=False)
    print(f"  loaded {len(books_full)} (slug,side) keys in {time.time()-t0:.0f}s")

    # Validate each event
    rows = []
    for _, r in tier_a_events.iterrows():
        # We INVERT — buy opposite outcome
        invert_side = "Down" if r.signal == "UP" else "Up"
        snap = get_book_snapshot_at(books_full, r.slug, invert_side, int(r.fire_us))
        if snap is None:
            rows.append({**r.to_dict(), "skip_reason": "no book"})
            continue
        ap, asz, bp, bsz, book_ts_us = snap
        if not (np.isfinite(ap[0]) and np.isfinite(bp[0])):
            rows.append({**r.to_dict(), "skip_reason": "nan top-of-book"})
            continue
        spread = ap[0] - bp[0]
        # apply spread filter (BTC = 0.02)
        SPREAD_MAX = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}.get(r.asset, 0.02)
        if spread > SPREAD_MAX:
            rows.append({**r.to_dict(), "skip_reason": f"spread {spread:.4f} > {SPREAD_MAX}",
                          "real_spread": spread, "real_ap0": float(ap[0]), "real_bp0": float(bp[0]),
                          "book_ts_us": book_ts_us})
            continue

        vwap, shares, spent, under = walk_asks(list(ap), list(asz), NOTIONAL)
        if under or not np.isfinite(vwap):
            rows.append({**r.to_dict(), "skip_reason": f"underfill spent ${spent:.2f}",
                          "real_vwap": vwap, "book_ts_us": book_ts_us})
            continue

        # Settle: we bet on invert_side, win if outcome == invert_side
        outcome = str(r.outcome).upper()
        invert_dir = "DOWN" if r.signal == "UP" else "UP"
        won_inv = int(outcome == invert_dir)
        profit_raw = shares * (won_inv - vwap)
        fee = max(profit_raw, 0.0) * FEE_RATE
        real_pnl = profit_raw - fee

        # Sanity: book ts should be < fire_us
        gap_ms = (int(r.fire_us) - book_ts_us) / 1000
        rows.append({
            **r.to_dict(),
            "skip_reason": None,
            "real_vwap": float(vwap), "real_shares": float(shares),
            "real_won_inv": won_inv, "real_pnl_invert": float(real_pnl),
            "real_spread": float(spread),
            "real_ap0": float(ap[0]), "real_bp0": float(bp[0]),
            "book_ts_us": book_ts_us,
            "book_ts_gap_ms": gap_ms,
            "approx_pnl_invert": float(r.pnl_invert),
        })

    out = pd.DataFrame(rows)
    valid = out[out.skip_reason.isna()].copy()
    skipped = out[~out.skip_reason.isna()].copy()

    print(f"\nValidation summary:")
    print(f"  total Tier A events: {len(out)}")
    print(f"  valid fills: {len(valid)}")
    print(f"  skipped: {len(skipped)}")
    if len(skipped):
        print(f"  skip reasons: {skipped.skip_reason.value_counts().to_dict()}")

    if len(valid) == 0:
        print("NO valid fills — abort.")
        return

    # Real vs approx PnL
    real_total = float(valid.real_pnl_invert.sum())
    approx_total = float(valid.approx_pnl_invert.sum())
    print(f"\n=== Real vs Approx PnL (Tier A INVERT, full L25, no subsample) ===")
    print(f"  REAL    (opposite-side L25 walk): ${real_total:+,.2f}  ({real_total/len(valid):+.2f}/trade)")
    print(f"  APPROX  (1-entry+spread+100bp):   ${approx_total:+,.2f}  ({approx_total/len(valid):+.2f}/trade)")
    print(f"  Δ                                   ${real_total-approx_total:+,.2f}  ({(real_total-approx_total)/len(valid):+.2f}/trade)")

    # Per-trade comparison
    valid["delta"] = valid.real_pnl_invert - valid.approx_pnl_invert
    print(f"\nPer-trade delta stats:")
    print(f"  mean : ${valid.delta.mean():+.2f}")
    print(f"  std  : ${valid.delta.std():+.2f}")
    print(f"  min  : ${valid.delta.min():+.2f}")
    print(f"  max  : ${valid.delta.max():+.2f}")

    # vwap comparison
    valid["approx_vwap_used"] = 1 - valid.entry_price + valid.get("spread_used", 0.02 + 0.01)
    print(f"\nVwap comparison:")
    print(f"  real opposite-side vwap mean : {valid.real_vwap.mean():.4f}")
    print(f"  approx (1-entry+spread+safety): {valid.approx_vwap_used.mean():.4f}")
    print(f"  real spread mean              : {valid.real_spread.mean():.4f}")

    # Held-out only
    held_start = pd.Timestamp("2026-05-17 08:25:43", tz="UTC")
    valid_held = valid[valid.at_ts >= held_start]
    if len(valid_held):
        real_held = float(valid_held.real_pnl_invert.sum())
        approx_held = float(valid_held.approx_pnl_invert.sum())
        print(f"\n=== HELD-OUT subset (May 17 08:25+) ===")
        print(f"  n: {len(valid_held)}")
        print(f"  REAL   : ${real_held:+.2f}  ({real_held/len(valid_held):+.2f}/trade)")
        print(f"  APPROX : ${approx_held:+.2f}  ({approx_held/len(valid_held):+.2f}/trade)")

    # Sanity: book ts gap should be small (seconds, not minutes)
    print(f"\nBook timestamp lag (fire_us - book_ts_us):")
    print(f"  mean: {valid.book_ts_gap_ms.mean():.0f} ms")
    print(f"  med : {valid.book_ts_gap_ms.median():.0f} ms")
    print(f"  max : {valid.book_ts_gap_ms.max():.0f} ms")

    out.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "tier_a_realfill_validation.csv", index=False)
    print(f"\nSaved: tier_a_realfill_validation.csv")


if __name__ == "__main__":
    main()
