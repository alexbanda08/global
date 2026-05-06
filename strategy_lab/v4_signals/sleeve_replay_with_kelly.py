"""sleeve_replay_with_kelly.py — Kelly-sized backtest of top-5 sleeves with per-sleeve stops.

Kelly fraction for Polymarket UpDown (entry at ask P, true win prob p):
  f* = max(0, (p - P) / (1 - P))

Per-trade sizing: stake = bankroll * f* * kelly_fraction (use half-Kelly for safety).
Capped at MAX_PCT_BANKROLL per trade.

Compares 4 sizing schemes:
  - FIXED_$1: each trade = $1 (current plan)
  - QUARTER_KELLY (kelly × 0.25, cap 10%): conservative
  - HALF_KELLY (kelly × 0.50, cap 25%): standard
  - FULL_KELLY (kelly × 1.00, cap 50%): aggressive (NOT recommended live)

For each scheme, compute final bankroll, Sharpe, MaxDD over the observed trade sequence.

Each sleeve uses the OPTIMAL SL/TP combo from TOP5_STOPS_OPTIMIZATION_2026_05_04.md:
  btc_5m_v3:        no stops (will use V3 hedge-hold in production)
  btc_5m_sniper:    no stops
  btc_15m_sniper:   SL=50%
  sol_15m_sniper:   SL=70%
  eth_15m_sniper:   no SL, TP=70%
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

# Reuse infrastructure
sys.path.insert(0, str(ROOT / "strategy_lab" / "v4_signals"))
from sleeve_replay_with_stops import (
    load_shadow, load_book_depth, replay_trade, TOP5_SLEEVES,
    TAKER_FEE_PCT, safe_float
)

# Per-sleeve hit-rate priors (from production paper data)
SLEEVE_HIT_PRIOR = {
    "poly_updown_btc_5m_v3":      0.651,   # n=43
    "poly_updown_btc_5m_sniper":  0.535,   # n=114
    "poly_updown_btc_15m_sniper": 0.547,   # n=53
    "poly_updown_sol_15m_sniper": 0.556,   # n=54
    "poly_updown_eth_15m_sniper": 0.541,   # n=37
}

# Optimal SL/TP per sleeve (from TOP5_STOPS_OPTIMIZATION)
SLEEVE_OPTIMAL_STOPS = {
    "poly_updown_btc_5m_v3":      (0.0, 0.0),    # no stops (V3 has hedge-hold in prod)
    "poly_updown_btc_5m_sniper":  (0.0, 0.0),    # no stops
    "poly_updown_btc_15m_sniper": (0.50, 0.0),   # SL=50%
    "poly_updown_sol_15m_sniper": (0.70, 0.0),   # SL=70%
    "poly_updown_eth_15m_sniper": (0.0, 0.70),   # TP=70%
}

# Sizing schemes to test
SIZING_SCHEMES = [
    ("FIXED_$1",       {"kind": "fixed", "amount": 1.0}),
    ("QUARTER_KELLY",  {"kind": "kelly", "fraction": 0.25, "max_pct": 0.10}),
    ("HALF_KELLY",     {"kind": "kelly", "fraction": 0.50, "max_pct": 0.25}),
    ("FULL_KELLY",     {"kind": "kelly", "fraction": 1.00, "max_pct": 0.50}),
]

# Starting bankroll
INITIAL_BANKROLL = 50.0


def kelly_size(p: float, entry_price: float, bankroll: float,
               fraction: float, max_pct: float) -> float:
    """Return $ stake using Kelly formula scaled by `fraction` and capped at max_pct of bankroll."""
    if not (0.001 < entry_price < 0.999):
        return 0.0
    if p <= entry_price:
        return 0.0  # no edge
    f_star = (p - entry_price) / (1.0 - entry_price)
    f_star *= fraction
    f_star = min(f_star, max_pct)
    f_star = max(f_star, 0.0)
    return bankroll * f_star


def sleeve_simulate(trades: list[dict], books: dict, scheme_name: str,
                     scheme_cfg: dict, hit_prior: float,
                     sl_drop: float, tp_rise: float,
                     initial_bankroll: float) -> dict:
    """Simulate sleeve with given sizing + stops. Returns equity curve stats.

    Each trade: size = scheme_cfg → entry → outcome (with stops) → bankroll updated.
    """
    bankroll = initial_bankroll
    pnls = []
    sizes = []
    skipped_no_edge = 0
    sorted_trades = sorted(trades, key=lambda t: t["at_unix"])

    for t in sorted_trades:
        # Determine entry price (use shadow's recorded entry_price)
        entry = t.get("entry_price_f")
        if not (entry and math.isfinite(entry) and 0 < entry < 1):
            continue

        # Compute size
        if scheme_cfg["kind"] == "fixed":
            stake = scheme_cfg["amount"]
        else:
            stake = kelly_size(
                p=hit_prior,
                entry_price=entry,
                bankroll=bankroll,
                fraction=scheme_cfg["fraction"],
                max_pct=scheme_cfg["max_pct"],
            )
            if stake <= 0:
                skipped_no_edge += 1
                continue

        # Replay with stops at this stake
        # Note: replay_trade is for $1 stake; rescale by `stake`
        result = replay_trade(t, books, sl_drop, tp_rise)
        # Rescale (replay returns PnL for $1 live notional)
        pnl = result["pnl_live"] * stake
        bankroll += pnl
        pnls.append(pnl)
        sizes.append(stake)
        if bankroll <= 0:
            # ruined
            break

    pnls_arr = np.asarray(pnls)
    n = len(pnls_arr)
    if n == 0:
        return {"scheme": scheme_name, "n": 0}
    eq = np.cumsum(pnls_arr) + initial_bankroll
    eq_z = np.concatenate([[initial_bankroll], eq])
    rmax = np.maximum.accumulate(eq_z)
    dd = float((eq_z - rmax).min())
    avg = float(pnls_arr.mean())
    std = float(pnls_arr.std(ddof=0))
    sharpe = avg / std if std > 0 else float("nan")
    win_rate = float((pnls_arr > 0).mean())

    sizes_arr = np.asarray(sizes)
    return {
        "scheme": scheme_name,
        "n": n,
        "hit_rate": win_rate,
        "total_pnl": float(pnls_arr.sum()),
        "final_bankroll": bankroll,
        "max_dd": dd,
        "sharpe": sharpe,
        "avg_size": float(sizes_arr.mean()),
        "max_size": float(sizes_arr.max()),
        "skipped_no_edge": skipped_no_edge,
    }


def main() -> int:
    print(f"=== Kelly Sizing Backtest — Top 5 Sleeves ===")
    print(f"Starting bankroll: ${INITIAL_BANKROLL}")
    print(f"Hit-rate priors (from production data): {SLEEVE_HIT_PRIOR}")
    print(f"Optimal SL/TP per sleeve: {SLEEVE_OPTIMAL_STOPS}")

    # Load all data
    shadow = load_shadow()
    by_sleeve = defaultdict(list)
    for t in shadow:
        by_sleeve[t["sleeve_id"]].append(t)
    books_all = {}
    for asset in ("btc", "eth", "sol"):
        for k, v in load_book_depth(asset).items():
            books_all[k] = v

    # Per-sleeve sweep (each sleeve independently with its own bankroll)
    print(f"\n{'='*120}")
    print(f"PER-SLEEVE: each starts with ${INITIAL_BANKROLL/5:.0f} (1/5 of total bankroll)")
    print(f"{'='*120}")
    per_sleeve_bankroll = INITIAL_BANKROLL / 5
    sleeve_summary = {}
    for sleeve_id in TOP5_SLEEVES:
        trades = by_sleeve.get(sleeve_id, [])
        if not trades:
            continue
        sl, tp = SLEEVE_OPTIMAL_STOPS[sleeve_id]
        prior = SLEEVE_HIT_PRIOR[sleeve_id]
        print(f"\n[{sleeve_id}]  prior_p={prior:.3f}  SL={sl*100:.0f}%  TP={tp*100:.0f}%  (n={len(trades)})")
        print(f"  {'scheme':18s}  {'final$':>8s}  {'PnL$':>8s}  {'sharpe':>7s}  {'maxDD$':>8s}  {'avg_size':>9s}  {'max_size':>9s}  {'skip':>5s}")
        sleeve_summary[sleeve_id] = {}
        for scheme_name, scheme_cfg in SIZING_SCHEMES:
            r = sleeve_simulate(trades, books_all, scheme_name, scheme_cfg, prior,
                                sl, tp, per_sleeve_bankroll)
            sleeve_summary[sleeve_id][scheme_name] = r
            if r.get("n", 0) == 0:
                print(f"  {scheme_name:18s}  (no trades)")
                continue
            print(f"  {scheme_name:18s}  ${r['final_bankroll']:>+7.2f}  ${r['total_pnl']:>+7.2f}  "
                  f"{r['sharpe']:>+7.3f}  ${r['max_dd']:>+7.2f}  ${r['avg_size']:>+8.3f}  "
                  f"${r['max_size']:>+8.3f}  {r['skipped_no_edge']:>5d}")

    # Combined portfolio: all sleeves share ONE bankroll, trades interleaved chronologically
    print(f"\n{'='*120}")
    print(f"COMBINED PORTFOLIO: single ${INITIAL_BANKROLL} bankroll, all 5 sleeves trades interleaved")
    print(f"{'='*120}")
    all_trades = []
    for sleeve_id in TOP5_SLEEVES:
        for t in by_sleeve.get(sleeve_id, []):
            t["_sleeve"] = sleeve_id
            t["_sl"], t["_tp"] = SLEEVE_OPTIMAL_STOPS[sleeve_id]
            t["_prior"] = SLEEVE_HIT_PRIOR[sleeve_id]
            all_trades.append(t)
    all_trades.sort(key=lambda t: t["at_unix"])

    print(f"\nTotal interleaved trades: {len(all_trades)}")
    for scheme_name, scheme_cfg in SIZING_SCHEMES:
        bankroll = INITIAL_BANKROLL
        pnls = []
        sizes = []
        skipped = 0
        for t in all_trades:
            entry = t.get("entry_price_f")
            if not (entry and math.isfinite(entry) and 0 < entry < 1):
                continue
            if scheme_cfg["kind"] == "fixed":
                stake = scheme_cfg["amount"]
            else:
                stake = kelly_size(
                    p=t["_prior"], entry_price=entry, bankroll=bankroll,
                    fraction=scheme_cfg["fraction"], max_pct=scheme_cfg["max_pct"],
                )
                if stake <= 0:
                    skipped += 1
                    continue
            r = replay_trade(t, books_all, t["_sl"], t["_tp"])
            pnl = r["pnl_live"] * stake
            bankroll += pnl
            pnls.append(pnl)
            sizes.append(stake)
            if bankroll <= 0:
                break

        if not pnls:
            print(f"  {scheme_name:18s}  (no trades)")
            continue
        arr = np.asarray(pnls)
        eq = np.cumsum(arr) + INITIAL_BANKROLL
        eq_z = np.concatenate([[INITIAL_BANKROLL], eq])
        rmax = np.maximum.accumulate(eq_z)
        dd = float((eq_z - rmax).min())
        sharpe = float(arr.mean()/arr.std(ddof=0)) if arr.std(ddof=0) > 0 else float("nan")
        sizes_arr = np.asarray(sizes)
        roi = (bankroll - INITIAL_BANKROLL) / INITIAL_BANKROLL * 100
        print(f"\n  [{scheme_name}]  n={len(pnls)}  skipped={skipped}")
        print(f"    final bankroll:  ${bankroll:.2f}  (ROI {roi:+.1f}%)")
        print(f"    total PnL:       ${arr.sum():+.2f}")
        print(f"    Sharpe:          {sharpe:+.3f}")
        print(f"    MaxDD:           ${dd:+.2f}")
        print(f"    avg trade size:  ${sizes_arr.mean():+.3f}  (max ${sizes_arr.max():+.3f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
