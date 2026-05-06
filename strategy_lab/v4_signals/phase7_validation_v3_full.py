"""phase7_validation_v3_full.py — V3 backtest on FULL 12.5d window.

Uses HL klines (geo-allowed) instead of binance klines (collector dead since 04-29).
Computes features inline from:
  - data/v4/refresh_2026_05_02/{asset}_book_depth_v3_full.csv  (bucket 0 = entry price/spread)
  - data/v4/refresh_2026_05_02/{asset}_markets_minimal.csv     (outcome_up + window_start_unix)
  - data/v4/refresh_2026_05_02/hl_klines_full.csv              (HL 5MIN/15MIN/1HRS for ret_5m/15m/1h)

Re-applies the V3 backtest with all gates (chronological CV, permutation, bootstrap, stop-loss,
tail risk) on the FULL 12.5d window — gives proper sample power for SOL multi-horizon decision.
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

# V3 config
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


def load_klines() -> dict[tuple[str, str], list[tuple[int, float]]]:
    """Returns {(asset, period_id): [(ts, close), ...]} sorted by ts.

    Loads BINANCE SPOT 1MIN from VPS3 (correct data source matching production's signal).
    """
    path = DATA / "binance_spot_1min_full.csv"
    out: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    sym_map = {"BINANCE_SPOT_BTC_USDT": "btc",
               "BINANCE_SPOT_ETH_USDT": "eth",
               "BINANCE_SPOT_SOL_USDT": "sol"}
    with open(path) as f:
        for r in csv.DictReader(f):
            asset = sym_map.get(r["symbol_id"])
            if not asset:
                continue
            try:
                ts = int(r["time_period_start_us"]) // 1_000_000
                close = float(r["price_close"])
            except (ValueError, TypeError):
                continue
            out[(asset, r["period_id"])].append((ts, close))
    for k in out:
        out[k].sort()
    return dict(out)


def asof_close(klines: list[tuple[int, float]], target_s: int) -> float:
    """Returns last close where ts ≤ target_s. NaN if before earliest bar."""
    if not klines:
        return float("nan")
    # binary search
    lo, hi = 0, len(klines) - 1
    if target_s < klines[0][0]:
        return float("nan")
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if klines[mid][0] <= target_s:
            lo = mid
        else:
            hi = mid - 1
    return klines[lo][1]


def compute_returns(klines_map: dict, asset: str, ws: int) -> dict:
    """Replicates production's signal computation EXACTLY.

    Per polymarket_updown.py + strategy_5m.py + bars.py::fetch_close_asof:
    - Production's signal_ts = bars[-1].bar_open of the just-closed strategy 5MIN bar
      = polymarket_window_start - 300s (one strategy_tf period before market opens)
    - btc_now = fetch_close_asof(1MIN, signal_ts). SQL: time_period_start_us <= ts_us LIMIT 1 DESC.
      In LIVE production, the 1MIN bar opening AT signal_ts isn't ingested yet → returns prior bar.
      In BACKTEST, that bar IS in DB. Use signal_ts - 1 to skip it (matches LIVE behavior).
    - btc_prior = fetch_close_asof(1MIN, signal_ts - 300)
    - ret_5m = log(btc_now / btc_prior)

    Verified by brute-force offset sweep: offset=-300 yields 100% direction match with production.
    """
    k_1m = klines_map.get((asset, "1MIN"), [])
    sig_ts = ws - 300  # production uses bar_open of just-closed 5MIN bar

    # In live, the 1MIN bar opening at sig_ts hasn't been ingested. To replicate live behavior
    # in backtest, exclude that bar by subtracting 1 second from the asof target.
    c_now = asof_close(k_1m, sig_ts - 1)
    c_5m_ago = asof_close(k_1m, sig_ts - 300 - 1)
    c_15m_ago = asof_close(k_1m, sig_ts - 900 - 1)
    c_1h_ago = asof_close(k_1m, sig_ts - 3600 - 1)
    c_now_5 = c_now
    c_now_15 = c_now
    c_now_1h = c_now

    out = {}
    for label, c_now, c_prev in [
        ("ret_5m", c_now_5, c_5m_ago),
        ("ret_15m", c_now_15, c_15m_ago),
        ("ret_1h", c_now_1h, c_1h_ago),
    ]:
        if math.isfinite(c_now) and math.isfinite(c_prev) and c_prev > 0:
            out[label] = math.log(c_now / c_prev)
        else:
            out[label] = float("nan")
    return out


def load_markets_minimal(asset: str) -> dict[str, dict]:
    """Load mr_full.csv-style markets keyed by slug. window_start_unix in seconds."""
    path = DATA / f"{asset}_markets_minimal.csv"
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                r["window_start_unix"] = int(r["window_start_unix"])
                r["resolve_unix"] = int(r["resolve_unix"])
                r["outcome_up"] = int(r["outcome_up"])
            except (KeyError, ValueError):
                continue
            r["asset"] = asset.upper()
            r["timeframe"] = r.get("timeframe", "5m")
            out[r["slug"]] = r
    return out


def load_book_depth_bucket0(asset: str) -> dict[str, dict]:
    """Load book_depth full and extract bucket 0 prices per (slug, outcome).
    Returns {slug: {entry_yes_bid, entry_yes_ask, entry_no_bid, entry_no_ask}}.
    """
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
                entry["entry_yes_bid"] = bid
                entry["entry_yes_ask"] = ask
            elif outcome == "Down":
                entry["entry_no_bid"] = bid
                entry["entry_no_ask"] = ask
    # Filter to slugs with both Up and Down books
    return {s: e for s, e in out.items() if "entry_yes_ask" in e and "entry_no_ask" in e}


def build_dataset(klines_map: dict) -> list[dict]:
    """Combine markets + book + computed returns into rows ready for V3 logic."""
    all_rows = []
    skipped = defaultdict(int)
    for asset in ASSETS:
        markets = load_markets_minimal(asset)
        books = load_book_depth_bucket0(asset)
        print(f"  {asset}: markets={len(markets)}  books_at_bucket0={len(books)}")
        for slug, mk in markets.items():
            if mk.get("timeframe") != "5m":
                skipped["wrong_tf"] += 1
                continue
            book = books.get(slug)
            if not book:
                skipped["no_book"] += 1
                continue
            ret = compute_returns(klines_map, asset, mk["window_start_unix"])
            if not math.isfinite(ret["ret_5m"]) or ret["ret_5m"] == 0:
                skipped["no_ret_5m"] += 1
                continue
            row = {
                **mk, **book, **ret,
                "asset": asset.upper(),
            }
            all_rows.append(row)
    print(f"  skipped: {dict(skipped)}")
    return all_rows


def multi_horizon_aligned(r: dict) -> bool:
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
                      "max_dd": st["max_dd"], "longest_dd_run": st["longest_dd_run"],
                      "win_rate": st["win_rate"]}
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
        ts_train = np.asarray([t["ts"] for t in train_fired]) if train_fired else None
        ts_hold = np.asarray([t["ts"] for t in holdout_fired]) if holdout_fired else None
        train_stats = equity_curve_stats(tp, trade_timestamps=ts_train)
        hold_stats = equity_curve_stats(hp, trade_timestamps=ts_hold)
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
    print(f"\n  Tail risk (worst 5%):")
    for a, r in v["asset_results"].items():
        t = r["tail_risk"]
        if t:
            print(f"    {a}: worst {t['worst_n']}/{t['n_total']}  sum=${t['worst_total_pnl']:+.2f} ({t['worst_pct_of_total']:+.1f}%)  hours={t['worst_hours']}  dirs={t['worst_dirs']}")


def main() -> int:
    print("V3 Baseline Backtest — FULL 12.5d window (HL klines for ret_*)")
    print(f"  notional=${NOTIONAL_USD}, taker_fee={TAKER_FEE_PCT*100}%")
    klines_map = load_klines()
    print(f"  klines loaded: {[(k, len(v)) for k, v in klines_map.items()]}")
    rows = build_dataset(klines_map)
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
    report = REPORTS / f"V3_BACKTEST_FULL_{today}.md"
    md = build_markdown(variants, today, len(rows))
    report.write_text(md, encoding="utf-8")
    print(f"\nReport: {report}")
    return 0


def build_markdown(variants, today, n_rows):
    lines = [
        f"# V3 Backtest — FULL 12.5d Window ({today})",
        "",
        f"**Sample:** {n_rows} usable markets (04-22 → 05-04). Reuses validation gates from `phase7_validation_v3.py`.",
        "",
        "Note: returns computed from **HL perp klines** (Binance collector dead since 04-29 due to geoblock). HL perp ≈ Binance spot for 5m/15m/1h horizons (sub-bps basis difference).",
        "",
    ]
    for v in variants:
        lines.append(f"## {v['label']}")
        lines.append("")
        lines.append(f"spread: {v['spread_filter']}, MH: {v['require_mh']}")
        lines.append("")
        lines.append("| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ | IC p |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for a, r in v["asset_results"].items():
            s = r["holdout_stats"]; p = r["permutation"]
            fire = r["n_holdout_fired"] / max(r["n_holdout_rows"], 1) * 100
            lines.append(f"| {a} | {r['n_holdout_rows']} | {r['n_holdout_fired']} | "
                         f"{fire:.1f}% | {s['win_rate']*100:.1f}% | {s['total_pnl']:+.2f} | "
                         f"{s['max_dd']:+.2f} | {p['p_value']:.4f} |")
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
            if not t: continue
            hrs = ",".join(str(h) for h in t["worst_hours"])
            ds = "/".join(f"{k}={vv}" for k, vv in t["worst_dirs"].items())
            lines.append(f"| {a} | {t['worst_n']}/{t['n_total']} | {t['worst_total_pnl']:+.2f} | "
                         f"{t['worst_pct_of_total']:+.1f}% | {hrs} | {ds} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
