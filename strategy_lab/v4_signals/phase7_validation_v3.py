"""phase7_validation_v3.py — V3 baseline backtest with same validation gates as phase7_validation.py.

V3 logic (entry at window_start, t=0):
  - direction = "Up" if ret_5m > 0 else "Down"
  - quantile gate: |ret_5m| > Q_per_asset (BTC q90, ETH q95, SOL q85)
  - SOL multi-horizon: 5m sign == 15m sign == 1h sign
  - spread filter: per-asset (BTC/ETH = 0.02, SOL = 0.025 with FIX)
  - entry price: features_v3.csv 'entry_yes_ask' or 'entry_no_ask'
  - hold to resolution (5min)

Compares 3 variants:
  V3_BASELINE              — single 0.02 spread filter (current production)
  V3_SOL_FIX               — per-asset spread (BTC/ETH=0.02, SOL=0.025)  ← THE FIX
  V3_SOL_FIX_NO_MH         — V3_SOL_FIX without SOL multi-horizon (sanity check)

Reuses existing infrastructure:
  polymarket_stats.equity_curve_stats: Sharpe / Sortino / Calmar / MaxDD / win rate

Validation gates (same as Phase 7 V5 validation):
  1. Chronological 80/20 split (Q quantile fit on train only)
  2. Permutation test 1000x (IC p-value)
  3. Bootstrap CI 2000x on holdout PnL + hit rate
  4. Per-hour-of-day breakdown
  5. Stop-loss sim
  6. Tail risk (worst 5%)
"""
from __future__ import annotations
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "strategy_lab" / "data" / "polymarket"
REPORTS = ROOT / "strategy_lab" / "reports"

sys.path.insert(0, str(ROOT / "strategy_lab"))
from polymarket_stats import equity_curve_stats  # noqa

# V3 config (per V3_LIVE_LAUNCH_SPEC)
V3_PER_ASSET_QUANTILE = {
    ("BTC", "5m", "UP"):   0.90,
    ("BTC", "5m", "DOWN"): 0.90,
    ("ETH", "5m", "UP"):   0.95,
    ("ETH", "5m", "DOWN"): 0.95,
    ("SOL", "5m", "UP"):   0.85,    # paired with multi-horizon
    ("SOL", "5m", "DOWN"): 0.85,
}
V3_REQUIRE_MULTI_HORIZON = {("SOL", "5m")}

TAKER_FEE_PCT = 0.02
NOTIONAL_USD = 1.0
RNG = np.random.default_rng(42)
N_BOOTSTRAP = 2000
N_PERMUTATION = 1000
ASSETS = ("btc", "eth", "sol")


def safe_float(x: str) -> float:
    if x is None or x == "":
        return float("nan")
    try:
        return float(x)
    except ValueError:
        return float("nan")


def load_features(asset: str) -> list[dict]:
    """Load features_v3.csv joined with markets_v3.csv (for bid prices)."""
    # First load markets_v3 by slug → bid prices
    markets_path = DATA / f"{asset}_markets_v3.csv"
    bids: dict[str, dict] = {}
    with open(markets_path, newline="") as fh:
        for r in csv.DictReader(fh):
            slug = r.get("slug")
            if not slug:
                continue
            yes_bid = safe_float(r.get("entry_yes_bid", ""))
            no_bid = safe_float(r.get("entry_no_bid", ""))
            bids[slug] = {"entry_yes_bid": yes_bid, "entry_no_bid": no_bid}

    # Now load features_v3 + merge bids
    path = DATA / f"{asset}_features_v3.csv"
    rows = []
    skipped_no_bid = 0
    skipped_bad_ret = 0
    skipped_bad_ask = 0
    for r in csv.DictReader(open(path, newline="")):
        try:
            r["window_start_unix"] = int(r["window_start_unix"])
            r["outcome_up"] = int(r["outcome_up"])
            r["ret_5m"] = safe_float(r["ret_5m"])
            r["ret_15m"] = safe_float(r.get("ret_15m", ""))
            r["ret_1h"] = safe_float(r.get("ret_1h", ""))
            r["entry_yes_ask"] = safe_float(r["entry_yes_ask"])
            r["entry_no_ask"] = safe_float(r["entry_no_ask"])
        except (KeyError, ValueError, TypeError):
            continue
        slug = r.get("slug")
        bid_data = bids.get(slug)
        if not bid_data:
            skipped_no_bid += 1
            continue
        r["entry_yes_bid"] = bid_data["entry_yes_bid"]
        r["entry_no_bid"] = bid_data["entry_no_bid"]
        if not (math.isfinite(r["ret_5m"]) and r["ret_5m"] != 0):
            skipped_bad_ret += 1
            continue
        if not (math.isfinite(r["entry_yes_ask"]) and 0 < r["entry_yes_ask"] < 1):
            skipped_bad_ask += 1
            continue
        if not (math.isfinite(r["entry_no_ask"]) and 0 < r["entry_no_ask"] < 1):
            skipped_bad_ask += 1
            continue
        r["asset"] = asset.upper()
        r["timeframe"] = r.get("timeframe", "5m")
        rows.append(r)
    print(f"  {asset}: loaded {len(rows)}  (skipped: no_bid={skipped_no_bid}, "
          f"bad_ret={skipped_bad_ret}, bad_ask={skipped_bad_ask})")
    return rows


