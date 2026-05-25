"""Slot-anchored VWAP continuation v2 — add Markov/F7/cross-asset gates.

Same architecture as `vwap_continuation_v2_gated.py` (which layers gates on
the 15m-anchored fires) but using the SLOT-ANCHORED dev_bps. The slot-
anchored variant has 50+ deployable configs already; we expect gates to
push WR even higher.

Outputs:
  data/v4/canonical/_results/vwap_slot_v2_gated.csv
  strategy_lab/reports/VWAP_SLOT_V2_GATED_2026_05_23.md
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))

from load import load_klines_asof  # noqa: E402
from markov_regime_micro import build_labels_for_asset, regime_at_us, BEAR, BULL  # noqa: E402

PT_IN = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_slot_anchored_5m_per_fire.parquet"
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_slot_v2_gated.csv"
OUT_MD = ROOT / "strategy_lab" / "reports" / "VWAP_SLOT_V2_GATED_2026_05_23.md"


def rsi_at_anchor(eu: np.ndarray, cl: np.ndarray, anchor_us: int) -> float:
    closes = []
    for off_s in range(-840, 1, 60):
        idx = int(np.searchsorted(eu, anchor_us + off_s * 1_000_000, side="right")) - 1
        if idx < 0 or idx >= len(cl):
            closes.append(float("nan"))
            continue
        closes.append(float(cl[idx]))
    if any(not math.isfinite(c) or c <= 0 for c in closes) or len(closes) < 15:
        return float("nan")
    arr = np.asarray(closes, dtype=np.float64)
    log_rets = np.log(arr[1:] / arr[:-1])
    gains = np.where(log_rets > 0, log_rets, 0.0).mean()
    losses = np.where(log_rets < 0, -log_rets, 0.0).mean()
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    if gains == 0:
        return 0.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def main():
    print(f"[1] loading {PT_IN.name}...")
    pt = pd.read_parquet(PT_IN)
    print(f"    {len(pt):,} filled slot-anchored fires")

    print("[2] loading 1MIN klines + Markov labels...")
    klines_1m = {}
    markov = {}
    for a in ("BTC", "ETH", "SOL"):
        eu, cl = load_klines_asof(a, "binance-spot-ws", "1MIN")
        klines_1m[a] = (eu.astype("int64"), cl.astype("float64"))
        m_eu, _, m_lab = build_labels_for_asset(a, window_bars=20, bar_minutes=1, mode="vol_adaptive")
        markov[a] = (m_eu.astype("int64"), m_lab.astype("int8"))
        print(f"    {a}: 1MIN n={len(eu):,}, M1V valid={int((m_lab>=0).sum()):,}")

    print("[3] loading 1s for cross-asset slot-dev_bps...")
    df_1s = pd.read_parquet(KL1S)
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us", "source"])
    df_1s = df_1s.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    SYM_MAP = {"BINANCE_SPOT_BTC_USDT": "BTC", "BINANCE_SPOT_ETH_USDT": "ETH", "BINANCE_SPOT_SOL_USDT": "SOL"}
    df_1s["asset_x"] = df_1s["symbol_id"].map(SYM_MAP)
    arrs = {}
    for asset in ("BTC", "ETH", "SOL"):
        sub = df_1s[df_1s["asset_x"] == asset].copy().sort_values("time_period_start_us").reset_index(drop=True)
        arrs[asset] = {
            "ts": sub["time_period_start_us"].values.astype("int64"),
            "close": sub["price_close"].values.astype("float64"),
            "vol": sub["volume_traded"].fillna(0).values.astype("float64"),
        }
        print(f"    {asset}: 1s rows={len(arrs[asset]['ts']):,}")

    def slot_dev_bps_at(asset: str, slot_start_us: int, target_us: int) -> float:
        a = arrs[asset]
        ts = a["ts"]; cl = a["close"]; vol = a["vol"]
        lo = int(np.searchsorted(ts, slot_start_us, side="left"))
        hi = int(np.searchsorted(ts, target_us, side="right"))
        if hi <= lo:
            return float("nan")
        cum_pv = float((cl[lo:hi] * vol[lo:hi]).sum())
        cum_v = float(vol[lo:hi].sum())
        if cum_v <= 0:
            return float("nan")
        vwap = cum_pv / cum_v
        fi = hi - 1
        if fi < 0:
            return float("nan")
        c_now = float(cl[fi])
        if vwap <= 0 or c_now <= 0:
            return float("nan")
        return 10000.0 * math.log(c_now / vwap)

    print("[4] computing gates per fire (RSI, M1V, cross-asset)...")
    pt = pt.reset_index(drop=True)
    n = len(pt)
    rsi_arr = np.full(n, np.nan)
    m1v_arr = np.full(n, -1, dtype=np.int8)
    other1_dev = np.full(n, np.nan)
    other2_dev = np.full(n, np.nan)
    ASSETS = ("BTC", "ETH", "SOL")
    pt["slot_start_us"] = (pt.fire_s - pt.fire_offset_s).astype("int64") * 1_000_000
    for i in range(n):
        if i % 5000 == 0 and i > 0:
            print(f"    {i}/{n}")
        r = pt.iloc[i]
        asset = r.asset; fire_us = int(r.fire_us); slot_start_us = int(r.slot_start_us)
        eu, cl = klines_1m[asset]
        rsi_arr[i] = rsi_at_anchor(eu, cl, fire_us)
        m_eu, m_lab = markov[asset]
        m1v_arr[i] = regime_at_us(m_eu, m_lab, fire_us)
        others = [a for a in ASSETS if a != asset]
        other1_dev[i] = slot_dev_bps_at(others[0], slot_start_us, fire_us)
        other2_dev[i] = slot_dev_bps_at(others[1], slot_start_us, fire_us)
    pt["rsi_14"] = rsi_arr
    pt["m1v_regime"] = m1v_arr
    pt["other1_dev_bps"] = other1_dev
    pt["other2_dev_bps"] = other2_dev

    pt["f7_pass"] = np.where(pt.direction == "UP", pt.rsi_14 > 50, pt.rsi_14 < 50)
    pt["m1v_pass"] = np.where(pt.direction == "UP", pt.m1v_regime == BULL, pt.m1v_regime == BEAR)
    cross_full_up = (pt.direction == "UP") & (pt.other1_dev_bps > 0) & (pt.other2_dev_bps > 0)
    cross_full_dn = (pt.direction == "DOWN") & (pt.other1_dev_bps < 0) & (pt.other2_dev_bps < 0)
    pt["cross_full"] = cross_full_up | cross_full_dn
    cross_par_up = (pt.direction == "UP") & ((pt.other1_dev_bps > 0) | (pt.other2_dev_bps > 0))
    cross_par_dn = (pt.direction == "DOWN") & ((pt.other1_dev_bps < 0) | (pt.other2_dev_bps < 0))
    pt["cross_partial"] = cross_par_up | cross_par_dn

    print(f"\n[5] gate stats:")
    for g in ("f7_pass", "m1v_pass", "cross_full", "cross_partial"):
        print(f"    {g}: {int(pt[g].sum()):,} / {n:,} ({pt[g].mean()*100:.1f}%)")

    bins = [3, 5, 10, 15, 20, 30, 50, 1e9]
    labels = ["3-5bps", "5-10bps", "10-15bps", "15-20bps", "20-30bps", "30-50bps", ">50bps"]
    pt["dev_tier"] = pd.cut(pt.dev_bps_vwap.abs(), bins=bins, labels=labels)

    print(f"\n[6] enumerating gate stacks...")
    rows = []
    GATE_OPTIONS = [
        ("none", lambda d: pd.Series(True, index=d.index)),
        ("f7", lambda d: d.f7_pass),
        ("m1v", lambda d: d.m1v_pass),
        ("cross_partial", lambda d: d.cross_partial),
        ("cross_full", lambda d: d.cross_full),
        ("f7+m1v", lambda d: d.f7_pass & d.m1v_pass),
        ("f7+cross_partial", lambda d: d.f7_pass & d.cross_partial),
        ("m1v+cross_partial", lambda d: d.m1v_pass & d.cross_partial),
        ("f7+m1v+cross_partial", lambda d: d.f7_pass & d.m1v_pass & d.cross_partial),
        ("f7+cross_full", lambda d: d.f7_pass & d.cross_full),
        ("m1v+cross_full", lambda d: d.m1v_pass & d.cross_full),
    ]
    for asset in ASSETS:
        for off in sorted(pt.fire_offset_s.unique()):
            for tier in labels:
                base = pt[(pt.asset == asset) & (pt.fire_offset_s == off) & (pt.dev_tier == tier)].copy()
                if len(base) < 30:
                    continue
                for gname, gfn in GATE_OPTIONS:
                    mask = gfn(base)
                    kept = base[mask]
                    if len(kept) < 30:
                        continue
                    rows.append({
                        "asset": asset, "fire_offset_s": int(off), "dev_tier": tier,
                        "gate": gname, "n": len(kept),
                        "wr": float(kept.won.mean()),
                        "avg_pnl": float(kept.pnl_legacy_usd.mean()),
                        "sum_pnl": float(kept.pnl_legacy_usd.sum()),
                        "avg_entry": float(kept.entry_vwap.mean()),
                    })
    out = pd.DataFrame(rows).round(3)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"    wrote {OUT_CSV}")

    dep = out[(out.n >= 30) & (out.wr >= 0.65) & (out.avg_pnl > 1.0)].copy().sort_values("sum_pnl", ascending=False)
    print(f"\n--- STRICT DEPLOY (n>=30, WR>=65%, $/tr>=$1): {len(dep)} configs ---")
    print(dep.head(40).to_string(index=False))

    ultra = out[(out.n >= 100) & (out.wr >= 0.75) & (out.avg_pnl >= 1.0)].copy().sort_values("sum_pnl", ascending=False)
    print(f"\n--- ULTRA (n>=100, WR>=75%, $/tr>=$1): {len(ultra)} configs ---")
    print(ultra.head(20).to_string(index=False))

    md = []
    md.append(f"# Slot-anchored VWAP v2 gated ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
    md.append("")
    md.append("Layered F7/M1V/cross-asset gates on top of slot-anchored VWAP fires.")
    md.append("")
    md.append("## ULTRA (n>=100, WR>=75%, $/tr>=$1)")
    md.append("")
    if len(ultra) > 0:
        md.append(ultra.head(30).to_markdown(index=False))
    else:
        md.append("NONE")
    md.append("")
    md.append("## STRICT (n>=30, WR>=65%, $/tr>=$1) — top 50")
    md.append("")
    md.append(dep.head(50).to_markdown(index=False))
    md.append("")
    md.append(f"_data: `data/v4/canonical/_results/vwap_slot_v2_gated.csv`_")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
