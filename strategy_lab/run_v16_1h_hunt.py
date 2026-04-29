"""
V16 — 1h hunt, round 3.

Key additions:
  * Risk-per-trade sweep: {1.5%, 3%, 5%}
  * Fee regime sweep: {taker 0.045%, maker 0.015%} — tells us edge sensitivity
  * Portfolio combiner: build a 3-asset equally-weighted portfolio, report
    portfolio-level CAGR/Sharpe/DD (should have lower DD than any single asset).
  * Strategy set narrowed to the survivors from v14/v15 plus a few new angles:
      - RangeKalman (standalone best on ETH)
      - BBbreak (survivor)
      - MTF_Momentum (1h Donchian + 4h + 1d trend filter)
      - Plus new S12: "TrendRiderLS" (Supertrend-driven long/short)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import talib

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "strategy_lab" / "features"
OUT = ROOT / "strategy_lab" / "results" / "v16"
OUT.mkdir(parents=True, exist_ok=True)

SLIP = 0.0003
INIT = 10_000.0
FUNDING_APR = 0.08


# -------- indicators (duplicated for self-contained run) --------
def atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum.reduce([h - l, np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    return pd.Series(tr, index=df.index).ewm(alpha=1 / n, adjust=False).mean().values


def ema(x, n): return x.ewm(span=n, adjust=False).mean()


def kalman_ema(c, alpha):
    n = len(c); k = np.zeros(n); k[0] = c[0]
    for i in range(1, n):
        k[i] = k[i - 1] + alpha * (c[i] - k[i - 1])
    return k


def supertrend(df, n=10, mult=3.0):
    at = atr(df, n)
    hl2 = (df["high"].values + df["low"].values) / 2.0
    ub = hl2 + mult * at; lb = hl2 - mult * at
    close = df["close"].values
    N = len(close); trend = np.ones(N, dtype=np.int8)
    fub = np.full(N, np.nan); flb = np.full(N, np.nan)
    for i in range(1, N):
        if not np.isfinite(ub[i]): continue
        fub[i] = ub[i] if (np.isnan(fub[i - 1]) or ub[i] < fub[i - 1] or close[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (np.isnan(flb[i - 1]) or lb[i] > flb[i - 1] or close[i - 1] < flb[i - 1]) else flb[i - 1]
        if close[i] > (fub[i - 1] if np.isfinite(fub[i - 1]) else ub[i]):
            trend[i] = 1
        elif close[i] < (flb[i - 1] if np.isfinite(flb[i - 1]) else lb[i]):
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return trend


def donchian_up(h, n): return h.rolling(n).max().shift(1)
def donchian_dn(l, n): return l.rolling(n).min().shift(1)


def bb(c, n=120, k=2.0):
    m = c.rolling(n).mean(); s = c.rolling(n).std()
    return m, m + k * s, m - k * s


# -------- simulator --------
def simulate(df, long_entries, short_entries=None,
             tp_atr=5.0, sl_atr=2.0, trail_atr=3.5, max_hold=72,
             risk_per_trade=0.03, leverage_cap=3.0, fee=0.00045):
    op = df["open"].values; hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    at = atr(df)
    sig_l = long_entries.values.astype(bool)
    sig_s = short_entries.values.astype(bool) if short_entries is not None else np.zeros(len(df), dtype=bool)

    N = len(df); cash = INIT
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = sl = tp = 0.0; size = 0.0; entry_idx = 0; last_exit = -9999
    hh = 0.0; ll = 0.0
    trades = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx
            if trail_atr is not None:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - trail_atr * at[i]
                    if new_sl > sl: sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trail_atr * at[i]
                    if new_sl < sl: sl = new_sl

            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if lo[i] <= sl: ep = sl * (1 - SLIP); reason = "SL"; exited = True
                elif hi[i] >= tp: ep = tp * (1 - SLIP); reason = "TP"; exited = True
                elif held >= max_hold: ep = cl[i]; reason = "TIME"; exited = True
            else:
                if hi[i] >= sl: ep = sl * (1 + SLIP); reason = "SL"; exited = True
                elif lo[i] <= tp: ep = tp * (1 + SLIP); reason = "TP"; exited = True
                elif held >= max_hold: ep = cl[i]; reason = "TIME"; exited = True

            if exited:
                pnl = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * fee
                realized = size * pnl - fee_cost
                notional = size * entry_p
                eq_at_entry = cash
                cash += realized
                ret = realized / max(eq_at_entry, 1.0)
                trades.append({"ret": ret, "realized": realized, "notional": notional,
                               "reason": reason, "side": pos, "bars": held,
                               "entry": entry_p, "exit": ep,
                               # Dashboard-schema fields (set net_gain explicitly so
                               # short PnL doesn't get mis-derived from price diff alone):
                               "entry_time": df.index[entry_idx],
                               "exit_time":  df.index[i],
                               "entry_price": float(entry_p),
                               "exit_price":  float(ep),
                               "shares":      float(size),
                               "net_gain":    float(realized)})
                pos = 0; last_exit = i; eq[i] = cash; continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep = op[i + 1] * (1 + SLIP * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0:
                    risk_dollars = cash * risk_per_trade
                    stop_dist = sl_atr * at[i]
                    size_risk = risk_dollars / stop_dist
                    size_cap = (cash * leverage_cap) / ep
                    size = min(size_risk, size_cap)
                    s_stop = ep - sl_atr * at[i] * direction
                    t_stop = ep + tp_atr * at[i] * direction
                    if size > 0 and np.isfinite(s_stop) and np.isfinite(t_stop):
                        pos = direction; entry_p = ep; sl = s_stop; tp = t_stop; entry_idx = i + 1
                        hh = ep; ll = ep

        if pos == 0: eq[i] = cash
        else: eq[i] = cash + size * (cl[i] - entry_p) * pos
    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


def metrics(label, eq, trades):
    if len(trades) < 5:
        return {"label": label, "n": len(trades), "final": float(eq.iloc[-1]),
                "cagr": 0, "sharpe": 0, "dd": 0, "win": 0, "pf": 0, "cagr_net": 0,
                "exposure": 0, "avg_lev": 0, "funding_drag": 0}
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = float((eq / eq.cummax() - 1).min())
    pnl = np.array([t["ret"] for t in trades])
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else 0
    exposure = sum(t["bars"] for t in trades) / max(len(eq), 1)
    avg_lev = np.mean([t["notional"] for t in trades]) / float(eq.mean())
    funding_drag = FUNDING_APR * avg_lev * exposure
    return dict(label=label, n=len(trades), final=float(eq.iloc[-1]),
                cagr=round(cagr, 4), cagr_net=round(cagr - funding_drag, 4),
                sharpe=round(sh, 3), dd=round(dd, 4),
                win=round((pnl > 0).mean(), 3), pf=round(pf, 3),
                exposure=round(exposure, 3), avg_lev=round(avg_lev, 2),
                funding_drag=round(funding_drag, 4))


def portfolio_metrics(eqs: dict):
    """Equal-weight combine per-asset equity curves."""
    # Rebase each to 1.0 at start of its earliest overlap
    aligned = pd.concat({k: v / v.iloc[0] for k, v in eqs.items()}, axis=1)
    aligned = aligned.dropna(how="all").ffill()
    start = aligned.dropna().index.min()
    port = aligned[aligned.index >= start].mean(axis=1)
    port = port * INIT
    rets = port.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25) / dt if dt else 1
    sh = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0
    yrs = (port.index[-1] - port.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (port.iloc[-1] / port.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    dd = float((port / port.cummax() - 1).min())
    return dict(cagr=round(cagr, 4), sharpe=round(sh, 3), dd=round(dd, 4),
                final=float(port.iloc[-1]), yrs=round(yrs, 2)), port


# -------- signal builders --------
def sig_rangekalman(df, alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800):
    c = df["close"].values
    kal = kalman_ema(c, alpha)
    rng = pd.Series(np.abs(c - kal), index=df.index).rolling(rng_len).mean().values * rng_mult
    upper = kal + rng
    regime = c > pd.Series(c, index=df.index).rolling(regime_len).mean().values
    u_prev = np.roll(upper, 1); c_prev = np.roll(c, 1)
    sig = (c > upper) & (c_prev <= u_prev) & regime
    sig[0] = False
    return pd.Series(sig, index=df.index)


def sig_rangekalman_short(df, alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800):
    c = df["close"].values
    kal = kalman_ema(c, alpha)
    rng = pd.Series(np.abs(c - kal), index=df.index).rolling(rng_len).mean().values * rng_mult
    lower = kal - rng
    regime_bear = c < pd.Series(c, index=df.index).rolling(regime_len).mean().values
    l_prev = np.roll(lower, 1); c_prev = np.roll(c, 1)
    sig = (c < lower) & (c_prev >= l_prev) & regime_bear
    sig[0] = False
    return pd.Series(sig, index=df.index)


def sig_bbbreak(df, n=120, k=2.0, regime_len=600):
    _, ub, _ = bb(df["close"], n, k)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"] > ub) & (df["close"].shift(1) <= ub.shift(1)) & pd.Series(regime, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_mtf(df, don_n=24, d_ema=200, h4_ema=50):
    daily = df["close"].resample("1D").last().dropna()
    d_bull = (daily > ema(daily, d_ema)).reindex(df.index, method="ffill").fillna(False)
    h4 = df["close"].resample("4h").last().dropna()
    h4_bull = (h4 > ema(h4, h4_ema)).reindex(df.index, method="ffill").fillna(False)
    up = donchian_up(df["high"], don_n).values
    return pd.Series((df["close"].values > up) & d_bull.values & h4_bull.values, index=df.index)


def sig_trend_rider_long(df, st_n=14, st_mult=3.0, regime_len=600):
    tr = supertrend(df, st_n, st_mult)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    tr_prev = np.roll(tr, 1)
    return pd.Series((tr == 1) & (tr_prev == -1) & regime, index=df.index)


def sig_trend_rider_short(df, st_n=14, st_mult=3.0, regime_len=600):
    tr = supertrend(df, st_n, st_mult)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    tr_prev = np.roll(tr, 1)
    return pd.Series((tr == -1) & (tr_prev == 1) & regime_bear, index=df.index)


STRATS = [
    ("RangeKalman_L",  sig_rangekalman, None, {"alpha": 0.07}),
    ("RangeKalman_LS", sig_rangekalman, sig_rangekalman_short, {"alpha": 0.07}),
    ("RangeKalman_L_a05", sig_rangekalman, None, {"alpha": 0.05}),
    ("BBbreak",        sig_bbbreak,     None, {"n": 120, "k": 2.0}),
    ("BBbreak_w",      sig_bbbreak,     None, {"n": 168, "k": 2.2}),
    ("MTF_d24",        sig_mtf,         None, {"don_n": 24}),
    ("MTF_d48",        sig_mtf,         None, {"don_n": 48}),
    ("TrendRider_LS",  sig_trend_rider_long, sig_trend_rider_short, {"st_n": 14, "st_mult": 3.0}),
]


def main():
    START = pd.Timestamp("2019-01-01", tz="UTC")
    rows = []
    # Track per-asset best equity curves for portfolio combiner
    per_asset_best = {}  # symbol -> (label, eq)

    # Fee regimes
    FEES = [("taker", 0.00045), ("maker", 0.00015)]
    # Risk/leverage grid
    RISK_LEV = [(0.015, 2.0), (0.03, 2.0), (0.03, 3.0), (0.05, 3.0)]

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = pd.read_parquet(FEAT / f"{sym}_1h_features.parquet")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
        df = df[df.index >= START]
        print(f"\n=== {sym}  ({len(df):,} bars) ===", flush=True)

        best_for_sym = None
        for (fee_name, fee), (risk, lev), (sname, sl_fn, ss_fn, params) in [
            (f, rl, s) for f in FEES for rl in RISK_LEV for s in STRATS
        ]:
            plabel = ",".join(f"{k}={v}" for k, v in params.items())
            try:
                l_sig = sl_fn(df, **params); l_sig = l_sig & ~l_sig.shift(1).fillna(False)
                s_sig = None
                if ss_fn is not None:
                    s_sig = ss_fn(df, **params); s_sig = s_sig & ~s_sig.shift(1).fillna(False)
                trades, eq = simulate(df, l_sig, short_entries=s_sig,
                                      tp_atr=5.0, sl_atr=2.0, trail_atr=3.5, max_hold=72,
                                      risk_per_trade=risk, leverage_cap=lev, fee=fee)
                r = metrics(f"{sym}_{sname}_{plabel}_{fee_name}_r{risk}L{lev}", eq, trades)
                r["symbol"] = sym; r["strategy"] = sname; r["params"] = plabel
                r["fee_mode"] = fee_name; r["risk"] = risk; r["leverage"] = lev
                rows.append(r)
                if (best_for_sym is None) or (
                    r["cagr_net"] > best_for_sym[0]["cagr_net"]
                    and r["dd"] >= -0.45 and r["sharpe"] >= 0.6
                ):
                    best_for_sym = (r, eq)
            except Exception as e:
                print(f"  {sname} {plabel} {fee_name} r{risk}L{lev}  ERR: {e}")

        if best_for_sym is not None:
            r, eq = best_for_sym
            per_asset_best[sym] = (r, eq)
            print(f"  best: {r['label']}  CAGR={r['cagr']*100:+6.1f}% Sh={r['sharpe']:.2f} DD={r['dd']*100:+6.1f}% avgL={r['avg_lev']:.2f}")

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v16_hunt_results.csv", index=False)

    cols = ["symbol", "strategy", "params", "fee_mode", "risk", "leverage",
            "avg_lev", "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf",
            "exposure", "funding_drag", "final"]

    # Top-10 single-asset by cagr_net
    top = out[(out["dd"] >= -0.40) & (out["sharpe"] >= 0.6)].copy()
    top = top.sort_values("cagr_net", ascending=False).head(20)
    print("\n=== Top single-asset configs (DD>=-40%, Sharpe>=0.6) ===")
    print(top[cols].to_string(index=False))

    # Portfolio: best-per-asset combo
    if len(per_asset_best) >= 2:
        eqs = {k: v[1] for k, v in per_asset_best.items()}
        pm, port_eq = portfolio_metrics(eqs)
        print("\n=== Portfolio (equal-weight, best per asset) ===")
        for k, (r, _) in per_asset_best.items():
            print(f"  {k}: {r['label']}  CAGR={r['cagr']*100:+6.1f}% Sh={r['sharpe']:.2f} DD={r['dd']*100:+6.1f}%")
        print(f"  PORTFOLIO: CAGR {pm['cagr']*100:+.1f}% / Sharpe {pm['sharpe']:.2f} / DD {pm['dd']*100:+.1f}% / Final ${pm['final']:,.0f} over {pm['yrs']} yrs")
        port_eq.to_csv(OUT / "v16_portfolio_equity.csv")
        with open(OUT / "v16_portfolio_metrics.json", "w") as fh:
            json.dump({"per_asset": {k: v[0] for k, v in per_asset_best.items()},
                       "portfolio": pm}, fh, indent=2, default=str)

    # Winners
    winners = out[(out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["sharpe"] >= 0.9)].copy()
    winners = winners.sort_values("cagr_net", ascending=False)
    winners.to_csv(OUT / "v16_winners.csv", index=False)
    print(f"\nWinners (CAGR>=55%, DD>=-40%, Sharpe>=0.9): {len(winners)}")
    if len(winners):
        print(winners[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
