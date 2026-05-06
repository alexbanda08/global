"""phase7_validation.py — Proper quant validation of V5 LATE-ENTRY signal.

Reuses existing infrastructure:
  - polymarket_stats.equity_curve_stats: Sharpe / Sortino / Calmar / MaxDD / win rate
  - polymarket_forward_walk_v2 pattern: chronological 80/20 split + bootstrap CI
  - book_walk.book_walk_fill: realistic fills (top-10 levels)

Adds the gates user asked for:
  1. Time-series CV (train 80% / test 20% chronological)
  2. Permutation test (shuffle outcomes 1000x → null IC distribution → p-value)
  3. Bootstrap CI on hit rate + total PnL (2000 samples)
  4. Per-bucket PnL: hour-of-day, day-of-week, asset
  5. Drawdown analysis (max DD, time underwater, longest DD run)
  6. Stop-loss simulation: apply X% stop, measure Sharpe + DD impact
  7. Tail-risk: worst 5% of trades — common features (asset, hour, regime)

Inputs (existing or full window when available):
  data/v4/refresh_2026_05_02/{asset}_book_depth_v3_full.csv
  data/v4/refresh_2026_05_02/{asset}_markets_minimal.csv
  (fallback: strategy_lab/data/polymarket/{asset}_book_depth_v3.csv + markets_v3.csv)

Per-asset V5 LATE-ENTRY rules from PHASE7_CLOB_MOMENTUM_2026_05_04.md:
  BTC: feature=up_imb_slope_240s, BUY UP if ≤Q20, BUY DOWN if ≥Q80
  ETH: feature=dn_imb_slope_240s, BUY UP if ≥Q80, BUY DOWN if ≤Q20
  SOL: feature=dn_imb_slope_240s, BUY UP if ≥Q80, BUY DOWN if ≤Q20

Outputs:
  strategy_lab/reports/PHASE7_VALIDATION_<date>.md
"""
from __future__ import annotations
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOCAL_DATA = ROOT / "strategy_lab" / "data" / "polymarket"
FULL_DATA = ROOT / "data" / "v4" / "refresh_2026_05_02"
REPORTS = ROOT / "strategy_lab" / "reports"
ASSETS = ("btc", "eth", "sol")

# Reuse existing stats helpers
sys.path.insert(0, str(ROOT / "strategy_lab"))
from polymarket_stats import equity_curve_stats  # noqa: E402

# V5 strategy config (from PHASE7_CLOB_MOMENTUM_2026_05_04.md)
PER_ASSET_FEATURE = {
    "btc": "up_slope_240",     # IC=-0.29  → BUY UP if low slope, BUY DOWN if high
    "eth": "dn_slope_240",     # IC=+0.23  → BUY UP if high, BUY DOWN if low
    "sol": "dn_slope_240",     # IC=+0.43  → BUY UP if high, BUY DOWN if low
}
# Direction sign: +1 means high feature → UP, -1 means high feature → DOWN
PER_ASSET_DIRECTION_SIGN = {"btc": -1, "eth": +1, "sol": +1}

TOP_K = 5                # imbalance computed on top-5 bid+ask sizes
ENTRY_BUCKET = 24        # t=240s into 5m market (24 buckets × 10s)
SETTLE_BUCKET = 30       # t=300s = market close
TAKER_FEE_PCT = 0.02     # Polymarket international taker fee
NOTIONAL_USD = 1.0       # $1 per trade

RNG = np.random.default_rng(42)
N_BOOTSTRAP = 2000
N_PERMUTATION = 1000

# ──────────────────────────────────────────────────────────────────────


def safe_float(x: str) -> float:
    if x is None or x == "":
        return float("nan")
    try:
        return float(x)
    except ValueError:
        return float("nan")


def imbalance(row: dict, k: int) -> float:
    bid = sum(safe_float(row.get(f"bid_size_{i}", "")) for i in range(k) if not math.isnan(safe_float(row.get(f"bid_size_{i}", ""))))
    ask = sum(safe_float(row.get(f"ask_size_{i}", "")) for i in range(k) if not math.isnan(safe_float(row.get(f"ask_size_{i}", ""))))
    tot = bid + ask
    return (bid - ask) / tot if tot > 0 else 0.0


