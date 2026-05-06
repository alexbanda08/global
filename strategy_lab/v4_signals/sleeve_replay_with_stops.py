"""sleeve_replay_with_stops.py — production-replay backtest of top-5 sleeves with stop-loss/gain overlays.

Approach:
  1. For each shadow trade, derive market window_start_unix from `at` timestamp.
  2. Match to book_depth_v3_full to get intra-window orderbook (10s buckets).
  3. Replay the trade: entry at bucket 0, hold until window close OR stop trigger.
  4. Apply stop-loss / stop-gain combinations:
        - SL at YES drops to (entry × (1 - X)) for X in {0.0, 0.3, 0.5, 0.7}
        - TP at YES rises to (entry × (1 + Y)) for Y in {0.0, 0.3, 0.5, 0.7, ∞}
  5. Compare PnL across combinations per sleeve.

Notional rescaled to $1/trade (live target). Fee = 2% taker.

Important: for V3 BTC (sleeve #1), production already has hedge-hold (rev_bp=15) policy.
Stops here are layered on top of HOLD-TO-RESOLUTION baseline; results may differ from
V3's actual production behavior. Treat V3 results with care.
"""
from __future__ import annotations
import csv, math, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
SHADOW_DIR = ROOT / "data" / "v4" / "shadow_trades_2026_05_04"
BOOK_DIR = ROOT / "data" / "v4" / "refresh_2026_05_02"

TOP5_SLEEVES = [
    "poly_updown_btc_5m_v3",
    "poly_updown_btc_5m_sniper",
    "poly_updown_btc_15m_sniper",
    "poly_updown_sol_15m_sniper",
    "poly_updown_eth_15m_sniper",
]

LIVE_NOTIONAL = 1.0
TAKER_FEE_PCT = 0.02
RNG = np.random.default_rng(42)


def safe_float(x):
    if x is None or x == "":
        return float("nan")
    try:
        return float(x)
    except (ValueError, TypeError):
        return float("nan")


