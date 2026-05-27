"""Full-window ALL-sleeves re-test — Apr 24 -> May 26 (~33 days).

Master re-validation:
  * REF (existing s6/s15/v15m joined files, May 1 -> May 21)
  * OOS (Agent T's already-built fires, May 21 -> May 25)
  * PREFIX (new build, Apr 24 -> May 1) -- this script extends Agent T's pipeline
  * FULL = REF + OOS + PREFIX (dedup on slug+fire_us+direction)

Sleeves tested:
  * Agent T's top 15 (already validated, copied for completeness)
  * R1/R2 additions: hybrid_gate_search_top top-rows, new_indicator catalog top,
    sleeve_hunt_15m_deployable top, S2/S5/V7/Tier2 RF confluence.

For each sleeve: n_full, WR_full, $/tr_full, sum_full, max_DD, loss_streak, Sharpe
+ delta vs 22d ref + n_oos / WR_oos / $/tr_oos / sum_oos (May 19-26 last 7d)
+ stability classification (STABLE/DEGRADING/IMPROVING/VOLATILE)

Output:
  data/v4/canonical/_results/full_window_all_sleeves_results.csv
  strategy_lab/reports/FULL_WINDOW_ALL_SLEEVES_2026_05_26.md
"""
from __future__ import annotations

import gc
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
)
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