def multi_horizon_aligned(r: dict) -> bool:
    """SOL: 5m, 15m, 1h must all agree on sign."""
    s5 = math.copysign(1.0, r["ret_5m"]) if r["ret_5m"] != 0 else 0
    if not math.isfinite(r["ret_15m"]) or not math.isfinite(r["ret_1h"]):
        return False
    s15 = math.copysign(1.0, r["ret_15m"]) if r["ret_15m"] != 0 else 0
    s1h = math.copysign(1.0, r["ret_1h"]) if r["ret_1h"] != 0 else 0
    return (s5 == s15) and (s5 == s1h) and s5 != 0


def trade_pnl(direction: str, entry_price: float, outcome_up: int) -> float:
    cost = NOTIONAL_USD * (1 + TAKER_FEE_PCT)
    shares = NOTIONAL_USD / entry_price
    if direction == "Up":
        gross = shares if outcome_up == 1 else 0.0
    else:
        gross = shares if outcome_up == 0 else 0.0
    return gross - cost


def fit_quantile_threshold(rows: list[dict], asset: str, tf: str, direction: str, q: float) -> float:
    """Fit the |ret_5m| quantile threshold on TRAIN rows."""
    vals = sorted(abs(r["ret_5m"]) for r in rows
                  if r["asset"] == asset and r["timeframe"] == tf
                  and ((direction == "UP" and r["ret_5m"] > 0) or (direction == "DOWN" and r["ret_5m"] < 0)))
    n = len(vals)
    if n < 30:
        return float("nan")
    return vals[int(n * q)]


def evaluate_v3(rows: list[dict],
                thresholds: dict,
                spread_filter: dict[str, float],
                require_mh: bool) -> list[dict]:
    """Apply V3 logic; return fired trades with pnl."""
    fired = []
    for r in rows:
        asset = r["asset"]
        tf = r["timeframe"]
        direction = "UP" if r["ret_5m"] > 0 else "DOWN"
        thr = thresholds.get((asset, tf, direction))
        if thr is None or not math.isfinite(thr):
            continue
        if abs(r["ret_5m"]) < thr:
            continue
        # Multi-horizon for SOL (toggleable)
        if require_mh and (asset, tf) in V3_REQUIRE_MULTI_HORIZON:
            if not multi_horizon_aligned(r):
                continue
        # REAL spread filter: skip if (yes_ask - yes_bid) > spread_thresh, matching production controller
        spread_thresh = spread_filter.get(asset, 0.02)
        yes_spread = r["entry_yes_ask"] - r["entry_yes_bid"]
        no_spread = r["entry_no_ask"] - r["entry_no_bid"]
        # Take the side we'd be buying
        if direction == "UP":
            this_side_spread = yes_spread
        else:
            this_side_spread = no_spread
        if not math.isfinite(this_side_spread) or this_side_spread > spread_thresh:
            continue
        # Fire
        side = "Up" if direction == "UP" else "Down"
        entry = r["entry_yes_ask"] if side == "Up" else r["entry_no_ask"]
        pnl = trade_pnl(side, entry, r["outcome_up"])
        fired.append({
            **r, "direction": side, "entry_price": entry, "pnl": pnl, "ts": r["window_start_unix"],
        })
    return fired


def chrono_split(rows: list[dict], train_frac: float = 0.8) -> tuple[list[dict], list[dict]]:
    s = sorted(rows, key=lambda r: r["window_start_unix"])
    cut = int(len(s) * train_frac)
    return s[:cut], s[cut:]


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


