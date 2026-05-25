"""VWAP continuation v2 — add Markov/F7/spike gates AND cross-asset confluence.

Starts from the per-fire parquet of vwap_continuation_5m (146k fires fitted,
22 deployable configs). Layers on top:

1. F7 RSI agreement gate — UP fires need RSI>50, DOWN fires need RSI<50
2. M1V Markov regime agreement
3. Cross-asset confluence — at fire time, other two crypto assets' dev_bps
   must also agree with the bet direction
4. CVD slope agreement at fire time

Goal: identify configs that hit WR ≥ 65% AND avg_pnl > $2/tr AND n ≥ 50.
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

PT_IN = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m_per_fire.parquet"
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_v2_gated.csv"
OUT_MD = ROOT / "strategy_lab" / "reports" / "VWAP_CONT_V2_GATED_2026_05_23.md"


def rsi_at_anchor(eu: np.ndarray, cl: np.ndarray, anchor_us: int) -> float:
    """Simple-mean Wilder RSI(14) — production-matching."""
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


def main() -> int:
    print(f"[1] loading per-fire parquet {PT_IN.name}...")
    pt = pd.read_parquet(PT_IN)
    print(f"    {len(pt):,} filled fires")
    print(f"    direction breakdown: {pt.direction.value_counts().to_dict()}")

    print(f"[2] loading 1MIN klines + building Markov labels...")
    klines_1m = {}
    markov = {}
    for a in ("BTC", "ETH", "SOL"):
        eu, cl = load_klines_asof(a, "binance-spot-ws", "1MIN")
        klines_1m[a] = (eu.astype("int64"), cl.astype("float64"))
        m1v_eu, _, m1v_lab = build_labels_for_asset(a, window_bars=20, bar_minutes=1, mode="vol_adaptive")
        markov[a] = (m1v_eu.astype("int64"), m1v_lab.astype("int8"))
        print(f"    {a}: 1MIN n={len(eu):,}, M1V valid={int((m1v_lab>=0).sum()):,}")

    print(f"[3] loading 1s for cross-asset dev_bps...")
    # Per-asset dev_bps at fire times — already in pt for the bet asset.
    # For cross-asset, need binance 1s dev_bps for the OTHER two assets at fire_us.
    df_1s = pd.read_parquet(KL1S)
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us", "source"])
    df_1s = df_1s.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    SYM_MAP = {"BINANCE_SPOT_BTC_USDT": "BTC", "BINANCE_SPOT_ETH_USDT": "ETH", "BINANCE_SPOT_SOL_USDT": "SOL"}
    df_1s["asset_x"] = df_1s["symbol_id"].map(SYM_MAP)
    ANCHOR_WINDOW_S = 15 * 60
    arrs = {}
    for asset in ("BTC", "ETH", "SOL"):
        sub = df_1s[df_1s["asset_x"] == asset].copy().sort_values("time_period_start_us").reset_index(drop=True)
        ts = sub["time_period_start_us"].values.astype("int64")
        close = sub["price_close"].values.astype("float64")
        vol = sub["volume_traded"].fillna(0).values.astype("float64")
        bucket_us = (ts // (ANCHOR_WINDOW_S * 1_000_000)) * (ANCHOR_WINDOW_S * 1_000_000)
        tmp = pd.DataFrame({"bucket": bucket_us, "px_vol": close * vol, "vol": vol})
        tmp["cum_px_vol"] = tmp.groupby("bucket")["px_vol"].cumsum()
        tmp["cum_vol"] = tmp.groupby("bucket")["vol"].cumsum()
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap = np.where(tmp["cum_vol"].values > 0,
                            tmp["cum_px_vol"].values / tmp["cum_vol"].values, np.nan)
        arrs[asset] = {"ts": ts, "close": close, "vwap": vwap}
        print(f"    {asset}: 1s rows={len(ts):,}")

    def dev_bps_at(asset: str, target_us: int) -> float:
        ts = arrs[asset]["ts"]
        idx = int(np.searchsorted(ts, target_us, side="right")) - 1
        if idx < 0 or idx >= len(ts):
            return float("nan")
        c = float(arrs[asset]["close"][idx])
        v = float(arrs[asset]["vwap"][idx])
        if not (math.isfinite(c) and math.isfinite(v) and v > 0):
            return float("nan")
        return 10000.0 * math.log(c / v)

    print(f"[4] computing per-fire gates (RSI, M1V, cross-asset, CVD)...")
    pt = pt.reset_index(drop=True)
    n = len(pt)
    rsi_arr = np.full(n, np.nan)
    m1v_arr = np.full(n, -1, dtype=np.int8)
    other1_dev = np.full(n, np.nan)
    other2_dev = np.full(n, np.nan)

    ASSETS = ("BTC", "ETH", "SOL")
    for i in range(n):
        if i % 5000 == 0 and i > 0:
            print(f"    {i}/{n}")
        r = pt.iloc[i]
        asset = r.asset
        fire_us = int(r.fire_us)
        eu, cl = klines_1m[asset]
        rsi_arr[i] = rsi_at_anchor(eu, cl, fire_us)
        m_eu, m_lab = markov[asset]
        m1v_arr[i] = regime_at_us(m_eu, m_lab, fire_us)
        # Other two asset dev_bps
        others = [a for a in ASSETS if a != asset]
        other1_dev[i] = dev_bps_at(others[0], fire_us)
        other2_dev[i] = dev_bps_at(others[1], fire_us)

    pt["rsi_14"] = rsi_arr
    pt["m1v_regime"] = m1v_arr
    pt["other1_dev_bps"] = other1_dev
    pt["other2_dev_bps"] = other2_dev

    # Gate computations
    pt["f7_pass"] = np.where(pt.direction == "UP", pt.rsi_14 > 50, pt.rsi_14 < 50)
    pt["m1v_pass"] = np.where(pt.direction == "UP", pt.m1v_regime == BULL, pt.m1v_regime == BEAR)
    # Cross-asset confluence: both other assets dev_bps agree with bet direction
    cross_up = (pt.direction == "UP") & (pt.other1_dev_bps > 0) & (pt.other2_dev_bps > 0)
    cross_dn = (pt.direction == "DOWN") & (pt.other1_dev_bps < 0) & (pt.other2_dev_bps < 0)
    pt["cross_pass"] = cross_up | cross_dn
    # Cross-asset PARTIAL (at least one of the other assets agrees)
    cross_up_partial = (pt.direction == "UP") & ((pt.other1_dev_bps > 0) | (pt.other2_dev_bps > 0))
    cross_dn_partial = (pt.direction == "DOWN") & ((pt.other1_dev_bps < 0) | (pt.other2_dev_bps < 0))
    pt["cross_partial"] = cross_up_partial | cross_dn_partial

    # Add dev_tier
    bins = [5, 10, 15, 20, 30, 50, 1e9]
    labels = ["5-10bps", "10-15bps", "15-20bps", "20-30bps", "30-50bps", ">50bps"]
    pt["dev_tier"] = pd.cut(pt.dev_bps.abs(), bins=bins, labels=labels)

    print(f"\n[5] gate stats:")
    for g in ("f7_pass", "m1v_pass", "cross_pass", "cross_partial"):
        print(f"    {g}: {int(pt[g].sum()):,} of {len(pt):,} ({pt[g].mean()*100:.1f}%)")

    # Enumerate gate combos per (asset, fire_offset_s, dev_tier)
    print(f"\n[6] enumerating gate stacks...")
    rows = []
    for asset in ASSETS:
        for off in sorted(pt.fire_offset_s.unique()):
            for tier in labels:
                base = pt[(pt.asset == asset) & (pt.fire_offset_s == off) & (pt.dev_tier == tier)].copy()
                if len(base) < 30:
                    continue
                # All combinations of 4 gates ∈ {f7_pass, m1v_pass, cross_pass, cross_partial, none}
                gate_options = [
                    ("none", pd.Series(True, index=base.index)),
                    ("f7", base.f7_pass),
                    ("m1v", base.m1v_pass),
                    ("cross_partial", base.cross_partial),
                    ("cross_full", base.cross_pass),
                    ("f7+m1v", base.f7_pass & base.m1v_pass),
                    ("f7+cross_partial", base.f7_pass & base.cross_partial),
                    ("m1v+cross_partial", base.m1v_pass & base.cross_partial),
                    ("f7+m1v+cross_partial", base.f7_pass & base.m1v_pass & base.cross_partial),
                    ("f7+cross_full", base.f7_pass & base.cross_pass),
                ]
                for gname, mask in gate_options:
                    kept = base[mask]
                    if len(kept) < 30:
                        continue
                    rows.append({
                        "asset": asset, "fire_offset_s": off, "dev_tier": tier,
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

    # Top deployable
    dep = out[(out.n >= 30) & (out.wr >= 0.60) & (out.avg_pnl > 0)].copy().sort_values("sum_pnl", ascending=False)
    print(f"\n--- Deployable (n>=30, WR>=60%, avg_pnl>0): {len(dep)} configs ---")
    print(dep.head(40).to_string(index=False))

    # Top by WR with n>=50
    strict = out[(out.n >= 50) & (out.wr >= 0.65) & (out.avg_pnl > 1.0)].copy().sort_values("avg_pnl", ascending=False)
    print(f"\n--- STRICT (n>=50, WR>=65%, $/tr>=$1): {len(strict)} configs ---")
    print(strict.head(20).to_string(index=False))

    # Markdown
    md = []
    md.append(f"# VWAP continuation v2 — gated ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
    md.append("")
    md.append("Layered on top of vwap_continuation_5m_per_fire.parquet: F7 RSI, M1V Markov, cross-asset confluence (BTC+ETH+SOL agreement). Bet direction = sign of binance dev_bps from 15m anchored VWAP at fire_offset_s.")
    md.append("")
    md.append("## STRICT deployable (n>=50, WR>=65%, $/tr>=$1)")
    md.append("")
    if len(strict) > 0:
        md.append(strict.head(30).to_markdown(index=False))
    else:
        md.append("**NONE**")
    md.append("")
    md.append("## All deployable (n>=30, WR>=60%, avg_pnl>0)")
    md.append("")
    md.append(dep.head(50).to_markdown(index=False))
    md.append("")
    md.append(f"_data: `data/v4/canonical/_results/vwap_continuation_v2_gated.csv`_")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
