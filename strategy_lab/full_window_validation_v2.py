"""Full-window OOS validation v2 — memory-conservative.

Approach (memory-conscious — assume ≤ 11 GB available):
  Stage 1: Score top 15 sleeves on EXISTING joined files (REF, May 1 -> May 21).
           Persist per-fire row sets, NOT full tables.
  Stage 2: Stream-build OOS slice (May 21 20:00 -> May 25 19:10) one asset/tf
           at a time, immediately scoring + releasing.
  Stage 3: Concatenate ref + oos summary, compute deltas, write report.

Conventions:
  - Fee = LegacyConfig (2%-on-profit-only)
  - ws_s = slot_start - window_s
  - Outcome from chainlink
  - Spread 0.02 BTC/ETH, 0.025 SOL
"""
from __future__ import annotations

import gc
import math
import sys
import time
from dataclasses import dataclass
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
REF_END_US = int(pd.Timestamp("2026-05-21T20:01:00Z").value // 1000)
FULL_END_US = int(pd.Timestamp("2026-05-25T19:15:00Z").value // 1000)
OOS_START_US = REF_END_US
OOS_END_US = FULL_END_US

ASSETS = ("BTC", "ETH", "SOL")
SPREAD = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
NOTIONAL = 25.0


# ---------------------------------------------------------------------------
# Sleeve definitions
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


TOP_SLEEVES: list[Sleeve] = [
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
]

# Gates that the existing joined files already have (don't recompute, just use)
EXISTING_BASE_GATES = [
    "g_rf_with", "g_rf_fresh", "g_rf_aged", "g_rf_strong", "g_rf_in_band",
    "g_tr_stack_with", "g_tr_stack_full_with", "g_tr_pvsra_with",
    "g_tr_above_cloud", "g_tr_within_adr", "g_tr_in_active_session",
    "g_tr_above_pp", "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_ribbon_agrees", "g_ribbon_slope_with", "g_tight_ribbon",
    "g_bb_pos_with", "g_stoch_with", "g_mfi_with", "g_cci_with",
    "g_within_dev", "g_dev_extreme",
]


# ---------------------------------------------------------------------------
# Stage 1: Score on existing REF files
# ---------------------------------------------------------------------------

def add_sms_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Add g_sms_liq_reclaim_with and other SMS gates from joined SMS columns."""
    df = df.copy()
    if "direction" not in df.columns:
        return df
    is_up = (df["direction"] == "UP").astype(np.int8)
    is_dn = (df["direction"] == "DOWN").astype(np.int8)
    lu = df.get("liquidity_up", pd.Series(np.nan, index=df.index)).fillna(0)
    ld = df.get("liquidity_dn", pd.Series(np.nan, index=df.index)).fillna(0)
    df["g_sms_liq_reclaim_with"] = (
        (is_up & (ld == 1)) | (is_dn & (lu == 1))
    ).astype(np.int8)
    df["g_sms_no_liquidity_above"] = (
        (is_up & (lu == 0)) | (is_dn & (ld == 0))
    ).astype(np.int8)
    return df


def stats(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0, "wins": 0}
    sum_pnl = float(sub["pnl_legacy_usd"].sum())
    wins = int(sub["won"].sum())
    return {"n": n, "wr": wins / n, "dpt": sum_pnl / n, "sum": sum_pnl, "wins": wins}


def apply_sleeve_filter(df: pd.DataFrame, sl: Sleeve) -> pd.DataFrame:
    """Apply the sleeve filter to a fire-row DataFrame. Missing gates default to TRUE."""
    if df is None or len(df) == 0:
        return df
    m = (df["asset"] == sl.asset)
    lo, hi = sl.offset_range
    m &= (df["fire_offset_s"] >= lo) & (df["fire_offset_s"] <= hi)
    for g in sl.gate_stack:
        if g in df.columns:
            m &= (df[g] == 1)
    if sl.direction_pick != "BOTH":
        m &= (df["direction"] == sl.direction_pick)
    return df[m]


def score_on_ref(base_file: Path, sms_file: Path,
                  sleeves: list[Sleeve], base_name: str) -> dict:
    """Returns dict[sleeve_id] -> stats for REF window only."""
    print(f"\n[REF] loading {base_file.name}...", flush=True)
    df = pd.read_parquet(base_file)
    print(f"  loaded {df.shape}", flush=True)
    # Add SMS columns
    sms_cols_needed = ["liquidity_up", "liquidity_dn"]
    if sms_file.exists():
        sms = pd.read_parquet(sms_file, columns=["slug", "fire_us"] +
                              [c for c in sms_cols_needed if c in pd.read_parquet(sms_file).columns])
        merge_keys = ["slug", "fire_us"]
        if "definition" in df.columns and "definition" in sms.columns:
            sms_full = pd.read_parquet(sms_file)
            if "definition" in sms_full.columns:
                sms = sms_full[merge_keys + ["definition"] + sms_cols_needed].drop_duplicates(
                    merge_keys + ["definition"])
                df = df.merge(sms, on=merge_keys + ["definition"], how="left")
        else:
            sms = sms.drop_duplicates(merge_keys)
            df = df.merge(sms, on=merge_keys, how="left")
        # add sms gates
        df = add_sms_gates(df)
    # Score each sleeve filtered to this base
    out = {}
    for sl in sleeves:
        if sl.base != base_name:
            continue
        sub = apply_sleeve_filter(df, sl)
        out[sl.sleeve_id] = stats(sub)
    return out


def score_ref_all(sleeves: list[Sleeve]) -> dict[str, dict]:
    """Score every sleeve on existing REF data, per-base."""
    res = {}
    for base, base_file, sms_file in [
        ("s6", RES_DIR / "s6_joined_all.parquet", RES_DIR / "s6_with_sms.parquet"),
        ("s15", RES_DIR / "s15_joined_all.parquet", RES_DIR / "s15_with_sms.parquet"),
        ("v15m", RES_DIR / "v15m_joined_all.parquet", RES_DIR / "v15m_with_sms.parquet"),
    ]:
        gc.collect()
        res.update(score_on_ref(base_file, sms_file, sleeves, base))
    return res


# ---------------------------------------------------------------------------
# Stage 2: OOS slice with on-the-fly features
# ---------------------------------------------------------------------------

def _asof_strict(end_us: np.ndarray, prices: np.ndarray, target_us: int) -> float:
    pos = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if pos < 0:
        return float("nan")
    return float(prices[pos])


def load_1s_asset(asset: str, min_us: int, max_us: int) -> pd.DataFrame:
    """Load 1s OHLCV for ONE asset within window. Memory-conservative."""
    sym_map = {
        "BTC": "BINANCE_SPOT_BTC_USDT",
        "ETH": "BINANCE_SPOT_ETH_USDT",
        "SOL": "BINANCE_SPOT_SOL_USDT",
    }
    sym = sym_map[asset]
    # Use pyarrow dataset with filter to avoid full load
    import pyarrow.dataset as ds
    import pyarrow.compute as pc
    dataset = ds.dataset(str(ROOT / "data" / "v4" / "canonical" / "klines_1s.parquet"))
    filt = ((pc.field("symbol_id") == sym) &
            (pc.field("time_period_start_us") >= min_us) &
            (pc.field("time_period_start_us") <= max_us))
    cols = ["time_period_start_us", "price_open", "price_high", "price_low",
            "price_close", "volume_traded", "taker_buy_base"]
    tbl = dataset.to_table(columns=cols, filter=filt)
    df = tbl.to_pandas()
    df = df.rename(columns={
        "time_period_start_us": "ts_us",
        "price_open": "open", "price_high": "high",
        "price_low": "low", "price_close": "close",
        "volume_traded": "volume",
    })
    df = df.drop_duplicates("ts_us").sort_values("ts_us").reset_index(drop=True)
    return df


def compute_features_inline(g: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Compute RF + ribbon + TR feature columns for ONE asset's 1s panel."""
    n = len(g)
    if n == 0:
        return g
    close = g["close"].astype(np.float64)
    high = g["high"].astype(np.float64)
    low = g["low"].astype(np.float64)
    volume = g["volume"].astype(np.float64).fillna(0.0)

    # --- Range Filter ---
    n_p, sn_p, qty = 14, 27, 2.618
    alpha_n = 2.0 / (n_p + 1.0)
    alpha_sn = 2.0 / (sn_p + 1.0)
    closes = close.values
    rf_close = np.empty(n, dtype=np.float64)
    rf_r = np.empty(n, dtype=np.float64)
    rf_dir = np.zeros(n, dtype=np.int8)
    ac = 0.0
    rng_smooth = 0.0
    rfilt = closes[0]
    rfilt_prev = closes[0]
    dir_prev = 0
    for t in range(n):
        c = closes[t]
        d = 0.0 if t == 0 else abs(c - closes[t - 1])
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
        rf_dir[t] = d_now
        rfilt_prev = rfilt
        dir_prev = d_now
    flips = np.r_[True, rf_dir[1:] != rf_dir[:-1]]
    age = np.empty(n, dtype=np.int32)
    a = -1
    for i in range(n):
        if flips[i]:
            a = 0
        else:
            a += 1
        age[i] = a
    rf_hi = rf_close + rf_r
    rf_lo = rf_close - rf_r
    denom = np.where((rf_hi - rf_lo) == 0, np.nan, (rf_hi - rf_lo))
    rf_band_pos = (closes - rf_lo) / denom

    # --- Ribbon ---
    EMA_PERIODS = list(range(5, 105, 5))
    ema_arrs = {}
    for p in EMA_PERIODS:
        ema_arrs[p] = close.ewm(span=p, adjust=False).mean().values
    ema_5 = ema_arrs[5]
    ema_100 = ema_arrs[100]
    ribbon_lead_slope_bps = pd.Series(ema_5).pct_change(5).values * 1e4
    ribbon_lead_vs_ref_bps = (ema_5 - ema_100) / ema_100 * 1e4
    stack = np.column_stack([ema_arrs[p] for p in EMA_PERIODS])
    align_up = (stack[:, :-1] > stack[:, 1:]).sum(axis=1)
    ribbon_alignment_pct = align_up / (len(EMA_PERIODS) - 1) * 100.0
    ribbon_compression_bps = stack.std(axis=1) / np.maximum(stack.mean(axis=1), 1e-12) * 1e4
    color = np.zeros(n, dtype=np.int8)
    is_up = ema_5 > ema_100
    slope_pos = ribbon_lead_slope_bps > 0.5
    slope_neg = ribbon_lead_slope_bps < -0.5
    color[is_up & slope_pos] = 1
    color[is_up & ~slope_pos] = 4
    color[~is_up & slope_neg] = 2
    color[~is_up & ~slope_neg] = 3

    # --- Stoch 60s ---
    w60 = 14 * 60
    ll = low.rolling(w60, min_periods=w60).min()
    hh = high.rolling(w60, min_periods=w60).max()
    denom2 = (hh - ll).replace(0, np.nan)
    stoch_k_60s = (100.0 * (close - ll) / denom2).rolling(3 * 60, min_periods=1).mean().values
    stoch_d_60s = pd.Series(stoch_k_60s).rolling(3 * 60, min_periods=1).mean().values

    # --- BB 60s ---
    bb_mid = close.rolling(60, min_periods=60).mean()
    bb_std = close.rolling(60, min_periods=60).std()
    bb_up = bb_mid + 2 * bb_std
    bb_lo = bb_mid - 2 * bb_std
    bb_denom = (bb_up - bb_lo).replace(0, np.nan)
    bb_pos_60s = ((close - bb_lo) / bb_denom).values
    bb_width_60s = ((bb_up - bb_lo) / bb_mid * 1e4).values

    # --- MFI 60s ---
    tp = (high + low + close) / 3.0
    tp_diff = tp.diff()
    mf = tp * volume
    pos_mf_60 = pd.Series(np.where(tp_diff > 0, mf, 0.0)).rolling(60, min_periods=60).sum().values
    neg_mf_60 = pd.Series(np.where(tp_diff < 0, mf, 0.0)).rolling(60, min_periods=60).sum().values
    ratio_60 = pos_mf_60 / np.maximum(neg_mf_60, 1e-12)
    mfi_60s = 100.0 - 100.0 / (1.0 + ratio_60)

    # --- CCI 60s ---
    sma60 = tp.rolling(60, min_periods=60).mean()
    md = (tp - sma60).abs().rolling(60, min_periods=60).mean()
    cci_60s = ((tp - sma60) / (0.015 * md.replace(0, np.nan))).values

    # --- TR EMAs (50/200/800) and pivots ---
    ema_50 = close.ewm(span=50, adjust=False).mean().values
    ema_200 = close.ewm(span=200, adjust=False).mean().values
    ema_800 = close.ewm(span=800, adjust=False).mean().values
    tr_above_ema50 = (closes > ema_50).astype(np.int8)
    tr_above_ema200 = (closes > ema_200).astype(np.int8)
    tr_above_ema800 = (closes > ema_800).astype(np.int8)
    tr_above_cloud = (closes > np.maximum(ema_50, ema_200)).astype(np.int8)
    # tr_ema_stack_bull/bear
    stack_bull = ((ema_arrs[5] > ema_arrs[15]) & (ema_arrs[15] > ema_50) &
                  (ema_50 > ema_200) & (ema_200 > ema_800)).astype(np.int8)
    stack_bear = ((ema_arrs[5] < ema_arrs[15]) & (ema_arrs[15] < ema_50) &
                  (ema_50 < ema_200) & (ema_200 < ema_800)).astype(np.int8)

    # Pivot Points from yesterday's day H/L/C
    ts = g["ts_us"].values.astype(np.int64)
    day_key = ts // (86400 * 1_000_000)
    df_day = pd.DataFrame({"day_key": day_key, "high": high.values, "low": low.values,
                           "close": closes, "open": g["open"].values})
    day_agg = df_day.groupby("day_key").agg(
        dh=("high", "max"), dl=("low", "min"),
        dc=("close", "last"), do=("open", "first"),
    ).reset_index()
    for c in ("dh", "dl", "dc", "do"):
        day_agg[f"p{c}"] = day_agg[c].shift(1)
    PP = (day_agg["pdh"] + day_agg["pdl"] + day_agg["pdc"]) / 3.0
    R1 = 2 * PP - day_agg["pdl"]
    S1 = 2 * PP - day_agg["pdh"]
    R2 = PP + (day_agg["pdh"] - day_agg["pdl"])
    S2 = PP - (day_agg["pdh"] - day_agg["pdl"])
    day_agg["PP"] = PP
    day_agg["R1"] = R1; day_agg["R2"] = R2
    day_agg["S1"] = S1; day_agg["S2"] = S2
    day_agg["adr_high"] = day_agg["pdo"] + (day_agg["pdh"] - day_agg["pdl"]) / 2
    day_agg["adr_low"] = day_agg["pdo"] - (day_agg["pdh"] - day_agg["pdl"]) / 2
    g = g.assign(day_key=day_key)
    g = g.merge(day_agg[["day_key", "PP", "R1", "R2", "S1", "S2", "adr_high", "adr_low"]],
                on="day_key", how="left")
    tr_above_pp = (closes > g["PP"].values).astype(np.int8)
    tr_within_adr = ((closes >= g["adr_low"].values) &
                     (closes <= g["adr_high"].values)).astype(np.int8)

    # Session flags
    hod = (ts % (86400 * 1_000_000)) // (3600 * 1_000_000)
    in_london = ((hod >= 7) & (hod < 15)).astype(np.int8)
    in_ny = ((hod >= 13) & (hod < 21)).astype(np.int8)
    in_tokyo = ((hod >= 23) | (hod < 7)).astype(np.int8)
    active_count = in_london + in_ny + in_tokyo

    # Assemble result
    g["rf_close"] = rf_close
    g["rf_dir"] = rf_dir
    g["rf_dir_age"] = age
    g["rf_band_pos"] = rf_band_pos
    g["ribbon_color"] = color
    g["ribbon_lead_slope_bps"] = ribbon_lead_slope_bps
    g["ribbon_compression_bps"] = ribbon_compression_bps
    g["stoch_k_60s"] = stoch_k_60s
    g["bb_pos_60s"] = bb_pos_60s
    g["mfi_60s"] = mfi_60s
    g["cci_60s"] = cci_60s
    g["tr_above_ema50"] = tr_above_ema50
    g["tr_above_ema200"] = tr_above_ema200
    g["tr_above_ema800"] = tr_above_ema800
    g["tr_above_cloud"] = tr_above_cloud
    g["tr_above_pp"] = tr_above_pp
    g["tr_within_adr"] = tr_within_adr
    g["tr_in_london"] = in_london
    g["tr_in_ny"] = in_ny
    g["tr_in_tokyo"] = in_tokyo
    g["tr_active_session_count"] = active_count
    g["tr_ema_stack_bull"] = stack_bull
    g["tr_ema_stack_bear"] = stack_bear
    return g


def compute_sms_5m_for_panel(g_1s: pd.DataFrame) -> pd.DataFrame:
    """Compute SMS-style 5m bar features (liquidity_up/dn) for one asset's 1s panel."""
    g = g_1s.copy()
    g["dt"] = pd.to_datetime(g["ts_us"], unit="us", utc=True)
    g = g.set_index("dt")
    bar = g.resample("5min").agg({
        "high": "max", "low": "min", "close": "last",
    }).dropna()
    if bar.empty:
        return pd.DataFrame(columns=["bar_ts_us", "liquidity_up", "liquidity_dn"])
    bar["last_high"] = bar["high"].rolling(20).max().shift(1)
    bar["last_low"] = bar["low"].rolling(20).min().shift(1)
    bar["liquidity_up"] = (bar["high"] >= bar["last_high"]).fillna(False).astype(np.int8)
    bar["liquidity_dn"] = (bar["low"] <= bar["last_low"]).fillna(False).astype(np.int8)
    bar["bar_ts_us"] = (bar.index.view("int64") // 1000).astype("int64")
    return bar.reset_index(drop=True)[["bar_ts_us", "liquidity_up", "liquidity_dn"]]


def asof_join_features(fires: pd.DataFrame, panel_1s: pd.DataFrame,
                       feat_cols: list) -> pd.DataFrame:
    """Causal asof join of feature columns from 1s panel at fire_us-1us."""
    if len(fires) == 0:
        return fires
    fires = fires.copy()
    fires["lookup_us"] = fires["fire_us"].astype("int64") - 1_000_000
    fires = fires.sort_values("lookup_us").reset_index(drop=True)
    p = panel_1s[["ts_us"] + feat_cols].copy()
    p["lookup_us"] = p["ts_us"]
    p = p.sort_values("lookup_us").reset_index(drop=True)
    m = pd.merge_asof(fires, p[["lookup_us"] + feat_cols],
                      on="lookup_us", direction="backward",
                      tolerance=5_000_000)
    return m


def asof_join_sms(fires: pd.DataFrame, sms_5m: pd.DataFrame, tf_min: int) -> pd.DataFrame:
    if len(fires) == 0 or len(sms_5m) == 0:
        return fires
    fires = fires.copy()
    bar_us = tf_min * 60 * 1_000_000
    fires["sms_lookup"] = fires["fire_us"].astype("int64") - bar_us
    fires = fires.sort_values("sms_lookup").reset_index(drop=True)
    s = sms_5m.sort_values("bar_ts_us").reset_index(drop=True)
    m = pd.merge_asof(fires, s, left_on="sms_lookup", right_on="bar_ts_us",
                      direction="backward", tolerance=2 * bar_us)
    return m


def compute_oos_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Compute binary g_* gates on a fire DataFrame (OOS slice) given features."""
    df = df.copy()
    is_up = (df["direction"] == "UP").astype(np.int8)
    is_dn = (df["direction"] == "DOWN").astype(np.int8)
    # RF gates
    if "rf_dir" in df.columns:
        df["g_rf_with"] = ((is_up & (df["rf_dir"] == 1)) |
                           (is_dn & (df["rf_dir"] == -1))).fillna(0).astype(np.int8)
        df["g_rf_fresh"] = (df["rf_dir_age"].fillna(999) <= 60).astype(np.int8)
        df["g_rf_aged"] = (df["rf_dir_age"].fillna(0) >= 60).astype(np.int8)
        df["g_rf_strong"] = ((is_up & (df["rf_band_pos"].fillna(0.5) > 0.7)) |
                              (is_dn & (df["rf_band_pos"].fillna(0.5) < 0.3))).astype(np.int8)
        df["g_rf_in_band"] = ((df["rf_band_pos"].fillna(0.5) >= 0.2) &
                                (df["rf_band_pos"].fillna(0.5) <= 0.8)).astype(np.int8)
    # TR gates
    sb = pd.to_numeric(df.get("tr_ema_stack_bull", 0), errors="coerce").fillna(0)
    sx = pd.to_numeric(df.get("tr_ema_stack_bear", 0), errors="coerce").fillna(0)
    df["g_tr_stack_with"] = ((is_up & (sb == 1)) | (is_dn & (sx == 1))).astype(np.int8)
    df["g_tr_stack_full_with"] = df["g_tr_stack_with"]
    def _safe_int8(col, default=0):
        return pd.to_numeric(col, errors="coerce").fillna(default).astype(np.int8)
    if "tr_above_cloud" in df.columns:
        v = _safe_int8(df["tr_above_cloud"], 0)
        df["g_tr_above_cloud"] = ((is_up & (v == 1)) | (is_dn & (v == 0))).astype(np.int8)
    df["g_tr_within_adr"] = _safe_int8(df.get("tr_within_adr", 1), 1)
    df["g_tr_in_active_session"] = (_safe_int8(df.get("tr_active_session_count", 0), 0) >= 1).astype(np.int8)
    if "tr_above_pp" in df.columns:
        v = _safe_int8(df["tr_above_pp"], 0)
        df["g_tr_above_pp"] = ((is_up & (v == 1)) | (is_dn & (v == 0))).astype(np.int8)
    if "tr_above_ema50" in df.columns:
        v = _safe_int8(df["tr_above_ema50"], 0)
        df["g_tr_above_ema50"] = ((is_up & (v == 1)) | (is_dn & (v == 0))).astype(np.int8)
    if "tr_above_ema200" in df.columns:
        v = _safe_int8(df["tr_above_ema200"], 0)
        df["g_tr_above_ema200"] = ((is_up & (v == 1)) | (is_dn & (v == 0))).astype(np.int8)
    if "tr_above_ema800" in df.columns:
        v = _safe_int8(df["tr_above_ema800"], 0)
        df["g_tr_above_ema800"] = ((is_up & (v == 1)) | (is_dn & (v == 0))).astype(np.int8)
    # Ribbon
    if "ribbon_color" in df.columns:
        df["g_ribbon_agrees"] = ((is_up & df["ribbon_color"].isin([1, 4])) |
                                  (is_dn & df["ribbon_color"].isin([2, 3]))).astype(np.int8)
        df["g_ribbon_slope_with"] = ((is_up & (df.get("ribbon_lead_slope_bps", 0) > 0)) |
                                       (is_dn & (df.get("ribbon_lead_slope_bps", 0) < 0))).astype(np.int8)
    if "ribbon_compression_bps" in df.columns:
        df["g_tight_ribbon"] = (df["ribbon_compression_bps"].fillna(999) < 2.0).astype(np.int8)
    # BB/stoch/mfi/cci
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
    # SMS
    if "liquidity_up" in df.columns:
        df["g_sms_liq_reclaim_with"] = (
            (is_up & (df["liquidity_dn"].fillna(0) == 1)) |
            (is_dn & (df["liquidity_up"].fillna(0) == 1))
        ).astype(np.int8)
        df["g_sms_no_liquidity_above"] = (
            (is_up & (df["liquidity_up"].fillna(0) == 0)) |
            (is_dn & (df["liquidity_dn"].fillna(0) == 0))
        ).astype(np.int8)
    df["g_within_dev"] = 1
    df["g_dev_extreme"] = 0
    return df


def build_oos_one_asset_tf(asset: str, tf: str, klines_1m: dict) -> pd.DataFrame:
    """Build the OOS fire DataFrame for ONE asset/tf. Includes ALL gate columns.

    AUDIT-FIX 2026-05-26 (Bug #1): use canonical 9-offset 5m grid {30, 60, ..., 270}
    matching s15_joined_all.parquet (base ref panel). Previously used 20 offsets
    (every 15s), causing ~1.89× fire inflation on lockbox vs train/val.
    For 15m: canonical 8-offset {60, 120, 240, 360, 480, 600, 720, 840} matching
    v15m_joined_all.parquet.
    """
    window_s = {"5m": 300, "15m": 900}[tf]
    offsets_5m = [30, 60, 90, 120, 150, 180, 210, 240, 270]  # 9-offset canonical grid
    offsets_15m = [60, 120, 240, 360, 480, 600, 720, 840]    # 8-offset canonical grid
    offsets = offsets_5m if tf == "5m" else offsets_15m

    print(f"\n[OOS] {asset} {tf}", flush=True)
    res = load_resolutions(assets=[asset], timeframes=[tf])
    res = res[res["outcome"].isin(("Up", "Down"))].copy()
    res = res[(res["slot_start_us"] >= OOS_START_US) &
              (res["slot_start_us"] <= OOS_END_US)].copy()
    if res.empty:
        return pd.DataFrame()
    res["ws_s"] = (res["slot_start_us"] // 1_000_000) - window_s
    print(f"  resolutions: {len(res):,}", flush=True)

    # Load 1s panel (one asset) with warmup buffer
    buf_us = 3 * 3600 * 1_000_000
    panel_1s = load_1s_asset(asset, OOS_START_US - buf_us, OOS_END_US + 60_000_000)
    print(f"  1s panel: {len(panel_1s):,}", flush=True)
    panel_1s = compute_features_inline(panel_1s, asset)
    sms_5m = compute_sms_5m_for_panel(panel_1s) if tf == "5m" else pd.DataFrame()

    # Stream L25 once
    cfg = LegacyConfig()
    spread = SPREAD[asset]
    end_us_1m, close_1m = klines_1m[asset]
    print(f"  streaming L25 for {len(res):,} slugs...", flush=True)
    t0 = time.time()
    books = load_orderbook_l25_streaming(
        asset.lower(), slugs=set(res["slug"].tolist()),
        subsample_1hz=True,
        min_ts_us=int(res["slot_start_us"].min()) - 3600 * 1_000_000,
        max_ts_us=int(res["slot_end_us"].max()) + 3600 * 1_000_000,
    )
    print(f"  L25 streamed in {time.time()-t0:.1f}s, {len(books)} pairs", flush=True)

    rows = []
    for r in res.itertuples(index=False):
        slug = r.slug
        ss = int(r.slot_start_us)
        se = int(r.slot_end_us)
        ws_s = int(r.ws_s)
        outcome = str(r.outcome)
        strike = _asof_strict(end_us_1m, close_1m, ss)
        settle = _asof_strict(end_us_1m, close_1m, se)
        for off in offsets:
            fire_us = ss + off * 1_000_000
            for direction, oc_key in (("UP", "Up"), ("DOWN", "Down")):
                fill = fill_at_book(books, slug, oc_key, fire_us, cfg=cfg,
                                    spread_filter=spread, notional_usd=NOTIONAL)
                if fill is None:
                    continue
                won = (outcome == oc_key)
                pnl = hold_pnl(fill, won=won, cfg=cfg)
                rows.append({
                    "asset": asset, "slug": slug, "tf": tf,
                    "slot_start_us": ss, "slot_end_us": se, "ws_s": ws_s,
                    "fire_offset_s": int(off), "fire_us": fire_us,
                    "strike_price": strike, "settle_price": settle,
                    "outcome": outcome, "direction": direction,
                    "pnl_legacy_usd": float(pnl), "won": int(won),
                    "entry_vwap": fill["vwap"],
                })
    del books
    gc.collect()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    print(f"  fires: {len(df):,}", flush=True)

    # Join features at fire_us
    feat_cols = ["rf_close", "rf_dir", "rf_dir_age", "rf_band_pos",
                 "ribbon_color", "ribbon_lead_slope_bps", "ribbon_compression_bps",
                 "stoch_k_60s", "bb_pos_60s", "mfi_60s", "cci_60s",
                 "tr_above_ema50", "tr_above_ema200", "tr_above_ema800",
                 "tr_above_cloud", "tr_above_pp", "tr_within_adr",
                 "tr_in_london", "tr_in_ny", "tr_in_tokyo", "tr_active_session_count",
                 "tr_ema_stack_bull", "tr_ema_stack_bear"]
    feat_cols = [c for c in feat_cols if c in panel_1s.columns]
    df = asof_join_features(df, panel_1s, feat_cols)
    # SMS join for 5m
    if tf == "5m" and not sms_5m.empty:
        df = asof_join_sms(df, sms_5m, tf_min=5)
    # Compute gates
    df = compute_oos_gates(df)
    print(f"  OOS df with gates: {df.shape}", flush=True)
    del panel_1s
    gc.collect()
    return df


def score_oos_for_sleeves(sleeves: list[Sleeve], klines_1m: dict) -> dict[str, dict]:
    """Build OOS slice + score every sleeve."""
    # Group sleeves by (asset, tf) — build that base ONCE
    by_key: dict[tuple, list[Sleeve]] = {}
    for sl in sleeves:
        by_key.setdefault((sl.asset, sl.tf), []).append(sl)
    out = {}
    for (asset, tf), sleeves_here in by_key.items():
        df = build_oos_one_asset_tf(asset, tf, klines_1m)
        if df is None or df.empty:
            for sl in sleeves_here:
                out[sl.sleeve_id] = {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0}
            continue
        # Persist OOS df for stability analysis
        df.to_parquet(OUT_DIR / f"oos_fires_{asset}_{tf}.parquet", index=False, compression="zstd")
        for sl in sleeves_here:
            sub = apply_sleeve_filter(df, sl)
            out[sl.sleeve_id] = stats(sub)
        del df
        gc.collect()
    return out


# ---------------------------------------------------------------------------
# Stage 3: stability + report
# ---------------------------------------------------------------------------

def compute_stability_per_sleeve(sleeves: list[Sleeve]) -> pd.DataFrame:
    """For each sleeve, compute weekly stats over REF + OOS combined."""
    rows = []
    # Load REF dfs once (one base at a time)
    for base, base_file, sms_file in [
        ("s6", RES_DIR / "s6_joined_all.parquet", RES_DIR / "s6_with_sms.parquet"),
        ("s15", RES_DIR / "s15_joined_all.parquet", RES_DIR / "s15_with_sms.parquet"),
        ("v15m", RES_DIR / "v15m_joined_all.parquet", RES_DIR / "v15m_with_sms.parquet"),
    ]:
        df = pd.read_parquet(base_file)
        if sms_file.exists():
            full = pd.read_parquet(sms_file)
            sms_cols = [c for c in ["liquidity_up", "liquidity_dn"] if c in full.columns]
            if sms_cols:
                if "definition" in df.columns and "definition" in full.columns:
                    sms = full[["slug", "fire_us", "definition"] + sms_cols].drop_duplicates(
                        ["slug", "fire_us", "definition"])
                    df = df.merge(sms, on=["slug", "fire_us", "definition"], how="left")
                else:
                    sms = full[["slug", "fire_us"] + sms_cols].drop_duplicates(["slug", "fire_us"])
                    df = df.merge(sms, on=["slug", "fire_us"], how="left")
                df = add_sms_gates(df)

        for sl in sleeves:
            if sl.base != base:
                continue
            # Also pull OOS for this asset/tf
            oos_path = OUT_DIR / f"oos_fires_{sl.asset}_{sl.tf}.parquet"
            if oos_path.exists():
                oos = pd.read_parquet(oos_path)
                comb = pd.concat([df[df.asset == sl.asset], oos], ignore_index=True)
                comb = comb.drop_duplicates(["slug", "fire_us", "direction"], keep="first")
            else:
                comb = df[df.asset == sl.asset]
            sub = apply_sleeve_filter(comb, sl)
            if len(sub) == 0:
                continue
            sub = sub.copy()
            sub["dt"] = pd.to_datetime(sub["fire_us"], unit="us", utc=True)
            # group by week of year
            sub["week_label"] = sub["dt"].dt.strftime("%Y-W%V")
            grp = sub.groupby("week_label").agg(
                n=("won", "size"), wr=("won", "mean"),
                dpt=("pnl_legacy_usd", "mean"),
                sum=("pnl_legacy_usd", "sum"),
                first=("dt", "min"),
            ).reset_index()
            grp["sleeve_id"] = sl.sleeve_id
            rows.append(grp)
        del df
        gc.collect()
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def main():
    t_start = time.time()

    print("=" * 70)
    print("Stage 1: score on REF data (existing joined files)")
    print("=" * 70)
    ref_scores = score_ref_all(TOP_SLEEVES)
    gc.collect()

    print("\n" + "=" * 70)
    print("Stage 2: build OOS slice + score")
    print("=" * 70)
    # Load 1m klines for strike/settle
    klines_1m = {}
    for a in ASSETS:
        e, c = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        klines_1m[a] = (e.astype("int64"), c.astype("float64"))
    oos_scores = score_oos_for_sleeves(TOP_SLEEVES, klines_1m)
    gc.collect()

    # Assemble per-sleeve summary
    rows = []
    for sl in TOP_SLEEVES:
        ref = ref_scores.get(sl.sleeve_id, {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0})
        oos = oos_scores.get(sl.sleeve_id, {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0})
        full_n = ref["n"] + oos["n"]
        full_sum = ref["sum"] + oos["sum"]
        full_wins = ref.get("wins", 0) + oos.get("wins", 0)
        full_wr = (full_wins / full_n) if full_n > 0 else np.nan
        full_dpt = (full_sum / full_n) if full_n > 0 else np.nan
        rows.append({
            "sleeve_id": sl.sleeve_id,
            "asset": sl.asset, "tf": sl.tf, "base": sl.base,
            "offset_range": f"{sl.offset_range[0]}-{sl.offset_range[1]}",
            "gate_stack": "&".join(sl.gate_stack),
            "direction_pick": sl.direction_pick,
            "ref_n_doc": sl.ref_n, "ref_wr_doc": sl.ref_wr,
            "ref_dpt_doc": sl.ref_dpt, "ref_sum_doc": sl.ref_sum,
            "ref_n_rerun": ref["n"], "ref_wr_rerun": ref["wr"],
            "ref_dpt_rerun": ref["dpt"], "ref_sum_rerun": ref["sum"],
            "oos_n": oos["n"], "oos_wr": oos["wr"],
            "oos_dpt": oos["dpt"], "oos_sum": oos["sum"],
            "full_n": full_n, "full_wr": full_wr,
            "full_dpt": full_dpt, "full_sum": full_sum,
            "wr_oos_minus_ref": (oos["wr"] - ref["wr"]) if (not np.isnan(oos["wr"]) and not np.isnan(ref["wr"])) else np.nan,
            "dpt_oos_minus_ref": (oos["dpt"] - ref["dpt"]) if (not np.isnan(oos["dpt"]) and not np.isnan(ref["dpt"])) else np.nan,
        })
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_DIR / "sleeve_full_window_validation.csv", index=False)
    print(f"\nwrote {OUT_DIR}/sleeve_full_window_validation.csv")

    # Stability
    print("\n" + "=" * 70)
    print("Stage 3: weekly stability")
    print("=" * 70)
    stab = compute_stability_per_sleeve(TOP_SLEEVES)
    stab.to_csv(OUT_DIR / "sleeve_weekly_stability.csv", index=False)
    print(f"wrote {OUT_DIR}/sleeve_weekly_stability.csv ({len(stab)} rows)")

    print(f"\nTotal runtime: {(time.time()-t_start)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