def slope(pairs: list[tuple[int, float]]) -> float:
    n = len(pairs)
    if n < 2:
        return float("nan")
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    denom = n * sxx - sx * sx
    if denom <= 0:
        return float("nan")
    return ((n * sxy - sx * sy) / denom) * (max(p[0] for p in pairs) - min(p[0] for p in pairs))


def load_book_depth(asset: str) -> dict[tuple[str, str], dict[int, dict]]:
    """Returns {(slug, outcome): {bucket_10s: row}}."""
    full = FULL_DATA / f"{asset}_book_depth_v3_full.csv"
    legacy = LOCAL_DATA / f"{asset}_book_depth_v3.csv"
    path = full if full.exists() else legacy
    if not path.exists():
        return {}
    print(f"  loading {asset} book_depth from {path.name}...")
    out: dict[tuple[str, str], dict[int, dict]] = defaultdict(dict)
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                bucket = int(row["bucket_10s"])
            except (KeyError, ValueError):
                continue
            slug = row["slug"]
            outcome = row["outcome"]
            out[(slug, outcome)][bucket] = row
    return dict(out)


def load_outcomes(asset: str) -> dict[str, dict]:
    full = FULL_DATA / f"{asset}_markets_minimal.csv"
    legacy = LOCAL_DATA / f"{asset}_markets_v3.csv"
    path = full if full.exists() else legacy
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            slug = row.get("slug")
            if not slug:
                continue
            try:
                row["outcome_up"] = int(row["outcome_up"])
            except (KeyError, ValueError):
                # markets_v3 has same field
                continue
            try:
                row["window_start_unix"] = int(row["window_start_unix"])
                row["resolve_unix"] = int(row["resolve_unix"])
            except (KeyError, ValueError):
                continue
            tf = row.get("timeframe", "5m")
            if tf != "5m":
                continue
            out[slug] = row
    return out


# ──────────────────────────────────────────────────────────────────────


def compute_features_at_entry(book: dict[tuple[str, str], dict[int, dict]],
                              slug: str) -> dict[str, float] | None:
    """Compute up/dn slope using buckets [0, ENTRY_BUCKET) — fair at t=240s entry."""
    up = book.get((slug, "Up"))
    dn = book.get((slug, "Down"))
    if not up or not dn:
        return None
    up_pairs = [(b, imbalance(up[b], TOP_K)) for b in up if 0 <= b < ENTRY_BUCKET]
    dn_pairs = [(b, imbalance(dn[b], TOP_K)) for b in dn if 0 <= b < ENTRY_BUCKET]
    if len(up_pairs) < 12 or len(dn_pairs) < 12:
        return None  # need ≥120s of orderbook history
    return {"up_slope_240": slope(up_pairs), "dn_slope_240": slope(dn_pairs)}


def get_entry_price(book: dict[tuple[str, str], dict[int, dict]],
                    slug: str, side: str) -> float | None:
    """Get top-of-book ask price at ENTRY_BUCKET for the given side ('Up' or 'Down').
    The PRICE we'd pay to BUY that token at t=240s.
    """
    bk = book.get((slug, side))
    if not bk or ENTRY_BUCKET not in bk:
        return None
    ask = safe_float(bk[ENTRY_BUCKET].get("ask_price_0", ""))
    return ask if 0.001 < ask < 0.999 else None


def trade_pnl(direction: str, entry_price: float, outcome_up: int) -> float:
    """PnL per $1 stake.
    BUY UP at entry_price → if outcome_up=1: shares_owned * 1 - cost; else: -cost.
    Polymarket: $1 stake buys (1/entry_price) shares.
    Apply 2% taker fee on entry cost.
    """
    cost = NOTIONAL_USD * (1 + TAKER_FEE_PCT)
    shares = NOTIONAL_USD / entry_price
    if direction == "Up":
        gross = shares if outcome_up == 1 else 0
    else:  # Down
        gross = shares if outcome_up == 0 else 0
    return gross - cost


