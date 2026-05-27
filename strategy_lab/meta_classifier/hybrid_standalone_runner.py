"""HYBRID_STANDALONE_2026_05_25 — run all 12 hybrid rules on the full 5m+15m fire
universes and emit per-cell deployable sleeves.

Conventions (per CLAUDE.md):
  - Fee = LegacyConfig (2%-on-profit-only) — matches production behavior.
  - Causal: features come from 1s bars where ts_us <= fire_us - 1_000_000.
  - Outcome = chainlink (canonical `outcome` col).
  - Window: Apr 30 → May 22 (the fire universe already enforces this).
  - Direction is SELECTED by the rule, not predetermined.

The 12 rules are vectorized in `apply_rule_vectorized` for speed; ~240k rows × 12
rules runs in <60s.

Outputs:
  data/v4/canonical/_results/hybrid_standalone_results.csv
  data/v4/canonical/_results/hybrid_standalone_per_fire_top.parquet
  data/v4/canonical/_results/hybrid_standalone_walkforward.csv
  data/v4/canonical/_results/hybrid_standalone_correlation.csv
"""
from __future__ import annotations

import sys
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON_RES = ROOT / "data" / "v4" / "canonical" / "_results"

FEAT_5M = CANON_RES / "hybrid_features_5m.parquet"
FEAT_15M = CANON_RES / "hybrid_features_15m.parquet"

OUT_RESULTS = CANON_RES / "hybrid_standalone_results.csv"
OUT_DEPLOY = CANON_RES / "hybrid_standalone_deployable.csv"
OUT_WALKF = CANON_RES / "hybrid_standalone_walkforward.csv"
OUT_CORR = CANON_RES / "hybrid_standalone_correlation.csv"

LEGACY_FEE_PCT = 0.02
ASSETS = ("BTC", "ETH", "SOL")
OFFSETS_5M = (30, 60, 90, 120, 150, 180, 210, 240, 270, 300)
OFFSETS_15M = (60, 120, 240, 360, 480, 600, 720, 840)


# ---------------------------------------------------------------------------
# PnL formula — legacy 2%-on-profit-only
# ---------------------------------------------------------------------------

def compute_pnl(direction_arr: np.ndarray, df: pd.DataFrame) -> np.ndarray:
    """Vectorized PnL: direction_arr is +1 (UP), -1 (DOWN), 0 (no fire).
    For UP: pnl = won ? shares*(1-vwap)*0.98 : -shares*vwap
    For DOWN: same with dn_vwap/dn_shares.
    Returns pnl array (NaN where direction==0 or fill_ok=False).
    """
    pnl = np.full(len(df), np.nan, dtype="float64")
    outcome = df["outcome"].astype(str).str.title().values  # 'Up' or 'Down'
    up_vwap = df["up_vwap"].astype("float64").values
    up_shares = df["up_shares"].astype("float64").values
    up_fill_ok = df["up_fill_ok"].astype(bool).values
    dn_vwap = df["dn_vwap"].astype("float64").values
    dn_shares = df["dn_shares"].astype("float64").values
    dn_fill_ok = df["dn_fill_ok"].astype(bool).values

    # UP direction
    is_up = (direction_arr == +1) & up_fill_ok
    won_up = is_up & (outcome == "Up")
    lost_up = is_up & (outcome != "Up")
    pnl[won_up] = up_shares[won_up] * (1.0 - up_vwap[won_up]) * (1.0 - LEGACY_FEE_PCT)
    pnl[lost_up] = -up_shares[lost_up] * up_vwap[lost_up]

    # DOWN direction
    is_dn = (direction_arr == -1) & dn_fill_ok
    won_dn = is_dn & (outcome == "Down")
    lost_dn = is_dn & (outcome != "Down")
    pnl[won_dn] = dn_shares[won_dn] * (1.0 - dn_vwap[won_dn]) * (1.0 - LEGACY_FEE_PCT)
    pnl[lost_dn] = -dn_shares[lost_dn] * dn_vwap[lost_dn]

    return pnl


