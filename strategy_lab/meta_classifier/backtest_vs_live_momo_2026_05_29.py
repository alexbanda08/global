"""Backtest vs live — momo HOLD_f7 + INV_NIGHT sleeves over the shadow window.

Window: 2026-05-27 00:00 UTC -> 2026-05-29 13:10 UTC (bounded by canonical
resolutions/klines coverage; L25 BTC to ~10:01, ETH/SOL to ~13:13).

Sleeves backtested with EXISTING production-verified harness logic:

  A) momo HOLD_f7 — MomoStrategy (v1) + MomoV2Strategy (v2), F7-basic gate.
     - v1 ret_2m = log(close@(ws_s+120) / close@ws_s),  fire @ ws_s+120
     - v2 ret_2m = log(close@(ws_s+60)  / close@(ws_s-60)), fire @ ws_s+60
     - ws_s = slot_start - window_s  (slug suffix - window_s)
     - Gate: |ret_2m| >= feed-backed q90 (rolling 14d, prod-style)
     - F7 basic: UP needs RSI(14)>50, DOWN needs RSI<50, anchored @ ws_s
     - Fill: L25 book-walk $25 @ fire_us, hold to settlement, legacy 2%-on-profit fee
     - HOLD policy = hold to settlement (no early sell) -> hold_pnl
     6 cells x 2 versions = 12 sleeves, of which 8 have live n>=14.

  B) INV_NIGHT trio — Updown5mStrategy(mode="volume") + inverse_volume_night flip.
     - ws_s = slot_start - window_s  (PREVIOUS slot start; verified 100% vs live)
     - ret_5m = log(close@ws_s / close@(ws_s-300))  (NOT the source-comment
       anchor of log(c@slot_start/c@slot_start-300) — empirically the live
       controller's `window_start_us` == ws_s, giving 100% direction match)
     - volume mode fires sign(ret_5m), every signal (no threshold)
     - inverse_volume_night: flip direction iff ws_s UTC hour in {1,2,3,4,5,9,10}
       else silent (no fire). Night anchor is ws_s (100% vs live; slot_start = 97.7%).
     - Fill @ slot_start (market open / bar_close), hold to settlement, legacy fee
     - 6 cells: poly_updown_{btc,eth,sol}_{5m,15m}_volume_INV_NIGHT
       (live has all 6 with n 74-232)

NOT backtested here (NO_BACKTEST_INFRA — require 1s-trade-derived features
fair_edge_bp / cvd_30s/60s / macd_hist / vwap_dev_bps that are NOT in the
canonical dataset for this window):
  - shadow_poly_updown_ALL_5m_phase1_kelly  (VwapKellyEnsembleStrategy)
  - shadow_poly_updown_ALL_5m_S3_prewindow  (PrewindowS3Strategy)
  - shadow_poly_updown_ALL_15m_S4_prewindow (PrewindowS4Strategy)
  - all poly_sniper_v5_* (sniper search v6-v9 features) and fade sleeves

Outputs: data/v4/canonical/_results/backtest_vs_live_momo_2026_05_29/
  per_trade.parquet, sleeve_table.csv  (printed table -> report)
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
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "backtest_vs_live_momo_2026_05_29"
OUT.mkdir(parents=True, exist_ok=True)

NOTIONAL = 25.0
GATE_Q = 0.90
LOOKBACK_DAYS = 14
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
SLUG_BATCH = 120

# Shadow window (UTC). Live first_fire ~2026-05-27 00:00, last ~05-29 13:10
# for the INV_NIGHT/13:00-bounded sleeves; momo sleeves run to ~19:00 live but
# canonical klines/resolutions cap at ~13:10-13:16 on 05-29.
WIN_LO_S = int(pd.Timestamp("2026-05-27 00:00:00", tz="UTC").timestamp())
WIN_HI_S = int(pd.Timestamp("2026-05-29 13:10:00", tz="UTC").timestamp())

NIGHT_HOURS_UTC = frozenset({1, 2, 3, 4, 5, 9, 10})


# ---------------------------------------------------------------------------
# Klines
# ---------------------------------------------------------------------------

def load_klines_all() -> dict:
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        eu, cl = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        out[a] = (eu.astype("int64"), cl.astype("float64"))
        print(f"    {a}: {len(eu)} 1MIN bars, last={pd.Timestamp(int(eu[-1]), unit='us', tz='UTC')}")
    return out


def asof_close(k, ts_s: int) -> float:
    eu, cl = k
    target = int(ts_s) * 1_000_000
    i = int(np.searchsorted(eu, target, side="right")) - 1
    return float("nan") if i < 0 else float(cl[i])


def ret_log(k, t0_s: int, t1_s: int) -> float:
    c0 = asof_close(k, t0_s)
    c1 = asof_close(k, t1_s)
    if not (math.isfinite(c0) and math.isfinite(c1)) or c0 <= 0 or c1 <= 0:
        return float("nan")
    return math.log(c1 / c0)


def rsi14_at(k, anchor_s: int) -> float:
    """Simple-mean Wilder RSI(14) over 15 1MIN closes ending @ anchor_s (= ws_s)."""
    eu, cl = k
    if len(eu) < 16:
        return float("nan")
    target = int(anchor_s) * 1_000_000
    i = int(np.searchsorted(eu, target, side="right")) - 1
    if i < 14 or i >= len(cl):
        return float("nan")
    if abs(int(eu[i]) - target) > 5 * 60 * 1_000_000:
        return float("nan")
    closes = cl[i - 14:i + 1]
    diffs = np.diff(closes)
    gain = np.where(diffs > 0, diffs, 0.0).mean()
    loss = np.where(diffs < 0, -diffs, 0.0).mean()
    if loss <= 0:
        return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return float(100.0 - 100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# Feed-backed q90 (production-style): rolling 14d q90 of |ret_2m| over ALL 1m bars.
# Built per (asset, anchor) using the v1 anchor convention ret_2m=log(c@t/c@t-120).
# For v2 the anchor is (t-60,t+60) but its magnitude distribution is ~identical;
# we use a single per-asset feed-backed threshold function.
# ---------------------------------------------------------------------------

def build_feedbacked_absret(k) -> tuple[np.ndarray, np.ndarray]:
    eu, cl = k
    ts_us = eu - 60_000_000  # bar START us (load_klines_asof gives END us)
    log_c = np.log(np.where(cl > 0, cl, np.nan))
    ar = np.full_like(log_c, np.nan)
    ar[2:] = np.abs(log_c[2:] - log_c[:-2])
    if len(ts_us) > 2:
        dt = ts_us[2:] - ts_us[:-2]
        ar[2:][dt != 120 * 1_000_000] = np.nan
    return ts_us, ar


def q90_asof(ts_us: np.ndarray, ar: np.ndarray, target_s: int) -> float:
    win = LOOKBACK_DAYS * 24 * 3600 * 1_000_000
    a = int(target_s) * 1_000_000
    valid = np.isfinite(ar)
    vs = ts_us[valid]
    vv = ar[valid]
    lo = int(np.searchsorted(vs, a - win, side="left"))
    hi = int(np.searchsorted(vs, a, side="right"))
    if hi - lo < 100:
        return float("nan")
    return float(np.quantile(vv[lo:hi], GATE_Q))


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

def load_universe() -> pd.DataFrame:
    res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
    res = res[res.outcome.isin(("Up", "Down"))].copy()
    res["slot_start"] = res.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    res["asset"] = res.ticker
    res["tf"] = res.timeframe
    res["window_s"] = res.tf.map({"5m": 300, "15m": 900})
    res["ws_s"] = res.slot_start - res.window_s   # momo signal anchor
    # window filter on slot_start (the market opening time)
    res = res[(res.slot_start >= WIN_LO_S) & (res.slot_start <= WIN_HI_S)]
    return res[["slug", "asset", "tf", "slot_start", "window_s", "ws_s", "outcome"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Build gated fires per sleeve family
# ---------------------------------------------------------------------------

def build_momo_fires(uni: pd.DataFrame, klines: dict, feed: dict, version: str) -> pd.DataFrame:
    """version in {'v1','v2'}. Returns gated fires with F7-basic gate applied."""
    rows = []
    for r in uni.itertuples(index=False):
        k = klines[r.asset]
        ws_s = int(r.ws_s)
        if version == "v1":
            ret = ret_log(k, ws_s, ws_s + 120)
            fire_s = ws_s + 120
        else:  # v2
            ret = ret_log(k, ws_s - 60, ws_s + 60)
            fire_s = ws_s + 60
        if not math.isfinite(ret):
            continue
        thr = q90_asof(feed[r.asset][0], feed[r.asset][1], ws_s)
        if not math.isfinite(thr) or abs(ret) < thr:
            continue
        signal = "UP" if ret > 0 else ("DOWN" if ret < 0 else None)
        if signal is None:
            continue
        rsi = rsi14_at(k, ws_s)
        # F7 basic gate
        if not math.isfinite(rsi):
            continue
        if signal == "UP" and rsi <= 50:
            continue
        if signal == "DOWN" and rsi >= 50:
            continue
        rows.append(dict(
            slug=r.slug, asset=r.asset, tf=r.tf, slot_start=int(r.slot_start),
            ws_s=ws_s, fire_s=int(fire_s), signal=signal, outcome=r.outcome,
            ret_2m=float(ret), threshold=float(thr), rsi_14=float(rsi),
            version=version,
        ))
    return pd.DataFrame(rows)


def build_invnight_fires(uni: pd.DataFrame, klines: dict) -> pd.DataFrame:
    """Volume base (sign of ret_5m) + night-hour flip.

    Anchor: ws_s = slot_start - window_s (verified 100% vs live).
    ret_5m = log(close@ws_s / close@(ws_s-300)); night check on ws_s hour.
    Fill @ slot_start (market open).
    """
    rows = []
    for r in uni.itertuples(index=False):
        k = klines[r.asset]
        ws_s = int(r.ws_s)  # = slot_start - window_s
        ret5 = ret_log(k, ws_s - 300, ws_s)
        if not math.isfinite(ret5) or ret5 == 0:
            continue
        base_signal = "UP" if ret5 > 0 else "DOWN"
        hour = pd.Timestamp(ws_s, unit="s", tz="UTC").hour
        if hour not in NIGHT_HOURS_UTC:
            continue  # silent outside night window
        signal = "DOWN" if base_signal == "UP" else "UP"  # flip
        rows.append(dict(
            slug=r.slug, asset=r.asset, tf=r.tf, slot_start=int(r.slot_start),
            ws_s=ws_s, fire_s=int(r.slot_start), signal=signal,
            base_signal=base_signal, outcome=r.outcome,
            ret_5m=float(ret5), hour=int(hour),
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Simulate fills (batched L25)
# ---------------------------------------------------------------------------

def simulate(fires: pd.DataFrame, cfg) -> pd.DataFrame:
    if fires.empty:
        return fires
    out_rows = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = fires[fires.asset == asset]
        if sub.empty:
            continue
        slugs = sorted(sub.slug.unique())
        spread = SPREAD_FILTER.get(asset, 0.02)
        n_batches = (len(slugs) + SLUG_BATCH - 1) // SLUG_BATCH
        import gc
        for bi in range(n_batches):
            batch = set(slugs[bi * SLUG_BATCH:(bi + 1) * SLUG_BATCH])
            print(f"      [{asset}] L25 batch {bi+1}/{n_batches} ({len(batch)} slugs)", flush=True)
            books = load_orderbook_l25_streaming(asset.lower(), slugs=batch, subsample_1hz=False)
            bsub = sub[sub.slug.isin(batch)]
            for r in bsub.itertuples(index=False):
                fill_oc = "Up" if r.signal == "UP" else "Down"
                fire_us = int(r.fire_s) * 1_000_000
                fill = fill_at_book(books, r.slug, outcome=fill_oc, fire_us=fire_us,
                                    cfg=cfg, notional_usd=NOTIONAL, spread_filter=spread)
                if fill is None:
                    continue
                won = ((r.signal == "UP" and r.outcome == "Up") or
                       (r.signal == "DOWN" and r.outcome == "Down"))
                pnl = hold_pnl(fill, won=won, cfg=cfg)
                d = r._asdict()
                d.update(dict(entry_vwap=float(fill.get("vwap", float("nan"))),
                              entry_shares=float(fill.get("shares", 0.0)),
                              entry_usd=float(fill.get("usd", 0.0)),
                              won=bool(won), pnl_legacy_usd=float(pnl)))
                out_rows.append(d)
            del books
            gc.collect()
    return pd.DataFrame(out_rows)


# ---------------------------------------------------------------------------

def main():
    print("[1] load klines + feed-backed |ret_2m|...")
    klines = load_klines_all()
    feed = {a: build_feedbacked_absret(klines[a]) for a in ("BTC", "ETH", "SOL")}

    print("[2] load universe (shadow window)...")
    uni = load_universe()
    print(f"    {len(uni)} resolved markets in window 05-27 -> 05-29 13:10")
    print(f"    by (asset,tf): {uni.groupby(['asset','tf']).size().to_dict()}")

    cfg = LegacyConfig()

    print("[3] build momo HOLD_f7 fires (v1 + v2)...")
    f_v1 = build_momo_fires(uni, klines, feed, "v1")
    f_v2 = build_momo_fires(uni, klines, feed, "v2")
    print(f"    v1 gated+F7 fires: {len(f_v1)}   v2: {len(f_v2)}")

    print("[4] build INV_NIGHT fires...")
    f_inv = build_invnight_fires(uni, klines)
    print(f"    INV_NIGHT fires (night-hour, flipped): {len(f_inv)}")
    if not f_inv.empty:
        print(f"      by (asset,tf): {f_inv.groupby(['asset','tf']).size().to_dict()}")

    print("[5] simulate L25 fills...")
    print("    [momo v1]")
    sv1 = simulate(f_v1, cfg)
    print("    [momo v2]")
    sv2 = simulate(f_v2, cfg)
    print("    [INV_NIGHT]")
    sinv = simulate(f_inv, cfg)

    # Tag sleeve ids
    if not sv1.empty:
        sv1["sleeve_id"] = sv1.apply(
            lambda r: f"poly_updown_{r.asset.lower()}_{r.tf}_momo_HOLD_f7", axis=1)
    if not sv2.empty:
        sv2["sleeve_id"] = sv2.apply(
            lambda r: f"poly_updown_{r.asset.lower()}_{r.tf}_momo_v2_HOLD_f7", axis=1)
    if not sinv.empty:
        sinv["sleeve_id"] = sinv.apply(
            lambda r: f"poly_updown_{r.asset.lower()}_{r.tf}_volume_INV_NIGHT", axis=1)

    allpt = pd.concat([d for d in (sv1, sv2, sinv) if not d.empty], ignore_index=True)
    allpt.to_parquet(OUT / "per_trade.parquet", index=False)

    # Aggregate per sleeve
    rows = []
    for sid, g in allpt.groupby("sleeve_id"):
        n = len(g)
        rows.append(dict(
            sleeve_id=sid, n_bt=n, bt_wr=float(g.won.mean() * 100),
            bt_pnl=float(g.pnl_legacy_usd.sum()),
            bt_per_tr=float(g.pnl_legacy_usd.mean()),
            bt_vwap=float(g.entry_vwap.mean()),
        ))
    tbl = pd.DataFrame(rows).sort_values("n_bt", ascending=False)
    tbl.to_csv(OUT / "sleeve_table.csv", index=False)

    print("\n" + "=" * 90)
    print("BACKTEST PER-SLEEVE (shadow window, legacy 2%-on-profit, L25 10Hz, F7-basic)")
    print("=" * 90)
    print(f"{'sleeve_id':<46} {'n':>4} {'WR%':>6} {'$/tr':>8} {'sum$':>9} {'vwap':>6}")
    for r in tbl.to_dict("records"):
        print(f"{r['sleeve_id']:<46} {r['n_bt']:>4} {r['bt_wr']:>6.2f} "
              f"{r['bt_per_tr']:>+8.3f} {r['bt_pnl']:>+9.2f} {r['bt_vwap']:>6.3f}")
    print(f"\noutputs -> {OUT}")


if __name__ == "__main__":
    main()
