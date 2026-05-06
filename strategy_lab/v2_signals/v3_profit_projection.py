"""V3 profit projection at $50/market for 1 week.

Re-runs the validated 3-sleeve portfolio (BTC q10 mag-only, ETH q5 mag-only,
SOL q15 multi-horizon, 5m only) with NOTIONAL=50 and prints:
  - Per-sleeve PnL (train, holdout, full 7-day)
  - Combined PnL
  - Per-day mean and 1-week extrapolation
  - Realistic-fill haircut (5pp slippage, per G3 gate)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, chronological_split

NOTIONAL = 50.0
FEE = 0.02
SLIPPAGE_PP = 0.05  # G3: 5pp haircut for realistic L10 fills

V3_CELLS = {
    "BTC_5m_q10":          {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "ETH_5m_q5":           {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "SOL_5m_q15_multi":    {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}


def evaluate_pnl(df, slippage_pp: float = 0.0):
    if len(df) == 0:
        return df.assign(pnl_after=0.0, hit=False)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    cost = np.clip(cost + slippage_pp, 0.01, 0.99)  # haircut
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    out = df.copy()
    out["hit"] = hit
    out["pnl_after"] = pnl_after
    return out


def run_sleeve(name, cell, slippage_pp=0.0):
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

    tr = evaluate_pnl(train_fired, slippage_pp)
    ho = evaluate_pnl(holdout_fired, slippage_pp)
    tr["split"], ho["split"] = "train", "holdout"
    out = pd.concat([tr, ho], ignore_index=True)
    out["sleeve"] = name
    out["thr"] = thr
    return out


def summarize(df, label):
    n = len(df)
    if n == 0:
        return f"{label:<22} n=0"
    hit = df["hit"].mean() * 100
    pnl = df["pnl_after"].sum()
    notional = n * NOTIONAL
    roi = (pnl / notional) * 100 if notional else 0.0
    return f"{label:<22} n={n:>4d} hit={hit:5.1f}% pnl=${pnl:>+9.2f} roi={roi:+6.2f}% notional=${notional:>8.2f}"


def main():
    for slippage, tag in [(0.0, "TOP-OF-ASK"), (SLIPPAGE_PP, "REALISTIC L10 (5pp haircut)")]:
        print(f"\n{'='*78}")
        print(f"V3 PORTFOLIO @ ${NOTIONAL:.0f}/market — {tag}")
        print(f"{'='*78}")

        all_rows = []
        for name, cell in V3_CELLS.items():
            sleeve_df = run_sleeve(name, cell, slippage_pp=slippage)
            all_rows.append(sleeve_df)
            for split in ["train", "holdout"]:
                s = sleeve_df[sleeve_df["split"] == split]
                print(f"  {summarize(s, f'{name} [{split}]')}")
        combined = pd.concat(all_rows, ignore_index=True)

        print(f"\n  --- COMBINED PORTFOLIO ---")
        for split in ["train", "holdout"]:
            s = combined[combined["split"] == split]
            print(f"  {summarize(s, f'PORTFOLIO [{split}]')}")
        full = combined
        print(f"  {summarize(full, 'PORTFOLIO [full 7d]')}")

        # Per-day breakdown (full window)
        full = full.copy()
        full["day"] = pd.to_datetime(full["window_start_unix"], unit="s", errors="coerce").dt.date
        per_day = full.groupby("day").agg(
            n=("pnl_after", "size"),
            pnl=("pnl_after", "sum"),
            hit=("hit", "mean"),
        ).reset_index()
        per_day["roi"] = per_day["pnl"] / (per_day["n"] * NOTIONAL) * 100
        print(f"\n  Per-day PnL (full 7d window):")
        for _, r in per_day.iterrows():
            print(f"    {r['day']}  n={int(r['n']):>3d}  hit={r['hit']*100:5.1f}%  pnl=${r['pnl']:>+8.2f}  roi={r['roi']:+6.2f}%")

        # 1-week projection: if 7d is the full window, total PnL IS the 1-week number.
        days = len(per_day)
        total_pnl = full["pnl_after"].sum()
        n_total = len(full)
        avg_daily_pnl = total_pnl / days if days else 0.0
        weekly_proj = avg_daily_pnl * 7
        avg_daily_n = n_total / days if days else 0.0
        print(f"\n  >>> 1-WEEK PROJECTION (avg daily × 7):")
        print(f"      avg trades/day:  {avg_daily_n:.1f}")
        print(f"      avg pnl/day:    ${avg_daily_pnl:+.2f}")
        print(f"      weekly pnl:     ${weekly_proj:+.2f}")
        print(f"      weekly notional: ${avg_daily_n * 7 * NOTIONAL:.2f}")
        if avg_daily_n * 7 * NOTIONAL:
            print(f"      weekly ROI:      {weekly_proj / (avg_daily_n * 7 * NOTIONAL) * 100:+.2f}%")


if __name__ == "__main__":
    main()
