"""Validate the discovered F2 trigger by replaying on canonical data.

Trigger:
    max_asz >= 200 AND offset >= 180s AND sum_asks >= 1.005
    AND |binance_ret_60s| > 3bp
Direction:
    Down if binance_ret_60s > 0 else Up   (CONTRARIAN to binance move)

Compute:
  - Fires per slug at this trigger
  - WR using chainlink resolution
  - Realized PnL (HOLD policy, real Polymarket fees)
  - Per-slug aggregation
  - Compare to F2 wallet actuals
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_chainlink_asof, asof_strict  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"

WINDOW_S = {"5m": 300, "15m": 900}
FEE_RATE = 0.07


def parse_slug(slug):
    parts = slug.split("-")
    if len(parts) != 4 or parts[1] != "updown":
        return None
    return parts[0].upper(), parts[2], int(parts[3])


def derive_outcome_chainlink(slug, rtds_cache):
    info = parse_slug(slug)
    if info is None:
        return None
    asset, tf, slot_start = info
    slot_end = slot_start + WINDOW_S[tf]
    ts, px = rtds_cache.get(asset, (None, None))
    if ts is None or len(ts) == 0:
        return None
    strike = asof_strict(ts, px, slot_start * 1_000_000)
    settle = asof_strict(ts, px, slot_end * 1_000_000)
    if not (strike > 0 and settle > 0):
        return None
    return "Up" if settle > strike else "Down"


def hold_pnl_per_share(entry_px, won):
    """Real Polymarket fee curve."""
    fee = FEE_RATE * entry_px * (1.0 - entry_px)
    return (1.0 - entry_px - fee) if won else (-entry_px - fee)


# ----- F2 trigger thresholds (discovered) -----
MIN_MAX_ASZ = 200
MIN_OFFSET_S = 180
MIN_SUM_ASKS = 1.005
MIN_RET_60S_BP = 3.0   # tightened from baseline


def trigger_should_fire(row) -> tuple[bool, str | None]:
    max_asz = max(row.get("up_asz") or 0, row.get("dn_asz") or 0)
    sum_asks = row.get("sum_asks")
    offset = row.get("offset_s")
    ret_60s = row.get("binance_ret_60s")

    if pd.isna(sum_asks) or pd.isna(ret_60s):
        return False, None
    if max_asz < MIN_MAX_ASZ:
        return False, None
    if offset is None or offset < MIN_OFFSET_S:
        return False, None
    if sum_asks < MIN_SUM_ASKS:
        return False, None
    if abs(ret_60s) * 10000 < MIN_RET_60S_BP:
        return False, None
    direction = "Down" if ret_60s > 0 else "Up"
    return True, direction


def main():
    # Load features (includes both fire moments + control moments)
    df = pd.read_parquet(CACHE / "_f2_features.parquet")
    print(f"loaded {len(df)} feature rows  fires={int(df.is_fire.sum())}")
    print()

    # Load chainlink for outcome derivation
    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}

    # Derive outcomes for every slug
    print("Deriving outcomes from chainlink RTDS...")
    slug_outcomes = {}
    for slug in df.slug.unique():
        slug_outcomes[slug] = derive_outcome_chainlink(slug, rtds)
    df["winner"] = df.slug.map(slug_outcomes)
    df = df[df.winner.notna()].copy()
    print(f"  rows with derived outcome: {len(df)}")
    print()

    # Apply trigger to every row
    print("Applying trigger rule to all (fire + control) rows...")
    fires_pred = df.apply(
        lambda r: pd.Series(trigger_should_fire(r), index=["fire", "direction"]),
        axis=1,
    )
    df["pred_fire"] = fires_pred["fire"]
    df["pred_direction"] = fires_pred["direction"]
    pred_fires = df[df.pred_fire].copy()
    print(f"  synthetic fires generated: {len(pred_fires)}")

    # WR + per-trade PnL
    pred_fires["won"] = pred_fires.pred_direction == pred_fires.winner
    # Use opp_ask for fired direction (since they buy at ask of the side they pick)
    pred_fires["entry_px"] = np.where(
        pred_fires.pred_direction == "Up", pred_fires.up_ask, pred_fires.dn_ask,
    )
    pred_fires = pred_fires[
        pred_fires.entry_px.notna()
        & (pred_fires.entry_px > 0) & (pred_fires.entry_px < 1)
    ].copy()

    pred_fires["pnl_per_share"] = pred_fires.apply(
        lambda r: hold_pnl_per_share(r.entry_px, bool(r.won)), axis=1,
    )

    wr = pred_fires.won.mean()
    mean_pnl = pred_fires.pnl_per_share.mean()
    print()
    print("=" * 80)
    print("SYNTHETIC TRIGGER RESULTS — HOLD policy, real Polymarket fees")
    print("=" * 80)
    print(f"  n_synthetic_fires : {len(pred_fires)}")
    print(f"  WR                : {wr*100:.2f}%")
    print(f"  mean_entry        : ${pred_fires.entry_px.mean():.4f}")
    print(f"  mean PnL/share    : ${mean_pnl:+.4f}")
    print(f"  median PnL/share  : ${pred_fires.pnl_per_share.median():+.4f}")
    print(f"  pct_winning_trades: {(pred_fires.pnl_per_share > 0).mean()*100:.2f}%")
    print()

    # Per direction
    for d in ("Up", "Down"):
        sub = pred_fires[pred_fires.pred_direction == d]
        if not sub.empty:
            print(f"  {d:5s}: n={len(sub):4d}  WR={sub.won.mean()*100:5.2f}%  "
                  f"mean_entry=${sub.entry_px.mean():.4f}  "
                  f"mean_pnl=${sub.pnl_per_share.mean():+.4f}")

    # Compare to actual F2 fires
    actual_fires = df[df.is_fire == 1].copy()
    actual_fires["won_actual"] = actual_fires.apply(
        lambda r: any(o == r.winner for o in str(r.outcomes_picked).split(",")),
        axis=1,
    )
    print()
    print("Comparison vs ACTUAL F2 fires:")
    print(f"  actual_fires           : {len(actual_fires)}")
    print(f"  actual WR (any leg won): {actual_fires.won_actual.mean()*100:.2f}%")

    # How many actual fires match the trigger?
    actual_match = actual_fires[actual_fires.pred_fire == True].copy()
    print(f"  actual fires matching trigger: {len(actual_match)} ({len(actual_match)/max(len(actual_fires),1)*100:.1f}%)")

    # Threshold sensitivity sweep — what trigger gets highest WR?
    print()
    print("=" * 80)
    print("Threshold sensitivity sweep — find highest-WR trigger")
    print("=" * 80)
    print(f"{'asz':>5s} {'off':>4s} {'sa':>6s} {'ret_bp':>7s}  {'n_fires':>8s}  "
          f"{'WR%':>6s}  {'mean_pnl':>9s}  {'sum_pnl':>9s}")
    print("-" * 70)
    results = []
    for asz_thr in (100, 200, 300, 500):
        for off_thr in (60, 120, 180, 240):
            for sa_thr in (1.005, 1.010, 1.020):
                for ret_bp in (1, 2, 3, 5):
                    asz_max = df[["up_asz", "dn_asz"]].max(axis=1)
                    mask = (
                        (asz_max >= asz_thr)
                        & (df.offset_s >= off_thr)
                        & (df.sum_asks >= sa_thr)
                        & (df.binance_ret_60s.abs() * 10000 >= ret_bp)
                    )
                    sub = df[mask].copy()
                    if len(sub) < 30:
                        continue
                    sub["pred_dir"] = np.where(sub.binance_ret_60s > 0, "Down", "Up")
                    sub["won"] = sub.pred_dir == sub.winner
                    sub["ent"] = np.where(
                        sub.pred_dir == "Up", sub.up_ask, sub.dn_ask,
                    )
                    sub = sub[sub.ent.notna() & (sub.ent > 0) & (sub.ent < 1)]
                    if len(sub) < 30:
                        continue
                    sub["pnl"] = sub.apply(
                        lambda r: hold_pnl_per_share(r.ent, bool(r.won)), axis=1
                    )
                    wr = sub.won.mean()
                    rec = {
                        "asz": asz_thr, "off": off_thr, "sa": sa_thr,
                        "ret_bp": ret_bp, "n": len(sub),
                        "wr": wr, "mean_pnl": float(sub.pnl.mean()),
                        "sum_pnl": float(sub.pnl.sum()),
                    }
                    results.append(rec)
                    if wr > 0.65:
                        print(f"  {asz_thr:>5d} {off_thr:>4d} {sa_thr:>6.3f} "
                              f"{ret_bp:>7.1f}  {len(sub):>8d}  "
                              f"{wr*100:>5.2f}%  ${rec['mean_pnl']:+.4f}  "
                              f"${rec['sum_pnl']:+.2f}")

    if results:
        ranked = sorted(results, key=lambda r: r["wr"], reverse=True)
        print()
        print("Top 5 by WR (n >= 30):")
        for r in ranked[:5]:
            print(f"  asz>={r['asz']:>4d} off>={r['off']:>3d} sa>={r['sa']:.3f} "
                  f"ret>={r['ret_bp']:.0f}bp  n={r['n']:4d}  "
                  f"WR={r['wr']*100:.2f}%  mean_pnl=${r['mean_pnl']:+.4f}  "
                  f"total=${r['sum_pnl']:+.2f}")

        # Save sweep
        (CACHE / "_f2_trigger_sweep.json").write_text(
            json.dumps(results, indent=2, default=str)
        )
        print(f"\nsaved sweep -> {CACHE / '_f2_trigger_sweep.json'}")


if __name__ == "__main__":
    main()
