"""
Strategy B - Cross-venue lead-lag.

Hypothesis: binance leads coinbase/kraken/okx. When binance moves but other
venues haven't caught up, expect mean reversion. When other venues move WITH
binance, expect continuation.

Universe: all 5m markets across BTC/ETH/SOL (~24k rows).
Conventions: UTC microseconds, chainlink outcome, asof_strict causal lookup,
ws_s anchor for primary fire, slot_end-60 anchor for LATE-15m variant.

Signals tested (per asset, per variant):
  A: binance leading + coinbase confirming -> if bn_ret>0 AND cb_ret>0 AND |lag|<eps -> UP (continuation)
  B: binance alone -> if bn_ret>0 AND cb_ret<=0 -> DOWN (mean revert)
  C: slower venue as truth -> sign(cb_ret)
Sweep eps and momentum threshold.
LATE-15m variant tested for 15m markets.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import (  # type: ignore
    get_klines, evaluate_no_book, slug_to_ws_s,
)
from load import asof_strict  # type: ignore


# ---------- Cross-venue plumbing ----------

VENUE_FALLBACK = {
    "BTC": ["coinbase-spot-ws", "kraken-spot-ws", "okx-ws"],
    "ETH": ["coinbase-spot-ws", "kraken-spot-ws", "okx-ws"],
    "SOL": ["coinbase-spot-ws", "kraken-spot-ws", "okx-ws"],
}


def fetch_returns(asset: str, fire_us: np.ndarray, lookback_us: int = 120_000_000):
    """For each fire_us, return (bn_ret, cb_ret, slower_venue_used).
    cb_ret falls back across [coinbase, kraken, okx] in order.

    bn_ret = bn_close(fire_us) / bn_close(fire_us - lookback) - 1
    """
    bn_end, bn_p = get_klines(asset, "binance-spot-ws", "1MIN")
    bn_now = np.array([asof_strict(bn_end, bn_p, int(t)) for t in fire_us], dtype=float)
    bn_prev = np.array([asof_strict(bn_end, bn_p, int(t) - lookback_us) for t in fire_us], dtype=float)
    bn_ret = bn_now / bn_prev - 1.0

    cb_ret = np.full_like(bn_ret, np.nan)
    venue_used = np.array(["none"] * len(fire_us), dtype=object)
    remaining = np.isnan(cb_ret)
    for venue in VENUE_FALLBACK[asset]:
        try:
            end, p = get_klines(asset, venue, "1MIN")
            if len(end) == 0:
                continue
        except Exception:
            continue
        idx = np.where(remaining)[0]
        for i in idx:
            t = int(fire_us[i])
            now = asof_strict(end, p, t)
            prev = asof_strict(end, p, t - lookback_us)
            if np.isfinite(now) and np.isfinite(prev) and prev > 0:
                cb_ret[i] = now / prev - 1.0
                venue_used[i] = venue
        remaining = np.isnan(cb_ret)
        if not remaining.any():
            break

    return bn_ret, cb_ret, venue_used


def build_predictions(df: pd.DataFrame, anchor: str, offset_s: int):
    """Add columns bn_ret/cb_ret/lag/fire_us. anchor in {'ws_s','slot_end_minus'}."""
    df = df.copy().reset_index(drop=True)
    if anchor == "ws_s":
        ws_s = df.slug.apply(lambda s: slug_to_ws_s(s, df.loc[df.slug == s, "timeframe"].iat[0]))
        fire_us = (ws_s.values + offset_s) * 1_000_000
    elif anchor == "slot_end_minus":
        fire_us = (df.slot_end_us.values.astype("int64") - offset_s * 1_000_000)
    else:
        raise ValueError(anchor)
    df["fire_us"] = fire_us.astype("int64")

    parts = []
    for asset, g in df.groupby("ticker"):
        bn, cb, vu = fetch_returns(asset, g.fire_us.values)
        sub = g.copy()
        sub["bn_ret"] = bn
        sub["cb_ret"] = cb
        sub["venue"] = vu
        sub["lag"] = bn - cb
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


def signal_variant(row, variant: str, eps: float, thr: float):
    bn, cb, lag = row.bn_ret, row.cb_ret, row.lag
    if not (np.isfinite(bn) and np.isfinite(cb)):
        return "SKIP"
    if variant == "A":   # confirmation -> continuation
        if abs(lag) < eps:
            if bn > thr and cb > 0:
                return "UP"
            if bn < -thr and cb < 0:
                return "DOWN"
        return "SKIP"
    if variant == "B":   # binance alone -> mean revert
        if bn > thr and cb <= 0:
            return "DOWN"
        if bn < -thr and cb >= 0:
            return "UP"
        return "SKIP"
    if variant == "C":   # slower venue as truth
        if cb > thr:
            return "UP"
        if cb < -thr:
            return "DOWN"
        return "SKIP"
    raise ValueError(variant)


# ---------- sweep + reporting ----------

def sweep(df_pred: pd.DataFrame):
    """Return DataFrame of (variant, eps_bp, thr_bp, asset, n, hit, pnl)."""
    rows = []
    eps_grid = [5e-5, 1e-4, 2e-4, 5e-4]      # 0.5bp, 1bp, 2bp, 5bp (only used by A)
    thr_grid = [0.0, 5e-5, 1e-4, 2e-4, 5e-4]  # 0, 0.5bp, 1bp, 2bp, 5bp
    for variant in ("A", "B", "C"):
        for eps in eps_grid:
            for thr in thr_grid:
                df_pred = df_pred.copy()
                df_pred["signal"] = df_pred.apply(
                    lambda r: signal_variant(r, variant, eps, thr), axis=1
                )
                fired = df_pred[df_pred.signal.isin(("UP", "DOWN"))]
                if len(fired) < 1:
                    continue
                # global metrics
                won_g = (fired.signal.str.upper() == fired.outcome.str.upper()).mean()
                rows.append({
                    "variant": variant, "eps_bp": eps * 1e4, "thr_bp": thr * 1e4,
                    "asset": "ALL", "n": len(fired), "hit": round(float(won_g), 4),
                })
                for asset, g in fired.groupby("ticker"):
                    if len(g) < 50:
                        continue
                    won = (g.signal.str.upper() == g.outcome.str.upper()).mean()
                    rows.append({
                        "variant": variant, "eps_bp": eps * 1e4, "thr_bp": thr * 1e4,
                        "asset": asset, "n": len(g), "hit": round(float(won), 4),
                    })
            if variant != "A":
                break  # B/C ignore eps
    return pd.DataFrame(rows)


def run_anchor(df_universe: pd.DataFrame, anchor: str, offset_s: int, label: str):
    print(f"\n=== {label} ===")
    df_pred = build_predictions(df_universe, anchor, offset_s)
    n_avail = df_pred[df_pred.bn_ret.notna() & df_pred.cb_ret.notna()].shape[0]
    print(f"  rows: {len(df_pred)}  with cross-venue both: {n_avail}")
    print(f"  venue fallback used (top 4):")
    print(df_pred.venue.value_counts().head(4).to_string())
    sweep_df = sweep(df_pred)
    return df_pred, sweep_df


def main():
    sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))
    from load import load_resolutions
    res = load_resolutions()  # 5m and 15m
    print(f"universe: {len(res)} markets total")
    print(res.groupby(['ticker', 'timeframe']).size().to_string())

    # --- Sample down if huge to control runtime ---
    SAMPLE_PER = 2500
    df_5m = res[res.timeframe == "5m"]
    df_15m = res[res.timeframe == "15m"]
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        sub5 = df_5m[df_5m.ticker == asset]
        sub15 = df_15m[df_15m.ticker == asset]
        if len(sub5) > SAMPLE_PER:
            sub5 = sub5.sample(SAMPLE_PER, random_state=42)
        if len(sub15) > SAMPLE_PER:
            sub15 = sub15.sample(SAMPLE_PER, random_state=42)
        parts.append(sub5)
        parts.append(sub15)
    res_s = pd.concat(parts, ignore_index=True)
    print(f"sampled to {len(res_s)} rows")

    # --- Primary fire: ws_s + 120 (5m markets) ---
    df5 = res_s[res_s.timeframe == "5m"].copy()
    df5_pred, sweep5 = run_anchor(df5, "ws_s", 120, "5m markets @ ws_s+120")

    # --- LATE-15m variant: 15m markets fired at slot_end - 60 ---
    df15 = res_s[res_s.timeframe == "15m"].copy()
    df15_pred, sweep15 = run_anchor(df15, "slot_end_minus", 60, "15m markets @ slot_end-60s")

    # --- Dump for report ---
    OUT = HERE
    sweep5.to_csv(OUT / "strat_B_sweep_5m.csv", index=False)
    sweep15.to_csv(OUT / "strat_B_sweep_15m_late.csv", index=False)

    # --- No-lookahead sample ---
    print("\n=== sample no-lookahead trades (5m, variant A best row guess) ===")
    print("(fire_us, bn_now ts, cb_now ts, slot_end_us) - all venue lookups <= fire_us by construction")
    smp = df5_pred[df5_pred.bn_ret.notna() & df5_pred.cb_ret.notna()].head(3)
    sample_rows = []
    for _, row in smp.iterrows():
        ws_s = slug_to_ws_s(row.slug, row.timeframe)
        sample_rows.append({
            "slug": row.slug, "ticker": row.ticker,
            "ws_s": ws_s,
            "fire_us": int(row.fire_us),
            "slot_end_us": int(row.slot_end_us),
            "fire <= slot_end-180s (margin)": int(row.fire_us) < (int(row.slot_end_us) - 180 * 1_000_000),
            "bn_ret": round(float(row.bn_ret), 6),
            "cb_ret": round(float(row.cb_ret), 6),
            "outcome": row.outcome,
        })
    pd.DataFrame(sample_rows).to_csv(OUT / "strat_B_lookahead_sample.csv", index=False)
    print(pd.DataFrame(sample_rows).to_string(index=False))

    # ----- Top configs ALL-asset summary -----
    print("\n=== sweep 5m head (sorted by hit, n>=200, ALL asset) ===")
    top = sweep5[(sweep5.asset == "ALL") & (sweep5.n >= 200)].sort_values("hit", ascending=False).head(10)
    print(top.to_string(index=False))

    print("\n=== sweep 15m LATE head (sorted by hit, n>=200, ALL asset) ===")
    top15 = sweep15[(sweep15.asset == "ALL") & (sweep15.n >= 200)].sort_values("hit", ascending=False).head(10)
    print(top15.to_string(index=False))


if __name__ == "__main__":
    main()
