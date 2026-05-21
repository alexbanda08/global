"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""V3 + directional regime filter — backtest evaluation.

Hypothesis: sniper UP signals fail when 1h trend is DOWN (mean-revert), and vice versa.
Fix: only fire UP if NOT in strong downtrend; only fire DOWN if NOT in strong uptrend.

Tests three regime gates:
  - none  (baseline V3)
  - soft  (skip UP if ret_1h < -0.5%; skip DOWN if ret_1h > +0.5%)
  - strict (skip UP if ret_1h < -0.2%; skip DOWN if ret_1h > +0.2%)

Reports per-direction hit rate + PnL for backtest holdout (chronological 80/20 split).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, chronological_split

NOTIONAL = 25.0
FEE = 0.02
SLIPPAGE_PP = 0.05  # realistic L10 haircut

V3_CELLS = {
    "btc_5m_q10":          {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5":           {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "sol_5m_q15_multi":    {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}


def evaluate_pnl(df, slippage_pp=0.0):
    if len(df) == 0:
        return df.assign(pnl_after=0.0, hit=False)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    cost = np.clip(cost + slippage_pp, 0.01, 0.99)
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    out = df.copy()
    out["hit"] = hit
    out["pnl_after"] = pnl_after
    out["direction"] = np.where(pred_up, "UP", "DOWN")
    return out


def run_sleeve(name, cell, regime_threshold=None, slippage_pp=SLIPPAGE_PP):
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

    train_fired = train_f[train_f["ret_5m"].abs() >= thr]
    holdout_fired = holdout_f[holdout_f["ret_5m"].abs() >= thr]

    # Apply regime filter
    if regime_threshold is not None:
        # UP signals: skip if ret_1h < -threshold (strong downtrend, blip will revert)
        # DOWN signals: skip if ret_1h > +threshold (strong uptrend, blip will revert)
        def regime_pass(df):
            up = df["ret_5m"] > 0
            ok_up = up & (df["ret_1h"] >= -regime_threshold)
            ok_down = (~up) & (df["ret_1h"] <= regime_threshold)
            return df[ok_up | ok_down]
        train_fired = regime_pass(train_fired)
        holdout_fired = regime_pass(holdout_fired)

    tr = evaluate_pnl(train_fired, slippage_pp); tr["split"] = "train"
    ho = evaluate_pnl(holdout_fired, slippage_pp); ho["split"] = "holdout"
    out = pd.concat([tr, ho], ignore_index=True)
    out["sleeve"] = name
    return out


def summary(df, label):
    n = len(df); hit = df["hit"].mean() if n else 0
    pnl = df["pnl_after"].sum()
    notional = n * NOTIONAL
    roi = pnl / notional * 100 if notional else 0
    return f"{label:<30} n={n:>4d} hit={hit*100:5.1f}% pnl=${pnl:>+8.2f} roi={roi:+6.2f}%"


def per_direction(df, label):
    print(f"  {label}:")
    for d in ("UP", "DOWN"):
        sub = df[df["direction"] == d]
        n = len(sub); hit = sub["hit"].mean() if n else 0
        pnl = sub["pnl_after"].sum()
        roi = pnl / (n * NOTIONAL) * 100 if n else 0
        print(f"    {d:<5} n={n:>4d} hit={hit*100:5.1f}% pnl=${pnl:>+8.2f} roi={roi:+6.2f}%")


def main():
    for label, regime_thr in [
        ("V3 baseline (no regime filter)", None),
        ("V3 + soft regime filter (±0.5%)", 0.005),
        ("V3 + strict regime filter (±0.2%)", 0.002),
        ("V3 + tight regime filter (±0.1%)", 0.001),
    ]:
        print(f"\n{'='*78}")
        print(f"{label}  (NOTIONAL=${NOTIONAL}, slip={SLIPPAGE_PP*100}pp)")
        print(f"{'='*78}")

        all_rows = []
        for name, cell in V3_CELLS.items():
            d = run_sleeve(name, cell, regime_threshold=regime_thr)
            all_rows.append(d)
            ho = d[d["split"] == "holdout"]
            print(f"  {summary(ho, name + ' [holdout]')}")
            per_direction(ho, "    direction")

        combined = pd.concat(all_rows, ignore_index=True)
        ho_combined = combined[combined["split"] == "holdout"]
        tr_combined = combined[combined["split"] == "train"]
        print(f"  --- COMBINED ---")
        print(f"  {summary(tr_combined, 'PORTFOLIO [train]')}")
        print(f"  {summary(ho_combined, 'PORTFOLIO [holdout]')}")


if __name__ == "__main__":
    main()
