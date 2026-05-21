"""
Strategy C - Hyperliquid liquidation cascades.

Hypothesis: HL liq cascades create directional pressure on binance spot.
  long_liq  (forced sells) -> DOWN bias
  short_liq (forced buys)  -> UP   bias
  net = short_liq_notional - long_liq_notional. net>0 -> UP; net<0 -> DOWN.

Spec mapping: 'A' = ask-side fills = long liquidations (forced sells)
              'B' = bid-side fills = short liquidations (forced buys)

DATA NOTE:
  load_hyperliquid_liquidations_full covers May 2025 -> Feb 2026 only.
  res universe is Apr 24 - May 16 2026 -> ZERO overlap with _full.
  We fall back to load_hyperliquid_liquidations (30d, Apr 16 -> May 16),
  which is HL trade-flow (no clean liq flag) but contains the side A/B field
  the spec keys on. Treat as best-available proxy for HL aggressor pressure.
  Flagged in report as data-coverage caveat.

Universe: 5m and 15m BTC/ETH/SOL.
For each market at fire_us = (ws_s + 120) * 1e6:
  lookback [fire_us - L, fire_us]  (L in {5min, 10min})
  long_liq_notional  = sum(price*size where side=='A')
  short_liq_notional = sum(price*size where side=='B')
  net = short_liq_notional - long_liq_notional
  Signal: UP if net > +T, DOWN if net < -T, else SKIP.
Threshold sweep T in {100k, 500k, 1M, 5M}.
LATE-15m variant: entry_us = slot_end_us - 60e6.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))

from harness import slug_to_ws_s  # type: ignore
from load import (  # type: ignore
    load_resolutions,
    load_hyperliquid_liquidations,         # 30d -- covers window
    load_hyperliquid_liquidations_full,    # full -- empty in window, included for completeness
)


# ---------- Data prep ----------

def build_liq_arrays(asset: str, prefer: str = "auto",
                     window_lo_us: int | None = None,
                     window_hi_us: int | None = None):
    """Return dict with sorted ts_us, notional, is_long, is_short arrays.

    prefer:
      'full' -> full file (May25-Feb26) only.
      '30d'  -> 30d file (Apr16-May16) only.
      'auto' -> 30d if full has 0 rows IN WINDOW, else full.
    """
    if prefer in ("full", "auto"):
        try:
            full = load_hyperliquid_liquidations_full(asset)
            full = full[full.dir.str.contains("Liquidated|Auto-Deleveraging", regex=True, na=False)]
            if window_lo_us is not None:
                full_in_win = full[(full.time_exchange_us >= window_lo_us) &
                                   (full.time_exchange_us < window_hi_us)]
            else:
                full_in_win = full
        except Exception:
            full = pd.DataFrame()
            full_in_win = pd.DataFrame()
    else:
        full = pd.DataFrame()
        full_in_win = pd.DataFrame()

    if prefer == "30d" or (prefer == "auto" and len(full_in_win) == 0):
        df = load_hyperliquid_liquidations(asset)
        df = df[df.side.isin(("A", "B"))].copy()
        df["notional"] = df.price.astype(float) * df["size"].astype(float)
        # Map: side 'A' (ask hit) -> long liq (forced sell). side 'B' (bid hit) -> short liq (forced buy).
        df["is_long_liq"]  = (df.side == "A").astype(int)
        df["is_short_liq"] = (df.side == "B").astype(int)
        df = df.sort_values("time_exchange_us").reset_index(drop=True)
        source = "30d_proxy"
    else:
        df = full.copy()
        df["notional"] = df.price.astype(float) * df["size"].astype(float)
        # In full file, all 'true' liq rows have side='B'. Use dir to classify.
        df["is_long_liq"] = df.dir.str.contains("Long|Auto-Deleveraging", na=False).astype(int)
        df["is_short_liq"] = df.dir.str.contains("Short", na=False).astype(int)
        df = df.sort_values("time_exchange_us").reset_index(drop=True)
        source = "full_clean"

    return {
        "ts_us":     df.time_exchange_us.values.astype("int64"),
        "notional":  df.notional.values.astype("float64"),
        "long_n":    (df.notional.values.astype("float64") * df.is_long_liq.values.astype("float64")),
        "short_n":   (df.notional.values.astype("float64") * df.is_short_liq.values.astype("float64")),
        "source":    source,
        "n_rows":    len(df),
    }


def window_sums(arrs, fire_us: np.ndarray, lookback_us: int):
    """For each fire time, return (long_sum, short_sum) of notional in (fire-lookback, fire]."""
    ts = arrs["ts_us"]
    longn = arrs["long_n"]
    shortn = arrs["short_n"]
    # cumulative for fast window sums
    cum_long = np.concatenate([[0.0], np.cumsum(longn)])
    cum_short = np.concatenate([[0.0], np.cumsum(shortn)])
    lo_idx = np.searchsorted(ts, fire_us - lookback_us, side="left")
    hi_idx = np.searchsorted(ts, fire_us, side="right")
    long_sum = cum_long[hi_idx] - cum_long[lo_idx]
    short_sum = cum_short[hi_idx] - cum_short[lo_idx]
    return long_sum, short_sum


# ---------- Signal + sweep ----------

def signal(net: float, thr: float) -> str:
    if not np.isfinite(net):
        return "SKIP"
    if net > +thr:
        return "UP"
    if net < -thr:
        return "DOWN"
    return "SKIP"


def build_predictions(df_universe: pd.DataFrame, anchor: str, offset_s: int,
                      lookback_min: int, liq_arrs_per_asset: dict):
    """Add fire_us, long_sum, short_sum, net columns. anchor in {'ws_s','slot_end_minus'}."""
    df = df_universe.copy().reset_index(drop=True)
    if anchor == "ws_s":
        # use slug -> ws_s
        ws_arr = np.array([slug_to_ws_s(s, t)
                           for s, t in zip(df.slug.values, df.timeframe.values)], dtype="int64")
        fire_us = (ws_arr + offset_s) * 1_000_000
    elif anchor == "slot_end_minus":
        fire_us = df.slot_end_us.values.astype("int64") - offset_s * 1_000_000
    else:
        raise ValueError(anchor)
    df["fire_us"] = fire_us.astype("int64")

    lookback_us = lookback_min * 60 * 1_000_000
    parts = []
    for asset, g in df.groupby("ticker"):
        arrs = liq_arrs_per_asset.get(asset)
        if arrs is None or arrs["n_rows"] == 0:
            sub = g.copy()
            sub["long_sum"] = np.nan
            sub["short_sum"] = np.nan
            sub["net"] = np.nan
            parts.append(sub)
            continue
        ls, ss = window_sums(arrs, g.fire_us.values.astype("int64"), lookback_us)
        sub = g.copy()
        sub["long_sum"] = ls
        sub["short_sum"] = ss
        sub["net"] = ss - ls
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


def sweep(df_pred: pd.DataFrame, thresholds=(10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000)):
    rows = []
    for thr in thresholds:
        df_pred = df_pred.copy()
        df_pred["signal"] = df_pred.net.apply(lambda n: signal(n, thr))
        fired = df_pred[df_pred.signal.isin(("UP", "DOWN"))]
        if len(fired) < 1:
            continue
        won_g = (fired.signal.str.upper() == fired.outcome.str.upper()).mean()
        rows.append({"thr_usd": thr, "asset": "ALL", "n": len(fired), "hit": round(float(won_g), 4)})
        for asset, g in fired.groupby("ticker"):
            if len(g) < 50:
                continue
            won = (g.signal.str.upper() == g.outcome.str.upper()).mean()
            rows.append({"thr_usd": thr, "asset": asset, "n": len(g), "hit": round(float(won), 4)})
    return pd.DataFrame(rows)


# ---------- Main ----------

def run_variant(df_uni, anchor, offset_s, lookback_min, liq_arrs, label):
    print(f"\n=== {label}: anchor={anchor} offset={offset_s}s lookback={lookback_min}min ===")
    df_pred = build_predictions(df_uni, anchor, offset_s, lookback_min, liq_arrs)
    nf = df_pred[df_pred.net.notna() & (df_pred.net.abs() > 0)].shape[0]
    print(f"  rows: {len(df_pred)}  with non-zero net: {nf}")
    sw = sweep(df_pred)
    return df_pred, sw


def main():
    res = load_resolutions()
    print(f"universe: {len(res)} markets total")
    print(res.groupby(['ticker', 'timeframe']).size().to_string())

    # Sample to control runtime
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

    # Build liq arrays per asset (auto picks the file with rows IN window)
    W_LO = int(res.slot_start_us.min())
    W_HI = int(res.slot_end_us.max())
    print(f"  window: {pd.Timestamp(W_LO, unit='us', tz='UTC')} -> {pd.Timestamp(W_HI, unit='us', tz='UTC')}")
    liq_arrs = {}
    for asset in ("BTC", "ETH", "SOL"):
        liq_arrs[asset] = build_liq_arrays(asset, prefer="auto",
                                            window_lo_us=W_LO, window_hi_us=W_HI)
        print(f"  {asset} liq source={liq_arrs[asset]['source']} rows={liq_arrs[asset]['n_rows']}")

    df_5m = res_s[res_s.timeframe == "5m"].copy()
    df_15m = res_s[res_s.timeframe == "15m"].copy()

    # ---- 5m primary @ ws_s + 120 ----
    all_sweeps = []
    for lb in (5, 10):
        df_p, sw = run_variant(df_5m, "ws_s", 120, lb, liq_arrs, f"5m @ ws_s+120 lookback={lb}min")
        sw["variant"] = f"5m_ws120_lb{lb}"
        all_sweeps.append(sw)
        if lb == 5:
            sample_pred_5m = df_p

    # ---- 15m primary @ ws_s + 120 ----
    for lb in (5, 10):
        df_p, sw = run_variant(df_15m, "ws_s", 120, lb, liq_arrs, f"15m @ ws_s+120 lookback={lb}min")
        sw["variant"] = f"15m_ws120_lb{lb}"
        all_sweeps.append(sw)

    # ---- LATE-15m variant @ slot_end - 60 ----
    for lb in (5, 10):
        df_p, sw = run_variant(df_15m, "slot_end_minus", 60, lb, liq_arrs, f"15m @ slot_end-60 lookback={lb}min (LATE)")
        sw["variant"] = f"15m_late_lb{lb}"
        all_sweeps.append(sw)

    sweep_all = pd.concat(all_sweeps, ignore_index=True)
    out_csv = HERE / "strat_C_sweep.csv"
    sweep_all.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}  ({len(sweep_all)} rows)")

    # ---- No-lookahead sample ----
    print("\n=== sample no-lookahead trades (5m ws_s+120 lb=5min) ===")
    smp = sample_pred_5m[sample_pred_5m.net.notna() & (sample_pred_5m.net.abs() > 0)].head(3)
    sample_rows = []
    for _, row in smp.iterrows():
        ws_s = slug_to_ws_s(row.slug, row.timeframe)
        sample_rows.append({
            "slug": row.slug, "ticker": row.ticker, "tf": row.timeframe,
            "ws_s": int(ws_s),
            "fire_us": int(row.fire_us),
            "slot_end_us": int(row.slot_end_us),
            "lookback_lo_us": int(row.fire_us - 5 * 60 * 1_000_000),
            "fire_lt_slot_end (margin>=180s)":
                int(row.fire_us) < (int(row.slot_end_us) - 180 * 1_000_000),
            "long_sum_usd": round(float(row.long_sum), 2),
            "short_sum_usd": round(float(row.short_sum), 2),
            "net_usd": round(float(row.net), 2),
            "outcome": row.outcome,
        })
    sdf = pd.DataFrame(sample_rows)
    print(sdf.to_string(index=False))
    sdf.to_csv(HERE / "strat_C_lookahead_sample.csv", index=False)

    # ---- Top configs ----
    print("\n=== top configs (n>=200, ALL asset, sorted by hit) ===")
    if len(sweep_all) == 0 or "asset" not in sweep_all.columns:
        print("(no fires emitted - sweep is empty)")
    else:
        top = sweep_all[(sweep_all.asset == "ALL") & (sweep_all.n >= 200)].sort_values("hit", ascending=False).head(10)
        print(top.to_string(index=False) if len(top) else "(no configs with n>=200)")
        top_assets = sweep_all[(sweep_all.asset != "ALL") & (sweep_all.n >= 200)].sort_values("hit", ascending=False).head(10)
        print("\n=== top per-asset configs (n>=200) ===")
        print(top_assets.to_string(index=False) if len(top_assets) else "(no per-asset configs with n>=200)")


if __name__ == "__main__":
    main()
