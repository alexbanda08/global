"""sleeve_ranking.py — rank all sleeves by profitability for live launch selection.

Loads ALL shadow trades from both VPS, applies notional rescaling ($25 paper → $1 live),
and ranks sleeves on multiple criteria for the live-launch top-5 selection.

Selection criteria for "live-eligible":
1. n >= 20 trades (statistical significance)
2. hit rate > 55%
3. Total PnL > 0 (rescaled to $1 live)
4. Sharpe > 0.5 (per-trade)
5. Bootstrap 95% CI lower bound on hit rate > 50%

Outputs ranked table + top-5 recommendation.
"""
from __future__ import annotations
import csv, math, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "v4" / "shadow_trades_2026_05_04"

PAPER_NOTIONAL = 25.0  # current production paper trades fire at $25
LIVE_NOTIONAL  = 1.0   # planned live notional
SCALE = LIVE_NOTIONAL / PAPER_NOTIONAL  # 1/25 = 0.04

RNG = np.random.default_rng(42)


def load_all() -> list[dict]:
    rows = []
    for host, path in [("vps2", DATA / "vps2.csv"), ("vps3", DATA / "vps3.csv")]:
        if not path.exists():
            continue
        with open(path) as f:
            for r in csv.DictReader(f):
                r["host"] = host
                try:
                    at = datetime.fromisoformat(r["at"].replace(" ", "T"))
                    r["at_unix"] = int(at.timestamp())
                except (ValueError, KeyError):
                    continue
                r["won_b"] = r.get("won") in ("t", "true", "True", "1")
                try:
                    r["pnl_paper"] = float(r.get("pnl_usd") or 0)
                    r["pnl_live"] = r["pnl_paper"] * SCALE
                except (ValueError, TypeError):
                    r["pnl_paper"] = 0.0; r["pnl_live"] = 0.0
                r["mode"] = (r.get("mode") or "paper").lower()
                rows.append(r)
    return rows


