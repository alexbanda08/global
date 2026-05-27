"""TASK 7 — Gate overlay of cross-exchange/HL direction on top deploy sleeves.

For each of the 5 deploy candidates (S1-S5):
  - Base 28d metrics
  - For each gate ∈ {coinbase_with, kraken_with, okx_with, hl_with,
    xchg_majority_with, xchg_all_with, hl_recent_liq}:
      - Filter sub-set to fires passing the gate
      - Report n, WR, $/tr, sum_pnl, lift_vs_base

Direction-match gate means: leader's recent direction agrees with the signal
('UP' if signal=UP and leader_ret > 0).
"""
from __future__ import annotations
import sys
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_trades, load_klines, load_okx_klines, load_hyperliquid_liquidations

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"

PT_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"

# Deploy sleeves
SLEEVES = [
    ("S1", "Baseline_v1",                "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive,            "M1V"),
    ("S2", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.mpass_w20_1m_voladaptive,            "M1V"),
    ("S3", "2B_late_fire_early_signal",  "BTC", "15m", lambda d: d.f7  & d.mpass_w20_1m_voladaptive,    "F7+M1V"),
    ("S4", "2C_edge_of_slot",            "BTC", "15m", lambda d: d.f7  & d.mpass_w20_5m_voladaptive,    "F7+M5V"),
    ("S5", "Baseline_v2",                "ETH",  "5m", lambda d: d.f7  & d.mpass_w20_5m_fixed,          "F7+M5F"),
]

WIN_START_US = int(pd.Timestamp("2026-04-30", tz="UTC").value // 1000)
WIN_END_US   = int(pd.Timestamp("2026-05-22", tz="UTC").value // 1000)


def asof_searchsorted(target_us, ref_us, ref_vals):
    pos = np.searchsorted(ref_us, target_us, side="right") - 1
    out = np.full(len(target_us), np.nan)
    valid = pos >= 0
    out[valid] = ref_vals[pos[valid]]
    return out

def binance_1s_arr(asset):
    df = load_klines_1s(asset=asset)
    df = df[(df.time_period_start_us >= WIN_START_US - 60_000_000) &
            (df.time_period_start_us <= WIN_END_US + 60_000_000)].copy()
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 1_000_000).astype("int64"), df.price_close.astype("float64").values

def hl_trades_per_sec(asset):
    df = load_hyperliquid_trades(asset=asset)
    df = df[(df.time_exchange_us >= WIN_START_US - 60_000_000) & (df.time_exchange_us <= WIN_END_US + 60_000_000)]
    cols = df.columns.tolist()
    pcol = "px" if "px" in cols else "price"; qcol = "sz" if "sz" in cols else "size"
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    px = df[pcol].astype("float64").values; sz = df[qcol].astype("float64").values
    g = pd.DataFrame({"ts_s": ts_s, "pq": px*sz, "q": sz}).groupby("ts_s").agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]; g["vwap"] = g.pq / g.q
    return (g.index.values * 1_000_000 + 1_000_000).astype("int64"), g["vwap"].astype("float64").values

def kline_1min_arr(asset, venue):
    if venue == "coinbase":
        df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue == "kraken":
        df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue == "okx":
        df = load_okx_klines(asset=asset, period_id="1MIN")
    df = df[(df.time_period_start_us >= WIN_START_US - 600_000_000) & (df.time_period_start_us <= WIN_END_US + 600_000_000)]
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 60_000_000).astype("int64"), df.price_close.astype("float64").values

def hl_liq_count_arr(asset, lookback_s=60):
    """For each query timestamp, count HL liquidations in [t - lookback_s, t]."""
    df = load_hyperliquid_liquidations(asset=asset)
    return df.time_exchange_us.values.astype("int64")