# ---------------------------------------------------------------------------
# Rule definitions — return direction array (+1, -1, 0)
# ---------------------------------------------------------------------------

def _safe(df: pd.DataFrame, col: str, default=np.nan) -> np.ndarray:
    if col not in df.columns:
        return np.full(len(df), default, dtype="float64")
    v = df[col].values
    return v


def _bool(df: pd.DataFrame, col: str) -> np.ndarray:
    if col not in df.columns:
        return np.zeros(len(df), dtype=bool)
    v = df[col]
    return v.fillna(False).astype(bool).values


def rule_v1(df: pd.DataFrame) -> np.ndarray:
    """V1 — Pure RF trigger."""
    close = _safe(df, "rf_binance_close_1s")
    rf_close = _safe(df, "rf_close")
    rf_dir = _safe(df, "rf_dir")
    out = np.zeros(len(df), dtype="int8")
    up_mask = (rf_dir == +1) & (close > rf_close) & np.isfinite(close) & np.isfinite(rf_close)
    dn_mask = (rf_dir == -1) & (close < rf_close) & np.isfinite(close) & np.isfinite(rf_close)
    out[up_mask] = +1
    out[dn_mask] = -1
    return out


def rule_v2(df: pd.DataFrame) -> np.ndarray:
    """V2 — V1 + PVSRA color agree."""
    base = rule_v1(df)
    pv = _safe(df, "tr_pvsra")
    out = np.zeros(len(df), dtype="int8")
    out[(base == +1) & (pv > 0)] = +1
    out[(base == -1) & (pv < 0)] = -1
    return out


def rule_v3(df: pd.DataFrame) -> np.ndarray:
    """V3 — V1 + BB pos."""
    base = rule_v1(df)
    bb = _safe(df, "bb_pos_60s")
    out = np.zeros(len(df), dtype="int8")
    out[(base == +1) & (bb > 0.5)] = +1
    out[(base == -1) & (bb < 0.5)] = -1
    return out


def rule_v4(df: pd.DataFrame) -> np.ndarray:
    """V4 — V1 + EMA stack."""
    base = rule_v1(df)
    es = _safe(df, "tr_ema_stack_score")
    out = np.zeros(len(df), dtype="int8")
    out[(base == +1) & (es == +2)] = +1
    out[(base == -1) & (es == -2)] = -1
    return out


def rule_v5(df: pd.DataFrame) -> np.ndarray:
    """V5 — V2 + session active (london | ny | eu_brinks | us_brinks)."""
    base = rule_v2(df)
    s = _bool(df, "tr_in_london") | _bool(df, "tr_in_ny") | \
        _bool(df, "tr_eu_brinks") | _bool(df, "tr_us_brinks")
    out = np.zeros(len(df), dtype="int8")
    out[(base != 0) & s] = base[(base != 0) & s]
    return out


def rule_v6(df: pd.DataFrame) -> np.ndarray:
    """V6 — V2 + pivot confluence (within 20bps of any pivot/M-level)."""
    base = rule_v2(df)
    close = _safe(df, "rf_binance_close_1s")
    # any of: PP, R1, S1, R2, S2, R3, S3, M0, M1, M2, M3, M4, M5
    pivot_cols = ["tr_PP", "tr_R1", "tr_S1", "tr_R2", "tr_S2", "tr_R3", "tr_S3",
                  "tr_M0", "tr_M1", "tr_M2", "tr_M3", "tr_M4", "tr_M5"]
    avail = [c for c in pivot_cols if c in df.columns]
    if not avail:
        return np.zeros(len(df), dtype="int8")
    # min |close - pivot| / close
    valid_close = np.isfinite(close) & (close > 0)
    min_dist_bps = np.full(len(df), np.inf, dtype="float64")
    for c in avail:
        piv = _safe(df, c)
        d_bps = np.where(valid_close & np.isfinite(piv),
                          np.abs(close - piv) / close, np.inf)
        min_dist_bps = np.minimum(min_dist_bps, d_bps)
    confluence = min_dist_bps < 0.002   # within 20bps
    out = np.zeros(len(df), dtype="int8")
    out[(base != 0) & confluence] = base[(base != 0) & confluence]
    return out


