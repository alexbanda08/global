"""phase7_validation_v3_oracle.py — V3 backtest using Polymarket strike_price (Chainlink oracle)
as the price source. Guaranteed to match production's signal because production uses the SAME oracle.

For each 5m market with window_start_unix = ws:
    ret_5m  = log(this.strike_price / prev_5m_market.strike_price)        where prev = ws - 300
    ret_15m = log(this.strike_price / market_15m_back.strike_price)        where back = ws - 900
    ret_1h  = log(this.strike_price / market_1h_back.strike_price)         where back = ws - 3600

Eliminates the HL-vs-Binance signal noise problem (60% direction match with production)
and the timestamp/snapshot mismatch.
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
DATA = ROOT / "data" / "v4" / "refresh_2026_05_02"
REPORTS = ROOT / "strategy_lab" / "reports"
sys.path.insert(0, str(ROOT / "strategy_lab"))
from polymarket_stats import equity_curve_stats  # noqa

V3_PER_ASSET_QUANTILE = {
    ("BTC", "5m", "UP"):   0.90, ("BTC", "5m", "DOWN"): 0.90,
    ("ETH", "5m", "UP"):   0.95, ("ETH", "5m", "DOWN"): 0.95,
    ("SOL", "5m", "UP"):   0.85, ("SOL", "5m", "DOWN"): 0.85,
}
V3_REQUIRE_MULTI_HORIZON = {("SOL", "5m")}
TAKER_FEE_PCT = 0.02
NOTIONAL_USD = 1.0
RNG = np.random.default_rng(42)
N_BOOTSTRAP = 2000
N_PERMUTATION = 1000
ASSETS = ("btc", "eth", "sol")


def safe_float(x):
    if x is None or x == "":
        return float("nan")
    try:
        return float(x)
    except (ValueError, TypeError):
        return float("nan")


def load_markets_with_strike(asset: str) -> list[dict]:
    """Load mr_full.csv-derived markets_minimal.csv (has strike_price) for asset."""
    path = DATA / f"{asset}_markets_minimal.csv"
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                r["window_start_unix"] = int(r["window_start_unix"])
                r["resolve_unix"] = int(r["resolve_unix"])
                r["outcome_up"] = int(r["outcome_up"])
                r["strike_price"] = safe_float(r.get("strike_price", ""))
                r["settlement_price"] = safe_float(r.get("settlement_price", ""))
            except (KeyError, ValueError):
                continue
            if not math.isfinite(r["strike_price"]) or r["strike_price"] <= 0:
                continue
            r["asset"] = asset.upper()
            r["timeframe"] = r.get("timeframe", "5m")
            rows.append(r)
    return rows


def build_strike_index(rows: list[dict]) -> dict[tuple[str, int], dict]:
    """Index markets by (asset, window_start_unix) for fast lookup."""
    return {(r["asset"], r["window_start_unix"]): r for r in rows}


def compute_returns_from_strike(idx: dict, asset: str, ws: int) -> dict:
    """Compute ret_5m, ret_15m, ret_1h from chained strike_prices."""
    this = idx.get((asset, ws))
    if not this or not math.isfinite(this["strike_price"]):
        return {"ret_5m": float("nan"), "ret_15m": float("nan"), "ret_1h": float("nan")}
    p_now = this["strike_price"]
    out = {}
    for label, offset in [("ret_5m", 300), ("ret_15m", 900), ("ret_1h", 3600)]:
        prev = idx.get((asset, ws - offset))
        if prev and math.isfinite(prev["strike_price"]) and prev["strike_price"] > 0:
            out[label] = math.log(p_now / prev["strike_price"])
        else:
            out[label] = float("nan")
    return out


def load_book_depth_bucket0(asset: str) -> dict[str, dict]:
    path = DATA / f"{asset}_book_depth_v3_full.csv"
    out: dict[str, dict] = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                bucket = int(r["bucket_10s"])
            except (KeyError, ValueError):
                continue
            if bucket != 0:
                continue
            slug = r["slug"]
            outcome = r["outcome"]
            bid = safe_float(r.get("bid_price_0", ""))
            ask = safe_float(r.get("ask_price_0", ""))
            if not (math.isfinite(bid) and math.isfinite(ask)):
                continue
            entry = out.setdefault(slug, {})
            if outcome == "Up":
                entry["entry_yes_bid"] = bid; entry["entry_yes_ask"] = ask
            elif outcome == "Down":
                entry["entry_no_bid"] = bid; entry["entry_no_ask"] = ask
    return {s: e for s, e in out.items() if "entry_yes_ask" in e and "entry_no_ask" in e}


def multi_horizon_aligned(r):
    s5 = math.copysign(1.0, r["ret_5m"]) if r["ret_5m"] != 0 else 0
    if not math.isfinite(r["ret_15m"]) or not math.isfinite(r["ret_1h"]):
        return False
    s15 = math.copysign(1.0, r["ret_15m"]) if r["ret_15m"] != 0 else 0
    s1h = math.copysign(1.0, r["ret_1h"]) if r["ret_1h"] != 0 else 0
    return (s5 == s15) and (s5 == s1h) and s5 != 0


def trade_pnl(direction, entry_price, outcome_up):
    cost = NOTIONAL_USD * (1 + TAKER_FEE_PCT)
    shares = NOTIONAL_USD / entry_price
    if direction == "Up":
        gross = shares if outcome_up == 1 else 0.0
    else:
        gross = shares if outcome_up == 0 else 0.0
    return gross - cost


def fit_quantile(rows, asset, tf, direction, q):
    vals = sorted(abs(r["ret_5m"]) for r in rows
                  if r["asset"] == asset and r["timeframe"] == tf
                  and ((direction == "UP" and r["ret_5m"] > 0) or (direction == "DOWN" and r["ret_5m"] < 0)))
    if len(vals) < 30:
        return float("nan")
    return vals[int(len(vals) * q)]


def evaluate_v3(rows, thresholds, spread_filter, require_mh):
    fired = []
    for r in rows:
        asset = r["asset"]; tf = r["timeframe"]
        direction = "UP" if r["ret_5m"] > 0 else "DOWN"
        thr = thresholds.get((asset, tf, direction))
        if thr is None or not math.isfinite(thr):
            continue
        if abs(r["ret_5m"]) < thr:
            continue
        if require_mh and (asset, tf) in V3_REQUIRE_MULTI_HORIZON:
            if not multi_horizon_aligned(r):
                continue
        spread_thresh = spread_filter.get(asset, 0.02)
        side_spread = (r["entry_yes_ask"] - r["entry_yes_bid"]) if direction == "UP" else (r["entry_no_ask"] - r["entry_no_bid"])
        if not math.isfinite(side_spread) or side_spread > spread_thresh:
            continue
        side = "Up" if direction == "UP" else "Down"
        entry = r["entry_yes_ask"] if side == "Up" else r["entry_no_ask"]
        if not (0 < entry < 1):
            continue
        pnl = trade_pnl(side, entry, r["outcome_up"])
        fired.append({**r, "direction": side, "entry_price": entry, "pnl": pnl, "ts": r["window_start_unix"]})
    return fired


def chrono_split(rows, train_frac=0.8):
    s = sorted(rows, key=lambda r: r["window_start_unix"])
    cut = int(len(s) * train_frac)
    return s[:cut], s[cut:]


def bootstrap_pnl(pnls):
    if len(pnls) == 0:
        return {"ci_lo": 0, "ci_hi": 0, "ci_lo_hit": 0, "ci_hi_hit": 0}
    samples = RNG.choice(pnls, size=(N_BOOTSTRAP, len(pnls)), replace=True)
    sums = samples.sum(axis=1)
    hits = (samples > 0).mean(axis=1)
    return {
        "ci_lo": float(np.quantile(sums, 0.025)),
        "ci_hi": float(np.quantile(sums, 0.975)),
        "ci_lo_hit": float(np.quantile(hits, 0.025)),
        "ci_hi_hit": float(np.quantile(hits, 0.975)),
    }


def permutation_test(feature_vals, outcomes):
    fv = np.asarray(feature_vals, dtype=float)
    ov = np.asarray(outcomes, dtype=float)
    valid = np.isfinite(fv) & np.isfinite(ov)
    fv, ov = fv[valid], ov[valid]
    if len(fv) < 30:
        return {"true_ic": float("nan"), "p_value": float("nan")}
    true_ic = float(np.corrcoef(fv, ov)[0, 1])
    null = np.empty(N_PERMUTATION)
    for i in range(N_PERMUTATION):
        null[i] = float(np.corrcoef(fv, RNG.permutation(ov))[0, 1])
    return {"true_ic": true_ic, "p_value": float((np.abs(null) >= abs(true_ic)).mean())}


def stop_loss_sim(fired, stops=(None, 0.5, 0.7, 0.9)):
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
                      "max_dd": st["max_dd"], "longest_dd_run": st["longest_dd_run"], "win_rate": st["win_rate"]}
    return out


def tail_risk(fired):
    if not fired:
        return {}
    pnls = np.asarray([t["pnl"] for t in fired])
    ix = np.argsort(pnls)
    cut = max(1, len(pnls) // 20)
    worst = ix[:cut]
    return {
        "n_total": len(fired),
        "worst_n": len(worst),
        "worst_total_pnl": float(pnls[worst].sum()),
        "worst_pct_of_total": float(pnls[worst].sum() / pnls.sum() * 100) if pnls.sum() != 0 else 0.0,
        "worst_hours": sorted(set(datetime.fromtimestamp(fired[i]["ts"], tz=timezone.utc).hour for i in worst)),
        "worst_dirs": {d: sum(1 for i in worst if fired[i]["direction"] == d) for d in ("Up", "Down")},
    }


def run_variant(label, all_rows, spread_filter, require_mh):
    by_asset = defaultdict(list)
    for r in all_rows:
        by_asset[r["asset"]].append(r)
    asset_results = {}
    for asset_up in ("BTC", "ETH", "SOL"):
        rows = by_asset.get(asset_up, [])
        if len(rows) < 100:
            continue
        train, holdout = chrono_split(rows)
        thresholds = {}
        for direction in ("UP", "DOWN"):
            q = V3_PER_ASSET_QUANTILE[(asset_up, "5m", direction)]
            thresholds[(asset_up, "5m", direction)] = fit_quantile(train, asset_up, "5m", direction, q)
        train_fired = evaluate_v3(train, thresholds, spread_filter, require_mh)
        holdout_fired = evaluate_v3(holdout, thresholds, spread_filter, require_mh)
        tp = np.asarray([t["pnl"] for t in train_fired])
        hp = np.asarray([t["pnl"] for t in holdout_fired])
        ts_t = np.asarray([t["ts"] for t in train_fired]) if train_fired else None
        ts_h = np.asarray([t["ts"] for t in holdout_fired]) if holdout_fired else None
        train_stats = equity_curve_stats(tp, trade_timestamps=ts_t)
        hold_stats = equity_curve_stats(hp, trade_timestamps=ts_h)
        boot = bootstrap_pnl(hp)
        perm = permutation_test([r["ret_5m"] for r in rows], [r["outcome_up"] for r in rows])
        sl = stop_loss_sim(holdout_fired)
        tr = tail_risk(holdout_fired)
        asset_results[asset_up] = {
            "n_train_rows": len(train), "n_holdout_rows": len(holdout),
            "n_train_fired": len(train_fired), "n_holdout_fired": len(holdout_fired),
            "train_stats": train_stats, "holdout_stats": hold_stats,
            "bootstrap": boot, "permutation": perm,
            "stop_loss_sim": sl, "tail_risk": tr,
            "thresholds": thresholds,
        }
    return {"label": label, "spread_filter": spread_filter, "require_mh": require_mh, "asset_results": asset_results}


def print_summary(v):
    print(f"\n=== {v['label']} ===")
    print(f"  spread: {v['spread_filter']}, MH: {v['require_mh']}")
    print(f"\n  {'asset':5s}  {'n_h_rows':>8s}  {'fired':>5s}  {'fire%':>6s}  {'hit%':>5s}  {'pnl$':>8s}  {'maxDD$':>8s}  {'IC p':>6s}")
    for a, r in v["asset_results"].items():
        s = r["holdout_stats"]; p = r["permutation"]
        fire = r["n_holdout_fired"] / max(r["n_holdout_rows"], 1) * 100
        print(f"  {a:5s}  {r['n_holdout_rows']:>8d}  {r['n_holdout_fired']:>5d}  {fire:>5.1f}%  "
              f"{s['win_rate']*100:>4.1f}%  {s['total_pnl']:>+8.2f}  {s['max_dd']:>+8.2f}  {p['p_value']:>6.4f}")
    print(f"\n  Stop-loss sim (holdout):")
    for a, r in v["asset_results"].items():
        print(f"    {a}:")
        for vname, st in r["stop_loss_sim"].items():
            print(f"      {vname:12s}  pnl=${st['total_pnl']:>+7.2f}  sharpe={st['sharpe']:>+6.2f}  maxDD=${st['max_dd']:>+6.2f}  win={st['win_rate']*100:>4.1f}%")


def main():
    print("V3 Backtest — Polymarket strike_price (Chainlink oracle, MATCHES production)")
    print(f"  notional=${NOTIONAL_USD}, taker_fee={TAKER_FEE_PCT*100}%")

    # Load all assets' markets, build strike index, then chain returns
    all_markets = []
    for asset in ASSETS:
        all_markets.extend(load_markets_with_strike(asset))
    strike_idx = build_strike_index(all_markets)
    print(f"  markets indexed: {len(all_markets)}")

    # Load book depth (for entry prices) once per asset, by slug
    books_all = {}
    for asset in ASSETS:
        for slug, book in load_book_depth_bucket0(asset).items():
            books_all[slug] = book
    print(f"  books_at_bucket0 indexed: {len(books_all)}")

    # Build dataset: for each 5m market, attach ret_5m/15m/1h + book entries
    rows = []
    skipped = defaultdict(int)
    for mk in all_markets:
        if mk.get("timeframe") != "5m":
            skipped["wrong_tf"] += 1
            continue
        slug = mk["slug"]
        book = books_all.get(slug)
        if not book:
            skipped["no_book"] += 1
            continue
        ret = compute_returns_from_strike(strike_idx, mk["asset"], mk["window_start_unix"])
        if not math.isfinite(ret["ret_5m"]) or ret["ret_5m"] == 0:
            skipped["no_ret_5m"] += 1
            continue
        rows.append({**mk, **book, **ret})
    print(f"  skipped: {dict(skipped)}")
    print(f"  total rows usable: {len(rows)}")

    variants = [
        run_variant("V3_BASELINE (uniform 0.02 spread, MH on V3 base)",
                    rows, {"BTC": 0.02, "ETH": 0.02, "SOL": 0.02}, require_mh=True),
        run_variant("V3_SOL_FIX (BTC/ETH=0.02, SOL=0.025, MH on)",
                    rows, {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}, require_mh=True),
        run_variant("V3_SOL_FIX_NO_MH (sanity: drop MH for SOL)",
                    rows, {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}, require_mh=False),
    ]
    for v in variants:
        print_summary(v)

    today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    report = REPORTS / f"V3_BACKTEST_ORACLE_{today}.md"
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
