"""Join RF + TR + TA + F7 + Markov features onto the fire universe.

Inputs (produced by parallel agents):
  data/v4/canonical/_results/range_filter_1s.parquet      (RF panel, agent A)
  data/v4/canonical/_results/traders_reality_1s.parquet   (TR panel, agent B)
  data/v4/canonical/_results/ta_indicators_1s.parquet     (TA panel — exists)
  data/v4/canonical/_results/hybrid_fire_universe_{tf}.parquet  (fires + fills)

Outputs:
  data/v4/canonical/_results/hybrid_features_5m.parquet
  data/v4/canonical/_results/hybrid_features_15m.parquet

Each output row = one fire × all feature columns at the asof-causal feature
snapshot from each 1s panel. Joins are `merge_asof` at `fire_us` per asset
(direction='backward', tolerance bounded so we never silently pull from a
gap > 30s wide).

F7 RSI + Markov M1V regime are computed separately:
  F7 RSI uses production-correct anchor `ws_s` (NOT fire_us) per CLAUDE.md.
  Markov M1V regime: snapshotted from markov_filter/_results/ (latest file).
"""
from __future__ import annotations

import sys
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

FU_5M = CANON_RES / "hybrid_fire_universe_5m.parquet"
FU_15M = CANON_RES / "hybrid_fire_universe_15m.parquet"

OUT_5M = CANON_RES / "hybrid_features_5m.parquet"
OUT_15M = CANON_RES / "hybrid_features_15m.parquet"

MARKOV_DIR = ROOT / "strategy_lab" / "markov_filter" / "_results"

# merge_asof tolerance — never grab features more than this old.
MAX_FEATURE_AGE_US = 30 * 1_000_000   # 30s

# ---------------------------------------------------------------------------
# F7 RSI — production-correct simple-mean Wilder at ws_s, on 1MIN closes.
# ---------------------------------------------------------------------------

RSI_PERIOD = 14
F7_BAR_S = 60   # production fetches 15 closes at offsets [-840 .. 0] from ws_s


def _rsi_simple_wilder(closes_1d: np.ndarray, period: int = RSI_PERIOD) -> float:
    """Production's rsi.py: simple-mean Wilder, NOT exponential.

    Expects `closes_1d` of length `period + 1` ending at ws_s. Returns
    NaN if input has fewer than `period+1` values.
    """
    if closes_1d.shape[0] < period + 1:
        return float("nan")
    closes_1d = closes_1d[-(period + 1):]
    diffs = np.diff(closes_1d)
    ups = np.where(diffs > 0, diffs, 0.0)
    dns = np.where(diffs < 0, -diffs, 0.0)
    avg_up = float(ups.mean())
    avg_dn = float(dns.mean())
    if avg_dn == 0 and avg_up == 0:
        return 50.0
    if avg_dn == 0:
        return 100.0
    rs = avg_up / avg_dn
    return 100.0 - (100.0 / (1.0 + rs))


def compute_f7_rsi_at_ws(fu: pd.DataFrame) -> pd.Series:
    """Anchor F7 RSI on production `ws_s` (NOT fire_us) per CLAUDE.md.

    Returns a Series of RSI values aligned to fu.index. NaN if klines absent
    or warmup not satisfied.
    """
    out = np.full(len(fu), np.nan, dtype="float64")
    for asset in fu["asset"].dropna().unique():
        kl = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
        if kl.empty:
            continue
        ts_us = kl["time_period_start_us"].values.astype("int64")
        close = kl["price_close"].values.astype("float64")
        sub = fu[fu["asset"] == asset]
        # For each row's ws_s, slice closes at offsets [-(RSI_PERIOD * 60), ..., 0]
        # relative to ws_s. ws_s is in SECONDS, klines are minute-start in us.
        for idx, ws_s in zip(sub.index, sub["ws_s"].astype("int64")):
            anchor_us = int(ws_s) * 1_000_000
            window_start_us = anchor_us - (RSI_PERIOD * F7_BAR_S) * 1_000_000
            lo = int(np.searchsorted(ts_us, window_start_us, side="left"))
            hi = int(np.searchsorted(ts_us, anchor_us, side="right"))
            if hi - lo < RSI_PERIOD + 1:
                continue
            rsi_val = _rsi_simple_wilder(close[lo:hi], period=RSI_PERIOD)
            out[idx] = rsi_val
    return pd.Series(out, index=fu.index, name="f7_rsi_at_ws")


# ---------------------------------------------------------------------------
# Markov regime — snapshot from latest markov_filter/_results/ artifact.
# ---------------------------------------------------------------------------

def _find_latest_markov() -> Path | None:
    """Pick a sensible default Markov regime snapshot."""
    cands = [
        MARKOV_DIR / "post_f7_fires_with_regimes.csv",
        MARKOV_DIR / "_chainlink_markov_fills.csv",
    ]
    for p in cands:
        if p.exists():
            return p
    return None