def rule_v7(df: pd.DataFrame) -> np.ndarray:
    """V7 — V2 + MFI."""
    base = rule_v2(df)
    mfi = _safe(df, "mfi_60s")
    out = np.zeros(len(df), dtype="int8")
    out[(base == +1) & (mfi > 50)] = +1
    out[(base == -1) & (mfi < 50)] = -1
    return out


def rule_v8(df: pd.DataFrame) -> np.ndarray:
    """V8 — V2 + NOT exhausted (adr_pos < 0.85 for UP, > 0.15 for DOWN).

    Computes adr_pos = (close - adr_low_proxy) / (adr_high_proxy - adr_low_proxy).
    Since adr_high/low are dropped (no col), use tr_close_vs_adr_high / adr_low as
    proxies. tr_close_vs_adr_high>=0 means we're above adr_high; <0 below.
    adr_pos can be derived from (1 - tr_close_vs_adr_high / adr_range), but we
    don't have raw adr. Approximation: use tr_close_vs_adr_high as bps:
      if tr_close_vs_adr_high > +0.0085 → exhausted on UP
      if tr_close_vs_adr_low  < -0.0085 → exhausted on DOWN
    """
    base = rule_v2(df)
    vs_hi = _safe(df, "tr_close_vs_adr_high")
    vs_lo = _safe(df, "tr_close_vs_adr_low")
    out = np.zeros(len(df), dtype="int8")
    # UP: not exhausted = close NOT yet near adr_high (vs_hi < 0)
    not_exh_up = (vs_hi < 0) | ~np.isfinite(vs_hi)
    # DOWN: not exhausted = close NOT yet near adr_low (vs_lo > 0)
    not_exh_dn = (vs_lo > 0) | ~np.isfinite(vs_lo)
    out[(base == +1) & not_exh_up] = +1
    out[(base == -1) & not_exh_dn] = -1
    return out


def rule_v9(df: pd.DataFrame) -> np.ndarray:
    """V9 — V2 + Markov M1V regime agrees with direction.

    regime values: 0 = down/bearish, 1 = neutral, 2 = up/bullish.
    Direction UP requires regime==2; DOWN requires regime==0.
    If Markov col is NaN, fall back to V2.
    """
    base = rule_v2(df)
    reg = _safe(df, "regime_w20_5m_voladaptive")
    has_reg = np.isfinite(reg)
    out = np.zeros(len(df), dtype="int8")
    # When regime missing → keep V2 direction
    no_reg = ~has_reg
    out[(base == +1) & (no_reg | (reg == 2))] = +1
    out[(base == -1) & (no_reg | (reg == 0))] = -1
    return out


def rule_v10(df: pd.DataFrame) -> np.ndarray:
    """V10 — Fresh RF flip (rf_dir agrees AND |rf_dir_age| <= 30s)."""
    close = _safe(df, "rf_binance_close_1s")
    rf_close = _safe(df, "rf_close")
    rf_dir = _safe(df, "rf_dir")
    age = _safe(df, "rf_dir_age")
    out = np.zeros(len(df), dtype="int8")
    fresh = np.isfinite(age) & (np.abs(age) <= 30)
    up_mask = (rf_dir == +1) & (close > rf_close) & fresh
    dn_mask = (rf_dir == -1) & (close < rf_close) & fresh
    out[up_mask] = +1
    out[dn_mask] = -1
    return out


