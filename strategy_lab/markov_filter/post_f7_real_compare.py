"""Per-sleeve F7 vs Markov comparison on REAL post-F7 production fires.

Source: VPS3 trading.events, window 2026-05-20 19:57 UTC → 2026-05-21 19:20 UTC
        (~23.5h, 25k events).

The sleeve_id ending in `_f7` means F7 filter is ACTIVE (production says "go").
The non-`_f7` baseline sleeves fire WITHOUT F7. Both deploy simultaneously, so
they create a real A/B on the same slugs.

For each production fire, we look up:
  - Markov regime at fire_us (using canonical binance 1m klines)
  - Then test whether Markov alignment ADDS edge on top of F7 production decisions.

Computes per-sleeve table for baseline vs +F7 vs +Markov vs +F7+Markov.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import load_klines  # noqa: E402
sys.path.insert(0, "strategy_lab/markov_filter")
from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, BEAR, SIDEWAYS, BULL,
)

EVENTS_CSV = "strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv"
FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
OUT_DIR = Path("strategy_lab/markov_filter/_results/post_f7_real_compare")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MARKOV_VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
}


def load_production_fires() -> pd.DataFrame:
    print("[1] Reading VPS3 events CSV...")
    ev = pd.read_csv(EVENTS_CSV, sep=",")
    print(f"    {len(ev):,} events loaded")
    ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")
    ev["is_f7"] = ev["sleeve_id"].str.endswith("_f7", na=False)
    ev["base_cell"] = ev["sleeve_id"].str.replace("poly_updown_", "").str.replace("_f7", "")
    return ev


def build_fires_and_outcomes(ev: pd.DataFrame) -> pd.DataFrame:
    """Join signals (reason=order_placed) with resolutions on (sleeve_id, condition_id)."""
    # Signals → fires
    sig = ev[ev["kind"] == "poly_updown_signal"].copy()
    sig = sig[sig["data"].str.contains('"order_placed"', na=False)]
    print(f"[2] Parsing {len(sig)} signal events (order_placed)...")
    parsed = sig["data"].map(json.loads)
    fires = pd.DataFrame({
        "fire_us": (sig["at"].astype("int64") // 1000).values,
        "fire_at": sig["at"].values,
        "sleeve_id": sig["sleeve_id"].values,
        "is_f7": sig["is_f7"].values,
        "base_cell": sig["base_cell"].values,
        "symbol": parsed.map(lambda d: d.get("symbol")).values,
        "tf": parsed.map(lambda d: d.get("tf")).values,
        "signal": parsed.map(lambda d: d.get("signal")).values,
        "condition_id": parsed.map(lambda d: d.get("condition_id")).values,
    })
    print(f"    {len(fires)} fires")

    # Resolutions
    res = ev[ev["kind"] == "poly_updown_resolution"].copy()
    rparsed = res["data"].map(json.loads)
    resdf = pd.DataFrame({
        "sleeve_id": res["sleeve_id"].values,
        "condition_id": rparsed.map(lambda d: d.get("condition_id")).values,
        "won": rparsed.map(lambda d: bool(d.get("won", False))).values,
        "pnl_usd": pd.to_numeric(rparsed.map(lambda d: d.get("pnl_usd", 0.0)),
                                 errors="coerce").values,
        "outcome": rparsed.map(lambda d: d.get("outcome")).values,
        "entry_price": pd.to_numeric(rparsed.map(lambda d: d.get("entry_price")),
                                     errors="coerce").values,
    })
    print(f"[3] Parsed {len(resdf)} resolutions")

    df = fires.merge(resdf, on=["sleeve_id", "condition_id"], how="inner")
    print(f"[4] Joined {len(df)} fire-resolution pairs")
    df = df.dropna(subset=["symbol", "tf", "signal", "pnl_usd", "fire_us"])
    df["version"] = df["base_cell"].apply(lambda c: "v2" if "_momo_v2_" in c else "v1")
    df["policy"]  = df["base_cell"].str.split("_").str[-1]
    df["sleeve"]  = df["symbol"].str.lower() + "_" + df["tf"] + "_" + df["version"]
    return df


def compute_markov_per_fire(df: pd.DataFrame) -> pd.DataFrame:
    print(f"\n[5] Building Markov labels per (asset × variant)...")
    cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ("BTC", "ETH", "SOL"):
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"],
                      fresh_klines_csv=FRESH_KLINES)
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            cache[(vname, asset)] = (end_us, labels)
            t_last = pd.Timestamp(end_us[-1] / 1e6, unit='s', tz='UTC') if len(end_us) else None
            n_lab = int((labels >= 0).sum())
            print(f"    {asset} {vname}: bars={len(end_us)}, labelled={n_lab}, last_bar={t_last}")
    print("    label cache ready")

    print(f"\n[6] Looking up regime at fire_us for {len(df)} fires × {len(MARKOV_VARIANTS)} variants...")
    for vname, _ in MARKOV_VARIANTS:
        regs = []
        for _, r in df.iterrows():
            end_us, labels = cache[(vname, r["symbol"])]
            regs.append(regime_at_us(end_us, labels, int(r["fire_us"])))
        df[f"regime_{vname}"] = regs
        pass_mask = (
            ((df["signal"] == "UP")   & (df[f"regime_{vname}"] == BULL)) |
            ((df["signal"] == "DOWN") & (df[f"regime_{vname}"] == BEAR))
        )
        df[f"markov_pass_{vname}"] = pass_mask
        # how many are warmed-up (regime != -1)
        warm = (df[f"regime_{vname}"] >= 0).sum()
        print(f"    {vname}: warm={warm}/{len(df)} pass={pass_mask.sum()} ({pass_mask.mean()*100:.1f}%)")
    return df


def summarize(g, label):
    n = len(g)
    if n == 0:
        return {"filter": label, "n": 0, "wr": 0.0, "avg": 0.0, "sum": 0.0}
    return {
        "filter": label, "n": n,
        "wr": round(g["won"].mean() * 100, 2),
        "avg": round(g["pnl_usd"].mean(), 3),
        "sum": round(g["pnl_usd"].sum(), 2),
    }


def per_sleeve_report(df: pd.DataFrame):
    """For each sleeve, compare:
       BASELINE         = all fires (both _f7 and non-_f7)
       F7_only          = only _f7 sleeve fires (production F7 says yes)
       NoF7             = only baseline (non-_f7) sleeve fires
       MARKOV_only      = ALL fires where markov passes
       F7+MARKOV        = _f7 sleeve fires where markov passes
       NoF7+MARKOV      = baseline sleeve fires where markov passes
    """
    sleeves = sorted(df["sleeve"].unique())
    print(f"\n=== PER-SLEEVE comparison ({len(sleeves)} sleeves) ===")
    all_rows = []
    for sleeve in sleeves:
        sub = df[df["sleeve"] == sleeve]
        if len(sub) < 5:
            print(f"\n--- {sleeve}  (n={len(sub)} — TOO SMALL, skipping)")
            continue
        f7_sub  = sub[sub["is_f7"]]
        no_sub  = sub[~sub["is_f7"]]
        rows = [
            summarize(sub,    "BASELINE_ALL"),
            summarize(no_sub, "BASELINE_no_f7"),
            summarize(f7_sub, "F7_production"),
        ]
        for vname, _ in MARKOV_VARIANTS:
            mk = f"markov_pass_{vname}"
            rows.append(summarize(sub[sub[mk]],                          f"MARKOV:{vname}"))
            rows.append(summarize(no_sub[no_sub[mk]],                    f"NoF7+MARKOV:{vname}"))
            rows.append(summarize(f7_sub[f7_sub[mk]],                    f"F7+MARKOV:{vname}"))
        sleeve_df = pd.DataFrame(rows)
        sleeve_df["sleeve"] = sleeve
        print(f"\n--- {sleeve}  (n_total={len(sub)}, n_baseline={len(no_sub)}, n_f7={len(f7_sub)}) ---")
        print(sleeve_df[["filter","n","wr","avg","sum"]].to_string(index=False))
        all_rows.append(sleeve_df)
    if not all_rows:
        return
    out = pd.concat(all_rows, ignore_index=True)
    out = out[["sleeve","filter","n","wr","avg","sum"]]
    out.to_csv(OUT_DIR / "per_sleeve_full.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'per_sleeve_full.csv'}")


def main():
    ev = load_production_fires()
    df = build_fires_and_outcomes(ev)
    if df.empty:
        print("NO FIRES"); return
    df = compute_markov_per_fire(df)
    df.to_csv(OUT_DIR / "fires_with_gates.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'fires_with_gates.csv'}")

    # Overall headline
    print("\n=== OVERALL ===")
    no_sub = df[~df["is_f7"]]
    f7_sub = df[df["is_f7"]]
    rows = [
        summarize(df,     "ALL_FIRES"),
        summarize(no_sub, "baseline (no _f7)"),
        summarize(f7_sub, "F7 production"),
    ]
    for vname, _ in MARKOV_VARIANTS:
        mk = f"markov_pass_{vname}"
        rows.append(summarize(df[df[mk]],                          f"MARKOV:{vname}"))
        rows.append(summarize(no_sub[no_sub[mk]],                  f"NoF7+MARKOV:{vname}"))
        rows.append(summarize(f7_sub[f7_sub[mk]],                  f"F7+MARKOV:{vname}"))
    print(pd.DataFrame(rows).to_string(index=False))

    per_sleeve_report(df)


if __name__ == "__main__":
    main()
