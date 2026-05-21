"""
Strategy F - Cross-asset (BTC leads ETH/SOL).

Hypothesis: BTC moves first; ETH/SOL inherit direction.

Universe: ETH and SOL 5m markets.
Signal at fire_us = (ws_s + 120) * 1e6:
  btc_ret = binance.BTC.close(fire_us) / binance.BTC.close(fire_us - 120s) - 1
  signal: UP if btc_ret > +thr, DOWN if btc_ret < -thr, else SKIP.

Sweep thr in {0, 5bp, 10bp, 20bp, 50bp}.
Variant: consensus = require BTC's own spot return aligned with ETH/SOL spot
return over the same window.
LATE-15m variant: same logic at slot_end - 60s for 15m markets.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import (  # type: ignore
    get_klines, slug_to_ws_s,
)
from load import asof_strict  # type: ignore


def fetch_btc_and_self(asset: str, fire_us: np.ndarray, lookback_us: int = 120_000_000):
    """Returns (btc_ret, self_ret) arrays. self_ret is the row's asset spot ret."""
    btc_end, btc_p = get_klines("BTC", "binance-spot-ws", "1MIN")
    btc_now = np.array([asof_strict(btc_end, btc_p, int(t)) for t in fire_us], dtype=float)
    btc_prev = np.array([asof_strict(btc_end, btc_p, int(t) - lookback_us) for t in fire_us], dtype=float)
    btc_ret = btc_now / btc_prev - 1.0

    self_end, self_p = get_klines(asset, "binance-spot-ws", "1MIN")
    self_now = np.array([asof_strict(self_end, self_p, int(t)) for t in fire_us], dtype=float)
    self_prev = np.array([asof_strict(self_end, self_p, int(t) - lookback_us) for t in fire_us], dtype=float)
    self_ret = self_now / self_prev - 1.0
    return btc_ret, self_ret


def build_predictions(df: pd.DataFrame, anchor: str, offset_s: int):
    df = df.copy().reset_index(drop=True)
    if anchor == "ws_s":
        fire_us = np.array(
            [(slug_to_ws_s(s, tf) + offset_s) * 1_000_000
             for s, tf in zip(df.slug, df.timeframe)], dtype="int64")
    elif anchor == "slot_end_minus":
        fire_us = df.slot_end_us.values.astype("int64") - offset_s * 1_000_000
    else:
        raise ValueError(anchor)
    df["fire_us"] = fire_us

    parts = []
    for asset, g in df.groupby("ticker"):
        if asset not in ("ETH", "SOL"):
            continue
        btc_ret, self_ret = fetch_btc_and_self(asset, g.fire_us.values)
        sub = g.copy()
        sub["btc_ret"] = btc_ret
        sub["self_ret"] = self_ret
        parts.append(sub)
    if not parts:
        return df.iloc[0:0]
    return pd.concat(parts, ignore_index=True)


def signal_basic(row, thr: float):
    if not np.isfinite(row.btc_ret):
        return "SKIP"
    if row.btc_ret > thr:
        return "UP"
    if row.btc_ret < -thr:
        return "DOWN"
    return "SKIP"


def signal_consensus(row, thr: float):
    if not (np.isfinite(row.btc_ret) and np.isfinite(row.self_ret)):
        return "SKIP"
    if row.btc_ret > thr and row.self_ret > 0:
        return "UP"
    if row.btc_ret < -thr and row.self_ret < 0:
        return "DOWN"
    return "SKIP"


def sweep(df_pred: pd.DataFrame):
    rows = []
    thr_grid = [0.0, 5e-5, 1e-4, 2e-4, 5e-4]  # 0, 0.5, 1, 2, 5 bp
    for variant, fn in (("basic", signal_basic), ("consensus", signal_consensus)):
        for thr in thr_grid:
            tmp = df_pred.copy()
            tmp["signal"] = tmp.apply(lambda r: fn(r, thr), axis=1)
            fired = tmp[tmp.signal.isin(("UP", "DOWN"))]
            if len(fired) < 1:
                continue
            won_g = (fired.signal.str.upper() == fired.outcome.str.upper()).mean()
            rows.append({"variant": variant, "thr_bp": thr * 1e4,
                         "asset": "ALL", "n": len(fired), "hit": round(float(won_g), 4)})
            for asset, g in fired.groupby("ticker"):
                if len(g) < 50:
                    continue
                won = (g.signal.str.upper() == g.outcome.str.upper()).mean()
                rows.append({"variant": variant, "thr_bp": thr * 1e4,
                             "asset": asset, "n": len(g), "hit": round(float(won), 4)})
    return pd.DataFrame(rows)