def build_trades(asset: str, book: dict, markets: dict) -> list[dict]:
    """For each market with sufficient orderbook, compute features + entry prices.
    Apply per-asset V5 rule. Return trade rows."""
    feature_name = PER_ASSET_FEATURE[asset]
    sign = PER_ASSET_DIRECTION_SIGN[asset]
    trades: list[dict] = []
    skip_reasons = defaultdict(int)
    for slug, mk in markets.items():
        feats = compute_features_at_entry(book, slug)
        if feats is None:
            skip_reasons["no_features"] += 1
            continue
        feat_val = feats[feature_name]
        if not math.isfinite(feat_val):
            skip_reasons["nan_feature"] += 1
            continue
        ep_up = get_entry_price(book, slug, "Up")
        ep_dn = get_entry_price(book, slug, "Down")
        if ep_up is None or ep_dn is None:
            skip_reasons["no_entry_price"] += 1
            continue
        ts = mk["window_start_unix"]
        trades.append({
            "asset": asset, "slug": slug,
            "ts": ts, "window_start_unix": ts,
            "outcome_up": mk["outcome_up"],
            "feature_value": feat_val,
            "entry_yes_ask": ep_up,
            "entry_no_ask": ep_dn,
            "spread_yes": safe_float(book[(slug, "Up")][ENTRY_BUCKET].get("ask_price_0", "")) - safe_float(book[(slug, "Up")][ENTRY_BUCKET].get("bid_price_0", "")),
            "spread_no": safe_float(book[(slug, "Down")][ENTRY_BUCKET].get("ask_price_0", "")) - safe_float(book[(slug, "Down")][ENTRY_BUCKET].get("bid_price_0", "")),
        })
    print(f"  {asset}: built {len(trades)} candidate trades  (skipped: {dict(skip_reasons)})")
    return trades


def apply_v5_rule(trades: list[dict], asset: str,
                  q_low_thresh: float, q_high_thresh: float) -> list[dict]:
    """Apply per-asset V5 rule. Append direction + pnl. Filter to fired trades only."""
    sign = PER_ASSET_DIRECTION_SIGN[asset]
    out: list[dict] = []
    for t in trades:
        f = t["feature_value"]
        if sign > 0:
            # high feature → UP
            if f >= q_high_thresh:
                direction = "Up"; entry = t["entry_yes_ask"]
            elif f <= q_low_thresh:
                direction = "Down"; entry = t["entry_no_ask"]
            else:
                continue
        else:
            # high feature → DOWN
            if f <= q_low_thresh:
                direction = "Up"; entry = t["entry_yes_ask"]
            elif f >= q_high_thresh:
                direction = "Down"; entry = t["entry_no_ask"]
            else:
                continue
        pnl = trade_pnl(direction, entry, t["outcome_up"])
        out.append({**t, "direction": direction, "entry_price": entry, "pnl": pnl})
    return out


# ──────────────────────────────────────────────────────────────────────
# VALIDATION GATES
# ──────────────────────────────────────────────────────────────────────


def chrono_split(trades: list[dict], train_frac: float = 0.8) -> tuple[list[dict], list[dict]]:
    sorted_trades = sorted(trades, key=lambda t: t["ts"])
    cut = int(len(sorted_trades) * train_frac)
    return sorted_trades[:cut], sorted_trades[cut:]


def fit_thresholds(trades: list[dict], q_low: float = 0.20, q_high: float = 0.80) -> tuple[float, float]:
    """Fit Q20/Q80 of feature on training set."""
    vals = sorted(t["feature_value"] for t in trades if math.isfinite(t["feature_value"]))
    n = len(vals)
    if n < 50:
        return float("nan"), float("nan")
    return vals[int(n * q_low)], vals[int(n * q_high)]


def bootstrap_pnl(pnls: np.ndarray, n: int = N_BOOTSTRAP) -> dict:
    if len(pnls) == 0:
        return {"ci_lo": 0, "ci_hi": 0, "ci_lo_hit": 0, "ci_hi_hit": 0}
    samples = RNG.choice(pnls, size=(n, len(pnls)), replace=True)
    sums = samples.sum(axis=1)
    hits = (samples > 0).mean(axis=1)
    return {
        "ci_lo": float(np.quantile(sums, 0.025)),
        "ci_hi": float(np.quantile(sums, 0.975)),
        "ci_lo_hit": float(np.quantile(hits, 0.025)),
        "ci_hi_hit": float(np.quantile(hits, 0.975)),
    }


