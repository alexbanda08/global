"""
V29 — Deep-dive on the long-short (V27) XSM variant.

Key question: is V27's OOS Sharpe 1.75 real?  Where does the short-side
alpha come from?  What are the right (lookback, top_k, leverage, rebal)
parameters?  Can we combine V27 with the V24 multi-filter?

Dimensions swept:
  * lookback_days      ∈ {7, 14, 21, 28, 56}
  * (top_k, bottom_k)  ∈ {(1,1), (2,2), (3,3), (4,4)}
  * rebal_days         ∈ {3, 7, 14}
  * leverage           ∈ {0.5, 1.0, 1.5, 2.0}
  * multi-filter on/off (use V24 bear gate on the LONG leg only)

Also: isolated short-only and long-only equity curves to measure
short-leg alpha.  Splits period into pre-2022 / post-2022 for regime
contribution.
"""
from __future__ import annotations
import itertools
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab import portfolio_audit as pa
from strategy_lab.v23_low_dd_xsm import low_dd_xsm, metrics, load_all, COINS, STARTS, build_panel

INIT = 10_000.0
FEE  = 0.00015
BARS_PER_DAY = 6
OUT = Path(__file__).resolve().parent / "results"


def long_short_backtest(
    data: dict,
    lookback_days: int = 14,
    top_k: int = 2,
    bottom_k: int = 2,
    rebal_days: int = 7,
    leverage: float = 1.0,
    btc_filter: bool = True,
    btc_ma_days: int = 100,
    multi_filter: bool = False,
    mf_btc_ma_fast: int = 50,
    mf_breadth_min: int = 5,
    long_only: bool = False,
    short_only: bool = False,
) -> tuple[pd.Series, dict]:
    """
    Native long-short backtest with optional hedging.

    If short_only=True: do ONLY the short leg.
    If long_only=True:  do ONLY the long leg.
    Otherwise both legs.
    """
    close, open_, idx = build_panel(data)
    n = len(idx)

    btc_ma = close["BTCUSDT"].rolling(btc_ma_days * BARS_PER_DAY).mean()
    btc_ma_fast = close["BTCUSDT"].rolling(mf_btc_ma_fast * BARS_PER_DAY).mean()
    per_coin_ma50 = {s: close[s].rolling(50 * BARS_PER_DAY).mean() for s in close}

    step = rebal_days * BARS_PER_DAY
    lookback_bars = lookback_days * BARS_PER_DAY
    init_bars = max(lookback_bars, btc_ma_days * BARS_PER_DAY)

    equity = np.empty(n); equity[0] = INIT
    cash = INIT
    positions = {s: 0.0 for s in close}
    trade_legs = 0

    for i in range(n):
        mv = sum(positions[s] * close.iloc[i][s] for s in positions
                 if not np.isnan(close.iloc[i][s]))
        eq = cash + mv
        equity[i] = eq

        if i < init_bars or (i - init_bars) % step != 0:
            continue

        # Bear filter on long leg
        btc_bear = False
        if btc_filter and not np.isnan(btc_ma.iloc[i]) and close["BTCUSDT"].iloc[i] < btc_ma.iloc[i]:
            btc_bear = True
        if multi_filter and not btc_bear:
            if not np.isnan(btc_ma_fast.iloc[i]) and i >= mf_btc_ma_fast * BARS_PER_DAY + 24:
                if btc_ma_fast.iloc[i] < btc_ma_fast.iloc[i - 24]:
                    btc_bear = True
            breadth = 0
            for s in close:
                if idx[i] < pd.Timestamp(STARTS[s], tz="UTC"): continue
                ma = per_coin_ma50[s].iloc[i]
                if not np.isnan(ma) and close.iloc[i][s] > ma:
                    breadth += 1
            if breadth < mf_breadth_min:
                btc_bear = True

        # Score all coins
        scores = {}
        for s in close:
            if idx[i] < pd.Timestamp(STARTS[s], tz="UTC"): continue
            if i < lookback_bars: continue
            p_now = close.iloc[i][s]; p0 = close.iloc[i - lookback_bars][s]
            if np.isnan(p_now) or np.isnan(p0) or p0 <= 0: continue
            scores[s] = (p_now / p0) - 1
        if len(scores) < top_k + bottom_k + 1:
            continue
        sorted_sym = sorted(scores, key=lambda s: scores[s], reverse=True)
        longs = sorted_sym[:top_k] if not short_only else []
        shorts = sorted_sym[-bottom_k:] if (bottom_k > 0 and not long_only) else []

        if btc_bear and not short_only:
            longs = []  # bear filter kills longs; shorts can still run

        # Target weights
        targets = {s: 0.0 for s in close}
        if longs:
            w = leverage / len(longs)
            for s in longs: targets[s] = +w
        if shorts:
            w = leverage / len(shorts)
            for s in shorts: targets[s] = -w

        # Rebalance
        for s in close:
            target_notional = eq * targets[s]
            px = open_.iloc[min(i+1, n-1)][s]
            if np.isnan(px): continue
            target_shares = target_notional / px
            diff = target_shares - positions[s]
            if abs(diff) * px < 0.005 * eq: continue
            gross = diff * px
            fee = abs(gross) * FEE
            cash -= gross + fee
            trade_legs += 1
            positions[s] = target_shares

    return pd.Series(equity, index=idx, name="equity"), {"legs": trade_legs}


