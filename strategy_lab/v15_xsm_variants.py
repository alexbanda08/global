"""
V15 — XSM variants exploration.

Starts from the V14 winner and sweeps orthogonal improvements:

  V15A  long-short XSM (long top-K, short bottom-K)
  V15B  multi-lookback composite rank (avg of 7d/14d/28d/56d)
  V15C  volatility-adjusted momentum (return / realized vol)
  V15D  vol-adjusted momentum + BTC bear filter + per-coin trend filter
  V15E  risk-parity weighting (inverse-vol, normalised)
  V15F  single-lookback momentum with bigger grid (k, lb, rb sweep)

All variants:
  - same 9-coin universe
  - 4h bars
  - Hyperliquid maker fees (0.015 %), no slippage
  - weekly rebalance by default
  - BTC-100d-MA bear filter optional

Output: strategy_lab/results/v15_xsm.csv — one row per config.
"""
from __future__ import annotations
import itertools, json
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
FEE = 0.00015
OUT = Path(__file__).resolve().parent / "results"


def load_all_4h() -> dict[str, pd.DataFrame]:
    out = {}
    for sym in COINS:
        try:
            out[sym] = pa.load_ohlcv(sym, STARTS[sym], END)
        except Exception as e:
            print(f"  skip {sym}: {e}")
    return out


