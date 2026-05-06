"""Phase 4 — Signal-quality Kelly sizing.

Hypothesis: fires where |ret_5m| is FAR above threshold should hit harder than
those barely above. Test by binning V3 fires by signal_strength = |ret_5m| / threshold,
compare hit rates.

If high-strength fires hit >5pp better than low-strength, adopt Kelly multiplier.

Sizing rule (final):
  ratio = |ret_5m| / threshold   (>= 1.0 always since fired)
  multiplier = clip(0.5 + (ratio - 1.0) * 0.5, 0.5, 1.5)
    ratio=1.0 -> 0.5x bet (barely above threshold)
    ratio=2.0 -> 1.0x bet (2x threshold)
    ratio=3.0 -> 1.5x bet (max)

Then test simulated PnL with this multiplier vs flat sizing.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, chronological_split

NOTIONAL = 25.0; FEE = 0.02; SLIP = 0.05

V3_CELLS = {
    "btc_5m_q10":          {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5":           {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "sol_5m_q15_multi":    {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}


def kelly_multiplier(ratio: np.ndarray) -> np.ndarray:
    """ratio = |ret_5m| / threshold. Maps to multiplier in [0.5, 1.5]."""
    return np.clip(0.5 + (ratio - 1.0) * 0.5, 0.5, 1.5)


def evaluate_pnl(df, slip, sized=False):
    if len(df) == 0:
        return df.assign(pnl_after=0.0, hit=False, notional=0.0)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    cost = np.clip(cost + slip, 0.01, 0.99)

    if sized:
        notional = NOTIONAL * df["kelly_mult"].values
    else:
        notional = np.full(len(df), NOTIONAL)

    shares = notional / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    out = df.copy()
    out["hit"] = hit
    out["notional"] = notional
    out["pnl_after"] = pnl_after
    return out


def run_sleeve(name, cell):
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
        thr_q = train_f["ret_5m"].abs().quantile(1 - cell["mag"])
    else:
        train_f, holdout_f = train, holdout
        thr_q = train_f["ret_5m"].abs().quantile(1 - cell["mag"])

    train_fired = train_f[train_f["ret_5m"].abs() >= thr_q].copy()
    holdout_fired = holdout_f[holdout_f["ret_5m"].abs() >= thr_q].copy()

    for d in (train_fired, holdout_fired):
        d["signal_ratio"] = d["ret_5m"].abs() / thr_q
        d["kelly_mult"] = kelly_multiplier(d["signal_ratio"].values)

    return train_fired, holdout_fired, thr_q


def main():
    for name, cell in V3_CELLS.items():
        train_f, ho_f, thr = run_sleeve(name, cell)
        print(f"\n=== {name} (threshold={thr:.5f}, train_fires={len(train_f)}, ho_fires={len(ho_f)}) ===")

        # Bin holdout by signal_ratio
        bins = [(1.00, 1.25), (1.25, 1.50), (1.50, 2.00), (2.00, 999)]
        for lo, hi in bins:
            sub = ho_f[(ho_f["signal_ratio"] >= lo) & (ho_f["signal_ratio"] < hi)]
            ev = evaluate_pnl(sub, SLIP, sized=False)
            if len(ev) > 0:
                print(f"  ratio [{lo:.2f},{hi:.2f}): n={len(ev):>3d}  hit={ev['hit'].mean()*100:5.1f}%  pnl_flat=${ev['pnl_after'].sum():+8.2f}  avg_mult={sub['kelly_mult'].mean():.2f}x")

        # Compute total PnL with flat vs Kelly-sized
        flat = evaluate_pnl(ho_f, SLIP, sized=False)
        kelly = evaluate_pnl(ho_f, SLIP, sized=True)
        flat_pnl = flat["pnl_after"].sum()
        kelly_pnl = kelly["pnl_after"].sum()
        flat_notional = flat["notional"].sum()
        kelly_notional = kelly["notional"].sum()
        print(f"  FLAT:  pnl=${flat_pnl:+.2f} on ${flat_notional:.0f} notional ({flat_pnl/flat_notional*100:+.2f}% ROI)")
        print(f"  KELLY: pnl=${kelly_pnl:+.2f} on ${kelly_notional:.0f} notional ({kelly_pnl/kelly_notional*100:+.2f}% ROI)")
        print(f"  Kelly delta: pnl ${kelly_pnl - flat_pnl:+.2f}, capital saved ${flat_notional - kelly_notional:+.0f}")


if __name__ == "__main__":
    main()
