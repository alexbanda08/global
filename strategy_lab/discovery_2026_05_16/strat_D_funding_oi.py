"""
Strategy D - Funding / OI regime overlay.

Hypothesis: regime gates improve momo.

Sources:
  - load_binance_metrics: 5-min granularity OI, long/short ratio, taker vol ratio.
    Symbols: BTCUSDT/ETHUSDT/SOLUSDT. Coverage: 2025-04-27 -> 2026-04-27.
    -> Only 3 days of overlap with res window (Apr 24-27). Limited.
  - load_hyperliquid_funding: 1h granularity funding rate + premium per BTC/ETH/SOL.
    Coverage: 2026-01-30 -> 2026-05-15. Full overlap.

Per market at fire_us = (ws_s + 120)*1e6 (or slot_end - 60s for LATE-15m):
  ret_2m_us = (ws_s + 120)*1e6   (NOTE: same as fire_us by construction)
  Use binance ret_2m direction as base momentum (sign over last 2 minutes).
  Compute regime features (causally, <fire_us):
    oi_delta_1h    = OI(fire) - OI(fire - 1h)             [binance_metrics]
    ls_ratio       = sum_toptrader_long_short_ratio at-or-before fire
    hl_funding     = funding rate at-or-before fire        [HL]
    hl_funding_4h_lo = min funding over last 4h
    hl_funding_4h_hi = max funding over last 4h
    hl_funding_cross = +1 if min<0<max in last 4h, 0 else

Variants:
  baseline      : momentum direction (UP if bn_ret_2m>0, DOWN if <0)
  gate_oi       : only fire when sign(oi_delta_1h) == sign(bn_ret_2m) (continuation)
  gate_ls_crowd : only fire when ls_ratio > thr -> bias DOWN (crowded-long reversal)
  gate_hl_cross : only fire when hl_funding_cross==1 -> direction = sign(funding now)
LATE-15m variant: same gates at slot_end - 60.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))

from harness import slug_to_ws_s, get_klines  # type: ignore
from load import (  # type: ignore
    load_resolutions,
    load_binance_metrics,
    load_hyperliquid_funding,
    asof_strict,
)


# ---------- Asof helpers ----------

def asof_array(ts_arr: np.ndarray, val_arr: np.ndarray, target_us: np.ndarray) -> np.ndarray:
    """Vectorized causal asof: return val[i] where ts[i] is largest <= target_us."""
    idx = np.searchsorted(ts_arr, target_us, side="right") - 1
    out = np.where(idx >= 0, val_arr[idx.clip(min=0)], np.nan)
    return out


def asof_window_min_max(ts_arr: np.ndarray, val_arr: np.ndarray,
                         target_us: np.ndarray, lookback_us: int):
    """For each target, return (min, max) of val over [target-lookback, target]."""
    hi = np.searchsorted(ts_arr, target_us, side="right")
    lo = np.searchsorted(ts_arr, target_us - lookback_us, side="left")
    n = len(target_us)
    mins = np.full(n, np.nan)
    maxs = np.full(n, np.nan)
    for i in range(n):
        if hi[i] > lo[i]:
            seg = val_arr[lo[i]:hi[i]]
            if len(seg):
                mins[i] = np.nanmin(seg)
                maxs[i] = np.nanmax(seg)
    return mins, maxs


# ---------- Feature builders ----------

def build_features(df_universe: pd.DataFrame, anchor: str, offset_s: int):
    """Add fire_us, bn_ret_2m, oi_delta_1h, ls_ratio, hl_funding,
    hl_funding_min_4h, hl_funding_max_4h, hl_funding_cross_4h to df.
    """
    df = df_universe.copy().reset_index(drop=True)
    # fire_us
    if anchor == "ws_s":
        ws_arr = np.array([slug_to_ws_s(s, t)
                           for s, t in zip(df.slug.values, df.timeframe.values)], dtype="int64")
        fire_us = (ws_arr + offset_s) * 1_000_000
    elif anchor == "slot_end_minus":
        fire_us = df.slot_end_us.values.astype("int64") - offset_s * 1_000_000
    else:
        raise ValueError(anchor)
    df["fire_us"] = fire_us.astype("int64")

    # ---- Per-asset binance ret_2m (causal) ----
    parts = []
    for asset, g in df.groupby("ticker"):
        sub = g.copy().reset_index(drop=True)
        fire = sub.fire_us.values.astype("int64")
        bn_end, bn_p = get_klines(asset, "binance-spot-ws", "1MIN")
        bn_now = np.array([asof_strict(bn_end, bn_p, int(t)) for t in fire], dtype=float)
        bn_prev = np.array([asof_strict(bn_end, bn_p, int(t) - 120_000_000) for t in fire], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            bn_ret = bn_now / bn_prev - 1.0
        sub["bn_ret_2m"] = bn_ret

        # ---- binance_metrics: OI delta 1h, long/short ratio ----
        try:
            m = load_binance_metrics(f"{asset}USDT")
            mts = m.create_time_us.values.astype("int64")
            oi = pd.to_numeric(m.sum_open_interest, errors="coerce").values
            ls = pd.to_numeric(m.sum_toptrader_long_short_ratio, errors="coerce").values
            oi_now = asof_array(mts, oi, fire)
            oi_prev = asof_array(mts, oi, fire - 3600_000_000)
            with np.errstate(invalid="ignore"):
                oi_delta = oi_now - oi_prev
            ls_now = asof_array(mts, ls, fire)
        except Exception as e:
            print(f"  ! binance_metrics fail for {asset}: {e}")
            oi_delta = np.full(len(fire), np.nan)
            ls_now = np.full(len(fire), np.nan)
        sub["oi_delta_1h"] = oi_delta
        sub["ls_ratio"] = ls_now

        # ---- HL funding: cross-zero in last 4h ----
        try:
            f = load_hyperliquid_funding(asset)
            fts = f.funding_time_us.values.astype("int64")
            fr = f.funding_rate.astype(float).values
            f_now = asof_array(fts, fr, fire)
            f_min, f_max = asof_window_min_max(fts, fr, fire, 4 * 3600_000_000)
        except Exception as e:
            print(f"  ! HL funding fail for {asset}: {e}")
            f_now = np.full(len(fire), np.nan)
            f_min = np.full(len(fire), np.nan)
            f_max = np.full(len(fire), np.nan)
        sub["hl_funding"] = f_now
        sub["hl_funding_min_4h"] = f_min
        sub["hl_funding_max_4h"] = f_max
        with np.errstate(invalid="ignore"):
            cross = ((f_min < 0) & (f_max > 0)).astype(int)
        sub["hl_funding_cross_4h"] = cross
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


# ---------- Signal variants ----------

def sig_baseline(row, thr: float = 0.0):
    r = row.bn_ret_2m
    if not np.isfinite(r):
        return "SKIP"
    if r > thr:
        return "UP"
    if r < -thr:
        return "DOWN"
    return "SKIP"


def sig_gate_oi(row, thr: float = 0.0):
    """Continuation: only fire when OI rising AND momo same direction."""
    r = row.bn_ret_2m
    oi = row.oi_delta_1h
    if not (np.isfinite(r) and np.isfinite(oi)):
        return "SKIP"
    if r > thr and oi > 0:
        return "UP"
    if r < -thr and oi < 0:
        return "DOWN"
    return "SKIP"


def sig_gate_ls_crowd(row, ls_thr: float = 2.5):
    """Crowded-long reversal: only fire when ls_ratio > thr -> DOWN."""
    ls = row.ls_ratio
    if not np.isfinite(ls):
        return "SKIP"
    if ls > ls_thr:
        return "DOWN"
    if ls < (1.0 / ls_thr):
        return "UP"
    return "SKIP"


def sig_gate_hl_cross(row, _unused=None):
    """HL funding crossed zero last 4h -> direction = sign(funding now)."""
    if not (np.isfinite(row.hl_funding) and np.isfinite(row.hl_funding_cross_4h)):
        return "SKIP"
    if row.hl_funding_cross_4h != 1:
        return "SKIP"
    if row.hl_funding > 0:
        return "UP"
    if row.hl_funding < 0:
        return "DOWN"
    return "SKIP"


VARIANTS = {
    "baseline":      ([0.0, 1e-4, 2e-4, 5e-4],            sig_baseline),
    "gate_oi":       ([0.0, 1e-4, 2e-4, 5e-4],            sig_gate_oi),
    "gate_ls_crowd": ([1.5, 2.0, 2.5, 3.0],               sig_gate_ls_crowd),
    "gate_hl_cross": ([None],                             sig_gate_hl_cross),
}


def sweep(df_feat: pd.DataFrame):
    rows = []
    for name, (grid, fn) in VARIANTS.items():
        for thr in grid:
            df = df_feat.copy()
            if thr is None:
                df["signal"] = df.apply(fn, axis=1)
            else:
                df["signal"] = df.apply(lambda r: fn(r, thr), axis=1)
            fired = df[df.signal.isin(("UP", "DOWN"))]
            if len(fired) < 1:
                continue
            won_g = (fired.signal.str.upper() == fired.outcome.str.upper()).mean()
            rows.append({
                "variant": name, "thr": (np.nan if thr is None else thr),
                "asset": "ALL", "n": len(fired), "hit": round(float(won_g), 4),
            })
            for asset, g in fired.groupby("ticker"):
                if len(g) < 50:
                    continue
                won = (g.signal.str.upper() == g.outcome.str.upper()).mean()
                rows.append({
                    "variant": name, "thr": (np.nan if thr is None else thr),
                    "asset": asset, "n": len(g), "hit": round(float(won), 4),
                })
    return pd.DataFrame(rows)


def run_anchor(df_uni, anchor, offset_s, label):
    print(f"\n=== {label}: anchor={anchor} offset={offset_s}s ===")
    df_feat = build_features(df_uni, anchor, offset_s)
    print(f"  rows: {len(df_feat)}")
    n_oi = df_feat.oi_delta_1h.notna().sum()
    n_ls = df_feat.ls_ratio.notna().sum()
    n_fund = df_feat.hl_funding.notna().sum()
    n_cross = (df_feat.hl_funding_cross_4h == 1).sum()
    print(f"  feature coverage: bn_ret={df_feat.bn_ret_2m.notna().sum()} oi_delta={n_oi} ls_ratio={n_ls} hl_funding={n_fund} cross_4h={n_cross}")
    sw = sweep(df_feat)
    return df_feat, sw


def main():
    res = load_resolutions()
    print(f"universe: {len(res)} markets")

    SAMPLE_PER = 2000
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            sub = res[(res.ticker == asset) & (res.timeframe == tf)]
            if len(sub) > SAMPLE_PER:
                sub = sub.sample(SAMPLE_PER, random_state=42)
            parts.append(sub)
    res_s = pd.concat(parts, ignore_index=True)
    print(f"sampled to {len(res_s)} rows")

    df_5m = res_s[res_s.timeframe == "5m"].copy()
    df_15m = res_s[res_s.timeframe == "15m"].copy()

    all_sweeps = []

    # ---- 5m @ ws_s + 120 ----
    df_feat_5m, sw = run_anchor(df_5m, "ws_s", 120, "5m @ ws_s+120")
    sw["block"] = "5m_ws120"
    all_sweeps.append(sw)

    # ---- 15m @ ws_s + 120 ----
    df_feat_15m, sw = run_anchor(df_15m, "ws_s", 120, "15m @ ws_s+120")
    sw["block"] = "15m_ws120"
    all_sweeps.append(sw)

    # ---- 15m LATE @ slot_end - 60 ----
    df_feat_15ml, sw = run_anchor(df_15m, "slot_end_minus", 60, "15m @ slot_end-60 (LATE)")
    sw["block"] = "15m_late"
    all_sweeps.append(sw)

    sweep_all = pd.concat(all_sweeps, ignore_index=True)
    out_csv = HERE / "strat_D_sweep.csv"
    sweep_all.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}  ({len(sweep_all)} rows)")

    # ---- No-lookahead sample ----
    print("\n=== sample no-lookahead trades (5m, baseline, first 3 with all features) ===")
    nl = df_feat_5m[df_feat_5m.bn_ret_2m.notna() & df_feat_5m.hl_funding.notna()].head(3)
    rows_nl = []
    for _, row in nl.iterrows():
        ws_s = slug_to_ws_s(row.slug, row.timeframe)
        rows_nl.append({
            "slug": row.slug, "ticker": row.ticker, "tf": row.timeframe,
            "ws_s": int(ws_s),
            "fire_us": int(row.fire_us),
            "slot_end_us": int(row.slot_end_us),
            "fire_lt_slot_end (margin>=180s)":
                int(row.fire_us) < (int(row.slot_end_us) - 180 * 1_000_000),
            "bn_ret_2m": round(float(row.bn_ret_2m), 6),
            "oi_delta_1h": (round(float(row.oi_delta_1h), 2) if np.isfinite(row.oi_delta_1h) else None),
            "ls_ratio": (round(float(row.ls_ratio), 3) if np.isfinite(row.ls_ratio) else None),
            "hl_funding": (round(float(row.hl_funding), 6) if np.isfinite(row.hl_funding) else None),
            "hl_funding_cross_4h": int(row.hl_funding_cross_4h) if np.isfinite(row.hl_funding_cross_4h) else None,
            "outcome": row.outcome,
        })
    sdf = pd.DataFrame(rows_nl)
    print(sdf.to_string(index=False))
    sdf.to_csv(HERE / "strat_D_lookahead_sample.csv", index=False)

    # ---- Top configs ----
    print("\n=== top configs (n>=200, ALL asset, sorted by hit) ===")
    if len(sweep_all) and "asset" in sweep_all.columns:
        top = sweep_all[(sweep_all.asset == "ALL") & (sweep_all.n >= 200)].sort_values("hit", ascending=False).head(15)
        print(top.to_string(index=False) if len(top) else "(no configs with n>=200)")
        top_a = sweep_all[(sweep_all.asset != "ALL") & (sweep_all.n >= 200)].sort_values("hit", ascending=False).head(15)
        print("\n=== top per-asset configs (n>=200) ===")
        print(top_a.to_string(index=False) if len(top_a) else "(no per-asset configs with n>=200)")


if __name__ == "__main__":
    main()