def load_shadow() -> list[dict]:
    rows = []
    for path in [SHADOW_DIR / "vps2.csv", SHADOW_DIR / "vps3.csv"]:
        if not path.exists():
            continue
        with open(path) as f:
            for r in csv.DictReader(f):
                if r["sleeve_id"] not in TOP5_SLEEVES:
                    continue
                try:
                    at = datetime.fromisoformat(r["at"].replace(" ", "T"))
                    r["at_unix"] = int(at.timestamp())
                    r["entry_price_f"] = safe_float(r.get("entry_price"))
                    r["pnl_paper"] = safe_float(r.get("pnl_usd")) or 0.0
                except (ValueError, KeyError):
                    continue
                r["won_b"] = r.get("won") in ("t", "true", "True", "1")
                r["sig"] = (r.get("signal") or "").upper()
                tf = (r.get("tf") or "").lower()
                if tf in ("5m", "5min"):
                    r["window_seconds"] = 300
                elif tf in ("15m", "15min"):
                    r["window_seconds"] = 900
                else:
                    continue
                # Derive window_start_unix: at = window_end + small delay; round down to tf boundary
                tf_s = r["window_seconds"]
                window_end = (r["at_unix"] // tf_s) * tf_s
                r["window_start_unix"] = window_end - tf_s
                # Build slug
                sym = (r.get("symbol") or "").lower()
                r["slug"] = f"{sym}-updown-{tf}-{r['window_start_unix']}"
                rows.append(r)
    return rows


def load_book_depth(asset: str) -> dict[tuple[str, str], dict[int, dict]]:
    """Returns {(slug, outcome): {bucket: {ask_0, bid_0}}}."""
    path = BOOK_DIR / f"{asset}_book_depth_v3_full.csv"
    if not path.exists():
        return {}
    out: dict[tuple[str, str], dict[int, dict]] = defaultdict(dict)
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                bucket = int(r["bucket_10s"])
            except (KeyError, ValueError):
                continue
            slug = r["slug"]
            outcome = r["outcome"]
            ask = safe_float(r.get("ask_price_0"))
            bid = safe_float(r.get("bid_price_0"))
            if not (math.isfinite(ask) and math.isfinite(bid)):
                continue
            out[(slug, outcome)][bucket] = {"ask": ask, "bid": bid}
    return dict(out)


def replay_trade(trade: dict, book: dict, sl_drop: float, tp_rise: float) -> dict:
    """Replay one trade with optional stop-loss + take-profit overlays.

    Args:
        sl_drop: stop-loss triggers when ask drops by sl_drop (0.0 = no SL).
                 Note: we exit by SELLING (taking the bid). Triggered when bid <= entry × (1 - sl_drop).
        tp_rise: take-profit triggers when ask rises by tp_rise (None = hold to resolution).
                 Triggered when bid >= entry × (1 + tp_rise).

    Returns dict with: pnl_live, exit_kind, exit_bucket.
    """
    sig = trade["sig"]                        # "UP" or "DOWN"
    if sig not in ("UP", "DOWN"):
        return {"pnl_live": 0.0, "exit_kind": "skip", "exit_bucket": -1}
    outcome_book = "Up" if sig == "UP" else "Down"
    bks = book.get((trade["slug"], outcome_book))
    if not bks:
        # No orderbook, can't replay; use observed PnL (live-rescaled)
        return {"pnl_live": trade["pnl_paper"] / 25.0, "exit_kind": "no_book", "exit_bucket": -1}

    # Entry: use shadow's recorded entry_price (production fill)
    entry = trade["entry_price_f"]
    if not (math.isfinite(entry) and 0 < entry < 1):
        # Fallback: bucket 0 ask
        b0 = bks.get(0)
        if not b0 or not (0 < b0["ask"] < 1):
            return {"pnl_live": trade["pnl_paper"] / 25.0, "exit_kind": "no_entry", "exit_bucket": -1}
        entry = b0["ask"]

    cost = LIVE_NOTIONAL * (1 + TAKER_FEE_PCT)
    shares = LIVE_NOTIONAL / entry

    # Determine settlement outcome bucket = max bucket
    final_bucket = max(bks.keys())
    # Whether trade WOULD WIN at settlement (without any stops)
    settle_won = trade["won_b"]

    # Walk buckets in order, detect stops
    sl_thresh = entry * (1 - sl_drop) if sl_drop > 0 else None
    tp_thresh = entry * (1 + tp_rise) if tp_rise > 0 and tp_rise < 10 else None

    exit_kind = "settle"
    exit_bucket = final_bucket
    exit_price = None  # if stop hits, price we sell at (on the bid)

    if sl_thresh is not None or tp_thresh is not None:
        for bucket in sorted(bks.keys()):
            if bucket == 0:
                continue  # entry bucket — don't trigger immediately
            entry_bid = bks[bucket].get("bid", float("nan"))
            if not math.isfinite(entry_bid):
                continue
            # Take-profit: bid risen high enough?
            if tp_thresh is not None and entry_bid >= tp_thresh:
                exit_kind = "take_profit"
                exit_bucket = bucket
                exit_price = entry_bid
                break
            # Stop-loss: bid dropped below threshold?
            if sl_thresh is not None and entry_bid <= sl_thresh:
                exit_kind = "stop_loss"
                exit_bucket = bucket
                exit_price = entry_bid
                break

    # Compute PnL
    if exit_kind == "settle":
        # Hold to resolution: gross = shares × ($1 if won else $0)
        gross = shares if settle_won else 0.0
    else:
        # Early exit: sell shares at exit_price (bid). Apply 2% taker fee on exit too.
        gross = shares * exit_price * (1 - TAKER_FEE_PCT)

    pnl = gross - cost
    return {"pnl_live": pnl, "exit_kind": exit_kind, "exit_bucket": exit_bucket}


def stats_for_pnls(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0}
    arr = np.asarray(pnls)
    n = len(arr)
    wins = (arr > 0).sum()
    hr = float(wins) / n
    avg = float(arr.mean())
    std = float(arr.std(ddof=0))
    sharpe = avg / std if std > 0 else float("nan")
    eq = np.cumsum(arr)
    eq_z = np.concatenate([[0.0], eq])
    rmax = np.maximum.accumulate(eq_z)
    dd = float((eq_z - rmax).min())
    return {
        "n": n,
        "hit_rate": hr,
        "total_pnl": float(arr.sum()),
        "avg_pnl": avg,
        "sharpe": sharpe,
        "max_dd": dd,
    }


def main() -> int:
    print("=== Production-replay with Stop-Loss / Take-Profit overlays ===")
    print(f"Live notional: ${LIVE_NOTIONAL}, taker fee: {TAKER_FEE_PCT*100}%")

    shadow = load_shadow()
    print(f"\nShadow trades for top-5 sleeves: {len(shadow)}")
    by_sleeve = defaultdict(list)
    for t in shadow:
        by_sleeve[t["sleeve_id"]].append(t)

    # Load all books once
    books_all = {}
    for asset in ("btc", "eth", "sol"):
        for k, v in load_book_depth(asset).items():
            books_all[k] = v
    print(f"Books loaded: {len(books_all)} (slug, outcome) pairs")

    # Test grid
    SL_VALUES = [0.0, 0.30, 0.50, 0.70]   # 0=disabled, 30%, 50%, 70%
    TP_VALUES = [0.0, 0.30, 0.50, 0.70]   # 0=disabled, 30%, 50%, 70%

    for sleeve_id in TOP5_SLEEVES:
        trades = by_sleeve.get(sleeve_id, [])
        if not trades:
            print(f"\n[{sleeve_id}] no shadow trades")
            continue
        print(f"\n{'='*100}")
        print(f"SLEEVE: {sleeve_id}  (n={len(trades)})")
        print(f"{'='*100}")

        # Baseline: hold to resolution (no stops)
        baseline = [replay_trade(t, books_all, 0.0, 0.0) for t in trades]
        baseline_stats = stats_for_pnls([r["pnl_live"] for r in baseline])
        no_book = sum(1 for r in baseline if r["exit_kind"] == "no_book")
        print(f"  Baseline (hold-to-resolution, no stops): n={baseline_stats['n']}  "
              f"hit={baseline_stats['hit_rate']*100:.1f}%  pnl=${baseline_stats['total_pnl']:+.2f}  "
              f"sharpe={baseline_stats['sharpe']:+.3f}  maxDD=${baseline_stats['max_dd']:+.2f}  "
              f"(no_book skips: {no_book})")

        # Grid sweep
        print(f"\n  {'SL\\TP':6s}  ", end="")
        for tp in TP_VALUES:
            print(f"  TP={tp*100:>3.0f}%      ", end="")
        print()
        for sl in SL_VALUES:
            print(f"  {sl*100:>3.0f}% SL  ", end="")
            for tp in TP_VALUES:
                results = [replay_trade(t, books_all, sl, tp) for t in trades]
                pnls = [r["pnl_live"] for r in results]
                s = stats_for_pnls(pnls)
                # Print: pnl / sharpe
                cell = f"${s['total_pnl']:>+5.2f}/{s['sharpe']:>+4.2f}"
                print(f"{cell:>14s}", end="")
            print()

        # Pick best combo (highest Sharpe with positive total PnL)
        best = None
        best_score = -1e9
        for sl in SL_VALUES:
            for tp in TP_VALUES:
                results = [replay_trade(t, books_all, sl, tp) for t in trades]
                pnls = [r["pnl_live"] for r in results]
                s = stats_for_pnls(pnls)
                if s["total_pnl"] > 0 and s["sharpe"] > best_score:
                    best_score = s["sharpe"]
                    best = (sl, tp, s)
        if best:
            sl, tp, s = best
            improve = s["total_pnl"] - baseline_stats["total_pnl"]
            print(f"\n  BEST combo: SL={sl*100:.0f}% TP={tp*100:.0f}%  →  "
                  f"hit={s['hit_rate']*100:.1f}%  pnl=${s['total_pnl']:+.2f}  "
                  f"sharpe={s['sharpe']:+.3f}  maxDD=${s['max_dd']:+.2f}  "
                  f"(vs baseline +${improve:+.2f})")

        # Exit-kind distribution at best combo
        if best:
            sl, tp, _ = best
            results = [replay_trade(t, books_all, sl, tp) for t in trades]
            kinds = defaultdict(int)
            for r in results:
                kinds[r["exit_kind"]] += 1
            print(f"  Exit kinds at best combo: {dict(kinds)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
