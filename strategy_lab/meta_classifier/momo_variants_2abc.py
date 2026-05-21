"""Momo variants 2A / 2B / 2C — late-fire experiments.

Tests three new firing-anchor configurations on top of v1 + v2 production
sleeves, with and without the F7 RSI filter. Built per the session 2026-05-20
request comparing "fire early into prev slot" (production) vs "fire near
slot_open of the new slot" (new variants).

Variants
========

Baseline_v1
    Production v1 anchors.
    5m  : ret_2m=(ws-300, ws-180)  fire=ws-180
    15m : ret_2m=(ws-900, ws-780)  fire=ws-780

Baseline_v2
    Production v2 anchors.
    5m  : ret_2m=(ws-360, ws-240)  fire=ws-240
    15m : ret_2m=(ws-960, ws-840)  fire=ws-840

2A — late fire, late signal
    Fresh signal computed AT fire time (last 2 min before slot opens).
    All tfs: ret_2m=(ws-240, ws-120)  fire=ws-120

2B — late fire, early signal (Design 3 anchor, delayed order)
    Reuses production v1 first-2-min signal but DELAYS the order to slot_start − 120s.
    5m  : ret_2m=(ws-300, ws-180)  fire=ws-120
    15m : ret_2m=(ws-900, ws-780)  fire=ws-120

2C — edge of slot fire
    Fire AT slot_open (ws), signal anchored on prior 2 min.
    All tfs: ret_2m=(ws-120, ws-0)  fire=ws-0

F7 filter (overlay)
===================
RSI(14) on binance 1m at fire time must agree with signal direction:
  UP signal kept iff RSI > 50
  DOWN signal kept iff RSI < 50
(F7x stricter: UP needs RSI>60, DOWN<40 — we report both)

Outputs
=======
data/v4/canonical/_results/momo_variants_2abc_2026_05_20/
  per_trade.parquet      — one row per (variant, slug) gated fire with fill + PnL
  per_variant_cell.csv   — aggregate WR + PnL per (variant, asset, tf, F7-state)
  summary.csv            — overall aggregate per variant + F7-state
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

from load import (  # noqa: E402
    load_resolutions,
    load_klines_asof,
    load_orderbook_l25_streaming,
)
from engine_v2 import (  # noqa: E402
    LegacyConfig,
    LiveMimicConfig,
    fill_at_book,
    hold_pnl,
)
from fees import poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402

REAL_FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)   # 0.07 — real Polymarket curve

OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20"
OUT.mkdir(parents=True, exist_ok=True)

NOTIONAL = 25.0
GATE_Q = 0.90
LOOKBACK_DAYS = 14
MIN_TRAIN_SAMPLES = 50
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}

# Variant config: (anchors_per_tf, fire_offset_per_tf)
#   anchors_per_tf[tf] = (off0, off1)   ret_2m = log(close@(ws+off1) / close@(ws+off0))
#   fire_offset_per_tf[tf] = fire offset relative to ws (slot_start)
VARIANTS = {
    "Baseline_v1": dict(
        anchors={"5m": (-300, -180), "15m": (-900, -780)},
        fire={"5m": -180, "15m": -780},
    ),
    "Baseline_v2": dict(
        anchors={"5m": (-360, -240), "15m": (-960, -840)},
        fire={"5m": -240, "15m": -840},
    ),
    "2A_late_fire_late_signal": dict(
        anchors={"5m": (-240, -120), "15m": (-240, -120)},
        fire={"5m": -120, "15m": -120},
    ),
    "2B_late_fire_early_signal": dict(
        # Design 3 anchors (first 2 min of prev slot) but fire at slot_start − 120
        anchors={"5m": (-300, -180), "15m": (-900, -780)},
        fire={"5m": -120, "15m": -120},
    ),
    "2C_edge_of_slot": dict(
        anchors={"5m": (-120, 0), "15m": (-120, 0)},
        fire={"5m": 0, "15m": 0},
    ),
}


def asof_strict(k_arrays, ts_s: int) -> float:
    end_us, price_close = k_arrays
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(price_close[idx])


def compute_ret_2m(uni: pd.DataFrame, klines: dict, anchors_per_tf: dict) -> np.ndarray:
    out = np.full(len(uni), np.nan)
    for i, (asset, tf, ws) in enumerate(zip(uni.asset.values, uni.tf.values, uni.ws.values)):
        off0, off1 = anchors_per_tf[tf]
        c0 = asof_strict(klines[asset], int(ws) + int(off0))
        c1 = asof_strict(klines[asset], int(ws) + int(off1))
        if math.isfinite(c0) and math.isfinite(c1) and c0 > 0 and c1 > 0:
            out[i] = math.log(c1 / c0)
    return out


def compute_thresholds(uni: pd.DataFrame) -> dict:
    """q90 of |ret_2m| per (asset, tf, day) on prior 14d, excluding current day."""
    out: dict = {}
    for (a, t), g in uni.groupby(["asset", "tf"]):
        g = g.sort_values("ws").reset_index(drop=True)
        days = sorted(g.day.unique())
        for day in days:
            cutoff_lo = day - pd.Timedelta(days=LOOKBACK_DAYS)
            train = g[(g.day >= cutoff_lo) & (g.day < day)]
            samples = train["abs_ret_2m"].dropna().values
            if len(samples) >= MIN_TRAIN_SAMPLES:
                out[(a, t, str(pd.Timestamp(day).date()))] = float(np.quantile(samples, GATE_Q))
            else:
                out[(a, t, str(pd.Timestamp(day).date()))] = float("nan")
    return out


def compute_rsi_14_at(klines: dict, asset: str, anchor_s: int) -> float:
    """RSI(14) on 1-min binance closes at the bar ending <= anchor_s.

    CRITICAL: per CLAUDE.md production convention, F7 RSI must be anchored at
    ws_s = slot_start - window_s (start of PREVIOUS slot, same anchor as ret_2m
    signal). Anchoring at fire_s (= ws_s + 60-900s depending on variant) catches
    mean-reversion AFTER the signal window instead of momentum CONFIRMING the
    signal direction -- this was the 'F7 sign inverted' bug from prior session.

    Always pass anchor_s = ws_s = ws - window_s for correct F7 behavior.
    Returns NaN if the bar ending <= anchor_s is more than 5 min away (stale
    kline guard - prevents asof returning last-bar label for post-window fires).
    """
    end_us, price_close = klines[asset]
    if len(end_us) < 16:
        return float("nan")
    target = int(anchor_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    if idx < 14 or idx >= len(price_close):
        return float("nan")
    # Stale-kline guard: bar end time must be within 5 min of anchor
    bar_end_us = int(end_us[idx])
    if abs(bar_end_us - target) > 5 * 60 * 1_000_000:
        return float("nan")
    closes = price_close[idx - 14: idx + 1]   # 15 closes -> 14 returns
    diffs = np.diff(closes)
    gain = np.where(diffs > 0, diffs, 0.0).mean()
    loss = np.where(diffs < 0, -diffs, 0.0).mean()
    if loss <= 0:
        return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return float(100.0 - 100.0 / (1.0 + rs))


def f7_keep(signal: str, rsi: float, strict: bool = False) -> bool:
    if not math.isfinite(rsi):
        return False
    if strict:
        if signal == "UP" and rsi <= 60: return False
        if signal == "DOWN" and rsi >= 40: return False
    else:
        if signal == "UP" and rsi <= 50: return False
        if signal == "DOWN" and rsi >= 50: return False
    return True


def load_klines_all() -> dict:
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        end_us, price_close = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        out[a] = (end_us.astype("int64"), price_close.astype("float64"))
        if len(end_us):
            print(f"    {a}: {len(end_us)} bars  "
                  f"{pd.Timestamp(int(end_us[0]) - 60_000_000, unit='us', tz='UTC').date()} ->"
                  f"{pd.Timestamp(int(end_us[-1]), unit='us', tz='UTC').date()}")
    return out


def load_universe() -> pd.DataFrame:
    res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
    res = res[res.outcome.isin(("Up", "Down"))].copy()
    res["ws"] = res.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    res["asset"] = res.ticker
    res["tf"] = res.timeframe
    res["window_s"] = res.tf.map({"5m": 300, "15m": 900})
    res["day"] = pd.to_datetime(res.ws, unit="s").dt.floor("D")
    return res[["slug", "asset", "tf", "ws", "window_s", "day", "outcome"]].reset_index(drop=True)


def build_gated_for_variant(uni: pd.DataFrame, klines: dict, vname: str, vcfg: dict) -> pd.DataFrame:
    u = uni.copy()
    u["variant"] = vname
    u["fire_off"] = u.tf.map(vcfg["fire"])
    u["fire_s"] = u.ws + u.fire_off
    u["ret_2m"] = compute_ret_2m(u, klines, vcfg["anchors"])
    u["abs_ret_2m"] = u.ret_2m.abs()
    thr_map = compute_thresholds(u)
    u["threshold"] = u.apply(
        lambda r: thr_map.get((r.asset, r.tf, str(pd.Timestamp(r.day).date())), float("nan")), axis=1
    )
    gated = u[(u.abs_ret_2m.notna()) & (u.threshold.notna()) &
              (u.abs_ret_2m >= u.threshold)].copy()
    gated["signal"] = gated.ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
    return gated


def simulate_fires(gated: pd.DataFrame, books_idx: dict, asset: str, klines: dict,
                    cfg) -> pd.DataFrame:
    """For each gated fire on `asset`, get fill + PnL + RSI@fire.

    Returns per-trade rows with TWO PnL columns:
      - pnl_legacy_usd  : engine_v2 LegacyConfig (2% on profit only) — matches production shadow
      - pnl_real_usd    : real Polymarket fee 0.07*p*(1-p) per share, every leg
    """
    rows = []
    spread = SPREAD_FILTER.get(asset, 0.02)
    for r in gated.itertuples(index=False):
        if r.asset != asset:
            continue
        fire_us = int(r.fire_s) * 1_000_000
        outcome_to_fill = "Up" if r.signal == "UP" else "Down"
        fill = fill_at_book(books_idx, r.slug, outcome=outcome_to_fill,
                              fire_us=fire_us, cfg=cfg, notional_usd=NOTIONAL,
                              spread_filter=spread)
        if fill is None:
            continue
        won = (r.signal == "UP" and r.outcome == "Up") or (r.signal == "DOWN" and r.outcome == "Down")
        # Legacy PnL (production shadow accounting)
        pnl_legacy = hold_pnl(fill, won=won, cfg=cfg)
        # Real PnL: vectorized formula recomputed
        shares = float(fill.get("shares", 0.0))
        vwap = float(fill.get("vwap", float("nan")))
        if shares > 0 and math.isfinite(vwap):
            fee_per_share = REAL_FEE_RATE * vwap * (1.0 - vwap)
            if won:
                pnl_real = shares * (1.0 - vwap) - shares * fee_per_share
            else:
                pnl_real = -shares * vwap - shares * fee_per_share
        else:
            pnl_real = float("nan")
        # F7 RSI anchor = ws_s = ws - window_s (start of prev slot, signal anchor)
        # NOT fire_s -- that catches post-signal mean reversion, not momentum confirmation.
        window_s = 300 if r.tf == "5m" else 900
        ws_s = int(r.ws) - window_s
        rsi = compute_rsi_14_at(klines, r.asset, ws_s)
        rows.append(dict(
            variant=r.variant, slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws),
            ws_s=ws_s, fire_s=int(r.fire_s),
            signal=r.signal, outcome=r.outcome, won=won,
            entry_vwap=vwap, entry_shares=shares,
            entry_usd=fill.get("usd"),
            pnl_legacy_usd=float(pnl_legacy), pnl_real_usd=float(pnl_real),
            ret_2m=float(r.ret_2m), threshold=float(r.threshold),
            rsi_14=float(rsi), rsi_anchor_s=ws_s,
        ))
    return pd.DataFrame(rows)


def main():
    print("[1] load canonical klines...")
    klines = load_klines_all()

    print("[2] load resolutions universe...")
    uni = load_universe()
    print(f"    {len(uni)} resolved markets, {uni.day.min().date()} ->{uni.day.max().date()}")
    print(f"    by (asset,tf): {uni.groupby(['asset','tf']).size().to_dict()}")

    print("[3] compute gated universe per variant...")
    gated_all = []
    for vname, vcfg in VARIANTS.items():
        g = build_gated_for_variant(uni, klines, vname, vcfg)
        gated_all.append(g)
        print(f"    {vname:35} gated={len(g):>5}  by (asset,tf): "
              f"{g.groupby(['asset','tf']).size().to_dict()}")
    gated_uni = pd.concat(gated_all, ignore_index=True)
    gated_uni.to_parquet(OUT / "gated_universe.parquet", index=False)

    print("[4] simulate fires per asset (load L25 once per asset)...")
    # LegacyConfig: matches production shadow accounting (no latency, no min_book_events filter,
    # fee_model=legacy_2pct_on_profit). Real PMXT fee column is computed in parallel inside simulate_fires.
    cfg = LegacyConfig()
    all_rows = []
    for asset in ("BTC", "ETH", "SOL"):
        gated_slugs = set(gated_uni[gated_uni.asset == asset].slug.unique())
        if not gated_slugs:
            print(f"    [{asset}] no gated rows, skipping")
            continue
        print(f"    [{asset}] loading L25 for {len(gated_slugs)} slugs...")
        books_idx = load_orderbook_l25_streaming(asset.lower(), slugs=gated_slugs,
                                                   subsample_1hz=True)
        print(f"    [{asset}] L25 streams loaded: {len(books_idx)}")
        per_variant = []
        for vname in VARIANTS.keys():
            gv = gated_uni[(gated_uni.variant == vname) & (gated_uni.asset == asset)]
            if gv.empty:
                continue
            res = simulate_fires(gv, books_idx, asset, klines, cfg)
            print(f"      {vname:35} fires_with_fill={len(res):>5} / {len(gv)}")
            per_variant.append(res)
        if per_variant:
            all_rows.append(pd.concat(per_variant, ignore_index=True))

    if not all_rows:
        print("NO RESULTS — check L25 loader / gates")
        return
    pt = pd.concat(all_rows, ignore_index=True)
    pt.to_parquet(OUT / "per_trade.parquet", index=False)

    # === F7 + F7x overlay column ===
    pt["f7_keep"] = pt.apply(lambda r: f7_keep(r.signal, r.rsi_14, strict=False), axis=1)
    pt["f7x_keep"] = pt.apply(lambda r: f7_keep(r.signal, r.rsi_14, strict=True), axis=1)

    # === Aggregate per (variant, asset, tf, F7-state) with BOTH pnl columns ===
    print()
    print("[5] aggregating (legacy + real fees side-by-side)...")
    cells = []
    for (variant, asset, tf), g in pt.groupby(["variant", "asset", "tf"]):
        for f7_state, sub in [
            ("ALL", g), ("F7", g[g.f7_keep]), ("F7x", g[g.f7x_keep]),
        ]:
            if sub.empty:
                continue
            cells.append(dict(
                variant=variant, asset=asset, tf=tf, f7_state=f7_state,
                n=len(sub), wr=float(sub.won.mean()),
                tot_legacy=float(sub.pnl_legacy_usd.sum()),
                tot_real=float(sub.pnl_real_usd.sum()),
                per_legacy=float(sub.pnl_legacy_usd.mean()),
                per_real=float(sub.pnl_real_usd.mean()),
                delta_per_trade=float(sub.pnl_real_usd.mean() - sub.pnl_legacy_usd.mean()),
            ))
    cells_df = pd.DataFrame(cells)
    cells_df.to_csv(OUT / "per_variant_cell.csv", index=False)

    # === Variant-level rollup ===
    print()
    print("=== Per-variant rollup (all cells combined) ===")
    rollup = []
    for variant, g in pt.groupby("variant"):
        for f7_state, sub in [("ALL", g), ("F7", g[g.f7_keep]), ("F7x", g[g.f7x_keep])]:
            if sub.empty:
                continue
            rollup.append(dict(
                variant=variant, f7_state=f7_state, n=len(sub),
                wr=float(sub.won.mean()),
                tot_legacy=float(sub.pnl_legacy_usd.sum()),
                tot_real=float(sub.pnl_real_usd.sum()),
                per_legacy=float(sub.pnl_legacy_usd.mean()),
                per_real=float(sub.pnl_real_usd.mean()),
            ))
    rl = pd.DataFrame(rollup)
    rl.to_csv(OUT / "summary.csv", index=False)
    print(f"{'variant':<32} {'F7':>4} {'n':>5} {'WR':>6} {'leg_tot':>9} {'real_tot':>9} {'leg/tr':>8} {'real/tr':>8}")
    for r in rollup:
        print(f"{r['variant']:<32} {r['f7_state']:>4} {r['n']:>5} {r['wr']*100:>5.1f}% "
              f"${r['tot_legacy']:>+8.2f} ${r['tot_real']:>+8.2f} ${r['per_legacy']:>+7.4f} ${r['per_real']:>+7.4f}")

    print()
    print("=== Per-cell breakdown (legacy / real PnL) ===")
    print(f"{'variant':<32} {'cell':<10} {'F7':>4} {'n':>5} {'WR':>6} {'leg_tot':>9} {'real_tot':>9} {'leg/tr':>8} {'real/tr':>8}")
    for r in cells_df.sort_values(["variant", "asset", "tf", "f7_state"]).to_dict("records"):
        cell = f"{r['asset'].lower()}_{r['tf']}"
        print(f"{r['variant']:<32} {cell:<10} {r['f7_state']:>4} {r['n']:>5} "
              f"{r['wr']*100:>5.1f}% ${r['tot_legacy']:>+8.2f} ${r['tot_real']:>+8.2f} "
              f"${r['per_legacy']:>+7.4f} ${r['per_real']:>+7.4f}")
    print()
    print(f"outputs written to {OUT}")


if __name__ == "__main__":
    main()
