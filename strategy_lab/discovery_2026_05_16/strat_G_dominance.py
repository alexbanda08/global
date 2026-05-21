"""
Strategy G -- BTC Dominance Regime Overlay.

Hypothesis: BTC dominance rising -> BTC outperforms alts.
  weekly_delta = dom(today) - dom(7d_ago).
  - dom_up (>0): bias BTC Up, SOL Down.
  - dom_dn (<0): bias BTC Down, SOL Up.
  - ETH is between.

Tests:
  1. Per (asset, timeframe, dom regime): hit rate of Up vs Down outcomes.
     Is there a directional bias?
  2. Use dom regime as a CONFIRMATION on a naive binance-momentum signal.
     Compare: naive vs (naive AND dom_agrees).

Anchor: ws_s. Outcome = chainlink. Fee = 2% on profit only.

Note: dominance is daily and ends 2026-05-01 in the cache.
Markets Apr 24 -> May 1 have fresh dominance.
Markets May 2 -> May 16 use forward-filled dominance (weekly_delta becomes stale 0).
We split results into FRESH-DOM and STALE-DOM partitions in the report.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import (  # type: ignore
    load_resolutions, load_cryptocap_dominance, load_klines_asof, asof_strict,
    slug_to_ws_s,
)
from harness import evaluate_no_book, hold_pnl_no_book, get_klines  # type: ignore


OUT = ROOT / "strategy_lab" / "discovery_2026_05_16"
OUT.mkdir(parents=True, exist_ok=True)


def build_dominance_series() -> pd.DataFrame:
    """Daily BTC dominance, with daily and weekly deltas."""
    dom = load_cryptocap_dominance(symbol_id="CRYPTOCAP_BTC_D", period_id="1DAY").copy()
    dom["price_close"] = dom.price_close.astype(float)
    dom = dom.sort_values("time_period_start_us").reset_index(drop=True)
    dom["dom_t"] = dom.price_close
    dom["dom_t_1d"] = dom.dom_t.shift(1)
    dom["dom_t_7d"] = dom.dom_t.shift(7)
    dom["daily_delta"] = dom.dom_t - dom.dom_t_1d
    dom["weekly_delta"] = dom.dom_t - dom.dom_t_7d
    return dom[["time_period_start_us", "dom_t", "daily_delta", "weekly_delta"]]


def lookup_dom_at(slot_start_us: int, dom_ts_us: np.ndarray, dom_vals: np.ndarray) -> float:
    """asof on a 1D sorted array. Returns dom value as-of the day containing slot_start."""
    if len(dom_ts_us) == 0:
        return float("nan")
    i = int(np.searchsorted(dom_ts_us, slot_start_us, side="right") - 1)
    if i < 0:
        return float("nan")
    return float(dom_vals[i])


def attach_regime(res: pd.DataFrame) -> pd.DataFrame:
    dom = build_dominance_series().dropna(subset=["weekly_delta"]).reset_index(drop=True)
    ts = dom.time_period_start_us.values
    res = res.copy()
    res["daily_delta"] = [lookup_dom_at(int(x), ts, dom.daily_delta.values) for x in res.slot_start_us]
    res["weekly_delta"] = [lookup_dom_at(int(x), ts, dom.weekly_delta.values) for x in res.slot_start_us]
    # Regime tag
    res["weekly_regime"] = np.where(
        res.weekly_delta > 0.0, "DOM_UP",
        np.where(res.weekly_delta < 0.0, "DOM_DN", "DOM_FLAT"),
    )
    res["daily_regime"] = np.where(
        res.daily_delta > 0.0, "DOM_UP",
        np.where(res.daily_delta < 0.0, "DOM_DN", "DOM_FLAT"),
    )
    # Fresh vs stale: dom data ends May 1; if slot_start > may 1 + 1 day, the weekly_delta is partly stale.
    fresh_cutoff = int(pd.Timestamp("2026-05-02", tz="UTC").timestamp() * 1e6)
    res["dom_fresh"] = res.slot_start_us < fresh_cutoff
    return res


def naive_momentum_signal(res: pd.DataFrame) -> pd.DataFrame:
    """Binance momentum over the previous full window, anchored on ws_s (production anchor)."""
    out = res.copy()
    signals = []
    for asset in ["BTC", "ETH", "SOL"]:
        end_us, prices = get_klines(asset, "binance-spot-ws", "1MIN")
        for tf, w in [("5m", 300), ("15m", 900)]:
            sub_idx = res.index[(res.ticker == asset) & (res.timeframe == tf)].tolist()
            for i in sub_idx:
                slug = res.at[i, "slug"]
                ws_s = slug_to_ws_s(slug, tf)
                p_start = asof_strict(end_us, prices, int(ws_s) * 1_000_000)
                p_end = asof_strict(end_us, prices, int(ws_s + w) * 1_000_000)
                if not (np.isfinite(p_start) and np.isfinite(p_end) and p_start > 0):
                    signals.append((i, "SKIP"))
                    continue
                ret = (p_end - p_start) / p_start
                signals.append((i, "UP" if ret > 0 else ("DOWN" if ret < 0 else "SKIP")))
    out["signal_naive"] = "SKIP"
    for i, s in signals:
        out.at[i, "signal_naive"] = s
    return out


def apply_dom_overlay(row, regime_col: str = "weekly_regime") -> str:
    """Bias rule per spec.

    DOM_UP -> bias BTC Up, SOL Down. ETH neutral.
    DOM_DN -> bias BTC Down, SOL Up. ETH neutral.
    """
    naive = row["signal_naive"]
    reg = row[regime_col]
    if naive == "SKIP":
        return "SKIP"
    bias = None
    if reg == "DOM_UP":
        if row.ticker == "BTC": bias = "UP"
        elif row.ticker == "SOL": bias = "DOWN"
    elif reg == "DOM_DN":
        if row.ticker == "BTC": bias = "DOWN"
        elif row.ticker == "SOL": bias = "UP"
    if bias is None:
        return naive
    return naive if naive == bias else "SKIP"


def summarize_baseline_per_regime(res: pd.DataFrame, regime_col: str, label: str) -> pd.DataFrame:
    """Outcome distribution (Up-rate) by (asset, timeframe, regime)."""
    res = res[res.outcome.isin(["Up", "Down"])].copy()
    res["is_up"] = (res.outcome == "Up").astype(int)
    g = (
        res.groupby(["ticker", "timeframe", regime_col])
        .agg(n=("is_up", "size"), up_rate=("is_up", "mean"))
        .reset_index()
    )
    g["regime_kind"] = label
    return g


def summarize_combined(res: pd.DataFrame, signal_col: str, label: str) -> dict:
    fired = res[res[signal_col].isin(("UP", "DOWN"))].copy()
    if len(fired) == 0:
        return {"label": label, "n": 0, "hit_rate": np.nan, "pnl_at_0.5": 0.0}
    fired["won"] = (fired[signal_col].str.upper() == fired.outcome.str.upper()).astype(int)
    fired["pnl"] = fired.apply(
        lambda r: hold_pnl_no_book(r[signal_col], r.outcome, 0.5), axis=1
    )
    return {
        "label": label,
        "n": int(len(fired)),
        "hit_rate": float(fired.won.mean()),
        "pnl_at_0.5": float(fired.pnl.sum()),
    }


def per_asset_summary(res: pd.DataFrame, signal_col: str) -> pd.DataFrame:
    fired = res[res[signal_col].isin(("UP", "DOWN"))].copy()
    if len(fired) == 0:
        return pd.DataFrame()
    fired["won"] = (fired[signal_col].str.upper() == fired.outcome.str.upper()).astype(int)
    fired["pnl"] = fired.apply(
        lambda r: hold_pnl_no_book(r[signal_col], r.outcome, 0.5), axis=1
    )
    return (
        fired.groupby(["ticker", "timeframe"])
        .agg(n=("won", "size"), hit=("won", "mean"), pnl=("pnl", "sum"))
        .round(4)
    )


def main():
    print("[G] Loading resolutions...")
    res = load_resolutions()  # all chainlink-resolved BTC/ETH/SOL x 5m/15m
    print(f"[G] {len(res)} markets total.")

    print("[G] Attaching dominance regime...")
    res = attach_regime(res)
    print(f"[G] regime tagging: weekly_regime dist:")
    print(res.weekly_regime.value_counts().to_string())
    print(f"[G] dom_fresh: {int(res.dom_fresh.sum())} fresh markets / {int((~res.dom_fresh).sum())} stale")

    # ---- TEST 1: baseline outcome distribution per regime ----
    print("\n[G] === TEST 1: outcome up-rate per regime (no signal) ===")
    rows = []
    for col, label in [("weekly_regime", "WEEKLY"), ("daily_regime", "DAILY")]:
        g = summarize_baseline_per_regime(res, col, label)
        rows.append(g)
    out_t1 = pd.concat(rows).reset_index(drop=True)
    out_t1.to_csv(OUT / "G_table1_outcome_per_regime.csv", index=False)
    print(out_t1.to_string())
    # Same on fresh-only
    fresh = res[res.dom_fresh]
    rows_fresh = []
    for col, label in [("weekly_regime", "WEEKLY-FRESH"), ("daily_regime", "DAILY-FRESH")]:
        g = summarize_baseline_per_regime(fresh, col, label)
        rows_fresh.append(g)
    out_t1f = pd.concat(rows_fresh).reset_index(drop=True)
    out_t1f.to_csv(OUT / "G_table1_outcome_per_regime_FRESH.csv", index=False)
    print("[G] same on FRESH partition:")
    print(out_t1f.to_string())

    # ---- TEST 2: naive momentum vs naive+dom-overlay ----
    print("\n[G] === TEST 2: naive binance momentum overlay test ===")
    print("[G] computing naive momentum signal (this loads klines)...")
    res = naive_momentum_signal(res)
    print(f"[G] naive signal dist: {res.signal_naive.value_counts().to_dict()}")

    print("[G] applying weekly dominance overlay...")
    res["signal_w_overlay"] = res.apply(apply_dom_overlay, axis=1, regime_col="weekly_regime")
    res["signal_d_overlay"] = res.apply(apply_dom_overlay, axis=1, regime_col="daily_regime")

    summary_rows = []
    for col, label in [
        ("signal_naive", "NAIVE-momentum"),
        ("signal_w_overlay", "NAIVE+WEEKLY-DOM"),
        ("signal_d_overlay", "NAIVE+DAILY-DOM"),
    ]:
        summary_rows.append(summarize_combined(res, col, label))
        summary_rows.append(summarize_combined(res[res.dom_fresh], col, f"{label}-FRESH"))

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT / "G_table2_overlay_vs_naive.csv", index=False)
    print(summary.to_string())

    # Per-asset for the best dual
    print("\n[G] === per-asset breakdown (FRESH partition) ===")
    fresh_res = res[res.dom_fresh].copy()
    for col, label in [
        ("signal_naive", "NAIVE"),
        ("signal_w_overlay", "NAIVE+WEEKLY-DOM"),
    ]:
        print(f"\n  {label}:")
        pa = per_asset_summary(fresh_res, col)
        print(pa.to_string())

    # Save predictions for further analysis
    res[["slug", "ticker", "timeframe", "slot_start_us", "outcome",
         "weekly_delta", "daily_delta", "weekly_regime", "daily_regime",
         "dom_fresh", "signal_naive", "signal_w_overlay", "signal_d_overlay"]
        ].to_parquet(OUT / "G_predictions.parquet")

    # Verdict
    naive_r = summarize_combined(res[res.dom_fresh], "signal_naive", "naive-fresh")
    over_r = summarize_combined(res[res.dom_fresh], "signal_w_overlay", "overlay-fresh")
    print("\n[G] === VERDICT (FRESH partition) ===")
    print(f"naive   hit={naive_r['hit_rate']:.4f} n={naive_r['n']} pnl_at_0.5={naive_r['pnl_at_0.5']:.2f}")
    print(f"overlay hit={over_r['hit_rate']:.4f} n={over_r['n']} pnl_at_0.5={over_r['pnl_at_0.5']:.2f}")
    if over_r["n"] >= 200 and over_r["hit_rate"] > naive_r["hit_rate"] + 0.02:
        verdict = "ALPHA-CANDIDATE"
    elif over_r["n"] < 50:
        verdict = "INCONCLUSIVE-LOW-N"
    else:
        verdict = "NULL"
    print(f"verdict: {verdict}")
    return {"naive": naive_r, "overlay": over_r, "verdict": verdict}


if __name__ == "__main__":
    main()