def build_panel(data: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    close = pd.DataFrame({s: df["close"].reindex(idx).ffill() for s, df in data.items()})
    open_ = pd.DataFrame({s: df["open"].reindex(idx).ffill() for s, df in data.items()})
    return close, open_, idx


def compute_score(close: pd.DataFrame, idx: pd.DatetimeIndex, i: int,
                  mode: str, lookback_bars: int | list,
                  vol_bars: int = 60) -> dict:
    """Return {sym: score} for eligible coins at bar i."""
    scores = {}
    for s in close.columns:
        p_now = close.iloc[i][s]
        if np.isnan(p_now): continue
        if idx[i] < pd.Timestamp(STARTS[s], tz="UTC"): continue

        if mode == "mom":
            lb = lookback_bars
            if i < lb: continue
            p0 = close.iloc[i - lb][s]
            if np.isnan(p0) or p0 <= 0: continue
            scores[s] = (p_now / p0) - 1

        elif mode == "composite":
            # Weighted average of ranks across multiple lookbacks
            lookbacks = lookback_bars  # list
            rets_per_lb = []
            for lb in lookbacks:
                if i < lb: rets_per_lb.append(None); continue
                p0 = close.iloc[i - lb][s]
                if np.isnan(p0) or p0 <= 0: rets_per_lb.append(None); continue
                rets_per_lb.append((p_now / p0) - 1)
            if any(r is None for r in rets_per_lb): continue
            scores[s] = np.mean(rets_per_lb)

        elif mode == "vol_adj":
            lb = lookback_bars
            if i < max(lb, vol_bars): continue
            p0 = close.iloc[i - lb][s]
            if np.isnan(p0) or p0 <= 0: continue
            ret = (p_now / p0) - 1
            # Realized vol over last `vol_bars` bars
            window = close.iloc[i - vol_bars:i][s].dropna()
            if len(window) < vol_bars // 2: continue
            vol = window.pct_change().std()
            if np.isnan(vol) or vol <= 1e-9: continue
            scores[s] = ret / vol
    return scores


def xsm_generic(data: dict,
                mode: str,                   # "mom" | "composite" | "vol_adj"
                lookback_days,               # int or list (for composite)
                top_k: int = 2,
                bottom_k: int = 0,           # if >0, long/short
                rebal_days: int = 7,
                btc_filter: bool = True,
                btc_ma_days: int = 100,
                per_coin_filter: bool = False,
                per_coin_ma_days: int = 50,
                vol_weighted: bool = False,
                leverage: float = 1.0,
                ) -> tuple[pd.Series, int]:
    close, open_, idx = build_panel(data)
    n = len(idx)
    equity = np.empty(n); equity[0] = INIT
    cash = INIT
    positions = {s: 0.0 for s in close}   # shares (positive long, negative short)
    trade_legs = 0

    step = rebal_days * 6
    if isinstance(lookback_days, list):
        lookback_bars = [d * 6 for d in lookback_days]
        init_bars = max(lookback_bars)
    else:
        lookback_bars = lookback_days * 6
        init_bars = lookback_bars

    # BTC filter pre-computed
    btc_ma = None
    if btc_filter and "BTCUSDT" in close:
        btc_ma = close["BTCUSDT"].rolling(btc_ma_days * 6).mean()

    per_coin_ma = {}
    if per_coin_filter:
        for s in close:
            per_coin_ma[s] = close[s].rolling(per_coin_ma_days * 6).mean()

    vol_bars = 60

    for i in range(n):
        # MTM
        mv = 0.0
        for s, sh in positions.items():
            if sh != 0 and not np.isnan(close.iloc[i][s]):
                mv += sh * close.iloc[i][s]
        eq = cash + mv

        if i >= init_bars and (i - init_bars) % step == 0:
            # BTC bear check
            btc_bear = False
            if btc_filter and btc_ma is not None:
                if not np.isnan(btc_ma.iloc[i]) and close["BTCUSDT"].iloc[i] < btc_ma.iloc[i]:
                    btc_bear = True
            if btc_bear:
                # flat
                for s in list(positions):
                    if positions[s] != 0:
                        px = open_.iloc[min(i+1, n-1)][s]
                        if np.isnan(px): continue
                        gross = positions[s] * px
                        fee = abs(gross) * FEE
                        cash += gross - fee
                        trade_legs += 1
                        positions[s] = 0.0
                equity[i] = eq
                continue

            scores = compute_score(close, idx, i, mode, lookback_bars, vol_bars)
            if len(scores) < top_k + bottom_k + 1:
                equity[i] = eq; continue

            sorted_sym = sorted(scores, key=lambda s: scores[s], reverse=True)
            longs = sorted_sym[:top_k]
            shorts = sorted_sym[-bottom_k:] if bottom_k > 0 else []

            # Per-coin trend filter on longs
            if per_coin_filter and per_coin_ma:
                longs = [s for s in longs
                         if not np.isnan(per_coin_ma[s].iloc[i])
                         and close.iloc[i][s] > per_coin_ma[s].iloc[i]]
                if bottom_k > 0:
                    shorts = [s for s in shorts
                              if not np.isnan(per_coin_ma[s].iloc[i])
                              and close.iloc[i][s] < per_coin_ma[s].iloc[i]]

            # Compute target weights
            targets = {s: 0.0 for s in close}
            if vol_weighted and len(longs) > 0:
                inv_vols = {}
                for s in longs + shorts:
                    win = close.iloc[max(0, i - vol_bars):i][s].dropna()
                    if len(win) < 20:
                        inv_vols[s] = 1.0
                    else:
                        v = win.pct_change().std()
                        inv_vols[s] = 1 / max(v, 1e-6)
                total_inv = sum(inv_vols.get(s, 1) for s in longs) or 1
                for s in longs:
                    targets[s] = +inv_vols.get(s, 1) / total_inv * leverage
                total_inv_s = sum(inv_vols.get(s, 1) for s in shorts) or 1
                for s in shorts:
                    targets[s] = -inv_vols.get(s, 1) / total_inv_s * leverage
            else:
                if longs:
                    w = leverage / len(longs)
                    for s in longs: targets[s] = +w
                if shorts:
                    w = leverage / len(shorts)
                    for s in shorts: targets[s] = -w

            # Rebalance each symbol
            for s in close:
                target_notional = eq * targets[s]
                px = open_.iloc[min(i+1, n-1)][s]
                if np.isnan(px): continue
                target_shares = target_notional / px
                current = positions[s]
                diff = target_shares - current
                if abs(diff) * px < 0.005 * eq: continue
                gross = diff * px
                fee = abs(gross) * FEE
                cash -= gross + fee
                trade_legs += 1
                positions[s] = target_shares

        equity[i] = eq

    return pd.Series(equity, index=idx, name="equity"), trade_legs


def mx(eq: pd.Series) -> dict:
    if len(eq) < 20: return {}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    bpy = pa.BARS_PER_YR
    sh = (rets.mean() * bpy) / (rets.std() * np.sqrt(bpy) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr":round(float(cagr),4), "sharpe":round(float(sh),3),
            "dd":round(dd,4),
            "calmar":round(cagr/abs(dd) if dd < 0 else 0, 3),
            "final":round(float(eq.iloc[-1]),0)}


def main():
    data = load_all_4h()
    print(f"Loaded {len(data)} coins")

    configs = []
    # V15A — long-short (long top-K, short bottom-K), BTC filter
    for k, b in [(2, 2), (3, 3), (2, 1), (3, 2)]:
        configs.append(("V15A_LS", "mom", 28, k, b, 7, True, False, False, 1.0))

    # V15B — composite multi-lookback rank (mean of [7d, 14d, 28d, 56d])
    for k in [2, 3]:
        configs.append((f"V15B_composite_k{k}", "composite", [7, 14, 28, 56], k, 0, 7, True, False, False, 1.0))

    # V15C — vol-adjusted momentum
    for lb, k in [(14, 2), (28, 2), (28, 3), (56, 2)]:
        configs.append((f"V15C_voladj_lb{lb}k{k}", "vol_adj", lb, k, 0, 7, True, False, False, 1.0))

    # V15D — vol-adjusted + per-coin filter
    for lb, k in [(28, 2), (28, 3)]:
        configs.append((f"V15D_voladj_TF_lb{lb}k{k}", "vol_adj", lb, k, 0, 7, True, True, False, 1.0))

    # V15E — vol-weighted (risk parity-ish) allocation
    for k in [2, 3]:
        configs.append((f"V15E_volwt_k{k}", "mom", 28, k, 0, 7, True, False, True, 1.0))

    # V15F — fine grid sweep of plain momentum
    for lb in [14, 21, 28, 42, 56]:
        for k in [1, 2, 3, 4]:
            for rb in [3, 7, 14]:
                configs.append((f"V15F_lb{lb}_k{k}_rb{rb}", "mom", lb, k, 0, rb, True, False, False, 1.0))

    rows = []
    for name, mode, lb, k, b, rb, btc_f, pc_f, vw, lev in configs:
        eq, legs = xsm_generic(data, mode, lb, k, b, rb, btc_f, 100, pc_f, 50, vw, lev)
        m = mx(eq)
        # per-year
        yrs = {}
        for y in (2022, 2023, 2024, 2025):
            s = pd.Timestamp(f"{y}-01-01", tz="UTC"); e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
            sub = eq[(eq.index >= s) & (eq.index < e)]
            yrs[y] = round(float(sub.iloc[-1] / sub.iloc[0] - 1), 3) if len(sub) > 5 else None
        row = {"name": name, "mode": mode, "lookback": str(lb), "top_k": k, "bottom_k": b,
               "rebal_d": rb, "btc_filter": btc_f, "per_coin_filter": pc_f,
               "vol_weighted": vw, "leverage": lev,
               "trade_legs": legs, **m,
               **{f"ret_{y-2000}": yrs[y] for y in (2022, 2023, 2024, 2025)}}
        rows.append(row)
        print(f"  {name:<28}  cagr={m.get('cagr',0)*100:+7.1f}% sh={m.get('sharpe',0):5.2f} "
              f"dd={m.get('dd',0)*100:+6.1f}% calmar={m.get('calmar',0):5.2f} "
              f"final=${m.get('final',0):,.0f} legs={legs}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v15_xsm.csv", index=False)

    print("\n=== TOP 15 BY CALMAR (FULL period) ===")
    print(df.sort_values("calmar", ascending=False).head(15)[
        ["name","cagr","sharpe","dd","calmar","final",
         "ret_22","ret_23","ret_24","ret_25","trade_legs"]].to_string(index=False))

    print("\n=== TOP 10 BY SHARPE ===")
    print(df.sort_values("sharpe", ascending=False).head(10)[
        ["name","cagr","sharpe","dd","calmar","final"]].to_string(index=False))


if __name__ == "__main__":
    main()
