"""Build joined hybrid feature parquets for 5m + 15m fire universes.

This is the operational entry point for HYBRID_STANDALONE_2026_05_25:
  Inputs:
    data/v4/canonical/_results/hybrid_fire_universe_{tf}.parquet
    data/v4/canonical/_results/range_filter_1s.parquet
    data/v4/canonical/_results/traders_reality_1s.parquet
    data/v4/canonical/_results/ta_indicators_1s.parquet
    strategy_lab/markov_filter/_results/post_f7_fires_with_regimes.csv
    binance-spot-ws 1MIN klines (via canonical/load.py)

  Outputs:
    data/v4/canonical/_results/hybrid_features_5m.parquet
    data/v4/canonical/_results/hybrid_features_15m.parquet

Causal anchor: features come from 1s bar where ts_us <= fire_us - 1_000_000.
F7 RSI uses ws_s anchor (per CLAUDE.md), simple-mean Wilder, on 1MIN closes.
Markov regime: asof-joined from post_f7_fires_with_regimes.csv by (asset, fire_us).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_klines  # noqa: E402

CANON_RES = ROOT / "data" / "v4" / "canonical" / "_results"

RF_PANEL = CANON_RES / "range_filter_1s.parquet"
TR_PANEL = CANON_RES / "traders_reality_1s.parquet"
TA_PANEL = CANON_RES / "ta_indicators_1s.parquet"
MARKOV_FILE = ROOT / "strategy_lab" / "markov_filter" / "_results" / "post_f7_fires_with_regimes.csv"

# 1s feature bar must end at ws_us = fire_us - 1_000_000  (CAUSAL — no lookahead)
CAUSAL_OFFSET_US = 1_000_000   # subtract 1s from fire_us to find a feature bar
MAX_FEATURE_AGE_US = 30 * 1_000_000

RSI_PERIOD = 14
F7_BAR_S = 60   # 1-min bars


def _vectorized_f7_rsi(asset: str, ws_s_arr: np.ndarray) -> np.ndarray:
    """Vectorized F7 RSI: for each ws_s, find the last 15 1MIN closes ending at ws_s,
    compute simple-mean Wilder. Returns float64 array same len as ws_s_arr.
    """
    kl = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
    if kl.empty:
        return np.full(len(ws_s_arr), np.nan, dtype="float64")
    ts_us = kl["time_period_start_us"].values.astype("int64")
    close = kl["price_close"].values.astype("float64")
    n = len(ws_s_arr)
    out = np.full(n, np.nan, dtype="float64")
    anchor_us = (ws_s_arr.astype("int64")) * 1_000_000
    # For each anchor, find rightmost klines index <= anchor (searchsorted right - 1)
    idx_hi = np.searchsorted(ts_us, anchor_us, side="right") - 1
    # Need idx_hi - RSI_PERIOD >= 0 (i.e. 15 bars including anchor bar)
    for i in range(n):
        hi = int(idx_hi[i])
        if hi < RSI_PERIOD:
            continue
        seg = close[hi - RSI_PERIOD: hi + 1]   # 15 closes
        diffs = np.diff(seg)
        ups = np.where(diffs > 0, diffs, 0.0)
        dns = np.where(diffs < 0, -diffs, 0.0)
        au = ups.mean()
        ad = dns.mean()
        if ad == 0 and au == 0:
            out[i] = 50.0
        elif ad == 0:
            out[i] = 100.0
        else:
            rs = au / ad
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def compute_f7_rsi_at_ws(fu: pd.DataFrame) -> pd.Series:
    """Anchor F7 RSI on production `ws_s` per CLAUDE.md. Vectorized per asset."""
    out = np.full(len(fu), np.nan, dtype="float64")
    for asset in fu["asset"].dropna().unique():
        mask = (fu["asset"] == asset).values
        sub_ws = fu.loc[mask, "ws_s"].values.astype("int64")
        vals = _vectorized_f7_rsi(asset, sub_ws)
        out[mask] = vals
    return pd.Series(out, index=fu.index, name="f7_rsi_at_ws")


def join_markov(fu: pd.DataFrame) -> pd.DataFrame:
    """Asof-join Markov M1V regime by (asset, fire_us). Adds regime_w20_5m_voladaptive
    column (M1V is the 5m vol-adaptive variant). Uses backward asof with 2h tolerance.
    """
    if not MARKOV_FILE.exists():
        for c in ("regime_w20_5m_voladaptive", "pass_w20_5m_voladaptive"):
            fu[c] = pd.NA
        return fu
    mk = pd.read_csv(MARKOV_FILE)
    needed = {"symbol", "fire_us", "regime_w20_5m_voladaptive"}
    if not needed.issubset(mk.columns):
        for c in ("regime_w20_5m_voladaptive", "pass_w20_5m_voladaptive"):
            fu[c] = pd.NA
        return fu
    mk["asset"] = mk["symbol"].str.upper()
    cols = ["asset", "fire_us", "regime_w20_5m_voladaptive", "pass_w20_5m_voladaptive"]
    cols = [c for c in cols if c in mk.columns]
    mk = mk[cols].dropna(subset=["fire_us"]).sort_values(["asset", "fire_us"])
    parts = []
    for asset, sub in fu.groupby("asset", sort=False):
        msub = mk[mk["asset"] == asset].sort_values("fire_us")
        ssub = sub.sort_values("fire_us")
        if msub.empty:
            for c in cols[2:]:
                ssub[c] = pd.NA
            parts.append(ssub)
            continue
        merged = pd.merge_asof(
            ssub, msub.drop(columns=["asset"]),
            on="fire_us", direction="backward",
            tolerance=int(2 * 3600 * 1_000_000),
            suffixes=("", "_mk"),
        )
        parts.append(merged)
    return pd.concat(parts, ignore_index=False).sort_index()


def _asof_join_panel(
    fu: pd.DataFrame,
    panel: pd.DataFrame,
    asset_col: str = "asset",
    ts_col: str = "ts_us",
    on_col: str = "fire_us",
    prefix: str = "",
    causal_offset_us: int = CAUSAL_OFFSET_US,
    drop_cols: tuple[str, ...] = ("close",),
) -> pd.DataFrame:
    """Asof-merge a per-asset 1s panel onto the fire universe with causal offset.

    The merge target is `fire_us - causal_offset_us` so we only pick bars
    that ENDED before the fire (no lookahead).

    Strategy:
    - Pre-rename ALL panel feature cols with `prefix` BEFORE merging, but skip
      cols that already start with the prefix (e.g. tr_ in traders_reality_1s).
    - Skip cols already in fu (avoid duplicate `close`, `ts_us`, etc).
    - drop_cols are removed from the panel before merging (e.g. drop `close`
      duplicate when TA already provided one).
    """
    panel = panel.copy()
    # Drop the asset+ts cols that we don't want appearing twice
    # Drop any cols already in fu (case-insensitive match)
    existing = set(fu.columns)
    panel_feat_cols = [c for c in panel.columns if c not in (asset_col, ts_col)]
    drop_set = set(drop_cols)
    keep = []
    for c in panel_feat_cols:
        if c in drop_set:
            continue
        keep.append(c)
    panel = panel[[asset_col, ts_col] + keep]
    # Apply prefix, but not if col already starts with prefix (avoid tr_tr_)
    if prefix:
        rename_map = {}
        for c in keep:
            if c.startswith(prefix):
                rename_map[c] = c   # leave as-is
            else:
                rename_map[c] = f"{prefix}{c}"
        panel = panel.rename(columns=rename_map)
    # Now drop any col already present in fu (avoid duplicate ema_5, etc.)
    final_cols = [asset_col, ts_col]
    for c in panel.columns:
        if c in (asset_col, ts_col):
            continue
        if c in existing:
            continue
        final_cols.append(c)
    panel = panel[final_cols]

    panel = panel.sort_values([asset_col, ts_col]).reset_index(drop=True)

    if "_merge_us" not in fu.columns:
        fu = fu.copy()
        fu["_merge_us"] = (fu[on_col].astype("int64") - causal_offset_us)

    parts = []
    panel_had_ts = ts_col in fu.columns  # was ts_us already there?
    for asset, sub in fu.groupby(asset_col, sort=False):
        psub = panel[panel[asset_col] == asset].sort_values(ts_col)
        if psub.empty:
            parts.append(sub)
            continue
        ssub = sub.sort_values("_merge_us")
        psub_drop = psub.drop(columns=[asset_col])
        merged = pd.merge_asof(
            ssub, psub_drop,
            left_on="_merge_us", right_on=ts_col,
            direction="backward",
            tolerance=MAX_FEATURE_AGE_US,
            suffixes=("", "_dup"),
        )
        parts.append(merged)
    out = pd.concat(parts, ignore_index=False).sort_index()
    # Drop any *_dup columns and the panel's ts_us if fu didn't originally have it
    dup_cols = [c for c in out.columns if c.endswith("_dup")]
    if dup_cols:
        out = out.drop(columns=dup_cols)
    if not panel_had_ts and ts_col in out.columns:
        out = out.drop(columns=[ts_col])
    return out


def build_tf(tf: str) -> Path:
    fu_path = CANON_RES / f"hybrid_fire_universe_{tf}.parquet"
    out_path = CANON_RES / f"hybrid_features_{tf}.parquet"
    t0 = time.time()
    print(f"[{tf}] loading {fu_path.name}...")
    fu = pd.read_parquet(fu_path).reset_index(drop=True)
    print(f"  fires: {len(fu):,}")
    fu["tf"] = tf  # ensure column

    # Load all 3 panels once
    print("  loading TA panel...")
    ta = pd.read_parquet(TA_PANEL)
    print(f"    TA rows: {len(ta):,}")
    print("  joining TA (causal)...")
    fu = _asof_join_panel(fu, ta, prefix="")

    print("  loading RF panel...")
    rf = pd.read_parquet(RF_PANEL)
    print(f"    RF rows: {len(rf):,}")
    # Rename `close` to `binance_close_1s` so V1 has the raw market close
    if "close" in rf.columns:
        rf = rf.rename(columns={"close": "binance_close_1s"})
    print("  joining RF...")
    # rf_close, rf_dir already prefixed; don't drop anything; binance_close_1s passes through
    fu = _asof_join_panel(fu, rf, prefix="rf_", drop_cols=())

    print("  loading TR panel...")
    tr = pd.read_parquet(TR_PANEL)
    print(f"    TR rows: {len(tr):,}")
    print("  joining TR...")
    fu = _asof_join_panel(fu, tr, prefix="tr_")

    # F7 RSI at ws_s
    print("  computing f7_rsi_at_ws...")
    fu["f7_rsi_at_ws"] = compute_f7_rsi_at_ws(fu)
    n_f7 = int(fu["f7_rsi_at_ws"].notna().sum())
    print(f"    f7_rsi populated: {n_f7:,} / {len(fu):,}")

    # Markov regime
    print("  joining markov regime...")
    fu = join_markov(fu)

    # Drop helper col
    if "_merge_us" in fu.columns:
        fu = fu.drop(columns=["_merge_us"])

    print(f"  writing {out_path.name}... shape={fu.shape}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fu.to_parquet(out_path, index=False, compression="zstd")
    dt = time.time() - t0
    print(f"  [{tf}] done in {dt:.1f}s — {out_path}")
    return out_path


def main():
    for tf in ("5m", "15m"):
        build_tf(tf)


if __name__ == "__main__":
    main()