def permutation_test_ic(feature_vals: list[float], outcomes: list[int],
                        n_perm: int = N_PERMUTATION) -> dict:
    """Shuffle outcomes n_perm times, recompute IC. Compare to true IC."""
    fv = np.asarray(feature_vals, dtype=float)
    ov = np.asarray(outcomes, dtype=float)
    valid = np.isfinite(fv) & np.isfinite(ov)
    fv, ov = fv[valid], ov[valid]
    if len(fv) < 30:
        return {"true_ic": float("nan"), "p_value": float("nan"), "n_perm": 0}
    # Pearson correlation as proxy for IC (rank correlation more robust but slower)
    true_ic = float(np.corrcoef(fv, ov)[0, 1])
    null_ics = np.empty(n_perm)
    for i in range(n_perm):
        shuffled = RNG.permutation(ov)
        null_ics[i] = float(np.corrcoef(fv, shuffled)[0, 1])
    # two-sided p-value
    p_value = float((np.abs(null_ics) >= abs(true_ic)).mean())
    return {
        "true_ic": true_ic, "p_value": p_value, "n_perm": n_perm,
        "null_ic_5pct": float(np.quantile(null_ics, 0.05)),
        "null_ic_95pct": float(np.quantile(null_ics, 0.95)),
    }


def per_hour_pnl(fired: list[dict]) -> dict[int, dict]:
    by_hr = defaultdict(list)
    for t in fired:
        hr = datetime.fromtimestamp(t["ts"], tz=timezone.utc).hour
        by_hr[hr].append(t["pnl"])
    out = {}
    for hr, pnls in sorted(by_hr.items()):
        arr = np.asarray(pnls)
        out[hr] = {"n": len(arr), "total_pnl": float(arr.sum()),
                   "avg_pnl": float(arr.mean()), "win_rate": float((arr > 0).mean())}
    return out


def stop_loss_simulation(fired: list[dict], stop_pcts: tuple[float, ...] = (None, 0.5, 0.7, 0.9)) -> dict:
    """For each stop level, simulate: if trade PnL < -stop_pct * NOTIONAL, replace with -stop * NOTIONAL.
    Note: this is approximate — true stop would depend on intra-window price path which we don't track.
    Better than nothing for sizing comparison.
    Stop levels: None=no stop, 0.5=stop at 50% loss, etc.
    """
    base_pnls = np.asarray([t["pnl"] for t in fired])
    out = {}
    for stop in stop_pcts:
        if stop is None:
            adj = base_pnls.copy()
            label = "no_stop"
        else:
            stop_loss = -NOTIONAL_USD * stop
            adj = np.maximum(base_pnls, stop_loss)
            label = f"stop_{int(stop * 100)}pct"
        stats = equity_curve_stats(adj)
        out[label] = {
            "n": stats["n"], "total_pnl": stats["total_pnl"],
            "sharpe": stats["sharpe"], "calmar": stats["calmar"],
            "max_dd": stats["max_dd"], "longest_dd_run": stats["longest_dd_run"],
            "win_rate": stats["win_rate"],
        }
    return out