def rule_v11(df: pd.DataFrame) -> np.ndarray:
    """V11 — Tight ribbon breakout (compression < 2bps AND bb_width increasing
    [vs panel: we only have current bb_width_60s; proxy "increasing" by
    bb_width_60s > bb_width_120s] AND tr_pvsra agrees)."""
    comp = _safe(df, "ribbon_compression_bps")
    bbw60 = _safe(df, "bb_width_60s")
    bbw120 = _safe(df, "bb_width_120s")
    pv = _safe(df, "tr_pvsra")
    tight = np.isfinite(comp) & (comp < 2)
    expanding = np.isfinite(bbw60) & np.isfinite(bbw120) & (bbw60 > bbw120)
    out = np.zeros(len(df), dtype="int8")
    out[tight & expanding & (pv > 0)] = +1
    out[tight & expanding & (pv < 0)] = -1
    return out


def rule_v12(df: pd.DataFrame) -> np.ndarray:
    """V12 — V2 + F7 RSI not extreme (25 < RSI < 75)."""
    base = rule_v2(df)
    rsi = _safe(df, "f7_rsi_at_ws")
    has_rsi = np.isfinite(rsi)
    moderate = has_rsi & (rsi > 25) & (rsi < 75)
    out = np.zeros(len(df), dtype="int8")
    # If RSI missing → fall back to V2 per task spec ("V12 alone needs F7")
    out[(base != 0) & (~has_rsi | moderate)] = base[(base != 0) & (~has_rsi | moderate)]
    return out


RULES = {
    "V1": rule_v1, "V2": rule_v2, "V3": rule_v3, "V4": rule_v4,
    "V5": rule_v5, "V6": rule_v6, "V7": rule_v7, "V8": rule_v8,
    "V9": rule_v9, "V10": rule_v10, "V11": rule_v11, "V12": rule_v12,
}


# ---------------------------------------------------------------------------
# Aggregation per (asset, tf, offset, rule)
# ---------------------------------------------------------------------------