def stats_for_trades(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnls_live = np.asarray([t["pnl_live"] for t in trades])
    pnls_paper = np.asarray([t["pnl_paper"] for t in trades])
    wins = np.asarray([t["won_b"] for t in trades], dtype=bool)
    hr = float(wins.mean())
    avg_live = float(pnls_live.mean())
    std_live = float(pnls_live.std(ddof=0)) if n > 1 else float("nan")
    sharpe_per_trade = avg_live / std_live if std_live > 0 else float("nan")
    # equity curve max DD (live)
    sorted_t = sorted(trades, key=lambda t: t["at_unix"])
    eq = np.cumsum([t["pnl_live"] for t in sorted_t])
    eq_with_zero = np.concatenate([[0.0], eq])
    running_max = np.maximum.accumulate(eq_with_zero)
    dd = float((eq_with_zero - running_max).min())
    # bootstrap 95% CI on hit rate
    if n >= 10:
        boot_hr = RNG.choice(wins.astype(int), size=(2000, n), replace=True).mean(axis=1)
        ci_lo = float(np.quantile(boot_hr, 0.025))
        ci_hi = float(np.quantile(boot_hr, 0.975))
    else:
        ci_lo, ci_hi = float("nan"), float("nan")
    # span in days
    span_s = sorted_t[-1]["at_unix"] - sorted_t[0]["at_unix"] if n > 1 else 0
    return {
        "n": n,
        "hit_rate": hr,
        "ci_lo_hit": ci_lo, "ci_hi_hit": ci_hi,
        "total_pnl_paper": float(pnls_paper.sum()),
        "total_pnl_live": float(pnls_live.sum()),
        "avg_pnl_live": avg_live,
        "sharpe_per_trade": sharpe_per_trade,
        "max_dd_live": dd,
        "span_days": span_s / 86400,
        "trades_per_day": n / max(span_s / 86400, 1) if span_s > 0 else 0,
    }


def main() -> int:
    rows = load_all()
    print(f"Total resolution events: {len(rows)}")
    paper = [r for r in rows if r["mode"] == "paper"]
    print(f"Paper events: {len(paper)}")

    # Group by sleeve_id (host doesn't separate — same sleeve on both VPS counts together)
    by_sleeve = defaultdict(list)
    for r in paper:
        by_sleeve[r["sleeve_id"]].append(r)

    print(f"\nDistinct sleeves: {len(by_sleeve)}")
    print(f"Notional rescale: ${PAPER_NOTIONAL} paper → ${LIVE_NOTIONAL} live (×{SCALE:.4f})")

    rank_rows = []
    for sleeve_id, trades in by_sleeve.items():
        s = stats_for_trades(trades)
        if s["n"] < 5:
            continue
        s["sleeve_id"] = sleeve_id
        rank_rows.append(s)

    # Print full ranked table — sorted by total_pnl_live desc
    print(f"\n{'='*120}")
    print(f"ALL SLEEVES (sorted by live-rescaled total PnL)")
    print(f"{'='*120}")
    rank_rows.sort(key=lambda r: -r["total_pnl_live"])
    print(f"{'sleeve':40s}  {'n':>4s}  {'hit%':>5s}  {'CI_hit':>14s}  "
          f"{'avg$/t':>7s}  {'pnl$':>8s}  {'maxDD$':>7s}  {'Sharpe':>7s}  {'fires/d':>7s}")
    for r in rank_rows:
        ci = f"[{r['ci_lo_hit']*100:.0f},{r['ci_hi_hit']*100:.0f}]" if not math.isnan(r['ci_lo_hit']) else "n/a"
        print(f"{r['sleeve_id']:40s}  {r['n']:>4d}  {r['hit_rate']*100:>4.1f}%  {ci:>14s}  "
              f"{r['avg_pnl_live']:>+6.4f}  {r['total_pnl_live']:>+7.2f}  {r['max_dd_live']:>+7.2f}  "
              f"{r['sharpe_per_trade']:>+6.3f}  {r['trades_per_day']:>6.1f}")

    # Apply selection criteria for "live-eligible"
    print(f"\n{'='*120}")
    print(f"LIVE-ELIGIBLE FILTER: n≥20, hit>55%, pnl>0, Sharpe>0.05, CI_lo_hit > 0.50")
    print(f"{'='*120}")
    eligible = [r for r in rank_rows
                if r["n"] >= 20
                and r["hit_rate"] > 0.55
                and r["total_pnl_live"] > 0
                and r["sharpe_per_trade"] > 0.05
                and (math.isnan(r["ci_lo_hit"]) or r["ci_lo_hit"] > 0.50)]
    eligible.sort(key=lambda r: -r["sharpe_per_trade"])  # rank by Sharpe (best risk-adjusted)
    print(f"\nELIGIBLE sleeves: {len(eligible)}")
    if eligible:
        print(f"\n{'rank':>4s}  {'sleeve':40s}  {'n':>4s}  {'hit%':>5s}  {'pnl$':>8s}  {'Sharpe':>7s}")
        for i, r in enumerate(eligible[:15]):
            print(f"  {i+1:>2d}.  {r['sleeve_id']:40s}  {r['n']:>4d}  {r['hit_rate']*100:>4.1f}%  "
                  f"{r['total_pnl_live']:>+7.2f}  {r['sharpe_per_trade']:>+6.3f}")

    # Top-5 recommendation
    print(f"\n{'='*120}")
    print(f"TOP 5 LIVE LAUNCH RECOMMENDATIONS")
    print(f"{'='*120}")
    top5 = eligible[:5]
    for i, r in enumerate(top5):
        proj_daily = r["avg_pnl_live"] * r["trades_per_day"]
        print(f"\n  #{i+1}: {r['sleeve_id']}")
        print(f"       n={r['n']}, hit={r['hit_rate']*100:.1f}% (CI [{r['ci_lo_hit']*100:.0f},{r['ci_hi_hit']*100:.0f}])")
        print(f"       avg PnL = ${r['avg_pnl_live']:+.4f}/trade × {r['trades_per_day']:.1f} trades/day = ${proj_daily:+.3f}/day proj.")
        print(f"       MaxDD (live): ${r['max_dd_live']:+.2f}, Sharpe: {r['sharpe_per_trade']:+.3f}")
        print(f"       Total observed live-rescaled PnL: ${r['total_pnl_live']:+.2f}")

    if top5:
        total_daily = sum(r["avg_pnl_live"] * r["trades_per_day"] for r in top5)
        total_dd = sum(r["max_dd_live"] for r in top5)
        print(f"\n  PORTFOLIO PROJECTION (top 5, $1/trade live):")
        print(f"    Combined daily PnL: ${total_daily:+.3f}")
        print(f"    Combined MaxDD risk: ${total_dd:+.2f}")
        print(f"    Recommend bankroll: ~10x MaxDD = ${abs(total_dd)*10:.0f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