def add_direction_cols(sub: pd.DataFrame, asset: str) -> pd.DataFrame:
    fire_us = (sub.fire_s.values * 1_000_000).astype("int64")
    bn_end, bn_px = binance_1s_arr(asset)
    hl_end, hl_px = hl_trades_per_sec(asset)
    cb_end, cb_px = kline_1min_arr(asset, "coinbase")
    kr_end, kr_px = kline_1min_arr(asset, "kraken")
    ok_end, ok_px = kline_1min_arr(asset, "okx")
    liq_ts_us = hl_liq_count_arr(asset)

    def ret(ref_end, ref_px, lookback_s):
        p_now = asof_searchsorted(fire_us - 1, ref_end, ref_px)
        p_old = asof_searchsorted(fire_us - lookback_s*1_000_000, ref_end, ref_px)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.log(p_now / p_old)

    sub = sub.copy()
    sub["bn_5s"]  = ret(bn_end, bn_px, 5)
    sub["bn_15s"] = ret(bn_end, bn_px, 15)
    sub["bn_60s"] = ret(bn_end, bn_px, 60)
    sub["hl_5s"]  = ret(hl_end, hl_px, 5)
    sub["hl_15s"] = ret(hl_end, hl_px, 15)
    sub["hl_60s"] = ret(hl_end, hl_px, 60)
    sub["cb_60s"] = ret(cb_end, cb_px, 60)
    sub["cb_120s"] = ret(cb_end, cb_px, 120)
    sub["kr_60s"] = ret(kr_end, kr_px, 60)
    sub["kr_120s"] = ret(kr_end, kr_px, 120)
    sub["ok_60s"] = ret(ok_end, ok_px, 60)
    sub["ok_120s"] = ret(ok_end, ok_px, 120)

    # HL liquidation count in last 60s
    liq_counts = np.zeros(len(fire_us), dtype="int64")
    for i, t in enumerate(fire_us):
        liq_counts[i] = int(((liq_ts_us >= t - 60_000_000) & (liq_ts_us < t)).sum())
    sub["hl_liq_60s"] = liq_counts
    return sub

def signal_sign(s): return 1.0 if s == "UP" else -1.0

def evaluate(name: str, sleeve_id: str, sub: pd.DataFrame, mask: np.ndarray, base_stats: dict) -> dict:
    n = int(mask.sum())
    if n == 0: return {"sleeve": sleeve_id, "gate": name, "n": 0, "wr": None, "mean_pnl": None,
                       "sum_pnl": 0.0, "lift_pnl_vs_base": None, "lift_wr_vs_base": None}
    sub_g = sub.loc[mask]
    n_won = int(sub_g.won.sum())
    wr = n_won / n
    pnl = sub_g.pnl_legacy_usd.values
    return {
        "sleeve": sleeve_id, "gate": name, "n": n,
        "wr": wr, "mean_pnl": float(pnl.mean()), "sum_pnl": float(pnl.sum()),
        "lift_pnl_vs_base": float(pnl.mean() - base_stats["mean_pnl"]),
        "lift_wr_vs_base":  float(wr - base_stats["wr"]),
        "retention_pct": 100*n / base_stats["n"],
    }

