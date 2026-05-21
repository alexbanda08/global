"""Overlay micro-Markov regime gate on top of pre-F7 baseline momo fires.

NOTE: canonical data (klines + trading_events_30d) ends 2026-05-19; F7 was
deployed 2026-05-20 19:57 UTC. So this overlay tests the gate on the full
pre-F7 baseline universe (May 6-19, ~13 days) rather than the small F7 cohort.
Result is a much larger-sample lift estimate that can be re-validated on
post-F7 data once VPS3 + canonical refresh.

For each (cell × policy × signal), computes the Markov current_regime at
fire_us under 4 variants:

  window      threshold_mode
  20 × 1m     vol_adaptive (q33/q66 over prior 14d)
  20 × 1m     fixed (BTC=0.3%, ETH=0.5%, SOL=0.8%)
  20 × 5m     vol_adaptive
  20 × 5m     fixed

Binary alignment gate:
  signal=UP    → allow only if regime == Bull
  signal=DOWN  → allow only if regime == Bear
  regime==Sideways → block both
  regime missing (warmup) → block

Reports per-variant (n_pre, n_post, WR_pre, WR_post, PnL_pre, PnL_post,
avg_pnl_pre, avg_pnl_post, retained_pct), grouped by:
  - overall
  - cell version (v1 vs v2)
  - cell symbol_tf (e.g. eth_5m)

Output: writes CSV + summary table to stdout.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, STATES, BEAR, SIDEWAYS, BULL,
)

# Use the pre-F7 baseline window: full trading_events_30d coverage.
WINDOW_START = pd.Timestamp("2026-05-06 00:00:00", tz="UTC")
EVENTS_PATH = "data/v4/canonical/trading_events_30d.parquet"
OUT_DIR = Path("strategy_lab/markov_filter/_results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]

# Fixed thresholds — calibrated to typical 20-bar moves
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},  # 20-min log return
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},  # 100-min log return
}


def load_fires_and_resolutions() -> pd.DataFrame:
    """Build per-fire dataset: one row per F7 fire, joined with its resolution.

    Returns: fire_us, symbol, tf, version, policy, sleeve_id, signal,
             condition_id, won, pnl_usd, cell.
    """
    print("[1] Loading trading_events_30d.parquet ...")
    ev = pd.read_parquet(EVENTS_PATH)
    ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")

    post = ev[ev["at"] >= WINDOW_START].copy()
    print(f"    {len(post):,} events in window {WINDOW_START} -> {post['at'].max()}")

    # Pre-F7 sleeves don't have _f7 suffix. Match all updown momo sleeves.
    sig = post[(post["kind"] == "poly_updown_signal") &
               post["sleeve_id"].str.contains("_momo", na=False)].copy()
    print(f"    {len(sig):,} candidate signal events (kind=signal, momo sleeve)")

    # Fast filter: drop non-fire signals by substring match before json parse
    fire_mask = sig["data"].str.contains('"reason": "order_placed"', na=False) | \
                sig["data"].str.contains('"reason":"order_placed"', na=False)
    sig = sig[fire_mask].copy()
    print(f"    {len(sig):,} fires (reason=order_placed, substring-filtered)")

    parsed = sig["data"].map(json.loads)
    fires = pd.DataFrame({
        "fire_us": (sig["at"].view("int64") // 1000).values,  # ns → us
        "fire_at": sig["at"].values,
        "sleeve_id": sig["sleeve_id"].values,
        "symbol": parsed.map(lambda d: d.get("symbol")).values,
        "tf": parsed.map(lambda d: d.get("tf")).values,
        "signal": parsed.map(lambda d: d.get("signal")).values,
        "condition_id": parsed.map(lambda d: d.get("condition_id")).values,
    })

    # Resolutions
    res = post[(post["kind"] == "poly_updown_resolution") &
               post["sleeve_id"].str.contains("_momo", na=False)].copy()
    print(f"    {len(res):,} resolution events (raw)")
    rparsed = res["data"].map(json.loads)
    resdf = pd.DataFrame({
        "sleeve_id": res["sleeve_id"].values,
        "condition_id": rparsed.map(lambda d: d.get("condition_id")).values,
        "won": rparsed.map(lambda d: bool(d.get("won", False))).values,
        "pnl_usd": rparsed.map(lambda d: float(d.get("pnl_usd", 0.0))).values,
        "outcome": rparsed.map(lambda d: d.get("outcome")).values,
    })
    print(f"    {len(resdf):,} resolutions parsed")

    # Join — every fire must have a matching resolution
    df = fires.merge(resdf, on=["sleeve_id", "condition_id"], how="inner")
    print(f"    {len(df):,} fire-resolution pairs after join")

    # Annotate cell breakdown
    df["cell"] = df["sleeve_id"].str.replace("poly_updown_", "").str.replace("_f7", "")
    df["version"] = df["cell"].apply(lambda c: "v2" if "_momo_v2_" in c else "v1")
    df["policy"]  = df["cell"].str.split("_").str[-1]
    df["symbol_tf"] = df["symbol"].str.lower() + "_" + df["tf"]
    df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
    df = df.dropna(subset=["pnl_usd", "fire_us"])
    return df


def build_all_label_series():
    """Pre-build (end_us, labels) per (asset, variant) → cached in-memory."""
    cache = {}
    for vname, params in VARIANTS:
        for asset in ("BTC", "ETH", "SOL"):
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"],
                      mode=params["mode"])
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            print(f"  building labels: {asset} {vname} ...", end=" ", flush=True)
            end_us, _closes, labels = build_labels_for_asset(asset, **kw)
            n_lab = (labels >= 0).sum()
            print(f"end_us[0..-1]={end_us[0] if len(end_us) else 'NA'}..{end_us[-1] if len(end_us) else 'NA'}, n_labelled={n_lab}")
            cache[(vname, asset)] = (end_us, labels)
    return cache


def apply_gate(df: pd.DataFrame, label_cache: dict) -> pd.DataFrame:
    """For each variant, mark which fires pass the binary alignment gate.
    Adds columns: regime_<vname>, pass_<vname>."""
    for vname, _ in VARIANTS:
        regimes = []
        for _, r in df.iterrows():
            asset = r["symbol"]
            end_us, labels = label_cache.get((vname, asset), (None, None))
            if end_us is None or len(end_us) == 0:
                regimes.append(-1)
                continue
            regimes.append(regime_at_us(end_us, labels, int(r["fire_us"])))
        df[f"regime_{vname}"] = regimes
    for vname, _ in VARIANTS:
        rc = df[f"regime_{vname}"]
        pass_mask = (
            ((df["signal"] == "UP")   & (rc == BULL)) |
            ((df["signal"] == "DOWN") & (rc == BEAR))
        )
        df[f"pass_{vname}"] = pass_mask
    return df


def summarize(df: pd.DataFrame, group_cols: list[str] | None = None) -> pd.DataFrame:
    """Build per-variant comparison: baseline vs Markov-gated."""
    rows = []
    n_pre = len(df)
    wins_pre = df["won"].sum()
    pnl_pre  = df["pnl_usd"].sum()
    if group_cols is None:
        groups = [("ALL", df)]
    else:
        groups = list(df.groupby(group_cols))
    for grp_key, g in groups:
        n_pre = len(g)
        wins_pre = int(g["won"].sum())
        pnl_pre  = float(g["pnl_usd"].sum())
        wr_pre   = wins_pre / n_pre * 100 if n_pre else 0.0
        avg_pre  = pnl_pre / n_pre if n_pre else 0.0

        row = {"group": grp_key if isinstance(grp_key, str) else "_".join(map(str, grp_key)),
               "n_pre": n_pre, "wr_pre": round(wr_pre, 2),
               "pnl_pre": round(pnl_pre, 2), "avg_pre": round(avg_pre, 3)}
        for vname, _ in VARIANTS:
            kept = g[g[f"pass_{vname}"]]
            n = len(kept)
            wins = int(kept["won"].sum())
            pnl = float(kept["pnl_usd"].sum())
            row[f"{vname}_n"]     = n
            row[f"{vname}_wr"]    = round(wins / n * 100, 2) if n else 0.0
            row[f"{vname}_pnl"]   = round(pnl, 2)
            row[f"{vname}_avg"]   = round(pnl / n, 3) if n else 0.0
            row[f"{vname}_keep%"] = round(n / n_pre * 100, 1) if n_pre else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def long_format(df: pd.DataFrame) -> pd.DataFrame:
    """Reshape wide summary into long: one row per (group, variant)."""
    out = []
    for _, r in df.iterrows():
        out.append({"group": r["group"], "variant": "BASELINE",
                    "n": int(r["n_pre"]), "wr": float(r["wr_pre"]),
                    "avg": float(r["avg_pre"]), "pnl": float(r["pnl_pre"]),
                    "keep%": 100.0})
        for v, _ in VARIANTS:
            out.append({"group": r["group"], "variant": v,
                        "n": int(r[f"{v}_n"]), "wr": float(r[f"{v}_wr"]),
                        "avg": float(r[f"{v}_avg"]), "pnl": float(r[f"{v}_pnl"]),
                        "keep%": float(r[f"{v}_keep%"])})
    return pd.DataFrame(out)


def main():
    df = load_fires_and_resolutions()
    if df.empty:
        print("NO FIRES — aborting"); return
    print(f"\n[2] Building Markov label series per (asset, variant)...")
    cache = build_all_label_series()
    print(f"\n[3] Applying gates to {len(df):,} fires...")
    df = apply_gate(df, cache)

    df.to_csv(OUT_DIR / "post_f7_fires_with_regimes.csv", index=False)
    print(f"    wrote {OUT_DIR}/post_f7_fires_with_regimes.csv")

    pd.set_option("display.width", 220)

    for name, group_cols in [
        ("ALL fires",                None),
        ("by version (v1/v2)",       ["version"]),
        ("by symbol_tf",             ["symbol_tf"]),
        ("by version × symbol_tf",   ["version", "symbol_tf"]),
    ]:
        s = summarize(df, group_cols=group_cols)
        suffix = "all" if group_cols is None else "_".join(group_cols)
        s.to_csv(OUT_DIR / f"summary_{suffix}.csv", index=False)
        long = long_format(s)
        print(f"\n=== {name} ===")
        print(long.to_string(index=False))


if __name__ == "__main__":
    main()