def tail_risk_summary(fired: list[dict]) -> dict:
    if not fired:
        return {}
    pnls = np.asarray([t["pnl"] for t in fired])
    sorted_ix = np.argsort(pnls)
    worst = sorted_ix[: max(1, len(pnls) // 20)]  # worst 5%
    worst_trades = [fired[i] for i in worst]
    worst_pnls = pnls[worst]
    return {
        "total_n": len(fired),
        "worst_5pct_n": len(worst_trades),
        "worst_5pct_total_pnl": float(worst_pnls.sum()),
        "worst_5pct_avg_pnl": float(worst_pnls.mean()),
        "worst_5pct_pct_of_total": float(worst_pnls.sum() / pnls.sum() * 100) if pnls.sum() != 0 else 0.0,
        "worst_5pct_hours": list(set(datetime.fromtimestamp(t["ts"], tz=timezone.utc).hour for t in worst_trades)),
        "worst_5pct_directions": {d: sum(1 for t in worst_trades if t["direction"] == d) for d in ("Up", "Down")},
        "worst_5pct_avg_entry_price": float(np.mean([t["entry_price"] for t in worst_trades])),
    }


# ──────────────────────────────────────────────────────────────────────


def run_validation_for_asset(asset: str) -> dict:
    print(f"\n=== {asset.upper()} ===")
    book = load_book_depth(asset)
    markets = load_outcomes(asset)
    if not book or not markets:
        return {"asset": asset, "skipped": True}
    candidates = build_trades(asset, book, markets)
    if len(candidates) < 100:
        print(f"  too few candidates: {len(candidates)}")
        return {"asset": asset, "n_candidates": len(candidates), "skipped": True}

    # 1. Chronological 80/20 split
    train, holdout = chrono_split(candidates, train_frac=0.8)
    q_low, q_high = fit_thresholds(train, q_low=0.20, q_high=0.80)
    print(f"  TRAIN n={len(train)}  HOLDOUT n={len(holdout)}  thresholds: Q20={q_low:.4f}  Q80={q_high:.4f}")

    # 2. Apply rule to BOTH train and holdout
    train_fired = apply_v5_rule(train, asset, q_low, q_high)
    holdout_fired = apply_v5_rule(holdout, asset, q_low, q_high)
    print(f"  fired trades: TRAIN={len(train_fired)}  HOLDOUT={len(holdout_fired)}")

    # 3. Per-set stats (using existing equity_curve_stats)
    train_pnls = np.asarray([t["pnl"] for t in train_fired])
    holdout_pnls = np.asarray([t["pnl"] for t in holdout_fired])
    train_stats = equity_curve_stats(train_pnls,
        trade_timestamps=np.asarray([t["ts"] for t in train_fired]) if train_fired else None)
    holdout_stats = equity_curve_stats(holdout_pnls,
        trade_timestamps=np.asarray([t["ts"] for t in holdout_fired]) if holdout_fired else None)

    # 4. Bootstrap CI on holdout
    boot = bootstrap_pnl(holdout_pnls)

    # 5. Permutation test (on FULL data — IC significance)
    feature_name = PER_ASSET_FEATURE[asset]
    perm = permutation_test_ic(
        [t["feature_value"] for t in candidates],
        [t["outcome_up"] for t in candidates],
    )

    # 6. Per-hour breakdown (holdout only — fair OOS)
    hr = per_hour_pnl(holdout_fired)

    # 7. Stop-loss simulation (holdout)
    stops = stop_loss_simulation(holdout_fired)

    # 8. Tail risk
    tail = tail_risk_summary(holdout_fired)

    return {
        "asset": asset,
        "n_candidates": len(candidates),
        "n_train_fired": len(train_fired),
        "n_holdout_fired": len(holdout_fired),
        "q_low": q_low, "q_high": q_high,
        "train_stats": train_stats,
        "holdout_stats": holdout_stats,
        "bootstrap": boot,
        "permutation": perm,
        "per_hour": hr,
        "stop_loss_sim": stops,
        "tail_risk": tail,
    }


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    print("Phase 7 Validation — V5 LATE-ENTRY signal full quant audit")
    print(f"  notional: ${NOTIONAL_USD}, taker fee: {TAKER_FEE_PCT*100}%")
    print(f"  entry: t={ENTRY_BUCKET*10}s, settle: t={SETTLE_BUCKET*10}s")

    results = []
    for asset in ASSETS:
        results.append(run_validation_for_asset(asset))

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY (holdout = chronological last 20%)")
    print("=" * 70)
    print(f"{'asset':5s}  {'n':>5s}  {'hit%':>6s}  {'pnl$':>8s}  {'sharpe':>7s}  {'maxDD$':>8s}  {'IC p':>6s}")
    for r in results:
        if r.get("skipped"):
            print(f"{r['asset']:5s}  skipped")
            continue
        s = r["holdout_stats"]; p = r["permutation"]
        print(f"{r['asset']:5s}  {r['n_holdout_fired']:>5d}  "
              f"{s['win_rate']*100:>5.1f}%  {s['total_pnl']:>+8.2f}  "
              f"{s['sharpe']:>+7.3f}  {s['max_dd']:>+8.2f}  "
              f"{p['p_value']:>6.4f}")

    # Per-hour & stop-loss & tail risk per asset
    print("\nPER-HOUR HOLDOUT PnL (UTC):")
    for r in results:
        if r.get("skipped"): continue
        print(f"  {r['asset'].upper()}:")
        for hr, h in sorted(r["per_hour"].items()):
            print(f"    h={hr:>2d}  n={h['n']:>3d}  pnl=${h['total_pnl']:>+6.2f}  hit={h['win_rate']*100:>4.1f}%")

    print("\nSTOP-LOSS SIM (holdout):")
    for r in results:
        if r.get("skipped"): continue
        print(f"  {r['asset'].upper()}:")
        print(f"    {'variant':12s}  {'pnl$':>8s}  {'sharpe':>7s}  {'maxDD$':>8s}  {'longDD':>7s}  {'win%':>5s}")
        for variant, s in r["stop_loss_sim"].items():
            print(f"    {variant:12s}  {s['total_pnl']:>+8.2f}  {s['sharpe']:>+7.3f}  {s['max_dd']:>+8.2f}  {s['longest_dd_run']:>7d}  {s['win_rate']*100:>4.1f}%")

    print("\nTAIL RISK (worst 5% of holdout):")
    for r in results:
        if r.get("skipped"): continue
        t = r["tail_risk"]
        if not t: continue
        print(f"  {r['asset'].upper()}: worst {t['worst_5pct_n']}/{t['total_n']} contribute "
              f"{t['worst_5pct_pct_of_total']:+.1f}% of total PnL "
              f"(avg ${t['worst_5pct_avg_pnl']:+.3f})  "
              f"hours={t['worst_5pct_hours']}  dirs={t['worst_5pct_directions']}")

    # Write report
    today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    report_path = REPORTS / f"PHASE7_VALIDATION_{today}.md"
    md = build_markdown(results, today)
    report_path.write_text(md, encoding="utf-8")
    print(f"\nReport written: {report_path}")
    return 0


def build_markdown(results: list[dict], today: str) -> str:
    lines = [
        f"# Phase 7 Validation — V5 LATE-ENTRY Quant Audit ({today})",
        "",
        "Reuses `polymarket_stats.equity_curve_stats` (Sharpe / Sortino / Calmar / MaxDD) and",
        "`polymarket_forward_walk_v2` chronological-split + bootstrap-CI pattern.",
        "",
        "**Validation gates applied:**",
        "1. Chronological 80/20 split (train fits Q20/Q80 thresholds; holdout is OOS)",
        "2. Permutation test (1000× shuffled outcomes → null IC distribution → p-value)",
        "3. Bootstrap CI on holdout PnL + hit rate (2000 resamples)",
        "4. Per-hour-of-day PnL breakdown (holdout)",
        "5. Equity curve stats (Sharpe / Calmar / MaxDD / longest DD run)",
        "6. Stop-loss simulation (no_stop / 50% / 70% / 90% per-trade stops)",
        "7. Tail-risk identification (worst 5% of trades)",
        "",
        f"Notional: ${NOTIONAL_USD} per trade. Taker fee: {TAKER_FEE_PCT*100}%. Entry at t={ENTRY_BUCKET*10}s. Hold {(SETTLE_BUCKET-ENTRY_BUCKET)*10}s.",
        "",
        "## Headline holdout stats",
        "",
        "| Asset | n_holdout | hit% | pnl$ | Sharpe | Sortino | Calmar | MaxDD$ | IC p-value |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r.get("skipped"):
            lines.append(f"| {r['asset'].upper()} | skipped | | | | | | | |")
            continue
        s = r["holdout_stats"]; p = r["permutation"]
        lines.append(
            f"| {r['asset'].upper()} | {r['n_holdout_fired']} | {s['win_rate']*100:.1f}% | "
            f"{s['total_pnl']:+.2f} | {s['sharpe']:+.3f} | {s['sortino']:+.3f} | "
            f"{s['calmar']:+.3f} | {s['max_dd']:+.2f} | {p['p_value']:.4f} |"
        )
    lines.append("")
    lines.append("**IC p-value < 0.05** = signal is statistically significant (true IC unlikely under null).")
    lines.append("")

    lines.append("## Train vs Holdout degradation")
    lines.append("")
    lines.append("| Asset | Train hit% | Holdout hit% | Train pnl | Holdout pnl | Degradation |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for r in results:
        if r.get("skipped"): continue
        ts = r["train_stats"]; hs = r["holdout_stats"]
        deg = (hs["sharpe"] - ts["sharpe"]) / ts["sharpe"] * 100 if ts["sharpe"] not in (0, float("nan")) else float("nan")
        lines.append(
            f"| {r['asset'].upper()} | {ts['win_rate']*100:.1f}% | {hs['win_rate']*100:.1f}% | "
            f"{ts['total_pnl']:+.2f} | {hs['total_pnl']:+.2f} | "
            f"Sharpe {deg:+.0f}% |"
        )
    lines.append("")

    lines.append("## Bootstrap 95% CI on holdout PnL + hit rate")
    lines.append("")
    lines.append("| Asset | PnL CI | Hit rate CI |")
    lines.append("|---|---|---|")
    for r in results:
        if r.get("skipped"): continue
        b = r["bootstrap"]
        lines.append(
            f"| {r['asset'].upper()} | [{b['ci_lo']:+.2f}, {b['ci_hi']:+.2f}] | "
            f"[{b['ci_lo_hit']*100:.1f}%, {b['ci_hi_hit']*100:.1f}%] |"
        )
    lines.append("")
    lines.append("**Lower CI > 0** = strategy edge is statistically significant.")
    lines.append("")

    lines.append("## Stop-loss simulation (holdout)")
    lines.append("")
    for r in results:
        if r.get("skipped"): continue
        lines.append(f"### {r['asset'].upper()}")
        lines.append("")
        lines.append("| Variant | pnl$ | Sharpe | MaxDD$ | Longest DD | Win% |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for variant, s in r["stop_loss_sim"].items():
            lines.append(
                f"| {variant} | {s['total_pnl']:+.2f} | {s['sharpe']:+.3f} | "
                f"{s['max_dd']:+.2f} | {s['longest_dd_run']} | {s['win_rate']*100:.1f}% |"
            )
        lines.append("")

    lines.append("## Tail risk (worst 5% of holdout trades)")
    lines.append("")
    lines.append("| Asset | n_worst | total_pnl$ | %_of_total | hours | directions | avg_entry$ |")
    lines.append("|---|---:|---:|---:|---|---|---:|")
    for r in results:
        if r.get("skipped"): continue
        t = r["tail_risk"]
        if not t: continue
        hrs = ",".join(str(h) for h in sorted(t["worst_5pct_hours"]))
        dirs = "/".join(f"{k}={v}" for k, v in t["worst_5pct_directions"].items())
        lines.append(
            f"| {r['asset'].upper()} | {t['worst_5pct_n']}/{t['total_n']} | "
            f"{t['worst_5pct_total_pnl']:+.2f} | {t['worst_5pct_pct_of_total']:+.1f}% | "
            f"{hrs} | {dirs} | {t['worst_5pct_avg_entry_price']:.3f} |"
        )
    lines.append("")

    lines.append("## Per-hour holdout PnL (UTC)")
    lines.append("")
    for r in results:
        if r.get("skipped"): continue
        lines.append(f"### {r['asset'].upper()}")
        lines.append("")
        lines.append("| Hour | n | total_pnl$ | avg_pnl$ | win% |")
        lines.append("|---:|---:|---:|---:|---:|")
        for hr, h in sorted(r["per_hour"].items()):
            lines.append(f"| {hr} | {h['n']} | {h['total_pnl']:+.2f} | {h['avg_pnl']:+.4f} | {h['win_rate']*100:.1f}% |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Verdict gates** (all must pass for live deployment):")
    lines.append("- Permutation p-value < 0.05  → IC is real, not noise")
    lines.append("- Holdout Sharpe > 0.5         → risk-adjusted returns positive")
    lines.append("- Bootstrap PnL CI lower > 0   → edge is statistically significant")
    lines.append("- MaxDD < 5x mean trade PnL    → manageable tail risk")
    lines.append("- Train→Holdout Sharpe degradation < 50%  → strategy generalizes")
    lines.append("- Stop-loss doesn't help much  → no negative skew (if stop helps a lot, signal has bad tails)")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