def run_anchor(df_universe: pd.DataFrame, anchor: str, offset_s: int, label: str):
    print(f"\n=== {label} ===")
    df_pred = build_predictions(df_universe, anchor, offset_s)
    n_avail = df_pred[df_pred.btc_ret.notna()].shape[0]
    print(f"  rows: {len(df_pred)}  with btc_ret defined: {n_avail}")
    sweep_df = sweep(df_pred)
    return df_pred, sweep_df


def main():
    sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))
    from load import load_resolutions
    res = load_resolutions(assets=["ETH", "SOL"])  # both timeframes
    print(f"universe: {len(res)} ETH/SOL markets")
    print(res.groupby(['ticker', 'timeframe']).size().to_string())

    # --- Sample for runtime control ---
    SAMPLE_PER = 2500
    parts = []
    for asset in ("ETH", "SOL"):
        for tf in ("5m", "15m"):
            sub = res[(res.ticker == asset) & (res.timeframe == tf)]
            if len(sub) > SAMPLE_PER:
                sub = sub.sample(SAMPLE_PER, random_state=42)
            parts.append(sub)
    res_s = pd.concat(parts, ignore_index=True)
    print(f"sampled to {len(res_s)} rows")

    # --- Primary: 5m markets at ws_s + 120 ---
    df5 = res_s[res_s.timeframe == "5m"].copy()
    df5_pred, sweep5 = run_anchor(df5, "ws_s", 120, "5m markets @ ws_s+120")

    # --- LATE: 15m markets at slot_end - 60 ---
    df15 = res_s[res_s.timeframe == "15m"].copy()
    df15_pred, sweep15 = run_anchor(df15, "slot_end_minus", 60, "15m markets @ slot_end-60s")

    OUT = HERE
    sweep5.to_csv(OUT / "strat_F_sweep_5m.csv", index=False)
    sweep15.to_csv(OUT / "strat_F_sweep_15m_late.csv", index=False)

    # --- No-lookahead sample ---
    print("\n=== sample no-lookahead trades (5m) ===")
    smp = df5_pred[df5_pred.btc_ret.notna()].head(3)
    sample_rows = []
    for _, row in smp.iterrows():
        ws_s = slug_to_ws_s(row.slug, row.timeframe)
        sample_rows.append({
            "slug": row.slug, "ticker": row.ticker,
            "ws_s": ws_s, "fire_us": int(row.fire_us),
            "slot_end_us": int(row.slot_end_us),
            "fire <= slot_end-180s": int(row.fire_us) < (int(row.slot_end_us) - 180 * 1_000_000),
            "btc_ret": round(float(row.btc_ret), 6),
            "self_ret": round(float(row.self_ret), 6),
            "outcome": row.outcome,
        })
    pd.DataFrame(sample_rows).to_csv(OUT / "strat_F_lookahead_sample.csv", index=False)
    print(pd.DataFrame(sample_rows).to_string(index=False))

    print("\n=== sweep 5m head (n>=200, ALL asset, by hit desc) ===")
    top = sweep5[(sweep5.asset == "ALL") & (sweep5.n >= 200)].sort_values("hit", ascending=False).head(10)
    print(top.to_string(index=False))

    print("\n=== sweep 15m LATE head (n>=200, ALL asset, by hit desc) ===")
    top15 = sweep15[(sweep15.asset == "ALL") & (sweep15.n >= 200)].sort_values("hit", ascending=False).head(10)
    print(top15.to_string(index=False))

    # ---- per-asset best for verdict ----
    print("\n=== best per asset (5m primary) ===")
    for asset in ("ETH", "SOL"):
        sub = sweep5[(sweep5.asset == asset) & (sweep5.n >= 200)]
        if len(sub) == 0:
            print(f"  {asset}: no row with n>=200"); continue
        bestrow = sub.sort_values("hit", ascending=False).iloc[0]
        print(f"  {asset}: {bestrow.to_dict()}")


if __name__ == "__main__":
    main()