def main():
    pt = pd.read_parquet(PT_PATH)
    # Restrict to window
    pt = pt[(pt.fire_s*1_000_000 >= WIN_START_US) & (pt.fire_s*1_000_000 <= WIN_END_US)]
    print(f"per-trade markov: {len(pt):,}")

    all_rows = []
    for sid, variant, asset, tf, fn, lbl in SLEEVES:
        print(f"\n=== {sid} {variant} {asset}_{tf} filter={lbl} ===", flush=True)
        g = pt[(pt.variant == variant) & (pt.asset == asset) & (pt.tf == tf)].copy()
        sub = g[fn(g)].sort_values("fire_s").reset_index(drop=True)
        n = len(sub)
        print(f"  base n={n}")
        if n < 30:
            continue
        sub = add_direction_cols(sub, asset)

        # Base stats
        base_n = len(sub)
        base_won = int(sub.won.sum())
        base_wr = base_won / base_n
        base_pnl = sub.pnl_legacy_usd.values
        base_stats = {"n": base_n, "wr": base_wr, "mean_pnl": float(base_pnl.mean()),
                       "sum_pnl": float(base_pnl.sum())}
        print(f"  base: n={base_n} wr={base_wr:.3f} mean=${base_pnl.mean():.3f} sum=${base_pnl.sum():.1f}")
        all_rows.append({"sleeve": sid, "gate": "BASE", "n": base_n,
                         "wr": base_wr, "mean_pnl": base_pnl.mean(), "sum_pnl": base_pnl.sum(),
                         "lift_pnl_vs_base": 0.0, "lift_wr_vs_base": 0.0, "retention_pct": 100.0})

        sig = sub.signal.map({"UP": 1.0, "DOWN": -1.0}).values

        for lb in [5, 15, 60]:
            # binance recent direction
            r = sub[f"bn_{lb}s"].values
            mask_with = (np.sign(r) == sig) & np.isfinite(r)
            mask_vs   = (np.sign(r) == -sig) & np.isfinite(r)
            all_rows.append(evaluate(f"g_bn_with_{lb}s", sid, sub, mask_with, base_stats))
            all_rows.append(evaluate(f"g_bn_against_{lb}s", sid, sub, mask_vs,  base_stats))
            # HL recent direction
            r = sub[f"hl_{lb}s"].values
            mask_with = (np.sign(r) == sig) & np.isfinite(r)
            mask_vs   = (np.sign(r) == -sig) & np.isfinite(r)
            all_rows.append(evaluate(f"g_hl_with_{lb}s", sid, sub, mask_with, base_stats))
            all_rows.append(evaluate(f"g_hl_against_{lb}s", sid, sub, mask_vs, base_stats))

        for lb in [60, 120]:
            # Coinbase / Kraken / OKX with-sign
            for v in ["cb", "kr", "ok"]:
                r = sub[f"{v}_{lb}s"].values
                mask_with = (np.sign(r) == sig) & np.isfinite(r)
                mask_vs   = (np.sign(r) == -sig) & np.isfinite(r)
                all_rows.append(evaluate(f"g_{v}_with_{lb}s", sid, sub, mask_with, base_stats))
                all_rows.append(evaluate(f"g_{v}_against_{lb}s", sid, sub, mask_vs, base_stats))

            # Xchg majority/all with-sign
            cb = sub[f"cb_{lb}s"].values
            kr = sub[f"kr_{lb}s"].values
            ok = sub[f"ok_{lb}s"].values
            agree_count = ((np.sign(cb) == sig) & np.isfinite(cb)).astype(int) + \
                          ((np.sign(kr) == sig) & np.isfinite(kr)).astype(int) + \
                          ((np.sign(ok) == sig) & np.isfinite(ok)).astype(int)
            all_rows.append(evaluate(f"g_xchg_majority_with_{lb}s", sid, sub, agree_count >= 2, base_stats))
            all_rows.append(evaluate(f"g_xchg_all_with_{lb}s",      sid, sub, agree_count >= 3, base_stats))
            disagree_count = ((np.sign(cb) == -sig) & np.isfinite(cb)).astype(int) + \
                              ((np.sign(kr) == -sig) & np.isfinite(kr)).astype(int) + \
                              ((np.sign(ok) == -sig) & np.isfinite(ok)).astype(int)
            all_rows.append(evaluate(f"g_xchg_majority_against_{lb}s", sid, sub, disagree_count >= 2, base_stats))

        # HL recent liq event (binary, no direction match — just regime gate)
        liq = sub.hl_liq_60s.values
        all_rows.append(evaluate("g_hl_liq_60s_any", sid, sub, liq > 0, base_stats))
        all_rows.append(evaluate("g_hl_liq_60s_high", sid, sub, liq >= 3, base_stats))

    res = pd.DataFrame(all_rows)
    res.to_csv(OUT_DIR / "_gate_overlay.csv", index=False)
    print("\n=== TOP +lift gates per sleeve ===")
    # show top lifts per sleeve
    for sid in res.sleeve.unique():
        if sid not in [s[0] for s in SLEEVES]: continue
        sub_ = res[(res.sleeve == sid) & (res.gate != "BASE") & (res.n >= 25)].copy()
        sub_ = sub_.sort_values("mean_pnl", ascending=False)
        print(f"\n{sid}:")
        print(sub_.head(10).to_string(index=False))
    print(f"\nWrote {OUT_DIR / '_gate_overlay.csv'}")

main()
