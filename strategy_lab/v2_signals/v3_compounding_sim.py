"""V3 compounding sim with bankroll constraint.

Walks the validated V3 trade sequence chronologically, applying a fractional-Kelly
sizing rule against the running bankroll. Tests several rules to find which one
takes a $5 starting bankroll to $50+ without blowing up.

Compares:
  - Fixed $5/market (current sim — assumes infinite bankroll)
  - Fixed $1/market until bankroll >= $50, then $5
  - Fractional Kelly: bet f * bankroll, capped at $5
  - Conservative: bet 5% of bankroll, capped at $5
  - Half-Kelly: bet 12% of bankroll, capped at $5
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, chronological_split

FEE = 0.02
SLIPPAGE_PP = 0.05  # realistic L10 haircut

V3_CELLS = {
    "BTC_5m_q10":       {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "ETH_5m_q5":        {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "SOL_5m_q15_multi": {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}


def gather_v3_trades(slippage_pp=SLIPPAGE_PP) -> pd.DataFrame:
    """Return all V3-fired trades chronologically with cost, hit, and per-$ payoff."""
    rows = []
    for name, cell in V3_CELLS.items():
        feats = load_features(cell["asset"]).dropna(
            subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask", "window_start_unix"]
        )
        feats = feats[feats["timeframe"] == cell["tf"]]
        train, holdout = chronological_split(feats)

        if cell["selector"] == "multi_horizon":
            same_tr = ((train["ret_5m"] > 0) & (train["ret_15m"] > 0) & (train["ret_1h"] > 0)) | \
                      ((train["ret_5m"] < 0) & (train["ret_15m"] < 0) & (train["ret_1h"] < 0))
            train_f = train[same_tr]
            same_full = ((feats["ret_5m"] > 0) & (feats["ret_15m"] > 0) & (feats["ret_1h"] > 0)) | \
                        ((feats["ret_5m"] < 0) & (feats["ret_15m"] < 0) & (feats["ret_1h"] < 0))
            full_f = feats[same_full]
            thr = train_f["ret_5m"].abs().quantile(1 - cell["mag"])
        else:
            full_f = feats
            thr = train["ret_5m"].abs().quantile(1 - cell["mag"])

        fired = full_f[full_f["ret_5m"].abs() >= thr].copy()
        if len(fired) == 0:
            continue

        pred_up = fired["ret_5m"] > 0
        actual_up = fired["outcome_up"] == 1
        hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
        cost = np.where(pred_up, fired["entry_yes_ask"], fired["entry_no_ask"])
        cost = np.clip(cost + slippage_pp, 0.01, 0.99)
        # per-$1 of notional: shares = 1/cost; payoff = (1-cost) on hit, -cost on miss
        # net pnl per $1 = hit ? (1-cost)/cost : -1
        pnl_per_dollar = np.where(hit, (1 - cost) / cost, -1.0)
        # apply fee on wins only
        pnl_per_dollar = np.where(pnl_per_dollar > 0, pnl_per_dollar * (1 - FEE), pnl_per_dollar)

        fired["sleeve"] = name
        fired["cost"] = cost
        fired["hit"] = hit.astype(bool)
        fired["pnl_per_dollar"] = pnl_per_dollar
        rows.append(fired[["window_start_unix", "sleeve", "cost", "hit", "pnl_per_dollar"]])

    df = pd.concat(rows, ignore_index=True)
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    return df


def simulate(trades: pd.DataFrame, sizing_fn, starting_bankroll: float = 5.0):
    """Walk trades chronologically, apply sizing_fn(bankroll, trade) -> stake."""
    bankroll = starting_bankroll
    history = []
    ruin_step = None
    for i, row in trades.iterrows():
        stake = sizing_fn(bankroll, row)
        stake = max(0.0, min(stake, bankroll))  # can't bet more than you have
        if stake < 0.01:  # too small to fire (Polymarket min)
            history.append({"i": i, "bankroll_pre": bankroll, "stake": 0, "pnl": 0,
                            "bankroll_post": bankroll, "skipped": True})
            continue
        pnl = stake * row["pnl_per_dollar"]
        bankroll_post = bankroll + pnl
        history.append({"i": i, "bankroll_pre": bankroll, "stake": stake, "pnl": pnl,
                        "bankroll_post": bankroll_post, "skipped": False, "hit": row["hit"]})
        bankroll = bankroll_post
        if bankroll <= 0.01 and ruin_step is None:
            ruin_step = i
    return pd.DataFrame(history), bankroll, ruin_step


def fixed(amount):
    return lambda b, r: amount


def step_sizing(small, large, threshold):
    return lambda b, r: small if b < threshold else large


def fractional(f, cap):
    return lambda b, r: min(b * f, cap)


def report(label, hist, final_bankroll, ruin_step, start):
    fired = hist[~hist["skipped"]]
    n_fired = len(fired)
    n_skipped = (hist["skipped"]).sum()
    if n_fired == 0:
        print(f"  {label:<40} all skipped")
        return
    hit_rate = fired["hit"].mean() * 100
    total_pnl = final_bankroll - start
    multiple = final_bankroll / start
    avg_stake = fired["stake"].mean()
    max_stake = fired["stake"].max()
    min_bankroll = hist["bankroll_post"].min() if len(hist) else start
    ruin_str = f"RUIN@trade{ruin_step}" if ruin_step is not None else "no ruin"
    pct_at_50 = (hist["bankroll_post"] >= 50).any()
    first_50 = None
    if pct_at_50:
        first_50 = (hist["bankroll_post"] >= 50).idxmax()
    print(f"  {label:<40} fired={n_fired:<3d} skip={n_skipped:<3d} hit={hit_rate:5.1f}% "
          f"bankroll ${start:.2f}->${final_bankroll:7.2f} ({multiple:5.1f}x) "
          f"min=${min_bankroll:5.2f} avg_stake=${avg_stake:.2f} max=${max_stake:.2f} "
          f"hit_$50@trade={first_50}  {ruin_str}")


def main():
    trades = gather_v3_trades()
    print(f"V3 trade sequence: n={len(trades)} fires over 7d")
    print(f"  per-$ pnl mean=${trades['pnl_per_dollar'].mean():+.4f}  "
          f"std={trades['pnl_per_dollar'].std():.4f}  "
          f"hit={trades['hit'].mean()*100:.1f}%  "
          f"win=${trades.loc[trades['hit'],'pnl_per_dollar'].mean():.3f}/$1  "
          f"loss=${trades.loc[~trades['hit'],'pnl_per_dollar'].mean():.3f}/$1")

    print(f"\n{'='*120}")
    print("STARTING BANKROLL = $5 — what survives?")
    print(f"{'='*120}")

    rules = [
        ("Fixed $5/market (current sim, no compound)", fixed(5.0), 5.0),
        ("Fixed $1/market (flat tiny)",                fixed(1.0), 5.0),
        ("Fixed $0.50/market (ultra tiny)",            fixed(0.50), 5.0),
        ("Step: $1 until $50, then $5",                step_sizing(1.0, 5.0, 50.0), 5.0),
        ("Step: $0.50 until $20, then $2 until $50, then $5",
            (lambda b, r: 0.50 if b < 20 else (2.0 if b < 50 else 5.0)), 5.0),
        ("Frac 5% of bankroll, cap $5",                fractional(0.05, 5.0), 5.0),
        ("Frac 10% of bankroll, cap $5",               fractional(0.10, 5.0), 5.0),
        ("Frac 20% of bankroll, cap $5 (~full Kelly)", fractional(0.20, 5.0), 5.0),
        ("Frac 12% of bankroll, cap $5 (~half Kelly)", fractional(0.12, 5.0), 5.0),
    ]

    for label, fn, start in rules:
        hist, final, ruin = simulate(trades, fn, starting_bankroll=start)
        report(label, hist, final, ruin, start)

    print(f"\n{'='*120}")
    print("STARTING BANKROLL = $20 — same rules, more headroom")
    print(f"{'='*120}")
    for label, fn, start in [
        ("Fixed $5/market",                          fixed(5.0), 20.0),
        ("Frac 10% of bankroll, cap $5",             fractional(0.10, 5.0), 20.0),
        ("Frac 20% of bankroll, cap $5",             fractional(0.20, 5.0), 20.0),
        ("Step: $2 until $50, then $5",              step_sizing(2.0, 5.0, 50.0), 20.0),
    ]:
        hist, final, ruin = simulate(trades, fn, starting_bankroll=start)
        report(label, hist, final, ruin, start)

    # Worst-case sequence stress: if the loss day (04-22) hit first
    print(f"\n{'='*120}")
    print("WORST-CASE: if the worst day's losses hit FIRST instead of last (re-order)")
    print(f"{'='*120}")
    # Sort by per-$ pnl ascending — losses first
    trades_worst = trades.sort_values("pnl_per_dollar").reset_index(drop=True)
    for label, fn, start in [
        ("Fixed $1/market", fixed(1.0), 5.0),
        ("Step: $1 until $50, then $5", step_sizing(1.0, 5.0, 50.0), 5.0),
        ("Frac 10%, cap $5", fractional(0.10, 5.0), 5.0),
        ("Frac 20%, cap $5", fractional(0.20, 5.0), 5.0),
    ]:
        hist, final, ruin = simulate(trades_worst, fn, starting_bankroll=start)
        report(label, hist, final, ruin, start)


if __name__ == "__main__":
    main()
