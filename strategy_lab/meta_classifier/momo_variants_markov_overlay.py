"""Markov filter overlay on top of variants backtest.

Reads `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
(produced by `momo_variants_2abc.py` after the ws_s F7 anchor fix).

For each (asset, markov_variant) combo, build the Markov regime label series
using `markov_regime_micro.build_labels_for_asset`. Then for each fire in
per_trade, look up the regime at fire_us (CAUSAL — labels only up to that
timestamp via asof).

A fire `passes` Markov filter iff:
    (signal == "UP"   and regime == BULL)
 or (signal == "DOWN" and regime == BEAR)

This matches the production overlay in
`strategy_lab/markov_filter/post_f7_real_compare_v2.py`.

Stack F7 × Markov:
    ALL         — no filters
    F7          — RSI(14) basic gate
    F7+M1F      — F7 + Markov w20_1m_fixed
    F7+M5F      — F7 + Markov w20_5m_fixed
    F7+M1V      — F7 + Markov w20_1m_voladaptive
    F7+M5V      — F7 + Markov w20_5m_voladaptive
    M1F (no F7)
    M5F (no F7)
    M1V (no F7)
    M5V (no F7)

Output:
    data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade_markov.parquet
    data/v4/canonical/_results/momo_variants_2abc_2026_05_20/markov_overlay_summary.csv

Production fee model verified 2026-05-22: legacy 2%-on-profit-only.
Uses `pnl_legacy_usd` column for production-parity PnL.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))

from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, BEAR, SIDEWAYS, BULL,
)

PER_TRADE = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade.parquet"
OUT_PT = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"
OUT_SUM = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "markov_overlay_summary.csv"

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

def f7_basic(sig, rsi):
    if not math.isfinite(rsi): return False
    if sig == "UP"   and rsi <= 50: return False
    if sig == "DOWN" and rsi >= 50: return False
    return True

def f7x(sig, rsi):
    if not math.isfinite(rsi): return False
    if sig == "UP"   and rsi <= 60: return False
    if sig == "DOWN" and rsi >= 40: return False
    return True


def main():
    print(f"[1] loading per_trade.parquet ({PER_TRADE.name})...")
    pt = pd.read_parquet(PER_TRADE)
    print(f"    {len(pt):,} fires")

    # F7 overlay (basic + extreme)
    pt["f7"]  = [f7_basic(s, r) for s, r in zip(pt.signal, pt.rsi_14)]
    pt["f7x"] = [f7x(s, r) for s, r in zip(pt.signal, pt.rsi_14)]

    # Build Markov labels per (variant, asset)
    print(f"[2] building Markov labels for {len(MARKOV_VARIANTS)} variants × 3 assets...")
    cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ("BTC", "ETH", "SOL"):
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"])
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            cache[(vname, asset)] = (end_us, labels)
            n_lbl = int((labels >= 0).sum())
            print(f"    {vname:<22} {asset}: {n_lbl:,} labelled bars (last={pd.Timestamp(int(end_us[-1]),unit='us',tz='UTC') if len(end_us) else 'N/A'})")

    # Regime lookup at each fire's fire_us
    print(f"[3] regime lookup for {len(pt):,} fires × {len(MARKOV_VARIANTS)} variants...")
    fire_us_arr = (pt.fire_s.values.astype("int64") * 1_000_000)
    asset_arr = pt.asset.values
    for vname, _ in MARKOV_VARIANTS:
        regs = np.full(len(pt), -1, dtype=np.int8)
        for asset in ("BTC", "ETH", "SOL"):
            end_us, labels = cache[(vname, asset)]
            if len(labels) == 0:
                continue
            mask = (asset_arr == asset)
            if not mask.any():
                continue
            # Vectorized asof for this asset
            target = fire_us_arr[mask]
            idx = np.searchsorted(end_us, target, side="right") - 1
            ok = (idx >= 0) & (idx < len(labels))
            reg = np.where(ok, labels[np.clip(idx, 0, len(labels)-1)], -1)
            regs[mask] = reg
        pt[f"regime_{vname}"] = regs
        # markov_pass = (UP+BULL) or (DOWN+BEAR)
        pt[f"mpass_{vname}"] = (
            ((pt.signal == "UP")   & (pt[f"regime_{vname}"] == BULL)) |
            ((pt.signal == "DOWN") & (pt[f"regime_{vname}"] == BEAR))
        )

    pt.to_parquet(OUT_PT, index=False)
    print(f"[4] saved {OUT_PT.name}")

    # ===== Aggregate =====
    print(f"\n[5] aggregating overlays per (variant, asset, tf, filter)...")
    rows = []
    overlays = [
        ("ALL",     lambda d: pd.Series(True, index=d.index)),
        ("F7",      lambda d: d.f7),
        ("F7x",     lambda d: d.f7x),
        ("M1F",     lambda d: d.mpass_w20_1m_fixed),
        ("M5F",     lambda d: d.mpass_w20_5m_fixed),
        ("M1V",     lambda d: d.mpass_w20_1m_voladaptive),
        ("M5V",     lambda d: d.mpass_w20_5m_voladaptive),
        ("F7+M1F",  lambda d: d.f7 & d.mpass_w20_1m_fixed),
        ("F7+M5F",  lambda d: d.f7 & d.mpass_w20_5m_fixed),
        ("F7+M1V",  lambda d: d.f7 & d.mpass_w20_1m_voladaptive),
        ("F7+M5V",  lambda d: d.f7 & d.mpass_w20_5m_voladaptive),
        ("F7x+M1F", lambda d: d.f7x & d.mpass_w20_1m_fixed),
        ("F7x+M5F", lambda d: d.f7x & d.mpass_w20_5m_fixed),
        ("F7x+M5V", lambda d: d.f7x & d.mpass_w20_5m_voladaptive),
    ]
    for (variant, asset, tf), g in pt.groupby(["variant","asset","tf"]):
        cell = f"{asset.lower()}_{tf}"
        for label, fn in overlays:
            try:
                mask = fn(g)
            except Exception:
                continue
            sub = g[mask]
            n = len(sub)
            if n == 0:
                continue
            wr = float(sub.won.mean())
            leg_tot = float(sub.pnl_legacy_usd.sum())
            leg_per = float(sub.pnl_legacy_usd.mean())
            rows.append(dict(
                variant=variant, cell=cell, asset=asset, tf=tf, filter=label,
                n=n, wr=wr, leg_tot=leg_tot, leg_per_tr=leg_per,
            ))
    summary = pd.DataFrame(rows).sort_values(["variant","cell","filter"])
    summary.to_csv(OUT_SUM, index=False)

    # ===== Top profit pockets =====
    print()
    print("=" * 100)
    print("TOP PROFIT POCKETS — production-matched PnL (legacy 2%-on-profit)")
    print("Sorted by leg_per_tr desc, min n=15")
    print("=" * 100)
    pkts = summary[summary.n >= 15].sort_values("leg_per_tr", ascending=False).head(30)
    print(f"{'variant':<32} {'cell':<10} {'filter':<10} {'n':>4} {'WR':>6} {'leg_tot':>9} {'/tr':>8}")
    for r in pkts.to_dict("records"):
        print(f"{r['variant']:<32} {r['cell']:<10} {r['filter']:<10} {r['n']:>4} "
              f"{r['wr']*100:>5.1f}% ${r['leg_tot']:>+7.2f} ${r['leg_per_tr']:>+7.4f}")

    # ===== F7 vs F7+Markov stacking on best cells =====
    print()
    print("=" * 100)
    print("F7 vs F7+MARKOV STACKING — Baseline_v1 BTC 15m (top production cell)")
    print("=" * 100)
    g_btc15_v1 = pt[(pt.variant == "Baseline_v1") & (pt.asset == "BTC") & (pt.tf == "15m")]
    print(f"{'filter':<12} {'n':>5} {'WR':>6} {'leg_tot':>9} {'leg/tr':>8}")
    for label, fn in overlays:
        try:
            mask = fn(g_btc15_v1)
        except Exception:
            continue
        sub = g_btc15_v1[mask]
        n = len(sub)
        if n == 0: continue
        wr = sub.won.mean()
        leg_tot = sub.pnl_legacy_usd.sum()
        leg_per = sub.pnl_legacy_usd.mean()
        print(f"{label:<12} {n:>5} {wr*100:>5.1f}% ${leg_tot:>+7.2f} ${leg_per:>+7.4f}")

    # Aggregate across ALL variants × cells
    print()
    print("=" * 100)
    print("AGGREGATE — all 5 variants × 6 cells combined, by filter")
    print("=" * 100)
    print(f"{'filter':<12} {'n':>6} {'WR':>6} {'leg_tot':>10} {'leg/tr':>8}")
    for label, fn in overlays:
        try:
            mask = fn(pt)
        except Exception:
            continue
        sub = pt[mask]
        n = len(sub)
        if n == 0: continue
        wr = sub.won.mean()
        leg_tot = sub.pnl_legacy_usd.sum()
        leg_per = sub.pnl_legacy_usd.mean()
        print(f"{label:<12} {n:>6} {wr*100:>5.1f}% ${leg_tot:>+9.2f} ${leg_per:>+7.4f}")

    print()
    print(f"saved: {OUT_PT}")
    print(f"saved: {OUT_SUM}")


if __name__ == "__main__":
    main()
