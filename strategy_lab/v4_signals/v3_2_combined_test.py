"""V3.2 — Combined patch test.

Applies all three adopted improvements together:
  - Phase 1: hour blocklist {1, 16, 22} UTC
  - Phase 3: 2-of-3 timeframe alignment (at least 1 of 15m/1h agrees with 5m sign)
  - Phase 5: liq quiet gate (skip if 5m liq notional > $10k)

Compares to V3 baseline on 7-day forward-walk holdout.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from strategy_lab.v2_signals.common import load_features, chronological_split

ROOT = Path(__file__).resolve().parents[2]
REFRESH = ROOT / "data" / "v4" / "refresh_2026_04_30"

NOTIONAL = 25.0; FEE = 0.02; SLIP = 0.05
HOUR_BLOCKLIST = {1, 16, 22}
LIQ_QUIET_USD = 10_000

V3_CELLS = {
    "btc_5m_q10":          {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5":           {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "sol_5m_q15_multi":    {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}


def load_binance_liq() -> pd.DataFrame:
    df = pd.read_csv(REFRESH / "binance_liq.csv")
    df["ts_unix"] = (df["time_exchange_us"] / 1e6).astype("int64")
    df["asset"] = df["symbol_id"].str.extract(r"PERP_(\w+)_USDT")[0].str.lower()
    df["notional"] = df["price"].astype(float) * df["size"].astype(float)
    return df[["ts_unix", "asset", "notional"]].sort_values("ts_unix").reset_index(drop=True)


def add_liq_5m(feats: pd.DataFrame, asset: str, liq_all: pd.DataFrame) -> pd.DataFrame:
    liq = liq_all[liq_all["asset"] == asset]
    liq_t = liq["ts_unix"].to_numpy()
    liq_n = liq["notional"].to_numpy()
    q = feats["window_start_unix"].to_numpy()
    lo = np.searchsorted(liq_t, q - 300, side="left")
    hi = np.searchsorted(liq_t, q, side="right")
    total_5m = np.array([liq_n[a:b].sum() if b > a else 0.0 for a, b in zip(lo, hi)])
    feats = feats.copy()
    feats["liq_total_5m"] = total_5m
    # Mark whether liq data is available for this market (within liq window coverage)
    if len(liq_t) > 0:
        feats["liq_data_available"] = (feats["window_start_unix"] >= liq_t.min()) & (feats["window_start_unix"] <= liq_t.max())
    else:
        feats["liq_data_available"] = False
    return feats


def hour_passes(window_start_unix: pd.Series) -> pd.Series:
    hour = pd.to_datetime(window_start_unix, unit="s", utc=True).dt.hour
    return ~hour.isin(HOUR_BLOCKLIST)


def macro_2of3_passes(df: pd.DataFrame) -> pd.Series:
    sign5 = np.sign(df["ret_5m"])
    agree_15 = (np.sign(df["ret_15m"]) == sign5).astype(int)
    agree_1h = (np.sign(df["ret_1h"]) == sign5).astype(int)
    return (agree_15 + agree_1h) >= 1


def liq_quiet_passes(df: pd.DataFrame) -> pd.Series:
    """Skip if 5m liq notional > threshold. If liq data unavailable, pass through (don't block)."""
    has_liq = df["liq_data_available"]
    quiet = df["liq_total_5m"] <= LIQ_QUIET_USD
    return (~has_liq) | quiet  # pass if no liq data OR quiet


def evaluate_pnl(df, slip):
    if len(df) == 0: return df.assign(pnl_after=0.0, hit=False)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    cost = np.clip(cost + slip, 0.01, 0.99)
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    out = df.copy()
    out["hit"] = hit
    out["pnl_after"] = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    out["direction"] = np.where(pred_up, "UP", "DOWN")
    return out


def run_sleeve(name, cell, gates):
    """gates = list of strings: 'hour', 'macro2of3', 'liq_quiet'"""
    feats = load_features(cell["asset"]).dropna(
        subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
    )
    feats = feats[feats["timeframe"] == cell["tf"]]
    train, holdout = chronological_split(feats)

    if cell["selector"] == "multi_horizon":
        same_tr = ((train["ret_5m"] > 0) & (train["ret_15m"] > 0) & (train["ret_1h"] > 0)) | \
                  ((train["ret_5m"] < 0) & (train["ret_15m"] < 0) & (train["ret_1h"] < 0))
        same_ho = ((holdout["ret_5m"] > 0) & (holdout["ret_15m"] > 0) & (holdout["ret_1h"] > 0)) | \
                  ((holdout["ret_5m"] < 0) & (holdout["ret_15m"] < 0) & (holdout["ret_1h"] < 0))
        train_f, holdout_f = train[same_tr], holdout[same_ho]
        thr = train_f["ret_5m"].abs().quantile(1 - cell["mag"])
    else:
        train_f, holdout_f = train, holdout
        thr = train_f["ret_5m"].abs().quantile(1 - cell["mag"])

    train_fired = train_f[train_f["ret_5m"].abs() >= thr].copy()
    holdout_fired = holdout_f[holdout_f["ret_5m"].abs() >= thr].copy()

    if "liq_quiet" in gates:
        liq_all = load_binance_liq()
        train_fired = add_liq_5m(train_fired, cell["asset"], liq_all)
        holdout_fired = add_liq_5m(holdout_fired, cell["asset"], liq_all)
    if "hour" in gates:
        train_fired = train_fired[hour_passes(train_fired["window_start_unix"])]
        holdout_fired = holdout_fired[hour_passes(holdout_fired["window_start_unix"])]
    if "macro2of3" in gates and cell["selector"] != "multi_horizon":
        # SOL already has 3-of-3 multi-horizon, so skip 2-of-3 gate (would be redundant)
        train_fired = train_fired[macro_2of3_passes(train_fired)]
        holdout_fired = holdout_fired[macro_2of3_passes(holdout_fired)]
    if "liq_quiet" in gates:
        train_fired = train_fired[liq_quiet_passes(train_fired)]
        holdout_fired = holdout_fired[liq_quiet_passes(holdout_fired)]

    tr = evaluate_pnl(train_fired, SLIP); tr["split"] = "train"
    ho = evaluate_pnl(holdout_fired, SLIP); ho["split"] = "holdout"
    out = pd.concat([tr, ho], ignore_index=True)
    out["sleeve"] = name
    return out


def summary(df, label):
    n = len(df); hit = df["hit"].mean() if n else 0
    pnl = df["pnl_after"].sum()
    notional = n * NOTIONAL
    roi = pnl / notional * 100 if notional else 0
    return f"{label:<32} n={n:>4d} hit={hit*100:5.1f}% pnl=${pnl:>+8.2f} roi={roi:+6.2f}%"


def main():
    variants = [
        ("V3 baseline (no gates)",                []),
        ("V3 + hour block",                       ["hour"]),
        ("V3 + macro 2-of-3",                     ["macro2of3"]),
        ("V3 + liq quiet",                        ["liq_quiet"]),
        ("V3 + hour + macro 2-of-3",              ["hour", "macro2of3"]),
        ("V3 + hour + macro + liq (V3.2 FULL)",   ["hour", "macro2of3", "liq_quiet"]),
    ]
    print(f"V3.2 combined patch test  (NOTIONAL=${NOTIONAL}, slip={SLIP*100}pp)\n")

    for label, gates in variants:
        print(f"=== {label} ===")
        all_rows = []
        for name, cell in V3_CELLS.items():
            d = run_sleeve(name, cell, gates)
            all_rows.append(d)
            ho = d[d["split"] == "holdout"]
            print(f"  {summary(ho, name + ' [HO]')}")
        combined = pd.concat(all_rows, ignore_index=True)
        ho_c = combined[combined["split"] == "holdout"]
        tr_c = combined[combined["split"] == "train"]
        print(f"  --- COMBINED ---")
        print(f"  {summary(tr_c, 'PORTFOLIO [TRAIN]')}")
        print(f"  {summary(ho_c, 'PORTFOLIO [HO]')}")
        print()


if __name__ == "__main__":
    main()
