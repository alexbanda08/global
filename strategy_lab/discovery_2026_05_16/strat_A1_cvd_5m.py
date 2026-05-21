"""Strategy A1 — CVD-momentum on 5m markets, production-style anchor.

Signal:
  ws_s     = slug_to_ws_s(slug, '5m')      # PREVIOUS slot start
  obs win  = [ws_s, ws_s + 120]   seconds  # production observation window
  fire_us  = (ws_s + 120) * 1e6            # production fire anchor
  CVD over CLOB trades on Up-side of the market during obs_win:
    signed = +size if BUY else -size
    cvd    = sum(signed)
  signal = UP   if cvd > +T
           DOWN if cvd < -T
           SKIP otherwise

NO LOOKAHEAD: every trade used has timestamp_us in [signal_us, fire_us). Compare to
outcome (chainlink). Quick PnL = flat 0.5 entry, 2% fee on profit.
"""
from __future__ import annotations
import sys, os, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_trades, slug_to_ws_s  # type: ignore
from discovery_2026_05_16.harness import hold_pnl_no_book  # type: ignore

THRESHOLDS = [0, 50, 100, 200, 500, 1000]
ASSETS = ["BTC", "ETH", "SOL"]


def compute_cvd_per_market(trades: pd.DataFrame, slug: str, signal_us: int, fire_us: int) -> float:
    """Sum signed notional ($) on Up-side trades in [signal_us, fire_us)."""
    sub = trades[(trades["slug"] == slug) &
                 (trades["outcome"] == "Up") &
                 (trades["timestamp_us"] >= signal_us) &
                 (trades["timestamp_us"] < fire_us)]
    if len(sub) == 0:
        return 0.0
    price = sub["price"].astype(float).to_numpy()
    size = sub["size"].astype(float).to_numpy()
    side = sub["side"].astype(str).str.upper().to_numpy()
    notional = price * size  # dollars
    signed = np.where(side == "BUY", notional, -notional)
    return float(signed.sum())