def join_markov_regime(fu: pd.DataFrame) -> pd.DataFrame:
    """Asof-join Markov M1V regime + pass-flags onto fu by (asset, fire_us).

    Uses `post_f7_fires_with_regimes.csv` if present. The file has one row per
    production fire (fire_us, symbol, regime_w20_*_*, pass_w20_*_*). We
    asof-merge on (asset, fire_us) so each backtest fire picks up the most
    recent production-fire's regime. If a fire pre-dates any production fire
    for its asset, regime cols stay NaN.
    """
    p = _find_latest_markov()
    if p is None:
        # No regime file available — return fu with empty regime cols.
        for c in ("regime_w20_1m_voladaptive", "pass_w20_1m_voladaptive",
                   "regime_w20_5m_voladaptive", "pass_w20_5m_voladaptive"):
            fu[c] = pd.NA
        return fu
    mk = pd.read_csv(p)
    if "symbol" not in mk.columns or "fire_us" not in mk.columns:
        return fu  # unexpected schema — skip
    mk["asset"] = mk["symbol"].str.upper()
    # Per-asset asof on fire_us.
    parts = []
    for asset, sub in fu.groupby("asset"):
        msub = mk[mk["asset"] == asset].sort_values("fire_us")
        if msub.empty:
            sub2 = sub.copy()
            for c in msub.columns:
                if c not in sub2.columns:
                    sub2[c] = pd.NA
            parts.append(sub2)
            continue
        ssub = sub.sort_values("fire_us")
        merged = pd.merge_asof(
            ssub, msub.drop(columns=["asset"]),
            on="fire_us", direction="backward",
            tolerance=int(2 * 3600 * 1_000_000),  # 2h tolerance — regime is slow
            suffixes=("", "_mk"),
        )
        parts.append(merged)
    return pd.concat(parts, ignore_index=False).sort_index()


# ---------------------------------------------------------------------------
# Generic asof-join of a 1s feature panel onto fires.
# ---------------------------------------------------------------------------

def _asof_join_panel(
    fu: pd.DataFrame,
    panel_path: Path,
    feature_cols: list[str] | None = None,
    asset_col: str = "asset",
    ts_col: str = "ts_us",
    on_col: str = "fire_us",
    prefix: str = "",
) -> pd.DataFrame:
    """Asof-merge a per-asset 1s panel onto the fire universe.

    The panel is expected to have (asset, ts_us, <features>...).
    """
    if not panel_path.exists():
        print(f"  [join] panel missing: {panel_path.name} — skipping")
        return fu
    panel = pd.read_parquet(panel_path)
    if feature_cols is not None:
        keep = [c for c in feature_cols if c in panel.columns]
        panel = panel[[asset_col, ts_col] + keep]
    panel = panel.sort_values([asset_col, ts_col]).reset_index(drop=True)
    parts = []
    for asset, sub in fu.groupby(asset_col, sort=False):
        psub = panel[panel[asset_col] == asset].sort_values(ts_col)
        if psub.empty:
            parts.append(sub)
            continue
        ssub = sub.sort_values(on_col)
        merged = pd.merge_asof(
            ssub, psub.drop(columns=[asset_col]),
            left_on=on_col, right_on=ts_col,
            direction="backward",
            tolerance=MAX_FEATURE_AGE_US,
            suffixes=("", "_p"),
        )
        if prefix:
            renamed = {c: f"{prefix}{c}" for c in merged.columns
                        if c in panel.columns and c not in (asset_col, ts_col, on_col)}
            merged = merged.rename(columns=renamed)
        parts.append(merged)
    return pd.concat(parts, ignore_index=False).sort_index()


# ---------------------------------------------------------------------------
# Top-level entry points.
# ---------------------------------------------------------------------------

def join_for_timeframe(tf: str) -> Path:
    """Build the hybrid feature parquet for a single timeframe.

    Returns the output path. Raises FileNotFoundError if the upstream fire
    universe parquet isn't there yet.
    """
    fu_path = FU_5M if tf == "5m" else FU_15M
    out_path = OUT_5M if tf == "5m" else OUT_15M
    if not fu_path.exists():
        raise FileNotFoundError(
            f"fire universe missing: {fu_path}. Run hybrid_fire_universe_build.py first."
        )
    print(f"[hybrid_features {tf}] loading {fu_path.name}...")
    fu = pd.read_parquet(fu_path).reset_index(drop=True)
    print(f"  fires: {len(fu):,}")

    # TA panel (always-present canonical TA).
    print("  joining ta_indicators_1s...")
    fu = _asof_join_panel(fu, TA_PANEL)
    # Range Filter DW panel (agent A).
    print("  joining range_filter_1s (may be missing pre-agent-A)...")
    fu = _asof_join_panel(fu, RF_PANEL, prefix="rf_")
    # Traders Reality stack (agent B).
    print("  joining traders_reality_1s (may be missing pre-agent-B)...")
    fu = _asof_join_panel(fu, TR_PANEL, prefix="tr_")

    # F7 RSI at ws_s.
    print("  computing f7_rsi at ws_s...")
    fu["f7_rsi_at_ws"] = compute_f7_rsi_at_ws(fu)

    # Markov regime asof.
    print("  asof-joining markov regime snapshot...")
    fu = join_markov_regime(fu)

    print(f"  writing {out_path.name}...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fu.to_parquet(out_path, index=False, compression="zstd")
    print(f"  wrote {len(fu):,} rows × {len(fu.columns)} cols")
    return out_path


def main():
    for tf in ("5m", "15m"):
        try:
            join_for_timeframe(tf)
        except FileNotFoundError as e:
            print(f"  [skip {tf}] {e}")


if __name__ == "__main__":
    main()