def period_split(eq: pd.Series) -> dict:
    # Pre-2022 vs 2022-onwards
    cut = pd.Timestamp("2022-01-01", tz="UTC")
    early = eq[eq.index < cut]
    late  = eq[eq.index >= cut]
    def m(sub):
        if len(sub) < 50 or sub.iloc[-1] <= 0: return {}
        rets = sub.pct_change(fill_method=None).fillna(0)
        yrs = (sub.index[-1] - sub.index[0]).days / 365.25
        cagr = (sub.iloc[-1]/sub.iloc[0])**(1/max(yrs,0.01)) - 1
        bpy = 365.25 * 24 / 4
        sh = (rets.mean()*bpy)/(rets.std()*np.sqrt(bpy) + 1e-12)
        dd = float((sub/sub.cummax() - 1).min())
        return {"cagr": float(cagr), "sharpe": float(sh), "dd": dd,
                "final": float(sub.iloc[-1])}
    return {"pre_2022": m(early), "post_2022": m(late)}


def main():
    data = load_all()

    rows = []

    # 1. Leverage sweep on the baseline V27 L2/S2 14d 7d
    for lev in [0.5, 1.0, 1.5, 2.0]:
        eq, stats = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                         rebal_days=7, leverage=lev)
        m = metrics(eq); oos_m = metrics(eq[eq.index >= pd.Timestamp("2022-01-01", tz="UTC")])
        ps = period_split(eq)
        row = {"bucket": "lev-sweep", "lb": 14, "k": 2, "b": 2, "rb": 7, "lev": lev,
               "mf": False, "legs": stats["legs"], **{f"full_{k}":v for k,v in m.items()},
               **{f"oos_{k}":v for k,v in oos_m.items()},
               "pre_cagr": ps["pre_2022"].get("cagr", 0),
               "post_cagr": ps["post_2022"].get("cagr", 0)}
        rows.append(row)
        print(f"  LS L2/S2 lb=14 rb=7 lev={lev}x  "
              f"CAGR {m['cagr']*100:+6.1f}% Sh {m['sharpe']:+.2f} DD {m['dd']*100:+5.1f}%  "
              f"| OOS CAGR {oos_m['cagr']*100:+6.1f}% Sh {oos_m['sharpe']:+.2f} DD {oos_m['dd']*100:+5.1f}%",
              flush=True)

    # 2. k/b sweep at L=1x
    for k, b in [(1,1), (2,2), (3,3), (4,4), (2,1), (3,2)]:
        eq, stats = long_short_backtest(data, lookback_days=14, top_k=k, bottom_k=b,
                                         rebal_days=7, leverage=1.0)
        m = metrics(eq); oos_m = metrics(eq[eq.index >= pd.Timestamp("2022-01-01", tz="UTC")])
        ps = period_split(eq)
        rows.append({"bucket":"k-b-sweep", "lb":14, "k":k, "b":b, "rb":7, "lev":1.0,
                     "mf":False, "legs":stats["legs"], **{f"full_{x}":v for x,v in m.items()},
                     **{f"oos_{x}":v for x,v in oos_m.items()},
                     "pre_cagr":ps["pre_2022"].get("cagr",0),
                     "post_cagr":ps["post_2022"].get("cagr",0)})
        print(f"  LS L{k}/S{b} lb=14 rb=7 lev=1x  "
              f"CAGR {m['cagr']*100:+6.1f}% Sh {m['sharpe']:+.2f} DD {m['dd']*100:+5.1f}%  "
              f"| OOS Sh {oos_m['sharpe']:+.2f} DD {oos_m['dd']*100:+5.1f}%", flush=True)

    # 3. Lookback sweep
    for lb in [7, 14, 21, 28, 56]:
        eq, stats = long_short_backtest(data, lookback_days=lb, top_k=2, bottom_k=2,
                                         rebal_days=7, leverage=1.0)
        m = metrics(eq); oos_m = metrics(eq[eq.index >= pd.Timestamp("2022-01-01", tz="UTC")])
        rows.append({"bucket":"lookback-sweep", "lb":lb, "k":2, "b":2, "rb":7, "lev":1.0,
                     "mf":False, "legs":stats["legs"], **{f"full_{x}":v for x,v in m.items()},
                     **{f"oos_{x}":v for x,v in oos_m.items()}})
        print(f"  LS L2/S2 lb={lb}d rb=7 lev=1x  "
              f"CAGR {m['cagr']*100:+6.1f}% Sh {m['sharpe']:+.2f} DD {m['dd']*100:+5.1f}%  "
              f"| OOS Sh {oos_m['sharpe']:+.2f} DD {oos_m['dd']*100:+5.1f}%", flush=True)

    # 4. Rebalance sweep
    for rb in [3, 7, 14]:
        eq, stats = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                         rebal_days=rb, leverage=1.0)
        m = metrics(eq); oos_m = metrics(eq[eq.index >= pd.Timestamp("2022-01-01", tz="UTC")])
        rows.append({"bucket":"rebal-sweep", "lb":14, "k":2, "b":2, "rb":rb, "lev":1.0,
                     "mf":False, "legs":stats["legs"], **{f"full_{x}":v for x,v in m.items()},
                     **{f"oos_{x}":v for x,v in oos_m.items()}})
        print(f"  LS L2/S2 lb=14d rb={rb}d lev=1x  "
              f"CAGR {m['cagr']*100:+6.1f}% Sh {m['sharpe']:+.2f} DD {m['dd']*100:+5.1f}%  "
              f"| OOS Sh {oos_m['sharpe']:+.2f} DD {oos_m['dd']*100:+5.1f}%", flush=True)

    # 5. Multi-filter on long leg
    for lev in [1.0, 1.5]:
        eq, stats = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                         rebal_days=7, leverage=lev, multi_filter=True)
        m = metrics(eq); oos_m = metrics(eq[eq.index >= pd.Timestamp("2022-01-01", tz="UTC")])
        rows.append({"bucket":"mf-hybrid", "lb":14, "k":2, "b":2, "rb":7, "lev":lev,
                     "mf":True, "legs":stats["legs"], **{f"full_{x}":v for x,v in m.items()},
                     **{f"oos_{x}":v for x,v in oos_m.items()}})
        print(f"  LS+MF L2/S2 lb=14 rb=7 lev={lev}x  "
              f"CAGR {m['cagr']*100:+6.1f}% Sh {m['sharpe']:+.2f} DD {m['dd']*100:+5.1f}%  "
              f"| OOS Sh {oos_m['sharpe']:+.2f} DD {oos_m['dd']*100:+5.1f}%", flush=True)

    # 6. Isolate long-only and short-only
    eq_long_only, _ = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                           rebal_days=7, leverage=1.0, long_only=True)
    eq_short_only, _ = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                            rebal_days=7, leverage=1.0, short_only=True)
    eq_long_only.to_csv(OUT/"v29_long_only_equity.csv", header=["equity"])
    eq_short_only.to_csv(OUT/"v29_short_only_equity.csv", header=["equity"])
    print("\n--- ISOLATED LEGS (L2/S2, lb=14d, rb=7d, 1x) ---")
    m_l = metrics(eq_long_only); m_s = metrics(eq_short_only)
    ps_l = period_split(eq_long_only); ps_s = period_split(eq_short_only)
    print(f"  LONG-ONLY  : full CAGR {m_l['cagr']*100:+6.1f}% Sh {m_l['sharpe']:+.2f} DD {m_l['dd']*100:+5.1f}%")
    print(f"                pre-2022 CAGR {ps_l['pre_2022'].get('cagr',0)*100:+6.1f}%  "
          f"post-2022 CAGR {ps_l['post_2022'].get('cagr',0)*100:+6.1f}%")
    print(f"  SHORT-ONLY : full CAGR {m_s['cagr']*100:+6.1f}% Sh {m_s['sharpe']:+.2f} DD {m_s['dd']*100:+5.1f}%")
    print(f"                pre-2022 CAGR {ps_s['pre_2022'].get('cagr',0)*100:+6.1f}%  "
          f"post-2022 CAGR {ps_s['post_2022'].get('cagr',0)*100:+6.1f}%")

    # Save best LS equity for PDF
    eq_best, _ = long_short_backtest(data, lookback_days=14, top_k=2, bottom_k=2,
                                      rebal_days=7, leverage=1.5, multi_filter=True)
    eq_best.to_csv(OUT/"v29_ls_best_equity.csv", header=["equity"])

    df = pd.DataFrame(rows)
    df.to_csv(OUT/"v29_long_short_deep.csv", index=False)

    print("\n=== TOP 10 BY OOS SHARPE (min full-period DD > -80%) ===")
    good = df[df["full_dd"] > -0.80].copy()
    good = good.sort_values("oos_sharpe", ascending=False).head(10)
    print(good[["bucket","lb","k","b","rb","lev","mf",
                "full_cagr","full_sharpe","full_dd","oos_cagr","oos_sharpe","oos_dd"]]
          .to_string(index=False))

    print("\n=== TOP 10 BY OOS DD (smallest first) ===")
    good2 = df[df["full_final"] > INIT].copy()
    good2 = good2.sort_values("oos_dd", ascending=False).head(10)
    print(good2[["bucket","lb","k","b","rb","lev","mf",
                 "full_cagr","full_sharpe","full_dd","oos_cagr","oos_sharpe","oos_dd"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