def run_asset(asset: str, sample_n: int | None = None, examples_out: list | None = None):
    print(f"\n=== {asset} 5m ===", flush=True)
    t0 = time.time()
    res = load_resolutions(assets=[asset], timeframes=["5m"]).copy()
    print(f"  universe: {len(res)} markets", flush=True)
    if sample_n is not None and len(res) > sample_n:
        res = res.sample(n=sample_n, random_state=42).reset_index(drop=True)
        print(f"  SAMPLED to {len(res)}", flush=True)
    trades = load_trades(asset.lower())
    print(f"  trades loaded: {len(trades):,} rows  ({time.time()-t0:.1f}s)", flush=True)

    # Pre-filter trades to Up outcome only and sort + group by slug for speed
    trades_up = trades[trades["outcome"] == "Up"][["slug","timestamp_us","price","size","side"]].copy()
    trades_up = trades_up.sort_values(["slug","timestamp_us"])
    # Group by slug into dict of numpy arrays
    print(f"  building per-slug index from {len(trades_up):,} Up trades...", flush=True)
    by_slug: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    # vectorized: groupby once
    for slug, grp in trades_up.groupby("slug", sort=False):
        ts = grp["timestamp_us"].to_numpy()
        price = grp["price"].astype(float).to_numpy()
        size = grp["size"].astype(float).to_numpy()
        side = grp["side"].astype(str).str.upper().to_numpy()
        notional = price * size
        signed = np.where(side == "BUY", notional, -notional)
        by_slug[slug] = (ts, signed)
    print(f"  indexed {len(by_slug)} slugs with Up trades  ({time.time()-t0:.1f}s)", flush=True)

    cvds = np.zeros(len(res), dtype=float)
    n_trades_per = np.zeros(len(res), dtype=int)
    slugs = res["slug"].to_numpy()
    timeframes = res["timeframe"].to_numpy()

    for i in range(len(res)):
        slug = slugs[i]
        tf = timeframes[i]
        ws_s = slug_to_ws_s(slug, tf)
        signal_us = int(ws_s * 1_000_000)
        fire_us = int((ws_s + 120) * 1_000_000)
        rec = by_slug.get(slug)
        if rec is None:
            continue
        ts, signed = rec
        lo = np.searchsorted(ts, signal_us, side="left")
        hi = np.searchsorted(ts, fire_us, side="left")
        if hi > lo:
            cvds[i] = signed[lo:hi].sum()
            n_trades_per[i] = hi - lo

    res["cvd_obs"] = cvds
    res["n_obs_trades"] = n_trades_per
    print(f"  signals computed  ({time.time()-t0:.1f}s)", flush=True)
    print(f"  cvd_obs stats: mean={cvds.mean():.1f} std={cvds.std():.1f} "
          f"min={cvds.min():.1f} max={cvds.max():.1f} nonzero={(cvds!=0).sum()}/{len(cvds)}", flush=True)

    # Generate example trades for lookahead audit
    if examples_out is not None and len(examples_out) < 3:
        # pick a market with non-zero cvd
        nonzero = res[res["n_obs_trades"] > 0].head(5)
        for _, row in nonzero.iterrows():
            if len(examples_out) >= 3:
                break
            slug = row["slug"]
            ws_s = slug_to_ws_s(slug, row["timeframe"])
            fire_us = int((ws_s + 120) * 1_000_000)
            sub_all = trades[(trades["slug"] == slug) & (trades["outcome"] == "Up")]
            sub_used = sub_all[(sub_all["timestamp_us"] >= int(ws_s * 1e6)) &
                               (sub_all["timestamp_us"] < fire_us)]
            if len(sub_used) >= 3:
                examples_out.append({
                    "asset": asset, "slug": slug,
                    "ws_s": int(ws_s), "fire_us": fire_us,
                    "max_trade_ts_us": int(sub_used["timestamp_us"].max()),
                    "n_used": int(len(sub_used)),
                    "max_lt_fire": int(sub_used["timestamp_us"].max()) < fire_us,
                })

    rows = []
    for T in THRESHOLDS:
        sig = np.where(cvds > T, "UP", np.where(cvds < -T, "DOWN", "SKIP"))
        res["signal"] = sig
        fired = res[res["signal"].isin(("UP", "DOWN"))].copy()
        n = len(fired)
        if n == 0:
            rows.append({"asset": asset, "threshold": T, "n_fires": 0,
                         "hit_rate": np.nan, "pnl_flat_0.5": 0.0,
                         "n_up": 0, "n_down": 0})
            continue
        won = (fired["signal"].str.upper() == fired["outcome"].str.upper()).astype(int)
        hit = won.mean()
        pnls = fired.apply(lambda r: hold_pnl_no_book(r["signal"], r["outcome"], 0.5), axis=1)
        rows.append({
            "asset": asset, "threshold": T, "n_fires": n,
            "hit_rate": round(float(hit), 4),
            "pnl_flat_0.5": round(float(pnls.sum()), 2),
            "n_up": int((fired["signal"] == "UP").sum()),
            "n_down": int((fired["signal"] == "DOWN").sum()),
        })
    return pd.DataFrame(rows)


def main():
    examples = []
    all_results = []
    for asset in ASSETS:
        df = run_asset(asset, examples_out=examples)
        all_results.append(df)
        print("\n--- per-threshold sweep ---", flush=True)
        print(df.to_string(index=False), flush=True)

    combined = pd.concat(all_results, ignore_index=True)
    # combined across assets per threshold
    agg = combined.groupby("threshold").apply(
        lambda g: pd.Series({
            "n_fires": int(g["n_fires"].sum()),
            "hit_rate": float((g["hit_rate"] * g["n_fires"]).sum() / max(g["n_fires"].sum(), 1)),
            "pnl_flat_0.5": float(g["pnl_flat_0.5"].sum()),
        })
    ).reset_index()
    print("\n=== A1 COMBINED (all assets) ===", flush=True)
    print(agg.to_string(index=False), flush=True)

    print("\n=== A1 NO-LOOKAHEAD EXAMPLES (max trade ts_us must be < fire_us) ===", flush=True)
    for ex in examples[:3]:
        print(f"  {ex['asset']} slug={ex['slug']} ws_s={ex['ws_s']} fire_us={ex['fire_us']} "
              f"n_used={ex['n_used']} max_trade_ts_us={ex['max_trade_ts_us']} "
              f"OK={ex['max_lt_fire']}", flush=True)

    out_dir = ROOT / "strategy_lab" / "discovery_2026_05_16"
    combined.to_csv(out_dir / "_A1_per_asset_threshold.csv", index=False)
    agg.to_csv(out_dir / "_A1_combined.csv", index=False)
    print(f"\nWrote: {out_dir/'_A1_per_asset_threshold.csv'}", flush=True)


if __name__ == "__main__":
    main()
