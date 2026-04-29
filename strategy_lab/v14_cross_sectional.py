"""
V14 — Cross-sectional momentum (XSM) portfolio.

Different paradigm from everything else we've tried:
  * Every week (Mondays 00:00 UTC in 4h-bar terms), rank ALL 9 coins by
    their past-N-day return.
  * Go LONG the top K ranked (equal weight).  Stay flat otherwise.
  * Rebalance weekly.

This is the classical CTA / factor-investing approach.  Research shows it
adds uncorrelated returns to time-series-momentum trend followers (the
V3B/V4C family we already run).

All coins must have futures available on Hyperliquid.  Fee model: 0.015 %
maker per side, executed on Monday 00:00 UTC bar open.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab import portfolio_audit as pa

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT",
         "LINKUSDT","ADAUSDT","XRPUSDT",
         "BNBUSDT","DOGEUSDT","AVAXUSDT"]

STARTS = {
    "BTCUSDT":"2018-01-01","ETHUSDT":"2018-01-01","BNBUSDT":"2018-01-01",
    "XRPUSDT":"2018-06-01","ADAUSDT":"2018-06-01",
    "LINKUSDT":"2019-03-01","DOGEUSDT":"2019-09-01",
    "SOLUSDT":"2020-10-01","AVAXUSDT":"2020-11-01",
}
END = "2026-04-01"
INIT = 10_000.0
FEE  = 0.00015   # Hyperliquid maker
OUT  = Path(__file__).resolve().parent / "results"


def load_all_4h() -> dict[str, pd.DataFrame]:
    out = {}
    for sym in COINS:
        try:
            df = pa.load_ohlcv(sym, STARTS[sym], END)
            out[sym] = df
        except Exception as e:
            print(f"  skip {sym}: {e}")
    return out


def xsm_backtest(lookback_days: int = 14, top_k: int = 3,
                 rebal_days: int = 7, use_momentum: bool = True,
                 leverage: float = 1.0,
                 btc_trend_filter: bool = False,
                 btc_trend_ma_days: int = 100,
                 per_coin_trend_filter: bool = False,
                 per_coin_ma_days: int = 50) -> tuple[pd.Series, list, dict]:
    """
    Weekly (by default) rank and rebalance.
    """
    data = load_all_4h()
    # Master index = union of all coins' 4h bars
    idx = sorted(set().union(*[df.index for df in data.values()]))
    idx = pd.DatetimeIndex(idx)
    # Align close matrix
    close = pd.DataFrame({s: df["close"].reindex(idx).ffill() for s, df in data.items()})
    open_ = pd.DataFrame({s: df["open"].reindex(idx).ffill() for s, df in data.items()})

    # Rebalance every rebal_days × 6 bars (1 day = 6 × 4h bars)
    step = rebal_days * 6
    n = len(idx)

    # Pre-compute trend filter series
    btc_close = close["BTCUSDT"].ffill() if "BTCUSDT" in close else None
    btc_ma = None
    if btc_trend_filter and btc_close is not None:
        btc_ma = btc_close.rolling(btc_trend_ma_days * 6).mean()

    per_coin_ma = None
    if per_coin_trend_filter:
        per_coin_ma = {s: close[s].rolling(per_coin_ma_days * 6).mean() for s in close}
    equity = np.empty(n); equity[0] = INIT
    cash = INIT
    positions = {s: 0.0 for s in data}   # shares per coin
    trade_log = []
    rebalance_log = []

    lookback_bars = lookback_days * 6

    for i in range(n):
        t = idx[i]

        # Mark-to-market
        mv = sum(positions[s] * close.iloc[i][s] for s in positions
                 if not np.isnan(close.iloc[i][s]))
        eq = cash + mv

        # Rebalance if it's a rebalance bar
        if i >= lookback_bars and (i - lookback_bars) % step == 0:
            # Compute past-return ranking
            eligible = {}
            for s in data:
                p_now = close.iloc[i][s]
                p_ago = close.iloc[i - lookback_bars][s]
                if np.isnan(p_now) or np.isnan(p_ago) or p_ago <= 0:
                    continue
                ret = (p_now / p_ago) - 1
                # Skip coins that aren't live yet (NaN at lookback point)
                if idx[i - lookback_bars] < pd.Timestamp(STARTS[s], tz="UTC"):
                    continue
                eligible[s] = ret
            if len(eligible) < top_k + 1:
                continue

            # BTC trend filter — if BTC is below its MA, go flat (exit all)
            btc_bear = False
            if btc_trend_filter and btc_ma is not None:
                if not np.isnan(btc_ma.iloc[i]) and btc_close.iloc[i] < btc_ma.iloc[i]:
                    btc_bear = True
            if btc_bear:
                # Close everything, stay in cash this rebalance
                for s in list(positions):
                    if positions[s] != 0:
                        px = open_.iloc[min(i+1, n-1)][s]
                        if np.isnan(px): continue
                        gross = positions[s] * px
                        fee = abs(gross) * FEE
                        cash += gross - fee
                        trade_log.append({"ts": idx[min(i+1, n-1)], "sym": s,
                                          "action": "EXIT_BEAR", "px": px,
                                          "shares": positions[s], "fee": fee})
                        positions[s] = 0.0
                rebalance_log.append({"ts": idx[i], "winners": "FLAT_BTC_BEAR",
                                      "equity": round(eq, 2)})
                equity[i] = eq
                continue

            if use_momentum:
                winners = sorted(eligible, key=lambda s: eligible[s], reverse=True)[:top_k]
            else:
                winners = sorted(eligible, key=lambda s: eligible[s])[:top_k]   # reversal

            # Per-coin trend filter — drop coins below own MA
            if per_coin_trend_filter and per_coin_ma is not None:
                winners = [s for s in winners
                           if not np.isnan(per_coin_ma[s].iloc[i])
                           and close.iloc[i][s] > per_coin_ma[s].iloc[i]]
                if len(winners) == 0:
                    # all candidates in downtrend -> flat
                    for s in list(positions):
                        if positions[s] != 0:
                            px = open_.iloc[min(i+1, n-1)][s]
                            if np.isnan(px): continue
                            gross = positions[s] * px
                            fee = abs(gross) * FEE
                            cash += gross - fee
                            trade_log.append({"ts": idx[min(i+1, n-1)], "sym": s,
                                              "action": "EXIT_TF", "px": px,
                                              "shares": positions[s], "fee": fee})
                            positions[s] = 0.0
                    rebalance_log.append({"ts": idx[i], "winners": "FLAT_TF",
                                          "equity": round(eq, 2)})
                    equity[i] = eq
                    continue

            # Rebalance: target equal-notional positions in winners
            target_notional_per_coin = eq * leverage / top_k
            # Close positions not in winners
            for s in list(positions):
                if positions[s] != 0 and s not in winners:
                    px = open_.iloc[min(i+1, n-1)][s]
                    if np.isnan(px): continue
                    gross = positions[s] * px
                    fee = abs(gross) * FEE
                    cash += gross - fee
                    trade_log.append({"ts": idx[min(i+1, n-1)], "sym": s,
                                      "action": "EXIT", "px": px,
                                      "shares": positions[s], "fee": fee})
                    positions[s] = 0.0
            # Open / adjust positions for winners
            for s in winners:
                target_shares = target_notional_per_coin / close.iloc[i][s]
                current = positions[s]
                diff = target_shares - current
                if abs(diff) * close.iloc[i][s] < 0.01 * eq:   # < 1 % — skip
                    continue
                px = open_.iloc[min(i+1, n-1)][s]
                if np.isnan(px): continue
                gross = diff * px
                fee = abs(gross) * FEE
                cash -= gross + fee
                action = "ENTER" if current == 0 else ("ADD" if diff > 0 else "TRIM")
                trade_log.append({"ts": idx[min(i+1, n-1)], "sym": s,
                                  "action": action, "px": px, "shares": diff, "fee": fee})
                positions[s] = target_shares
            rebalance_log.append({"ts": idx[i], "winners": ",".join(winners),
                                  "equity": round(eq, 2)})

        equity[i] = eq

    eq_series = pd.Series(equity, index=idx, name="equity")
    stats = {
        "lookback_days": lookback_days, "top_k": top_k,
        "rebal_days": rebal_days, "use_momentum": use_momentum,
        "leverage": leverage,
        "n_rebalances": len(rebalance_log),
        "n_trade_legs": len(trade_log),
    }
    return eq_series, trade_log, stats


def _metrics(eq: pd.Series) -> dict:
    if len(eq) < 20: return {}
    rets = eq.pct_change().fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    sh = (rets.mean() * pa.BARS_PER_YR) / (rets.std() * np.sqrt(pa.BARS_PER_YR) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr":round(float(cagr),4), "sharpe":round(float(sh),3),
            "dd":round(dd,4),
            "calmar":round(cagr/abs(dd) if dd<0 else 0,3),
            "final":round(float(eq.iloc[-1]),0)}


def per_year_stats(eq: pd.Series, trades: list) -> dict:
    out = {}
    for y in (2022, 2023, 2024, 2025):
        s = pd.Timestamp(f"{y}-01-01", tz="UTC")
        e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
        eq_y = eq[(eq.index >= s) & (eq.index < e)]
        if len(eq_y) < 20:
            out[y] = None; continue
        ret = eq_y.iloc[-1] / eq_y.iloc[0] - 1
        dd = float((eq_y / eq_y.cummax() - 1).min())
        # WR = fraction of rebalance-to-rebalance periods that made money
        # use equity at rebalance timestamps only — approximate with weekly close
        weekly = eq.resample("1W").last().loc[s:e]
        week_rets = weekly.pct_change().dropna()
        wr = float((week_rets > 0).mean()) if len(week_rets) > 0 else None
        out[y] = {"ret":round(float(ret),3), "dd":round(dd,3),
                  "weekly_wr":round(wr,3) if wr is not None else None,
                  "n_weeks":len(week_rets)}
    return out


def main():
    # Sweep a sensible set of configs — now with BTC trend filter variants
    # format: (lb, k, rb, use_mom, lev, btc_filter, per_coin_filter)
    configs = [
        (28, 3, 7,  True,  1.0, False, False),  # baseline
        (56, 3, 7,  True,  1.0, False, False),  # 8-wk
        # BTC-bear-filter variants — flat when BTC < 100-day MA
        (28, 3, 7,  True,  1.0, True,  False),
        (56, 3, 7,  True,  1.0, True,  False),
        (28, 2, 7,  True,  1.0, True,  False),
        (28, 4, 7,  True,  1.0, True,  False),
        # Per-coin trend filter — only hold coins above own 50d MA
        (28, 3, 7,  True,  1.0, False, True),
        (28, 3, 7,  True,  1.0, True,  True),   # both filters
        (56, 3, 7,  True,  1.0, True,  True),   # both filters, 8-wk momentum
        # Leveraged versions of filtered
        (28, 3, 7,  True,  2.0, True,  True),
        (56, 3, 7,  True,  2.0, True,  True),
    ]
    rows = []
    for lb, k, rb, use_mom, lev, bf, pf in configs:
        eq, trades, stats = xsm_backtest(lb, k, rb, use_mom, lev,
                                          btc_trend_filter=bf,
                                          per_coin_trend_filter=pf)
        m = _metrics(eq)
        yr = per_year_stats(eq, trades)
        row = {"lookback_d": lb, "top_k": k, "rebal_d": rb,
               "mom_or_rev": "MOM" if use_mom else "REV",
               "leverage": lev, "btc_filter": bf, "per_coin_filter": pf, **m,
               "n_trade_legs": stats["n_trade_legs"],
               **{f"ret_{y-2000}":(yr.get(y) or {}).get("ret") for y in (2022,2023,2024,2025)},
               **{f"wr_{y-2000}":(yr.get(y) or {}).get("weekly_wr") for y in (2022,2023,2024,2025)}}
        rows.append(row)
        filt_tag = ("+BTC_TF" if bf else "") + ("+COIN_TF" if pf else "") or "BASE"
        print(f"  lb={lb:3d}d k={k} rb={rb:2d}d {'MOM' if use_mom else 'REV'} lev={lev}x {filt_tag:<18}  "
              f"cagr={m.get('cagr',0)*100:+6.1f}% sharpe={m.get('sharpe',0):.2f} "
              f"dd={m.get('dd',0)*100:+5.1f}% calmar={m.get('calmar',0):.2f} "
              f"final=${m.get('final',0):,.0f} trades={stats['n_trade_legs']}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v14_cross_sectional.csv", index=False)

    print("\n=== BEST BY SHARPE ===")
    if len(df):
        print(df.sort_values("sharpe", ascending=False).head(5).to_string(index=False))


if __name__ == "__main__":
    main()
