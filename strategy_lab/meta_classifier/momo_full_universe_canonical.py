"""Full universe momo backtest — canonical-data version (2026-05-16).

Same simulation logic as momo_full_universe_validation.py (Phase 3 anchors),
but reads through `data/v4/canonical/load.py` per CLAUDE.md mandate.

Anchors (relative to slug_suffix `ws`, in seconds):
  v1 5m:   ret_2m = log(close@(ws-180) / close@(ws-300))   — first 2 min of prev slot (ws_s+120 vs ws_s for 5m)
  v1 15m:  ret_2m = log(close@(ws-780) / close@(ws-900))
  v2 5m:   ret_2m = log(close@(ws-240) / close@(ws-360))
  v2 15m:  ret_2m = log(close@(ws-840) / close@(ws-960))

Outputs:
  data/v4/canonical/_results/full_universe_2026_05_16/gated_universe.csv
  data/v4/canonical/_results/full_universe_2026_05_16/per_trade.csv
  data/v4/canonical/_results/full_universe_2026_05_16/summary.csv
  data/v4/canonical/_results/full_universe_2026_05_16/walkforward.csv
  data/v4/canonical/_results/full_universe_2026_05_16/permutation.csv
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from load import (  # noqa: E402
    load_resolutions,
    load_klines_asof,
    load_orderbook_l25_streaming,
)

# Reuse simulator + variants + helpers from the v05_09 script.
import momo_full_universe_validation as _v509  # noqa: E402

OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "full_universe_2026_05_16"
OUT.mkdir(parents=True, exist_ok=True)

# --- config (mirrors _v509) --------------------------------------------------
LEVELS = _v509.LEVELS
NOTIONAL = _v509.NOTIONAL
FEE = _v509.FEE
SPREAD_FILTER = _v509.SPREAD_FILTER
GATE_Q = _v509.GATE_Q
LOOKBACK_DAYS = _v509.LOOKBACK_DAYS
SLEEVE_ANCHORS = _v509.SLEEVE_ANCHORS
SLEEVE_FIRE = _v509.SLEEVE_FIRE
VARIANTS = _v509.VARIANTS
simulate_trade = _v509.simulate_trade


# --- canonical data adapters -------------------------------------------------

def load_klines() -> dict:
    """Return {asset: (end_us, price_close)} via canonical loader."""
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        end_us, price_close = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        out[a] = (end_us.astype("int64"), price_close.astype("float64"))
        if len(end_us):
            print(f"    {a}: {len(end_us)} bars, "
                  f"{pd.Timestamp(int(end_us[0]) - 60_000_000, unit='us', tz='UTC')} → "
                  f"{pd.Timestamp(int(end_us[-1]), unit='us', tz='UTC')}")
    return out


def load_universe() -> pd.DataFrame:
    """Chainlink-only resolutions, normalized to v509 schema."""
    res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
    res = res[res.outcome.isin(("Up", "Down"))].copy()
    res["ws"] = res.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    res["asset"] = res.ticker
    res["tf"] = res.timeframe
    res["window_s"] = res.tf.map({"5m": 300, "15m": 900})
    res["day"] = pd.to_datetime(res.ws, unit="s").dt.floor("D")
    # Use `slug` as the condition_id key — the L25 streaming loader is keyed by slug.
    res["condition_id"] = res.slug
    return res[["slug", "condition_id", "asset", "tf", "ws", "window_s", "day", "outcome"]].reset_index(drop=True)


def load_l25_for_asset(asset: str, gated_slugs: set | None) -> tuple[dict, dict]:
    """Canonical L25 streaming loader → dict[(slug,outcome)] → (ts, ap, asz, bp, bsz).
    Returns (books_dict, mid2slug={}). mid2slug unused since we use slug as the key.
    """
    print(f"    streaming L25 from canonical for {asset} (slugs={len(gated_slugs) if gated_slugs else 'ALL'})...")
    books = load_orderbook_l25_streaming(asset.lower(), slugs=gated_slugs, subsample_1hz=True)
    # Reshape values to match (ts, ap, asz, bp, bsz) tuple expected by find_book.
    out = {(slug, oc): rec for (slug, oc), rec in books.items()}
    print(f"    {asset}: {len(out)} (slug,outcome) keys, "
          f"{sum(len(v[0]) for v in out.values()):,} snapshots")
    return out, {}


def main():
    print("[1] load canonical klines + universe...")
    klines = load_klines()
    base_uni = load_universe()
    print(f"    universe: {len(base_uni)} resolved markets, "
          f"{base_uni.day.min().date()} → {base_uni.day.max().date()}")
    print(f"    by (asset, tf): {base_uni.groupby(['asset','tf']).size().to_dict()}")

    print("[2] build per-(version, tf) universes with confirmed anchors + fire offsets...")
    uni_frames = []
    for (version, tf), (off0, off1) in SLEEVE_ANCHORS.items():
        sub = base_uni[base_uni.tf == tf].copy()
        sub["version"] = version
        sub["anchor_off0_s"] = off0
        sub["anchor_off1_s"] = off1
        sub["fire_offset_s"] = SLEEVE_FIRE[(version, tf)]
        sub["ret_2m"] = _v509.compute_ret_2m(sub, klines, off0, off1)
        sub["abs_ret_2m"] = sub.ret_2m.abs()
        print(f"    {version} {tf}: anchors=(ws{off0:+d}, ws{off1:+d}) fire=ws{SLEEVE_FIRE[(version, tf)]:+d}  "
              f"n={len(sub)}  finite_ret_2m={sub.ret_2m.notna().sum()}")
        uni_frames.append(sub)
    uni = pd.concat(uni_frames, ignore_index=True)

    print("[3] compute q90 thresholds per (version, asset, tf, day) on rolling 14d lookback...")
    thr = _v509.compute_thresholds(uni)
    uni["threshold"] = uni.apply(
        lambda r: thr.get((r.version, r.asset, r.tf, str(r.day.date())), float("nan")), axis=1
    )

    gated = uni[(uni.abs_ret_2m.notna()) &
                (uni.threshold.notna()) &
                (uni.abs_ret_2m >= uni.threshold)].copy()
    gated["signal"] = gated.ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
    print(f"    gated: {len(gated)} (top-decile |ret_2m|, ≥50 prior samples/cell-day)")
    print(f"    by version+tf: {gated.groupby(['version','tf']).size().to_dict()}")
    gated.to_csv(OUT / "gated_universe.csv", index=False)

    print("[4] running variants per asset...")
    all_rows = []
    for asset in ("BTC", "ETH", "SOL"):
        print(f"  [{asset}] loading L25...")
        gated_slugs = set(gated[gated.asset == asset].slug.unique())
        books_a, _ = load_l25_for_asset(asset, gated_slugs=gated_slugs)
        if not books_a:
            print(f"    no books for {asset}, skipping")
            continue
        sub = gated[gated.asset == asset]
        print(f"    simulating {len(VARIANTS)} variants × {len(sub)} gated trades...")
        books = {asset: books_a}
        for vname, params in VARIANTS:
            for r in sub.to_dict("records"):
                res = simulate_trade(r, klines, books, params)
                if res is None:
                    continue
                all_rows.append({
                    "variant": vname,
                    "version": r["version"],
                    "fire_offset_s": int(r["fire_offset_s"]),
                    "slug": r["slug"], "asset": asset, "tf": r["tf"], "ws": int(r["ws"]),
                    "day": str(r["day"].date()),
                    "signal": r["signal"], "outcome": r["outcome"], "ret_2m": r["ret_2m"],
                    **res,
                })
        del books_a, books
        print(f"    {asset} done ({len(all_rows)} rows total so far)")

    df = pd.DataFrame(all_rows)
    df.to_csv(OUT / "per_trade.csv", index=False)
    print(f"\n[5] wrote {len(df)} per-trade-per-variant rows -> {OUT}/per_trade.csv")

    # ---- HOLD sanity vs production target ----
    hold = df[df.variant == "HOLD_baseline"]
    print("\n=== HOLD_baseline (production-target +$0.35/trade) ===")
    print(f"  overall:  n={len(hold)}  pnl/trade=${hold.pnl.mean():.4f}  "
          f"hit%={(hold.pnl > 0).mean()*100:.1f}  total=${hold.pnl.sum():.2f}")
    for v in ("v1", "v2"):
        h = hold[hold.version == v]
        if len(h):
            print(f"  {v}:      n={len(h)}  pnl/trade=${h.pnl.mean():.4f}  "
                  f"hit%={(h.pnl > 0).mean()*100:.1f}  total=${h.pnl.sum():.2f}")

    # ---- Per-(variant, version) summary ----
    print("\n=== Variant summary by version ===")
    summary = df.groupby(["version", "variant"]).agg(
        n=("pnl", "size"),
        n_fired=("fired", "sum"),
        fire_pct=("fired", lambda s: round(100 * s.sum() / max(len(s), 1), 1)),
        pnl_total=("pnl", lambda s: round(s.sum(), 2)),
        pnl_mean=("pnl", lambda s: round(s.mean(), 4)),
    ).sort_values(["version", "pnl_total"], ascending=[True, False])
    summary.to_csv(OUT / "summary.csv")
    print(summary.to_string())

    # ---- Per-cell winner ----
    print("\n=== Best variant per (version, asset, tf) by pnl_total ===")
    cell = df.groupby(["version", "asset", "tf", "variant"]).pnl.agg(["sum", "count", "mean"]).reset_index()
    cell.columns = ["version", "asset", "tf", "variant", "pnl_total", "n", "pnl_mean"]
    winners = cell.loc[cell.groupby(["version", "asset", "tf"]).pnl_total.idxmax()]
    winners.to_csv(OUT / "winners.csv", index=False)
    print(winners.sort_values("pnl_total", ascending=False).to_string(index=False))

    # ---- Walkforward by day ----
    print("\n[6] walkforward — out-of-sample by day...")
    wf_rows = []
    days = sorted(df.day.unique())
    for (version, variant), sub in df.groupby(["version", "variant"]):
        for d in days:
            test = sub[sub.day == d]
            if len(test) < 5:
                continue
            wf_rows.append({
                "version": version, "variant": variant, "day": d, "n": len(test),
                "pnl_total": float(test.pnl.sum()),
                "pnl_mean": float(test.pnl.mean()),
                "fire_pct": float(test.fired.mean()),
            })
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "walkforward.csv", index=False)
    wf_summary = wf.groupby(["version", "variant"]).agg(
        n_days=("day", "nunique"),
        days_positive=("pnl_total", lambda s: int((s > 0).sum())),
        oos_pnl_total=("pnl_total", "sum"),
        oos_pnl_mean_per_day=("pnl_total", "mean"),
        oos_pnl_std_per_day=("pnl_total", "std"),
    ).sort_values(["version", "oos_pnl_total"], ascending=[True, False])
    wf_summary["sharpe_per_day"] = (wf_summary.oos_pnl_mean_per_day / wf_summary.oos_pnl_std_per_day).round(3)
    wf_summary.to_csv(OUT / "walkforward_summary.csv")
    print(wf_summary.head(40).to_string())

    # ---- Direction permutation on top 3 variants per version ----
    print("\n[7] DIRECTION_PERM (1000 draws) on top 3 variants per version...")
    rng = np.random.default_rng(42)
    top_keys = []
    for v, gg in summary.groupby(level="version"):
        top_keys.extend([(v, var) for var in gg.head(3).index.get_level_values("variant").tolist()])
    perm_rows = []
    for (version, variant) in top_keys:
        sub = df[(df.variant == variant) & (df.version == version)]
        if len(sub) == 0:
            continue
        for (asset, tf), g in sub.groupby(["asset", "tf"]):
            obs_pnl = float(g.pnl.sum())
            n = len(g)
            pnls = g.pnl.values
            perm_pnls = []
            for _ in range(1000):
                flips = rng.integers(0, 2, size=n)
                p = np.where(flips, -pnls, pnls)
                perm_pnls.append(p.sum())
            perm_arr = np.array(perm_pnls)
            p_value = float((perm_arr >= obs_pnl).mean())
            perm_rows.append({
                "version": version, "variant": variant, "asset": asset, "tf": tf, "n": n,
                "obs_pnl": obs_pnl,
                "perm_mean": float(perm_arr.mean()),
                "perm_std": float(perm_arr.std()),
                "p_value": p_value,
            })
    perm = pd.DataFrame(perm_rows)
    perm.to_csv(OUT / "permutation.csv", index=False)
    print(perm.to_string(index=False))
    print(f"\nDone. Outputs in: {OUT}")


if __name__ == "__main__":
    main()
