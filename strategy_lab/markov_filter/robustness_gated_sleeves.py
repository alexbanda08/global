"""Robustness battery for the 11 gated sleeves from TV_AGENT_SHADOW_DEPLOY spec.

Loads strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv,
applies the per-sleeve gate stacks (HoD-Top8 + optional MTF2 / Markov),
and runs eval.metrics + eval.robustness on each. Outputs:

  - per-sleeve scorecard CSV  (Sortino, Sharpe, Calmar, MDD, bootstrap CIs,
    walk-forward retention, permutation p-value)
  - markdown report
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, "strategy_lab")

from scipy import stats as sstats
from eval.metrics import calmar_ratio


# ---------------------------------------------------------------------
# Gate definitions — mirror TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md
# ---------------------------------------------------------------------
HOD_TOP8_BY_CELL: dict[tuple[str, str], list[int]] = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo_v1", "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}

# (strategy, cell, gate_label) → defines the 11 sleeves to evaluate.
SLEEVES = [
    ("sniper",  "sol_5m",  "HOD"),
    ("sniper",  "eth_15m", "HOD+M5va"),
    ("momo_v1", "btc_15m", "HOD"),
    ("sniper",  "btc_15m", "HOD"),
    ("sniper",  "btc_5m",  "HOD"),
    ("momo_v2", "btc_5m",  "HOD+MTF2"),
    ("momo_v2", "btc_15m", "HOD"),
    ("momo_v2", "sol_5m",  "HOD"),
    ("momo_v2", "eth_15m", "HOD"),
    ("momo_v2", "sol_15m", "HOD"),
    ("sniper",  "eth_5m",  "HOD"),
]

NOTIONAL = 25.0  # USD risked per trade in backtest fills


# ---------------------------------------------------------------------
# Build MTF2 column from binance 1m klines (needed for momo_v2 btc_5m sleeve)
# ---------------------------------------------------------------------
def add_mtf2(fills: pd.DataFrame) -> pd.DataFrame:
    """Compute ret_15m and ret_1h at fire_us per asset, then derive mtf2_pass."""
    kl = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv")
    kl["asset"] = kl["symbol_id"].str.extract(r"BINANCE_SPOT_([A-Z]+)_USDT")
    fills = fills.copy()
    fills["mtf2_pass"] = False

    for asset, kg in kl.groupby("asset"):
        kg = kg.sort_values("time_period_start_us").reset_index(drop=True)
        end_us    = kg["time_period_start_us"].to_numpy() + 60_000_000  # bar END
        prices    = kg["price_close"].to_numpy()

        mask = fills["asset"] == asset
        sub  = fills[mask]
        fire = sub["fire_us"].to_numpy()

        idx_now  = np.searchsorted(end_us, fire,                       side="right") - 1
        idx_15m  = np.searchsorted(end_us, fire -   900_000_000,       side="right") - 1
        idx_1h   = np.searchsorted(end_us, fire - 3_600_000_000,       side="right") - 1
        good     = (idx_now >= 0) & (idx_15m >= 0) & (idx_1h >= 0)

        p_now = np.where(good, prices[np.clip(idx_now , 0, None)], np.nan)
        p_15  = np.where(good, prices[np.clip(idx_15m, 0, None)], np.nan)
        p_1h  = np.where(good, prices[np.clip(idx_1h , 0, None)], np.nan)

        ret_15 = np.log(p_now / p_15)
        ret_1h = np.log(p_now / p_1h)

        sig = sub["signal"].to_numpy()
        ok  = (
            (np.isfinite(ret_15) & np.isfinite(ret_1h)) &
            (
                ((sig == "UP")   & (ret_15 > 0) & (ret_1h > 0)) |
                ((sig == "DOWN") & (ret_15 < 0) & (ret_1h < 0))
            )
        )
        fills.loc[mask, "mtf2_pass"] = ok

    return fills


# ---------------------------------------------------------------------
# Sleeve filter
# ---------------------------------------------------------------------
def apply_gate(fills: pd.DataFrame, strategy: str, cell: str, gate: str) -> pd.DataFrame:
    df = fills[(fills["strategy"] == strategy) & (fills["cell_key"] == cell)].copy()
    if df.empty:
        return df
    hours = set(HOD_TOP8_BY_CELL[(strategy, cell)])
    df = df[df["hour"].isin(hours)]
    if "MTF2" in gate:
        df = df[df["mtf2_pass"]]
    if "M5va" in gate:
        df = df[df["markov_pass_w20_5m_voladaptive"]]
    return df


# ---------------------------------------------------------------------
# Per-sleeve metrics
# ---------------------------------------------------------------------
def metrics_for_sleeve(df: pd.DataFrame) -> dict:
    """Cash-equity metrics suitable for binary-outcome up/down markets.

    Per-trade Sharpe/Sortino (NOT annualized — annualization on binary outcomes
    with sqrt(trades/yr) yields meaningless 4-digit numbers).  Annualized Sharpe
    reported separately for those who want it.
    """
    if df.empty:
        return {"n": 0}
    df = df.sort_values("fire_us").reset_index(drop=True)
    pnl = df["pnl"].to_numpy()
    n   = int(len(df))
    sum_pnl = float(pnl.sum())
    wr      = float((pnl > 0).mean())
    per_tr  = sum_pnl / n

    # Cash equity curve in $
    eq_cash = np.cumsum(pnl)
    peak    = np.maximum.accumulate(eq_cash)
    dd_cash = eq_cash - peak               # negative
    mdd_dol = float(dd_cash.min()) if len(dd_cash) else 0.0

    # Per-trade Sharpe/Sortino
    sd      = float(pnl.std(ddof=1)) if n > 1 else 0.0
    losers  = pnl[pnl < 0]
    sd_dn   = float(losers.std(ddof=1)) if len(losers) > 1 else 0.0
    sharpe_pt  = (per_tr / sd)    if sd    > 0 else 0.0
    sortino_pt = (per_tr / sd_dn) if sd_dn > 0 else 0.0

    # Annualized
    span_days = max(1.0, (df["fire_us"].iloc[-1] - df["fire_us"].iloc[0]) / 1e6 / 86400.0)
    trades_per_year = n * 365.0 / span_days
    sharpe_ann  = sharpe_pt  * np.sqrt(trades_per_year)
    sortino_ann = sortino_pt * np.sqrt(trades_per_year)

    # Calmar: annualized PnL / |MDD| in $-space (interpretable for fixed-stake play)
    pnl_per_year = sum_pnl * 365.0 / span_days
    calmar = (pnl_per_year / abs(mdd_dol)) if mdd_dol != 0 else 0.0

    return {
        "n": n,
        "wr_pct": round(wr * 100, 2),
        "per_trade_$": round(per_tr, 3),
        "sum_$": round(sum_pnl, 2),
        "sharpe_pt":   round(sharpe_pt, 3),
        "sortino_pt":  round(sortino_pt, 3),
        "sharpe_ann":  round(sharpe_ann, 2),
        "sortino_ann": round(sortino_ann, 2),
        "calmar_ann":  round(calmar, 2),
        "max_dd_$":    round(mdd_dol, 2),
        "trades_per_year": round(trades_per_year, 0),
    }


# ---------------------------------------------------------------------
# Walk-forward 50/50 retention
# ---------------------------------------------------------------------
def walkforward_5050(df: pd.DataFrame) -> dict:
    if len(df) < 20:
        return {"wf_retention": np.nan, "train_sum": np.nan, "test_sum": np.nan}
    df = df.sort_values("fire_us").reset_index(drop=True)
    mid = len(df) // 2
    train, test = df.iloc[:mid], df.iloc[mid:]
    ts = float(train["pnl"].sum())
    es = float(test["pnl"].sum())
    return {
        "train_n":    int(len(train)),
        "test_n":     int(len(test)),
        "train_sum":  round(ts, 2),
        "test_sum":   round(es, 2),
        "train_wr":   round(float((train["pnl"] > 0).mean()) * 100, 2),
        "test_wr":    round(float((test["pnl"]  > 0).mean()) * 100, 2),
        "wf_retention": round(es / ts, 2) if ts != 0 else np.nan,
    }


# ---------------------------------------------------------------------
# Outcome-permutation test: shuffle win/loss labels keeping P(win) constant
# ---------------------------------------------------------------------
def permutation_outcome(df: pd.DataFrame, n_perm: int = 2000, seed: int = 42) -> dict:
    """Two complementary null tests.

    (a) Binomial test of WR vs the per-side break-even WR implied by vwap:
        each trade buys at vwap so a coin-flip would win at rate ≈ vwap.  A
        sleeve's edge = (real WR) − E[WR | random].  Test that diff > 0.
    (b) Monte-Carlo: re-sample N trade-PnLs with replacement from a HYPOTHETICAL
        random-signal sleeve (same notional, same vwap, win prob = vwap), and
        check the probability of observing the real sum_$ purely by luck.
    """
    if len(df) < 30:
        return {"perm_p": np.nan, "real_sum": np.nan}
    real_sum = float(df["pnl"].sum())
    real_wr  = float((df["won"] == True).mean())
    n = len(df)

    # break-even WR for each trade ≈ vwap (probability already priced in)
    vwap = df["vwap"].to_numpy()
    expected_wr = float(vwap.mean())

    # binomial test: H0 = real_wr == expected_wr  vs  H1 = real_wr > expected_wr
    n_won = int((df["won"] == True).sum())
    binom_p = float(sstats.binomtest(n_won, n, p=expected_wr, alternative="greater").pvalue)

    # Monte-Carlo on coin-flip sleeve at per-trade vwap probabilities
    rng = np.random.default_rng(seed)
    shares = df["shares"].to_numpy()
    fee_in = df["fee_in"].to_numpy()
    null_sums = np.empty(n_perm)
    for k in range(n_perm):
        sim_won = rng.random(n) < vwap
        # winner: gets shares * 1.0 - cost; loser: -cost.  cost = shares*vwap + fee
        cost  = shares * vwap + fee_in
        gross = np.where(sim_won, shares * 1.0, 0.0)
        # 2%-on-profit only for winners (production convention, CLAUDE.md)
        profit = np.where(sim_won, gross - cost, 0.0)
        net    = np.where(sim_won, profit * 0.98 + cost, 0.0) - cost  # = profit*0.98 if won, -cost if lost
        null_sums[k] = net.sum()
    mc_p = float((null_sums >= real_sum).mean())

    return {
        "real_wr_pct":  round(real_wr * 100, 2),
        "expected_wr_pct": round(expected_wr * 100, 2),
        "wr_edge_pct":  round((real_wr - expected_wr) * 100, 2),
        "binom_p":      round(binom_p, 4),
        "mc_p":         round(mc_p, 4),
        "mc_null_mean": round(float(null_sums.mean()), 2),
        "mc_null_q95":  round(float(np.quantile(null_sums, 0.95)), 2),
    }


# ---------------------------------------------------------------------
# Block bootstrap CI on per-trade returns
# ---------------------------------------------------------------------
def bootstrap_ci(df: pd.DataFrame, n_iter: int = 2000, seed: int = 42) -> dict:
    """Stationary block-bootstrap CI on sum_$, per-trade $, and per-trade Sharpe."""
    if len(df) < 30:
        return {}
    rng = np.random.default_rng(seed)
    pnl = df["pnl"].to_numpy()
    n   = len(pnl)
    block_prob = 0.1  # expected block length 10
    sums    = np.empty(n_iter)
    per_tr  = np.empty(n_iter)
    sharpes = np.empty(n_iter)
    for k in range(n_iter):
        idxs = np.empty(n, dtype=np.int64)
        i = 0
        while i < n:
            start = rng.integers(0, n)
            blen  = rng.geometric(block_prob)
            for b in range(blen):
                if i >= n: break
                idxs[i] = (start + b) % n
                i += 1
        sample = pnl[idxs]
        sums[k]    = sample.sum()
        per_tr[k]  = sample.mean()
        sd = sample.std(ddof=1)
        sharpes[k] = sample.mean() / sd if sd > 0 else 0.0
    def _ci(a):
        return (round(float(np.quantile(a, 0.025)), 3),
                round(float(np.quantile(a, 0.975)), 3))
    s_lo, s_hi = _ci(sums)
    p_lo, p_hi = _ci(per_tr)
    sh_lo, sh_hi = _ci(sharpes)
    return {
        "sum_ci_lo":    s_lo,    "sum_ci_hi":    s_hi,
        "per_tr_ci_lo": p_lo,    "per_tr_ci_hi": p_hi,
        "sharpe_pt_ci_lo": sh_lo,"sharpe_pt_ci_hi": sh_hi,
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
    fills["fire_ts"]  = pd.to_datetime(fills["fire_us"], unit="us", utc=True)
    fills["hour"]     = fills["fire_ts"].dt.hour
    fills["cell_key"] = fills["asset"].str.lower() + "_" + fills["tf"]
    # we evaluate the F7-OFF universe (= the universe the gated sleeves replace)
    fills = fills[fills["f7_mode"] == "off"].copy()

    print(f"[load] {len(fills)} fills, "
          f"{fills['fire_ts'].min()} → {fills['fire_ts'].max()}")
    fills = add_mtf2(fills)
    print(f"[mtf2] computed for {fills['mtf2_pass'].sum()} fills")

    rows = []
    for strategy, cell, gate in SLEEVES:
        sub = apply_gate(fills, strategy, cell, gate)
        m   = metrics_for_sleeve(sub)
        wf  = walkforward_5050(sub)
        bs  = bootstrap_ci(sub)
        pm  = permutation_outcome(sub)
        row = {
            "sleeve":   f"{strategy}_{cell}_{gate}",
            "strategy": strategy,
            "cell":     cell,
            "gate":     gate,
        }
        row.update(m); row.update(wf); row.update(bs); row.update(pm)
        rows.append(row)
        print(f"[done] {row['sleeve']:35s}  n={m.get('n',0):4d}  "
              f"sum=${m.get('sum_$',0):>+8.1f}  "
              f"sortino_pt={m.get('sortino_pt',0):+.2f}  "
              f"wf_ret={wf.get('wf_retention',np.nan):+.2f}  "
              f"binom_p={pm.get('binom_p',1):.4f}  "
              f"mc_p={pm.get('mc_p',1):.4f}")

    out = pd.DataFrame(rows)
    out_path = Path("strategy_lab/markov_filter/_results/robustness_gated_sleeves.csv")
    out.to_csv(out_path, index=False)
    print(f"\n[write] {out_path}")
    print(out.to_string())


if __name__ == "__main__":
    main()