def aggregate(per_fire: pd.DataFrame, name_tuple: tuple) -> dict:
    n = len(per_fire)
    if n == 0:
        return {"asset": name_tuple[0], "tf": name_tuple[1], "offset_s": name_tuple[2],
                "rule": name_tuple[3], "n": 0, "wins": 0, "WR": float("nan"),
                "sum_pnl": 0.0, "dollar_per_trade": float("nan"),
                "max_DD": 0.0, "max_loss_streak": 0, "sharpe_per_day": float("nan"),
                "n_days": 0}
    pnl = per_fire["pnl"].astype("float64").values
    wins = int((pnl > 0).sum())
    sum_pnl = float(pnl.sum())

    sub = per_fire.sort_values("fire_us")
    cum = sub["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_DD = float(dd.max()) if len(dd) else 0.0

    loss = (sub["pnl"].values <= 0).astype("int8")
    max_streak = 0; cur = 0
    for x in loss:
        if x:
            cur += 1
            if cur > max_streak: max_streak = cur
        else:
            cur = 0

    day = pd.to_datetime(sub["fire_us"], unit="us", utc=True).dt.floor("D")
    daily = sub.assign(_day=day).groupby("_day")["pnl"].sum()
    n_days = int(daily.shape[0])
    sharpe = float("nan")
    if n_days > 1:
        mu = float(daily.mean()); sig = float(daily.std(ddof=1))
        sharpe = mu / sig * math.sqrt(n_days) if sig and sig > 0 else float("nan")

    return {
        "asset": name_tuple[0], "tf": name_tuple[1], "offset_s": name_tuple[2],
        "rule": name_tuple[3], "n": n, "wins": wins,
        "WR": wins / n,
        "sum_pnl": sum_pnl,
        "dollar_per_trade": sum_pnl / n,
        "max_DD": max_DD,
        "max_loss_streak": int(max_streak),
        "sharpe_per_day": sharpe,
        "n_days": n_days,
    }


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run_all() -> pd.DataFrame:
    t0 = time.time()
    rows = []
    all_per_fire = []   # store per-fire records for top sleeves walk-forward

    for tf, feat_path, offsets in [
        ("5m", FEAT_5M, OFFSETS_5M),
        ("15m", FEAT_15M, OFFSETS_15M),
    ]:
        print(f"\n[{tf}] loading features...")
        df_all = pd.read_parquet(feat_path)
        df_all["tf"] = tf
        # Compute direction arrays for all 12 rules on the full panel (faster
        # than re-computing per (asset, offset)).
        print(f"  applying 12 rules to {len(df_all):,} fires...")
        dir_dict = {}
        for rname, fn in RULES.items():
            dir_dict[rname] = fn(df_all)

        for asset in ASSETS:
            for offset in offsets:
                cell_mask = (df_all["asset"].values == asset) & \
                             (df_all["fire_offset_s"].values == offset)
                if not cell_mask.any():
                    continue
                sub = df_all[cell_mask]
                for rname in RULES:
                    rule_dir = dir_dict[rname][cell_mask]
                    pnl = compute_pnl(rule_dir, sub)
                    fired = ~np.isnan(pnl)
                    if fired.sum() < 30:
                        continue
                    per_fire = pd.DataFrame({
                        "asset": asset,
                        "tf": tf,
                        "fire_offset_s": offset,
                        "rule": rname,
                        "slug": sub["slug"].values[fired],
                        "fire_us": sub["fire_us"].values[fired],
                        "direction": rule_dir[fired],
                        "pnl": pnl[fired],
                        "outcome": sub["outcome"].values[fired],
                    })
                    row = aggregate(per_fire, (asset, tf, offset, rname))
                    rows.append(row)
                    all_per_fire.append(per_fire)

    out = pd.DataFrame(rows)
    print(f"\n  total cells: {len(out)}, runtime: {time.time() - t0:.1f}s")
    out.to_csv(OUT_RESULTS, index=False)
    print(f"  wrote {OUT_RESULTS}")
    # Concatenate per-fire records and save (parquet)
    per_fire_full = pd.concat(all_per_fire, ignore_index=True) if all_per_fire else pd.DataFrame()
    per_fire_full.to_parquet(CANON_RES / "hybrid_standalone_per_fire.parquet",
                              index=False, compression="zstd")
    return out, per_fire_full


# ---------------------------------------------------------------------------
# Deployable filter
# ---------------------------------------------------------------------------

def filter_deployable(results: pd.DataFrame) -> pd.DataFrame:
    def is_deploy(r):
        if r["n"] < 50: return False
        wr_min = 0.70 if r["tf"] == "15m" else 0.65
        if r["WR"] < wr_min: return False
        if r["dollar_per_trade"] < 1.50: return False
        if r["sum_pnl"] < 300: return False
        if r["max_loss_streak"] > 5: return False
        return True
    dep = results[results.apply(is_deploy, axis=1)].copy()
    dep = dep.sort_values("sum_pnl", ascending=False).reset_index(drop=True)
    dep.to_csv(OUT_DEPLOY, index=False)
    print(f"  wrote {OUT_DEPLOY} ({len(dep)} deployable cells)")
    return dep


# ---------------------------------------------------------------------------
# Walk-forward validation on top-20 deployable
# ---------------------------------------------------------------------------

def walk_forward_top(deployable: pd.DataFrame, per_fire_full: pd.DataFrame) -> pd.DataFrame:
    """Train: Apr 30 — May 18, Test: May 18 — May 22 (calendar slice on fire_us)."""
    if deployable.empty or per_fire_full.empty:
        return pd.DataFrame()
    # pd.Timestamp.value is in nanoseconds → divide by 1000 to get microseconds
    train_end_us = int(pd.Timestamp("2026-05-18 00:00:00", tz="UTC").value // 1000)
    test_end_us = int(pd.Timestamp("2026-05-23 00:00:00", tz="UTC").value // 1000)
    top = deployable.head(20)
    rows = []
    for _, r in top.iterrows():
        key = (r["asset"], r["tf"], r["offset_s"], r["rule"])
        pf = per_fire_full[
            (per_fire_full["asset"] == key[0]) &
            (per_fire_full["tf"] == key[1]) &
            (per_fire_full["fire_offset_s"] == int(key[2])) &
            (per_fire_full["rule"] == key[3])
        ]
        train = pf[pf["fire_us"] < train_end_us]
        test = pf[(pf["fire_us"] >= train_end_us) & (pf["fire_us"] < test_end_us)]
        tn = len(train); ten = len(test)
        if tn == 0 or ten == 0:
            rows.append({
                "asset": key[0], "tf": key[1], "offset_s": key[2], "rule": key[3],
                "train_n": tn, "test_n": ten,
                "train_WR": float("nan"), "test_WR": float("nan"),
                "train_dpt": float("nan"), "test_dpt": float("nan"),
                "train_sum": float("nan"), "test_sum": float("nan"),
                "overfit_flag": False,
            })
            continue
        tr_pnl = train["pnl"].values
        te_pnl = test["pnl"].values
        tr_wr = float((tr_pnl > 0).sum() / tn)
        te_wr = float((te_pnl > 0).sum() / ten)
        tr_dpt = float(tr_pnl.mean())
        te_dpt = float(te_pnl.mean())
        overfit = te_wr < (tr_wr - 0.10)
        rows.append({
            "asset": key[0], "tf": key[1], "offset_s": key[2], "rule": key[3],
            "train_n": tn, "test_n": ten,
            "train_WR": tr_wr, "test_WR": te_wr,
            "train_dpt": tr_dpt, "test_dpt": te_dpt,
            "train_sum": float(tr_pnl.sum()), "test_sum": float(te_pnl.sum()),
            "overfit_flag": bool(overfit),
        })
    out = pd.DataFrame(rows)
    out.to_csv(OUT_WALKF, index=False)
    print(f"  wrote {OUT_WALKF}")
    return out


# ---------------------------------------------------------------------------
# Cross-asset correlation on top-10 daily PnL
# ---------------------------------------------------------------------------

def correlation_top(deployable: pd.DataFrame, per_fire_full: pd.DataFrame) -> pd.DataFrame:
    if deployable.empty or per_fire_full.empty:
        return pd.DataFrame()
    top = deployable.head(10)
    daily_series = {}
    for _, r in top.iterrows():
        key = (r["asset"], r["tf"], r["offset_s"], r["rule"])
        pf = per_fire_full[
            (per_fire_full["asset"] == key[0]) &
            (per_fire_full["tf"] == key[1]) &
            (per_fire_full["fire_offset_s"] == int(key[2])) &
            (per_fire_full["rule"] == key[3])
        ]
        if pf.empty: continue
        d = pd.to_datetime(pf["fire_us"], unit="us", utc=True).dt.floor("D")
        s = pf.groupby(d)["pnl"].sum()
        label = f"{key[0]}_{key[1]}_off{key[2]}_{key[3]}"
        daily_series[label] = s
    if not daily_series:
        return pd.DataFrame()
    daily_df = pd.DataFrame(daily_series).fillna(0)
    corr = daily_df.corr()
    corr.to_csv(OUT_CORR)
    print(f"  wrote {OUT_CORR}")
    return corr


def main():
    print("="*70)
    print("HYBRID STANDALONE 2026_05_25 RUNNER")
    print("="*70)
    results, per_fire_full = run_all()
    print(f"\nTotal cells: {len(results)}")
    if not results.empty:
        print("Top 5 by sum_pnl:")
        print(results.sort_values("sum_pnl", ascending=False).head().to_string(index=False))
    dep = filter_deployable(results)
    print(f"\nDeployable cells: {len(dep)}")
    if not dep.empty:
        print(dep.head(10).to_string(index=False))
    wf = walk_forward_top(dep, per_fire_full)
    if not wf.empty:
        print(f"\nWalk-forward (top-20):")
        print(wf.to_string(index=False))
    corr = correlation_top(dep, per_fire_full)
    if not corr.empty:
        print(f"\nCorrelation matrix shape: {corr.shape}")
    return results, dep, wf, corr


if __name__ == "__main__":
    main()