def permutation_test(feature_vals: list[float], outcomes: list[int], n_perm: int = N_PERMUTATION) -> dict:
    fv = np.asarray(feature_vals, dtype=float)
    ov = np.asarray(outcomes, dtype=float)
    valid = np.isfinite(fv) & np.isfinite(ov)
    fv, ov = fv[valid], ov[valid]
    if len(fv) < 30:
        return {"true_ic": float("nan"), "p_value": float("nan")}
    true_ic = float(np.corrcoef(fv, ov)[0, 1])
    null = np.empty(n_perm)
    for i in range(n_perm):
        null[i] = float(np.corrcoef(fv, RNG.permutation(ov))[0, 1])
    return {"true_ic": true_ic, "p_value": float((np.abs(null) >= abs(true_ic)).mean())}


def per_hour_pnl(fired: list[dict]) -> dict[int, dict]:
    by_hr = defaultdict(list)
    for t in fired:
        hr = datetime.fromtimestamp(t["ts"], tz=timezone.utc).hour
        by_hr[hr].append(t["pnl"])
    out = {}
    for hr, pnls in sorted(by_hr.items()):
        arr = np.asarray(pnls)
        out[hr] = {"n": len(arr), "total_pnl": float(arr.sum()),
                   "avg": float(arr.mean()), "win": float((arr > 0).mean())}
    return out


def stop_loss_sim(fired: list[dict], stops=(None, 0.5, 0.7, 0.9)) -> dict:
    base = np.asarray([t["pnl"] for t in fired])
    out = {}
    for s in stops:
        if s is None:
            adj = base.copy(); label = "no_stop"
        else:
            adj = np.maximum(base, -NOTIONAL_USD * s); label = f"stop_{int(s*100)}pct"
        ts_arr = np.asarray([t["ts"] for t in fired]) if len(fired) else None
        st = equity_curve_stats(adj, trade_timestamps=ts_arr)
        out[label] = {"n": st["n"], "total_pnl": st["total_pnl"], "sharpe": st["sharpe"],
                      "max_dd": st["max_dd"], "longest_dd_run": st["longest_dd_run"],
                      "win_rate": st["win_rate"]}
    return out