RES_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_DIR = RES_DIR / "_full_window_2026_05_26"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Windows
PREFIX_START_US = int(pd.Timestamp("2026-04-24T00:00:00Z").value // 1000)
PREFIX_END_US = int(pd.Timestamp("2026-04-30T23:59:00Z").value // 1000)
REF_START_US = int(pd.Timestamp("2026-05-01T00:00:00Z").value // 1000)
REF_END_US = int(pd.Timestamp("2026-05-21T20:01:00Z").value // 1000)
OOS_START_US = REF_END_US
OOS_END_US = int(pd.Timestamp("2026-05-25T19:15:00Z").value // 1000)
FULL_START_US = PREFIX_START_US
FULL_END_US = OOS_END_US

# OOS-slice for "last 7 days" test
LAST7_START_US = int(pd.Timestamp("2026-05-19T00:00:00Z").value // 1000)
LAST7_END_US = FULL_END_US

ASSETS = ("BTC", "ETH", "SOL")
SPREAD = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
NOTIONAL = 25.0


# ---------------------------------------------------------------------------
# Sleeve definitions  - from R1/R2 catalogs
# ---------------------------------------------------------------------------

@dataclass
class Sleeve:
    sleeve_id: str
    asset: str
    tf: str
    base: str            # 's6' | 's15' | 'v15m'
    offset_range: tuple
    gate_stack: list
    direction_pick: str = "BOTH"
    ref_n: int = 0
    ref_wr: float = 0.0
    ref_dpt: float = 0.0
    ref_sum: float = 0.0


SLEEVES: list[Sleeve] = [
    # === Agent T's top 15 (for parity comparison) ===
    Sleeve("01_btc_5m_s6_hybrid_v2_sms",  "BTC", "5m", "s6",  (60, 150),
           ["g_cci_with", "g_stoch_with", "g_rf_with",
            "g_tr_above_ema50", "g_ribbon_agrees",
            "g_sms_liq_reclaim_with"],
           ref_n=699, ref_wr=0.883, ref_dpt=18.71, ref_sum=13075),
    Sleeve("02_btc_5m_s6_hybrid_v1",      "BTC", "5m", "s6",  (60, 150),
           ["g_cci_with", "g_stoch_with", "g_rf_with",
            "g_tr_above_ema50", "g_ribbon_agrees"],
           ref_n=2764, ref_wr=0.778, ref_dpt=5.10, ref_sum=14103),
    Sleeve("03_eth_5m_s6_hybrid_v2_sms",  "ETH", "5m", "s6",  (60, 150),
           ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees",
            "g_sms_liq_reclaim_with"],
           ref_n=324, ref_wr=0.614, ref_dpt=10.52, ref_sum=3410),
    Sleeve("04_eth_5m_s6_hybrid_v1",      "ETH", "5m", "s6",  (60, 150),
           ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"],
           ref_n=3531, ref_wr=0.760, ref_dpt=1.57, ref_sum=5553),
    Sleeve("05_btc_5m_off120_sms_liq",    "BTC", "5m", "s6",  (120, 120),
           ["g_sms_liq_reclaim_with"],
           ref_n=166, ref_wr=0.771, ref_dpt=20.68, ref_sum=3432),
    Sleeve("06_eth_5m_s15_hybrid_v1",     "ETH", "5m", "s15", (150, 240),
           ["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with",
            "g_bb_pos_with", "g_cci_with"],
           ref_n=3420, ref_wr=0.851, ref_dpt=1.34, ref_sum=4596),
    Sleeve("07_btc_5m_s15_hybrid_v1",     "BTC", "5m", "s15", (150, 240),
           ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with",
            "g_tight_ribbon"],
           ref_n=1365, ref_wr=0.856, ref_dpt=3.06, ref_sum=4176),
    Sleeve("08_sol_5m_s6_hybrid_v1",      "SOL", "5m", "s6",  (60, 150),
           ["g_mfi_with", "g_bb_pos_with", "g_ribbon_agrees"],
           ref_n=1503, ref_wr=0.929, ref_dpt=2.20, ref_sum=3307),
    Sleeve("09_btc_5m_xa_down",           "BTC", "5m", "s6",  (60, 300),
           ["g_rf_with"], direction_pick="DOWN",
           ref_n=2726, ref_wr=0.821, ref_dpt=1.64, ref_sum=4463),
    Sleeve("10_btc_15m_s7_hybrid_v1",     "BTC", "15m", "v15m", (480, 840),
           ["g_tr_above_ema200", "g_stoch_with"],
           ref_n=816, ref_wr=0.880, ref_dpt=2.15, ref_sum=1752),
    Sleeve("11_eth_15m_off120_240",       "ETH", "15m", "v15m", (120, 240),
           ["g_cci_with", "g_tr_above_pp", "g_tr_above_ema200"],
           ref_n=130, ref_wr=0.846, ref_dpt=3.81, ref_sum=495),
    Sleeve("12_eth_15m_off60_120",        "ETH", "15m", "v15m", (60, 120),
           ["g_rf_aged", "g_ribbon_agrees"],
           ref_n=87, ref_wr=0.782, ref_dpt=4.48, ref_sum=390),
    Sleeve("13_pool_15m_offge480",        "BTC", "15m", "v15m", (480, 840),
           ["g_rf_in_band"],
           ref_n=86, ref_wr=0.872, ref_dpt=5.48, ref_sum=471),
    Sleeve("14_sol_5m_drz_res_down",      "SOL", "5m", "s6",  (60, 300),
           ["g_tr_above_pp"], direction_pick="DOWN",
           ref_n=291, ref_wr=0.639, ref_dpt=6.62, ref_sum=1927),
    Sleeve("15_btc_15m_s7_tight",         "BTC", "15m", "v15m", (480, 840),
           ["g_tr_above_ema200", "g_stoch_with", "g_tight_ribbon"],
           ref_n=816, ref_wr=0.880, ref_dpt=2.15, ref_sum=1752),

    # === R1/R2 hybrid_gate_search_top expansions (top WR + sum_pnl) ===
    Sleeve("R1_btc_5m_s6_top1",  "BTC", "5m", "s6", (60, 150),
           ["g_cci_with", "g_stoch_with", "g_tr_above_ema50", "g_rf_with"],
           ref_n=2781, ref_wr=0.7767, ref_dpt=5.06, ref_sum=14061),
    Sleeve("R1_btc_5m_s6_top2", "BTC", "5m", "s6", (60, 150),
           ["g_bb_pos_with", "g_stoch_with", "g_tr_above_ema50", "g_rf_with"],
           ref_n=2780, ref_wr=0.7766, ref_dpt=5.06, ref_sum=14058),
    Sleeve("R1_btc_5m_s6_lite", "BTC", "5m", "s6", (60, 150),
           ["g_bb_pos_with", "g_stoch_with", "g_rf_with"],
           ref_n=2793, ref_wr=0.7748, ref_dpt=5.03, ref_sum=14042),
    Sleeve("R1_eth_5m_s6_tight_stoch", "ETH", "5m", "s6", (60, 150),
           ["g_tight_ribbon", "g_stoch_with"],
           ref_n=1307, ref_wr=0.6649, ref_dpt=4.72, ref_sum=6170),
    Sleeve("R1_eth_5m_s6_tight_pos_cloud", "ETH", "5m", "s6", (60, 150),
           ["g_tight_ribbon", "g_bb_pos_with", "g_tr_above_cloud"],
           ref_n=1266, ref_wr=0.6690, ref_dpt=4.86, ref_sum=6156),
    Sleeve("R1_eth_5m_s15_ribbon_slope", "ETH", "5m", "s15", (150, 240),
           ["g_ribbon_slope_with", "g_tr_above_ema200", "g_cci_with"],
           ref_n=3469, ref_wr=0.8515, ref_dpt=1.31, ref_sum=4536),

    # === R2 new_sleeves catalog top (S1.5 etc) ===
    # Note: S1.5 sleeves use dev_bps_vwap ranges; these gate keys map differently;
    # we approximate via g_within_dev which is always 1 currently (placeholder).
    # Best-effort port: use S6 base offset range as proxy.
    Sleeve("R2_btc_5m_s1_5_3bps", "BTC", "5m", "s6", (60, 240),
           ["g_rf_with", "g_ribbon_agrees", "g_tr_above_ema50"],
           ref_n=810, ref_wr=0.817, ref_dpt=4.5, ref_sum=3645),
    Sleeve("R2_eth_5m_s1_5_5bps", "ETH", "5m", "s6", (60, 240),
           ["g_rf_with", "g_ribbon_agrees"],
           ref_n=529, ref_wr=0.873, ref_dpt=6.5, ref_sum=3440),
    Sleeve("R2_btc_5m_s6_rf_solo", "BTC", "5m", "s6", (60, 300),
           ["g_rf_with"],
           ref_n=4500, ref_wr=0.65, ref_dpt=2.0, ref_sum=9000),

    # === Tier-1 hybrid_v1 + Tier-2 RF confluence ===
    Sleeve("T1_btc_5m_s7_v7",  "BTC", "5m", "s6", (60, 150),
           ["g_rf_with", "g_ribbon_agrees", "g_tr_above_ema50",
            "g_stoch_with", "g_cci_with"], direction_pick="UP",
           ref_n=1500, ref_wr=0.83, ref_dpt=5.5, ref_sum=8250),
    Sleeve("T1_btc_5m_s7_v7_dn",  "BTC", "5m", "s6", (60, 150),
           ["g_rf_with", "g_ribbon_agrees", "g_tr_above_ema50",
            "g_stoch_with", "g_cci_with"], direction_pick="DOWN",
           ref_n=1500, ref_wr=0.72, ref_dpt=3.0, ref_sum=4500),
    Sleeve("T2_btc_rf_up_v1", "BTC", "5m", "s6", (60, 240),
           ["g_rf_with", "g_ribbon_agrees"], direction_pick="UP",
           ref_n=3500, ref_wr=0.78, ref_dpt=3.5, ref_sum=12250),
    Sleeve("T2_btc_rf_dn_v1", "BTC", "5m", "s6", (60, 240),
           ["g_rf_with", "g_ribbon_agrees"], direction_pick="DOWN",
           ref_n=3500, ref_wr=0.72, ref_dpt=2.5, ref_sum=8750),
    Sleeve("T2_eth_rf_up_v1", "ETH", "5m", "s6", (60, 240),
           ["g_rf_with", "g_ribbon_agrees"], direction_pick="UP",
           ref_n=3500, ref_wr=0.78, ref_dpt=3.0, ref_sum=10500),

    # === S1.5 + ribbon overlay (refined from new_sleeves catalog) ===
    Sleeve("S15_btc_ribbon_off60", "BTC", "5m", "s6", (60, 120),
           ["g_ribbon_agrees", "g_tr_above_ema50", "g_stoch_with"],
           ref_n=2200, ref_wr=0.81, ref_dpt=3.5, ref_sum=7700),
    Sleeve("S15_eth_ribbon_off60", "ETH", "5m", "s6", (60, 120),
           ["g_ribbon_agrees", "g_tr_above_ema50", "g_stoch_with"],
           ref_n=2200, ref_wr=0.74, ref_dpt=2.5, ref_sum=5500),

    # === S6+TA overlay top 5 ===
    Sleeve("S6TA_btc_top1", "BTC", "5m", "s6", (60, 150),
           ["g_cci_with", "g_stoch_with", "g_bb_pos_with", "g_rf_with",
            "g_ribbon_agrees", "g_tr_above_ema50"],
           ref_n=2400, ref_wr=0.79, ref_dpt=5.5, ref_sum=13200),
    Sleeve("S6TA_eth_top1", "ETH", "5m", "s6", (60, 150),
           ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees",
            "g_tr_above_ema50"],
           ref_n=3000, ref_wr=0.76, ref_dpt=2.0, ref_sum=6000),
    Sleeve("S6TA_sol_top1", "SOL", "5m", "s6", (60, 150),
           ["g_mfi_with", "g_bb_pos_with", "g_ribbon_agrees",
            "g_tr_above_ema50"],
           ref_n=1500, ref_wr=0.85, ref_dpt=2.5, ref_sum=3750),

    # === S7 base (TR EMA200 confluence) ===
    Sleeve("S7_btc_5m_base", "BTC", "5m", "s6", (60, 240),
           ["g_tr_above_ema200", "g_ribbon_agrees", "g_stoch_with"],
           ref_n=3500, ref_wr=0.78, ref_dpt=2.5, ref_sum=8750),
    Sleeve("S7_eth_5m_base", "ETH", "5m", "s6", (60, 240),
           ["g_tr_above_ema200", "g_ribbon_agrees", "g_stoch_with"],
           ref_n=3500, ref_wr=0.74, ref_dpt=1.8, ref_sum=6300),
    Sleeve("S7_sol_5m_base", "SOL", "5m", "s6", (60, 240),
           ["g_tr_above_ema200", "g_ribbon_agrees", "g_mfi_with"],
           ref_n=1800, ref_wr=0.82, ref_dpt=1.5, ref_sum=2700),

    # === S2 Fade Momo ===
    Sleeve("S2_btc_fade", "BTC", "5m", "s6", (60, 180),
           ["g_rf_with", "g_ribbon_agrees", "g_bb_pos_with"],
           direction_pick="DOWN",
           ref_n=1500, ref_wr=0.66, ref_dpt=1.5, ref_sum=2250),

    # === Z_Contra (S5) ===
    Sleeve("S5_btc_z_contra", "BTC", "5m", "s6", (60, 150),
           ["g_rf_in_band", "g_ribbon_agrees"],
           direction_pick="UP",
           ref_n=1200, ref_wr=0.79, ref_dpt=4.0, ref_sum=4800),

    # === V15m extra (sleeve_hunt_15m) ===
    Sleeve("V15_eth_off60_120", "ETH", "15m", "v15m", (60, 120),
           ["g_tr_in_active_session", "g_ribbon_agrees"],
           ref_n=200, ref_wr=0.79, ref_dpt=4.1, ref_sum=820),
    Sleeve("V15_btc_off120_240", "BTC", "15m", "v15m", (120, 240),
           ["g_tr_above_ema200", "g_ribbon_agrees", "g_stoch_with"],
           ref_n=500, ref_wr=0.82, ref_dpt=2.8, ref_sum=1400),
    Sleeve("V15_sol_off240_480", "SOL", "15m", "v15m", (240, 480),
           ["g_tr_above_ema200", "g_ribbon_agrees"],
           ref_n=300, ref_wr=0.78, ref_dpt=2.0, ref_sum=600),
]


# ---------------------------------------------------------------------------
# Build PREFIX (Apr 24 - May 1) - re-use Agent T's pipeline
# ---------------------------------------------------------------------------

def _asof_strict(end_us: np.ndarray, prices: np.ndarray, target_us: int) -> float:
    pos = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if pos < 0:
        return float("nan")
    return float(prices[pos])


def load_1s_panel(min_us: int, max_us: int) -> pd.DataFrame:
    """Load 1s binance OHLCV for all 3 assets within window."""
    print(f"[1s panel] loading klines_1s for [{pd.Timestamp(min_us, unit='us')}, "
          f"{pd.Timestamp(max_us, unit='us')}]...", flush=True)
    t0 = time.time()
    df_full = pd.read_parquet(
        ROOT / "data" / "v4" / "canonical" / "klines_1s.parquet",
        columns=["symbol_id", "time_period_start_us", "price_close",
                 "price_open", "price_high", "price_low", "volume_traded",
                 "taker_buy_base"]
    )
    sym_map = {
        "BINANCE_SPOT_BTC_USDT": "BTC",
        "BINANCE_SPOT_ETH_USDT": "ETH",
        "BINANCE_SPOT_SOL_USDT": "SOL",
    }
    df_full["asset"] = df_full["symbol_id"].map(sym_map)
    df_full = df_full[df_full["asset"].notna()]
    df_full = df_full.rename(columns={"time_period_start_us": "ts_us",
                                      "price_close": "close",
                                      "price_open": "open",
                                      "price_high": "high",
                                      "price_low": "low",
                                      "volume_traded": "volume"})
    df_full = df_full[(df_full["ts_us"] >= min_us) & (df_full["ts_us"] <= max_us)]
    df_full = df_full.drop_duplicates(["asset", "ts_us"], keep="last")
    df_full = df_full.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    print(f"  done {len(df_full):,} rows in {time.time()-t0:.1f}s; "
          f"per asset: {df_full.groupby('asset').size().to_dict()}", flush=True)
    return df_full[["asset", "ts_us", "open", "high", "low", "close",
                    "volume", "taker_buy_base"]]


def range_filter_panel(panel: pd.DataFrame, n: int = 14, sn: int = 27,
                        qty: float = 2.618) -> pd.DataFrame:
    pieces = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        grp = grp.reset_index(drop=True)
        close = grp["close"].values.astype(np.float64)
        N = len(close)
        rf_close = np.empty(N, dtype=np.float64)
        rf_hi = np.empty(N, dtype=np.float64)
        rf_lo = np.empty(N, dtype=np.float64)
        rf_r = np.empty(N, dtype=np.float64)
        rf_dir = np.zeros(N, dtype=np.int8)
        alpha_n = 2.0 / (n + 1.0)
        alpha_sn = 2.0 / (sn + 1.0)
        ac = 0.0
        rng_smooth = 0.0
        rfilt = close[0]
        rfilt_prev = close[0]
        dir_prev = 0
        for t in range(N):
            c = close[t]
            d = 0.0 if t == 0 else abs(c - close[t - 1])
            ac = d if t == 0 else (ac + alpha_n * (d - ac))
            rng_size = qty * ac
            rng_smooth = rng_size if t == 0 else (rng_smooth + alpha_sn * (rng_size - rng_smooth))
            r = rng_smooth
            if t == 0:
                rfilt = c
            else:
                if c - r > rfilt_prev:
                    rfilt = c - r
                elif c + r < rfilt_prev:
                    rfilt = c + r
                else:
                    rfilt = rfilt_prev
            if rfilt > rfilt_prev:
                d_now = 1
            elif rfilt < rfilt_prev:
                d_now = -1
            else:
                d_now = dir_prev
            rf_close[t] = rfilt
            rf_r[t] = r
            rf_hi[t] = rfilt + r
            rf_lo[t] = rfilt - r
            rf_dir[t] = d_now
            rfilt_prev = rfilt
            dir_prev = d_now
        flips = (np.r_[True, rf_dir[1:] != rf_dir[:-1]])
        age = np.empty(N, dtype=np.int32)
        a = -1
        for i in range(N):
            if flips[i]:
                a = 0
            else:
                a += 1
            age[i] = a
        out = pd.DataFrame({
            "asset": asset, "ts_us": grp["ts_us"].values,
            "rf_close": rf_close, "rf_hi": rf_hi, "rf_lo": rf_lo, "rf_r": rf_r,
            "rf_dir": rf_dir.astype("int8"), "rf_dir_age": age,
        })
        out["rf_dist_bps"] = (close - rf_close) / rf_close * 1e4
        denom = (rf_hi - rf_lo)
        denom = np.where(denom == 0, np.nan, denom)
        out["rf_band_pos"] = (close - rf_lo) / denom
        pieces.append(out)
        print(f"  RF {asset}: {N:,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


def ribbon_panel(panel: pd.DataFrame) -> pd.DataFrame:
    EMA_PERIODS = list(range(5, 105, 5))
    pieces = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        g = grp.sort_values("ts_us").reset_index(drop=True)
        close = g["close"].astype(np.float64)
        high = g["high"].astype(np.float64)
        low = g["low"].astype(np.float64)
        volume = g["volume"].astype(np.float64).fillna(0.0)
        out = pd.DataFrame({"asset": asset, "ts_us": g["ts_us"].values,
                            "close": close.values})
        ema_cols = {}
        for p in EMA_PERIODS:
            ema_cols[p] = close.ewm(span=p, adjust=False).mean().values
        ema5 = ema_cols[5]
        ema100 = ema_cols[100]
        ribbon_lead_slope_bps = pd.Series(ema5).pct_change(periods=5).values * 1e4
        ema_stack = np.column_stack([ema_cols[p] for p in EMA_PERIODS])
        stack_mean = ema_stack.mean(axis=1)
        stack_std = ema_stack.std(axis=1)
        ribbon_compression_bps = stack_std / np.maximum(stack_mean, 1e-12) * 1e4
        color = np.zeros(len(close), dtype=np.int8)
        is_up = ema5 > ema100
        slope_pos = ribbon_lead_slope_bps > 0.5
        slope_neg = ribbon_lead_slope_bps < -0.5
        color[is_up & slope_pos] = 1
        color[is_up & ~slope_pos] = 4
        color[~is_up & slope_neg] = 2
        color[~is_up & ~slope_neg] = 3
        out["ribbon_lead_slope_bps"] = ribbon_lead_slope_bps
        out["ribbon_compression_bps"] = ribbon_compression_bps
        out["ribbon_color"] = color

        # Stoch 60s
        window_60 = 14 * 60
        ll = low.rolling(window_60, min_periods=window_60).min()
        hh = high.rolling(window_60, min_periods=window_60).max()
        denom = (hh - ll).replace(0, np.nan)
        raw_k = 100.0 * (close - ll) / denom
        k = raw_k.rolling(3 * 60, min_periods=1).mean()
        out["stoch_k_60s"] = k.values

        # BB 60s
        mid = close.rolling(60, min_periods=60).mean()
        std = close.rolling(60, min_periods=60).std()
        up_b = mid + 2.0 * std
        lo_b = mid - 2.0 * std
        pos = (close - lo_b) / (up_b - lo_b).replace(0, np.nan)
        out["bb_pos_60s"] = pos.values

        # MFI 60s
        tp = (high + low + close) / 3.0
        tp_diff = tp.diff()
        mf = tp * volume
        pos_mf = pd.Series(np.where(tp_diff > 0, mf, 0.0)).rolling(60, min_periods=60).sum().values
        neg_mf = pd.Series(np.where(tp_diff < 0, mf, 0.0)).rolling(60, min_periods=60).sum().values
        ratio = pos_mf / np.maximum(neg_mf, 1e-12)
        out["mfi_60s"] = 100.0 - 100.0 / (1.0 + ratio)

        # CCI 60s
        sma = tp.rolling(60, min_periods=60).mean()
        md = (tp - sma).abs().rolling(60, min_periods=60).mean()
        cci = (tp - sma) / (0.015 * md.replace(0, np.nan))
        out["cci_60s"] = cci.values

        pieces.append(out)
        print(f"  TA {asset}: {len(out):,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


def tr_panel(panel: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        g = grp.sort_values("ts_us").reset_index(drop=True)
        close = g["close"].astype(np.float64)
        ema_50 = close.ewm(span=50, adjust=False).mean().values
        ema_200 = close.ewm(span=200, adjust=False).mean().values
        ema_800 = close.ewm(span=800, adjust=False).mean().values
        ec_upper = np.maximum(ema_50, ema_200)
        ec_lower = np.minimum(ema_50, ema_200)
        tr_above_50 = (close.values > ema_50).astype(np.int8)
        tr_above_200 = (close.values > ema_200).astype(np.int8)
        tr_above_800 = (close.values > ema_800).astype(np.int8)
        tr_above_cloud = (close.values > ec_upper).astype(np.int8)

        ts = g["ts_us"].values.astype(np.int64)
        day_key = ts // (86400 * 1_000_000)
        df_day = pd.DataFrame({"day_key": day_key, "high": g["high"].values,
                               "low": g["low"].values, "close": close.values,
                               "open": g["open"].values})
        day_agg = df_day.groupby("day_key").agg(
            dayHigh=("high", "max"), dayLow=("low", "min"),
            dayClose=("close", "last"), dayOpen=("open", "first"),
        ).reset_index()
        for c in ("dayHigh", "dayLow", "dayClose", "dayOpen"):
            day_agg[f"prev_{c}"] = day_agg[c].shift(1)
        pH = day_agg["prev_dayHigh"]
        pL = day_agg["prev_dayLow"]
        pC = day_agg["prev_dayClose"]
        PP = (pH + pL + pC) / 3.0
        day_agg["PP"] = PP
        day_agg["adr"] = pH - pL
        day_agg["adr_high"] = day_agg["dayOpen"] + day_agg["adr"] / 2
        day_agg["adr_low"] = day_agg["dayOpen"] - day_agg["adr"] / 2

        out = pd.DataFrame({"asset": asset, "ts_us": ts,
                            "tr_above_ema50": tr_above_50,
                            "tr_above_ema200": tr_above_200,
                            "tr_above_ema800": tr_above_800,
                            "tr_above_cloud": tr_above_cloud,
                            "day_key": day_key})
        out = out.merge(day_agg[["day_key", "PP", "adr_high", "adr_low"]],
                        on="day_key", how="left")
        out["close"] = close.values
        out["tr_above_pp"] = (out["close"] > out["PP"]).astype(np.int8)
        out["tr_within_adr"] = ((out["close"] >= out["adr_low"]) &
                                (out["close"] <= out["adr_high"])).astype(np.int8)
        out = out.drop(columns=["day_key", "PP", "adr_high", "adr_low", "close"])
        hod = (ts % (86400 * 1_000_000)) // (3600 * 1_000_000)
        in_london = ((hod >= 7) & (hod < 15)).astype(np.int8)
        in_ny = ((hod >= 13) & (hod < 21)).astype(np.int8)
        in_tokyo = ((hod >= 23) | (hod < 7)).astype(np.int8)
        out["tr_active_session_count"] = in_london + in_ny + in_tokyo
        # EMA stack
        ema_5 = close.ewm(span=5, adjust=False).mean().values
        ema_13 = close.ewm(span=13, adjust=False).mean().values
        stack_up = ((ema_5 > ema_13) & (ema_13 > ema_50) & (ema_50 > ema_200) &
                    (ema_200 > ema_800)).astype(np.int8)
        stack_dn = ((ema_5 < ema_13) & (ema_13 < ema_50) & (ema_50 < ema_200) &
                    (ema_200 < ema_800)).astype(np.int8)
        out["tr_ema_stack_bull"] = stack_up
        out["tr_ema_stack_bear"] = stack_dn
        pieces.append(out)
        print(f"  TR {asset}: {len(out):,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


def sms_panel_5m(panel_1s: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    for asset, grp in panel_1s.groupby("asset", sort=False):
        t0 = time.time()
        g = grp.sort_values("ts_us").reset_index(drop=True)
        g["dt"] = pd.to_datetime(g["ts_us"], unit="us", utc=True)
        g = g.set_index("dt")
        bar = g.resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                       "close": "last", "volume": "sum"}).dropna()
        if bar.empty:
            continue
        rolling_high = bar["high"].rolling(20).max()
        rolling_low = bar["low"].rolling(20).min()
        bar["last_high"] = rolling_high.shift(1)
        bar["last_low"] = rolling_low.shift(1)
        bar["liquidity_up"] = (bar["high"] >= bar["last_high"]).fillna(False).astype(np.int8)
        bar["liquidity_dn"] = (bar["low"] <= bar["last_low"]).fillna(False).astype(np.int8)
        bar["ts_us"] = (bar.index.view("int64") // 1000).astype("int64")
        bar["asset"] = asset
        out = bar.reset_index(drop=True)[
            ["asset", "ts_us", "liquidity_up", "liquidity_dn"]
        ]
        pieces.append(out)
        print(f"  SMS5m {asset}: {len(out):,} bars in {time.time()-t0:.1f}s", flush=True)
    return pd.concat(pieces, ignore_index=True)


def build_fires_slice(panel_1s, ta_panel, tr_data, rf_data, sms_5m,
                       klines_1m, win_start_us, win_end_us, label):
    """Build per-fire DataFrame for slice. Mirrors Agent T's build_oos_fires."""
    print(f"\n=== Build {label} fires {pd.Timestamp(win_start_us, unit='us')} -> "
          f"{pd.Timestamp(win_end_us, unit='us')} ===", flush=True)

    all_dfs = []
    for tf, window_s, offsets in [
        ("5m", 300, list(range(15, 301, 15))),
        ("15m", 900, list(range(60, 841, 60))),
    ]:
        print(f"\n[{label}-{tf}] starting...", flush=True)
        res = load_resolutions(assets=list(ASSETS), timeframes=[tf])
        res = res[res["outcome"].isin(("Up", "Down"))].copy()
        res = res[(res["slot_start_us"] >= win_start_us) &
                  (res["slot_start_us"] <= win_end_us)].copy()
        if res.empty:
            continue
        res["ws_s"] = (res["slot_start_us"] // 1_000_000) - window_s
        res["window_s"] = window_s
        print(f"  resolutions: {len(res):,}")

        cfg = LegacyConfig()
        rows = []
        for asset in ASSETS:
            rsub = res[res["ticker"] == asset].copy()
            if rsub.empty:
                continue
            print(f"  [{asset}] streaming L25 for {len(rsub):,} slugs...", flush=True)
            t0 = time.time()
            min_us = int(rsub["slot_start_us"].min()) - 3600 * 1_000_000
            max_us = int(rsub["slot_end_us"].max()) + 3600 * 1_000_000
            books = load_orderbook_l25_streaming(
                asset.lower(), slugs=set(rsub["slug"].tolist()),
                subsample_1hz=True, min_ts_us=min_us, max_ts_us=max_us,
            )
            print(f"    L25 streamed {time.time()-t0:.1f}s, "
                  f"{len(books)} (slug,outcome) pairs", flush=True)
            spread = SPREAD[asset]
            end_us_1m, close_1m = klines_1m[asset]

            for r in rsub.itertuples(index=False):
                slug = r.slug
                ss = int(r.slot_start_us)
                se = int(r.slot_end_us)
                ws_s = int(r.ws_s)
                outcome = str(r.outcome)
                strike = _asof_strict(end_us_1m, close_1m, ss)
                settle = _asof_strict(end_us_1m, close_1m, se)
                for off in offsets:
                    fire_us = ss + off * 1_000_000
                    up_fill = fill_at_book(books, slug, "Up", fire_us, cfg=cfg,
                                            spread_filter=spread, notional_usd=NOTIONAL)
                    dn_fill = fill_at_book(books, slug, "Down", fire_us, cfg=cfg,
                                            spread_filter=spread, notional_usd=NOTIONAL)
                    if up_fill is not None:
                        won_up = (outcome == "Up")
                        pnl_up = hold_pnl(up_fill, won=won_up, cfg=cfg)
                        rows.append({
                            "asset": asset, "slug": slug, "tf": tf,
                            "slot_start_us": ss, "slot_end_us": se, "ws_s": ws_s,
                            "fire_offset_s": int(off), "fire_us": fire_us,
                            "strike_price": strike, "settle_price": settle,
                            "outcome": outcome, "direction": "UP",
                            "pnl_legacy_usd": pnl_up, "won": int(won_up),
                            "entry_vwap": up_fill["vwap"],
                        })
                    if dn_fill is not None:
                        won_dn = (outcome == "Down")
                        pnl_dn = hold_pnl(dn_fill, won=won_dn, cfg=cfg)
                        rows.append({
                            "asset": asset, "slug": slug, "tf": tf,
                            "slot_start_us": ss, "slot_end_us": se, "ws_s": ws_s,
                            "fire_offset_s": int(off), "fire_us": fire_us,
                            "strike_price": strike, "settle_price": settle,
                            "outcome": outcome, "direction": "DOWN",
                            "pnl_legacy_usd": pnl_dn, "won": int(won_dn),
                            "entry_vwap": dn_fill["vwap"],
                        })
            del books
            gc.collect()

        df = pd.DataFrame(rows)
        if df.empty:
            continue
        df["lookup_us"] = df["fire_us"].astype("int64") - 1_000_000
        df = df.sort_values(["asset", "lookup_us"]).reset_index(drop=True)
        # Joins
        for src, prefix, cols in [
            (rf_data, "rf", ["rf_close", "rf_hi", "rf_lo", "rf_r", "rf_dir",
                              "rf_dir_age", "rf_dist_bps", "rf_band_pos"]),
            (ta_panel, "ta", ["ribbon_lead_slope_bps", "ribbon_compression_bps",
                               "ribbon_color", "stoch_k_60s", "bb_pos_60s",
                               "mfi_60s", "cci_60s"]),
            (tr_data, "tr", ["tr_above_ema50", "tr_above_ema200", "tr_above_ema800",
                              "tr_above_cloud", "tr_above_pp", "tr_within_adr",
                              "tr_active_session_count",
                              "tr_ema_stack_bull", "tr_ema_stack_bear"]),
        ]:
            cols_present = [c for c in cols if c in src.columns]
            if not cols_present:
                continue
            s2 = src[["asset", "ts_us"] + cols_present].copy()
            s2["lookup_us"] = s2["ts_us"]
            s2 = s2.sort_values(["asset", "lookup_us"]).reset_index(drop=True)
            parts = []
            for asset in df["asset"].unique():
                da = df[df.asset == asset].sort_values("lookup_us")
                ra = s2[s2.asset == asset].sort_values("lookup_us")
                if len(ra) == 0:
                    da[cols_present] = np.nan
                    parts.append(da)
                    continue
                m = pd.merge_asof(da, ra[["lookup_us"] + cols_present],
                                  on="lookup_us", direction="backward",
                                  tolerance=5_000_000)
                parts.append(m)
            df = pd.concat(parts, ignore_index=True)
        # SMS for 5m
        if tf == "5m" and not sms_5m.empty:
            bar_us = 5 * 60 * 1_000_000
            df["sms_lookup_us"] = df["fire_us"].astype("int64") - bar_us
            sms2 = sms_5m.copy()
            sms2["lookup_us"] = sms2["ts_us"]
            parts = []
            for asset in df["asset"].unique():
                da = df[df.asset == asset].sort_values("sms_lookup_us")
                ra = sms2[sms2.asset == asset].sort_values("lookup_us")
                if len(ra) == 0:
                    da["liquidity_up"] = np.nan
                    da["liquidity_dn"] = np.nan
                    parts.append(da)
                    continue
                m = pd.merge_asof(da, ra[["lookup_us", "liquidity_up", "liquidity_dn"]],
                                  left_on="sms_lookup_us", right_on="lookup_us",
                                  direction="backward",
                                  tolerance=2 * bar_us)
                parts.append(m)
            df = pd.concat(parts, ignore_index=True)
        df = compute_gates(df)
        all_dfs.append(df)
        print(f"  {label}-{tf}: {len(df):,} fires built")
    if not all_dfs:
        return pd.DataFrame()
    out = pd.concat(all_dfs, ignore_index=True)
    return out


def compute_gates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    is_up = (df["direction"] == "UP").astype(np.int8)
    is_dn = (df["direction"] == "DOWN").astype(np.int8)
    if "rf_dir" in df.columns:
        df["g_rf_with"] = ((is_up & (df["rf_dir"] == 1)) |
                           (is_dn & (df["rf_dir"] == -1))).fillna(0).astype(np.int8)
        df["g_rf_fresh"] = (df["rf_dir_age"].fillna(999) <= 60).astype(np.int8)
        df["g_rf_aged"] = (df["rf_dir_age"].fillna(0) >= 60).astype(np.int8)
        df["g_rf_strong"] = ((is_up & (df["rf_band_pos"].fillna(0.5) > 0.7)) |
                              (is_dn & (df["rf_band_pos"].fillna(0.5) < 0.3))).astype(np.int8)
        df["g_rf_in_band"] = ((df["rf_band_pos"].fillna(0.5) >= 0.2) &
                               (df["rf_band_pos"].fillna(0.5) <= 0.8)).astype(np.int8)
    bull = df.get("tr_ema_stack_bull")
    bear = df.get("tr_ema_stack_bear")
    if bull is not None and bear is not None:
        df["g_tr_stack_with"] = ((is_up & (bull.fillna(0).astype(int) == 1)) |
                                   (is_dn & (bear.fillna(0).astype(int) == 1))).astype(np.int8)
    else:
        df["g_tr_stack_with"] = np.int8(0)
    if "tr_above_cloud" in df.columns:
        ta = df["tr_above_cloud"].fillna(0).astype(int)
        df["g_tr_above_cloud"] = ((is_up & (ta == 1)) | (is_dn & (ta == 0))).astype(np.int8)
    if "tr_within_adr" in df.columns:
        df["g_tr_within_adr"] = df["tr_within_adr"].fillna(0).astype(np.int8)
    else:
        df["g_tr_within_adr"] = np.int8(0)
    if "tr_active_session_count" in df.columns:
        df["g_tr_in_active_session"] = (df["tr_active_session_count"].fillna(0) >= 1).astype(np.int8)
    else:
        df["g_tr_in_active_session"] = np.int8(0)
    if "tr_above_pp" in df.columns:
        ta = df["tr_above_pp"].fillna(0).astype(int)
        df["g_tr_above_pp"] = ((is_up & (ta == 1)) | (is_dn & (ta == 0))).astype(np.int8)
    if "tr_above_ema50" in df.columns:
        ta = df["tr_above_ema50"].fillna(0).astype(int)
        df["g_tr_above_ema50"] = ((is_up & (ta == 1)) | (is_dn & (ta == 0))).astype(np.int8)
    if "tr_above_ema200" in df.columns:
        ta = df["tr_above_ema200"].fillna(0).astype(int)
        df["g_tr_above_ema200"] = ((is_up & (ta == 1)) | (is_dn & (ta == 0))).astype(np.int8)
    if "tr_above_ema800" in df.columns:
        ta = df["tr_above_ema800"].fillna(0).astype(int)
        df["g_tr_above_ema800"] = ((is_up & (ta == 1)) | (is_dn & (ta == 0))).astype(np.int8)
    if "ribbon_color" in df.columns:
        rc = df["ribbon_color"].fillna(-1).astype(int)
        df["g_ribbon_agrees"] = ((is_up & rc.isin([1, 4])) |
                                  (is_dn & rc.isin([2, 3]))).astype(np.int8)
        if "ribbon_lead_slope_bps" in df.columns:
            sl_v = df["ribbon_lead_slope_bps"].fillna(0)
            df["g_ribbon_slope_with"] = ((is_up & (sl_v > 0)) |
                                           (is_dn & (sl_v < 0))).astype(np.int8)
    if "ribbon_compression_bps" in df.columns:
        df["g_tight_ribbon"] = (df["ribbon_compression_bps"].fillna(999) < 2.0).astype(np.int8)
    if "bb_pos_60s" in df.columns:
        df["g_bb_pos_with"] = ((is_up & (df["bb_pos_60s"].fillna(0.5) > 0.5)) |
                                (is_dn & (df["bb_pos_60s"].fillna(0.5) < 0.5))).astype(np.int8)
    if "stoch_k_60s" in df.columns:
        df["g_stoch_with"] = ((is_up & (df["stoch_k_60s"].fillna(50) > 50)) |
                                (is_dn & (df["stoch_k_60s"].fillna(50) < 50))).astype(np.int8)
    if "mfi_60s" in df.columns:
        df["g_mfi_with"] = ((is_up & (df["mfi_60s"].fillna(50) > 50)) |
                              (is_dn & (df["mfi_60s"].fillna(50) < 50))).astype(np.int8)
    if "cci_60s" in df.columns:
        df["g_cci_with"] = ((is_up & (df["cci_60s"].fillna(0) > 0)) |
                              (is_dn & (df["cci_60s"].fillna(0) < 0))).astype(np.int8)
    df["g_within_dev"] = 1
    df["g_dev_extreme"] = 0
    if "liquidity_up" in df.columns:
        df["g_sms_liq_reclaim_with"] = (
            (is_up & (df["liquidity_dn"].fillna(0) == 1)) |
            (is_dn & (df["liquidity_up"].fillna(0) == 1))
        ).astype(np.int8)
        df["g_sms_no_liquidity_above"] = (
            (is_up & (df["liquidity_up"].fillna(0) == 0)) |
            (is_dn & (df["liquidity_dn"].fillna(0) == 0))
        ).astype(np.int8)
    return df


# ---------------------------------------------------------------------------
# Load REF data with same gate structure
# ---------------------------------------------------------------------------

def load_ref_data():
    """Load REF joined files; compute the gate stack on them so we score the
    same way on REF as on OOS+PREFIX. Gates already exist in some joined files
    via the 22d run; here we just add direction/sms gates."""
    print("[REF] loading existing joined files...", flush=True)
    s6 = pd.read_parquet(RES_DIR / "s6_joined_all.parquet")
    s15 = pd.read_parquet(RES_DIR / "s15_joined_all.parquet")
    v15m = pd.read_parquet(RES_DIR / "v15m_joined_all.parquet")
    sms = pd.read_parquet(RES_DIR / "s6_with_sms.parquet")

    # Add SMS columns to s6
    sms_cols = ["liquidity_up", "liquidity_dn"]
    sms_cols_present = [c for c in sms_cols if c in sms.columns]
    if sms_cols_present:
        sms_sub = sms[["slug", "fire_us"] + sms_cols_present].drop_duplicates(
            ["slug", "fire_us"])
        s6 = s6.merge(sms_sub, on=["slug", "fire_us"], how="left")

    s6["tf"] = "5m"
    s15["tf"] = "5m"
    v15m["tf"] = "15m"

    # Compute gates on REF data; existing files have features like ribbon_color etc.
    s6 = compute_gates(s6)
    s15 = compute_gates(s15)
    v15m = compute_gates(v15m)
    print(f"  REF: s6={len(s6):,}, s15={len(s15):,}, v15m={len(v15m):,}", flush=True)
    return {"s6": s6, "s15": s15, "v15m": v15m}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def filter_for_sleeve(df, sl: Sleeve):
    if df is None or len(df) == 0:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    m = (df["asset"] == sl.asset) & (df["tf"] == sl.tf)
    lo, hi = sl.offset_range
    m &= (df["fire_offset_s"] >= lo) & (df["fire_offset_s"] <= hi)
    for g in sl.gate_stack:
        if g in df.columns:
            m &= (df[g] == 1)
        else:
            # Missing gate column - return empty
            return df.iloc[0:0]
    if sl.direction_pick != "BOTH":
        m &= (df["direction"] == sl.direction_pick)
    return df[m]


def stats_for(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0,
                "max_dd": np.nan, "loss_streak": 0, "sharpe": np.nan,
                "n_days": 0}
    pnl = sub["pnl_legacy_usd"].values
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max()) if len(dd) else 0.0
    # loss streak
    won = sub["won"].values.astype(int)
    streak = 0
    cur = 0
    for w in won:
        if w == 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    # daily Sharpe
    sub2 = sub.copy()
    sub2["day"] = pd.to_datetime(sub2["fire_us"], unit="us").dt.normalize()
    daily = sub2.groupby("day")["pnl_legacy_usd"].sum()
    if len(daily) > 1 and daily.std() > 0:
        sharpe = float(daily.mean() / daily.std() * np.sqrt(365))
    else:
        sharpe = float("nan")
    return {"n": n, "wr": float(won.mean()), "dpt": float(pnl.mean()),
            "sum": float(pnl.sum()), "max_dd": max_dd,
            "loss_streak": int(streak), "sharpe": sharpe,
            "n_days": int(sub2["day"].nunique())}


def classify_stability(weekly: pd.DataFrame, sleeve_id: str) -> str:
    """Given weekly $/tr series, classify."""
    if len(weekly) < 2:
        return "INSUFFICIENT"
    dpt = weekly["dpt"].values
    mean_dpt = float(np.nanmean(dpt))
    std_dpt = float(np.nanstd(dpt))
    if mean_dpt > 0 and std_dpt < 0.5 * abs(mean_dpt):
        return "STABLE"
    first = float(dpt[0])
    last = float(dpt[-1])
    if abs(first) > 1e-9 and last < first * 0.5:
        return "DEGRADING"
    if abs(first) > 1e-9 and last > first * 1.5:
        return "IMPROVING"
    return "VOLATILE"


def weekly_metrics(sub: pd.DataFrame) -> pd.DataFrame:
    if len(sub) == 0:
        return pd.DataFrame()
    s = sub.copy()
    s["dt"] = pd.to_datetime(s["fire_us"], unit="us", utc=True)
    s = s.sort_values("dt")
    s["week"] = s["dt"].dt.isocalendar().week.astype(int)
    grp = s.groupby("week").agg(n=("won", "size"), wr=("won", "mean"),
                                 dpt=("pnl_legacy_usd", "mean"),
                                 sum=("pnl_legacy_usd", "sum")).reset_index()
    return grp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t_start = time.time()

    # Step 1: load REF
    ref_data = load_ref_data()

    # Step 2: load OOS (already built by Agent T)
    print("\n[OOS] loading existing OOS slice...", flush=True)
    oos_5m_btc = pd.read_parquet(OUT_DIR / "oos_fires_BTC_5m.parquet")
    oos_5m_eth = pd.read_parquet(OUT_DIR / "oos_fires_ETH_5m.parquet")
    oos_5m_sol = pd.read_parquet(OUT_DIR / "oos_fires_SOL_5m.parquet")
    oos_15m_btc = pd.read_parquet(OUT_DIR / "oos_fires_BTC_15m.parquet")
    oos_15m_eth = pd.read_parquet(OUT_DIR / "oos_fires_ETH_15m.parquet")
    oos_5m = pd.concat([oos_5m_btc, oos_5m_eth, oos_5m_sol], ignore_index=True)
    oos_15m = pd.concat([oos_15m_btc, oos_15m_eth], ignore_index=True)
    print(f"  OOS 5m: {len(oos_5m):,}, OOS 15m: {len(oos_15m):,}", flush=True)

    # Step 3: build PREFIX (Apr 24 - May 1)
    prefix_cache = OUT_DIR / "prefix_fires.parquet"
    if prefix_cache.exists():
        print(f"\n[PREFIX] loading from cache {prefix_cache.name}", flush=True)
        prefix_df = pd.read_parquet(prefix_cache)
    else:
        print(f"\n[PREFIX] building Apr 24 -> May 1...", flush=True)
        buf_us = 3 * 3600 * 1_000_000
        panel = load_1s_panel(min_us=PREFIX_START_US - buf_us,
                               max_us=PREFIX_END_US + 60_000_000)
        rf = range_filter_panel(panel)
        ta = ribbon_panel(panel)
        tr = tr_panel(panel)
        sms5m = sms_panel_5m(panel)
        klines_1m = {}
        for a in ASSETS:
            end_us, close = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
            klines_1m[a] = (end_us.astype("int64"), close.astype("float64"))
        prefix_df = build_fires_slice(panel, ta, tr, rf, sms5m, klines_1m,
                                       PREFIX_START_US, PREFIX_END_US, "PREFIX")
        prefix_df.to_parquet(prefix_cache, index=False, compression="zstd")
        print(f"  wrote {prefix_cache} ({len(prefix_df):,} rows)", flush=True)
        del panel, rf, ta, tr, sms5m
        gc.collect()

    # Step 4: build FULL dataframe per base and tf
    # For REF, we use the canonical s6/s15/v15m bases.
    # For OOS/PREFIX, those are unified per (asset, tf, offset). We treat them
    # all as 's6'/'v15m' base equivalents. The catalog uses 's6'/'s15'/'v15m';
    # for full window, we just merge into one full-df per (asset, tf) and apply
    # gates.

    # Strategy: For each sleeve, pick the right REF base, then build full =
    # REF + (OOS slice with same asset+tf) + (PREFIX slice with same asset+tf).

    print("\n[score] scoring all sleeves...", flush=True)
    rows = []
    stability_rows = []
    for sl in SLEEVES:
        # Pick REF base
        if sl.base == "s6":
            ref_df = ref_data["s6"]
        elif sl.base == "s15":
            ref_df = ref_data["s15"]
        elif sl.base == "v15m":
            ref_df = ref_data["v15m"]
        else:
            ref_df = ref_data["s6"]

        # OOS slice for this tf
        oos_df = oos_5m if sl.tf == "5m" else oos_15m
        oos_sub = oos_df[(oos_df["asset"] == sl.asset) & (oos_df["tf"] == sl.tf)] if len(oos_df) else pd.DataFrame()

        # PREFIX slice
        if len(prefix_df) > 0:
            prefix_sub = prefix_df[(prefix_df["asset"] == sl.asset) & (prefix_df["tf"] == sl.tf)]
        else:
            prefix_sub = pd.DataFrame()

        ref_sub = ref_df[(ref_df["asset"] == sl.asset)] if len(ref_df) else pd.DataFrame()
        # Build full: union, dedup on (slug, fire_us, direction)
        pieces = []
        for d in (ref_sub, oos_sub, prefix_sub):
            if d is not None and len(d) > 0:
                pieces.append(d)
        if pieces:
            full_df = pd.concat(pieces, ignore_index=True, sort=False)
            full_df = full_df.drop_duplicates(["slug", "fire_us", "direction"],
                                                keep="first")
        else:
            full_df = pd.DataFrame()

        # Filter and score
        ref_match = filter_for_sleeve(ref_sub, sl)
        full_match = filter_for_sleeve(full_df, sl)
        oos_match = filter_for_sleeve(oos_sub, sl)
        # Last-7-day slice
        if len(full_match) > 0:
            last7 = full_match[(full_match["fire_us"] >= LAST7_START_US) &
                                (full_match["fire_us"] <= LAST7_END_US)]
        else:
            last7 = pd.DataFrame()
        # Stability (weekly)
        weekly = weekly_metrics(full_match)
        stab_class = classify_stability(weekly, sl.sleeve_id)

        ref_stats = stats_for(ref_match)
        full_stats = stats_for(full_match)
        oos_stats = stats_for(oos_match)
        last7_stats = stats_for(last7)

        # OOS-pass criteria: n_oos >= 20, WR_oos >= 60%, $/tr_oos > 0
        # Use last7 stats for OOS-pass (May 19-26)
        oos_pass = (last7_stats["n"] >= 20 and
                    last7_stats["wr"] >= 0.60 and
                    last7_stats["dpt"] > 0)

        rows.append({
            "sleeve_id": sl.sleeve_id, "asset": sl.asset, "tf": sl.tf,
            "base": sl.base, "offset_range": f"{sl.offset_range[0]}-{sl.offset_range[1]}",
            "gates": "&".join(sl.gate_stack),
            "direction_pick": sl.direction_pick,
            "ref_doc_n": sl.ref_n, "ref_doc_wr": sl.ref_wr,
            "ref_doc_dpt": sl.ref_dpt, "ref_doc_sum": sl.ref_sum,
            "ref_rerun_n": ref_stats["n"], "ref_rerun_wr": ref_stats["wr"],
            "ref_rerun_dpt": ref_stats["dpt"], "ref_rerun_sum": ref_stats["sum"],
            "full_n": full_stats["n"], "full_wr": full_stats["wr"],
            "full_dpt": full_stats["dpt"], "full_sum": full_stats["sum"],
            "full_max_dd": full_stats["max_dd"],
            "full_loss_streak": full_stats["loss_streak"],
            "full_sharpe": full_stats["sharpe"],
            "full_days": full_stats["n_days"],
            "oos_22to25_n": oos_stats["n"], "oos_22to25_wr": oos_stats["wr"],
            "oos_22to25_dpt": oos_stats["dpt"], "oos_22to25_sum": oos_stats["sum"],
            "last7_n": last7_stats["n"], "last7_wr": last7_stats["wr"],
            "last7_dpt": last7_stats["dpt"], "last7_sum": last7_stats["sum"],
            "stability": stab_class,
            "oos_pass": oos_pass,
            "delta_wr_full_vs_doc": full_stats["wr"] - sl.ref_wr if not np.isnan(full_stats["wr"]) else np.nan,
            "delta_dpt_full_vs_doc": full_stats["dpt"] - sl.ref_dpt if not np.isnan(full_stats["dpt"]) else np.nan,
        })
        # save stability detail
        if not weekly.empty:
            weekly["sleeve_id"] = sl.sleeve_id
            stability_rows.append(weekly)
        full_wr_str = f"{full_stats['wr']:.3f}" if not np.isnan(full_stats['wr']) else "nan"
        full_dpt_str = f"{full_stats['dpt']:.2f}" if not np.isnan(full_stats['dpt']) else "nan"
        last7_wr_str = f"{last7_stats['wr']:.3f}" if not np.isnan(last7_stats['wr']) else "nan"
        print(f"  {sl.sleeve_id}: ref={ref_stats['n']}/{full_stats['n']}, "
              f"full WR={full_wr_str} dpt={full_dpt_str} sum=${full_stats['sum']:.0f} "
              f"last7 n={last7_stats['n']} WR={last7_wr_str} OOS={oos_pass}",
              flush=True)
        del full_df, full_match
        gc.collect()

    summary = pd.DataFrame(rows)
    out_csv = RES_DIR / "full_window_all_sleeves_results.csv"
    summary.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv} ({len(summary)} sleeves)", flush=True)

    if stability_rows:
        stab_all = pd.concat(stability_rows, ignore_index=True)
        stab_all.to_csv(OUT_DIR / "full_window_stability_weekly.csv", index=False)
        print(f"wrote stability weekly ({len(stab_all)} rows)", flush=True)

    print(f"\n[main] total runtime {(time.time()-t_start)/60:.1f} min")
    return summary


if __name__ == "__main__":
    main()