def tail_risk(fired: list[dict]) -> dict:
    if not fired:
        return {}
    pnls = np.asarray([t["pnl"] for t in fired])
    ix = np.argsort(pnls)
    cut = max(1, len(pnls) // 20)
    worst = ix[:cut]
    worst_pnls = pnls[worst]
    return {
        "n_total": len(fired),
        "worst_n": len(worst),
        "worst_total_pnl": float(worst_pnls.sum()),
        "worst_pct_of_total": float(worst_pnls.sum() / pnls.sum() * 100) if pnls.sum() != 0 else 0.0,
        "worst_hours": sorted(set(datetime.fromtimestamp(fired[i]["ts"], tz=timezone.utc).hour for i in worst)),
        "worst_dirs": {d: sum(1 for i in worst if fired[i]["direction"] == d) for d in ("Up", "Down")},
    }


def run_variant(label: str, all_rows: list[dict], spread_filter: dict[str, float], require_mh: bool) -> dict:
    """Run one variant: chrono split → fit thresholds → eval train+holdout → all gates."""
    # Per-asset chrono split
    by_asset = defaultdict(list)
    for r in all_rows:
        by_asset[r["asset"]].append(r)
    asset_results = {}
    for asset_up in ("BTC", "ETH", "SOL"):
        rows = by_asset.get(asset_up, [])
        if len(rows) < 100:
            continue
        train, holdout = chrono_split(rows, train_frac=0.8)
        # Fit per-direction thresholds on TRAIN
        thresholds = {}
        for direction in ("UP", "DOWN"):
            q = V3_PER_ASSET_QUANTILE[(asset_up, "5m", direction)]
            thresholds[(asset_up, "5m", direction)] = fit_quantile_threshold(train, asset_up, "5m", direction, q)
        # Evaluate
        train_fired = evaluate_v3(train, thresholds, spread_filter, require_mh)
        holdout_fired = evaluate_v3(holdout, thresholds, spread_filter, require_mh)
        # Stats
        tp = np.asarray([t["pnl"] for t in train_fired])
        hp = np.asarray([t["pnl"] for t in holdout_fired])
        ts_train = np.asarray([t["ts"] for t in train_fired]) if train_fired else None
        ts_hold = np.asarray([t["ts"] for t in holdout_fired]) if holdout_fired else None
        train_stats = equity_curve_stats(tp, trade_timestamps=ts_train)
        hold_stats = equity_curve_stats(hp, trade_timestamps=ts_hold)
        boot = bootstrap_pnl(hp)
        # Permutation: feature = abs(ret_5m), outcome = outcome_up (signal direction)
        # NB: |ret_5m| isn't directional, so test on full row set (signed feature)
        perm = permutation_test([r["ret_5m"] for r in rows], [r["outcome_up"] for r in rows])
        hr = per_hour_pnl(holdout_fired)
        sl = stop_loss_sim(holdout_fired)
        tr = tail_risk(holdout_fired)
        asset_results[asset_up] = {
            "n_train_rows": len(train), "n_holdout_rows": len(holdout),
            "n_train_fired": len(train_fired), "n_holdout_fired": len(holdout_fired),
            "train_stats": train_stats, "holdout_stats": hold_stats,
            "bootstrap": boot, "permutation": perm,
            "per_hour": hr, "stop_loss_sim": sl, "tail_risk": tr,
            "thresholds": thresholds,
        }
    return {"label": label, "spread_filter": spread_filter, "require_mh": require_mh,
            "asset_results": asset_results}


def print_summary(variant: dict):
    print(f"\n=== {variant['label']} ===")
    print(f"  spread filter: {variant['spread_filter']}")
    print(f"  require multi-horizon SOL: {variant['require_mh']}")
    print(f"\n  {'asset':5s}  {'n_holdout':>9s}  {'fire%':>6s}  {'hit%':>5s}  {'pnl$':>8s}  {'sharpe':>7s}  {'maxDD$':>8s}  {'IC p':>6s}")
    for a, r in variant["asset_results"].items():
        s = r["holdout_stats"]; p = r["permutation"]
        fire = r["n_holdout_fired"] / max(r["n_holdout_rows"], 1) * 100
        print(f"  {a:5s}  {r['n_holdout_fired']:>5d}/{r['n_holdout_rows']:>3d}  {fire:>5.1f}%  "
              f"{s['win_rate']*100:>4.1f}%  {s['total_pnl']:>+8.2f}  {s['sharpe']:>+7.2f}  "
              f"{s['max_dd']:>+8.2f}  {p['p_value']:>6.4f}")
    print(f"\n  Stop-loss sim (holdout):")
    for a, r in variant["asset_results"].items():
        print(f"    {a}:")
        for v, st in r["stop_loss_sim"].items():
            print(f"      {v:12s}  pnl=${st['total_pnl']:>+7.2f}  sharpe={st['sharpe']:>+6.2f}  "
                  f"maxDD=${st['max_dd']:>+6.2f}  win={st['win_rate']*100:>4.1f}%")
    print(f"\n  Tail risk (worst 5% of holdout):")
    for a, r in variant["asset_results"].items():
        t = r["tail_risk"]
        if not t:
            continue
        print(f"    {a}: worst {t['worst_n']}/{t['n_total']}  "
              f"sum=${t['worst_total_pnl']:+.2f} ({t['worst_pct_of_total']:+.1f}% of total)  "
              f"hours={t['worst_hours']}  dirs={t['worst_dirs']}")


def main() -> int:
    print("V3 Baseline Backtest — partial window 04-22 → 04-29")
    print(f"  notional=${NOTIONAL_USD}, taker_fee={TAKER_FEE_PCT*100}%")
    all_rows = []
    for a in ASSETS:
        all_rows.extend(load_features(a))
    print(f"  rows loaded: {len(all_rows)}")

    variants = [
        run_variant("V3_BASELINE (uniform 0.02 spread)",
                    all_rows, {"BTC": 0.02, "ETH": 0.02, "SOL": 0.02}, require_mh=True),
        run_variant("V3_SOL_FIX (BTC/ETH=0.02, SOL=0.025)",
                    all_rows, {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}, require_mh=True),
        run_variant("V3_SOL_FIX_NO_MH (sanity check, no SOL multi-horizon)",
                    all_rows, {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}, require_mh=False),
    ]
    for v in variants:
        print_summary(v)

    # Markdown report
    today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    report = REPORTS / f"V3_BACKTEST_VALIDATION_{today}.md"
    md = build_markdown(variants, today)
    report.write_text(md, encoding="utf-8")
    print(f"\nReport: {report}")
    return 0


def build_markdown(variants: list[dict], today: str) -> str:
    lines = [
        f"# V3 Baseline Backtest — Validation ({today})",
        "",
        "**Reuses** `polymarket_stats.equity_curve_stats` + chronological-split + bootstrap-CI gates from `phase7_validation.py`.",
        "",
        "**3 variants tested:**",
        "1. `V3_BASELINE` — current production (uniform 0.02 spread filter, multi-horizon for SOL)",
        "2. `V3_SOL_FIX` — proposed fix (per-asset spread: BTC/ETH=0.02, SOL=0.025; multi-horizon for SOL)",
        "3. `V3_SOL_FIX_NO_MH` — sanity (drops SOL multi-horizon constraint to isolate spread filter effect)",
        "",
        "Each variant: chronological 80/20 split, Q (per direction) fit on TRAIN, all 3 assets evaluated. Holdout = last 20% chronologically. PnL math: $1 stake, 2% taker fee, entry at `entry_yes_ask` / `entry_no_ask` from `features_v3.csv`.",
        "",
    ]
    for v in variants:
        lines.append(f"## {v['label']}")
        lines.append("")
        lines.append(f"spread_filter: {v['spread_filter']}, require_mh: {v['require_mh']}")
        lines.append("")
        lines.append("### Headline holdout stats")
        lines.append("")
        lines.append("| Asset | n_holdout_rows | fired | fire% | hit% | pnl$ | Sharpe | MaxDD$ | IC p |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for a, r in v["asset_results"].items():
            s = r["holdout_stats"]; p = r["permutation"]
            fire = r["n_holdout_fired"] / max(r["n_holdout_rows"], 1) * 100
            lines.append(f"| {a} | {r['n_holdout_rows']} | {r['n_holdout_fired']} | "
                         f"{fire:.1f}% | {s['win_rate']*100:.1f}% | {s['total_pnl']:+.2f} | "
                         f"{s['sharpe']:+.2f} | {s['max_dd']:+.2f} | {p['p_value']:.4f} |")
        lines.append("")
        lines.append("### Stop-loss sim (holdout)")
        lines.append("")
        for a, r in v["asset_results"].items():
            lines.append(f"**{a}**")
            lines.append("")
            lines.append("| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            for vname, st in r["stop_loss_sim"].items():
                lines.append(f"| {vname} | {st['total_pnl']:+.2f} | {st['sharpe']:+.2f} | "
                             f"{st['max_dd']:+.2f} | {st['longest_dd_run']} | {st['win_rate']*100:.1f}% |")
            lines.append("")
        lines.append("### Bootstrap 95% CI (holdout)")
        lines.append("")
        lines.append("| Asset | PnL CI | Hit rate CI |")
        lines.append("|---|---|---|")
        for a, r in v["asset_results"].items():
            b = r["bootstrap"]
            lines.append(f"| {a} | [{b['ci_lo']:+.2f}, {b['ci_hi']:+.2f}] | "
                         f"[{b['ci_lo_hit']*100:.1f}%, {b['ci_hi_hit']*100:.1f}%] |")
        lines.append("")
        lines.append("### Tail risk (worst 5%)")
        lines.append("")
        lines.append("| Asset | n_worst | sum$ | %_total | hours | dirs |")
        lines.append("|---|---:|---:|---:|---|---|")
        for a, r in v["asset_results"].items():
            t = r["tail_risk"]
            if not t:
                continue
            hrs = ",".join(str(h) for h in t["worst_hours"])
            ds = "/".join(f"{k}={v}" for k, v in t["worst_dirs"].items())
            lines.append(f"| {a} | {t['worst_n']}/{t['n_total']} | {t['worst_total_pnl']:+.2f} | "
                         f"{t['worst_pct_of_total']:+.1f}% | {hrs} | {ds} |")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**Interpretation:**")
    lines.append("")
    lines.append("Compare V3_BASELINE vs V3_SOL_FIX. The fix is worth shipping if:")
    lines.append("- SOL fire rate increases meaningfully (0 → 5+/day in absolute terms)")
    lines.append("- SOL holdout PnL stays non-negative")
    lines.append("- BTC/ETH not adversely affected (spread filter unchanged for them)")
    lines.append("")
    lines.append("Compare V3_SOL_FIX vs V3_SOL_FIX_NO_MH to validate Concern A (V3.2 multi-horizon parity)")
    lines.append("— if the no-MH variant is significantly worse, multi-horizon is correctly a quality filter.")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
