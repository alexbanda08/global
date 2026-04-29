"""
V23-V28 — Low-drawdown XSM variants.

The BALANCED 1.5× champion has OOS DD -63%.  All of these variants try
to cut that by ≥ 15 pp while keeping Sharpe ≥ 1.5.

V23  Volatility-targeted sizing
     Each coin's weight = (target_vol / realised_vol_28d), clipped [0.25, 1.5]
     Automatic de-levering in high-vol regimes.

V24  Multi-filter regime
     Enter only when: BTC > 100d-MA AND BTC > 50d-MA rising AND
     market-breadth (≥ 5 of 9 coins above their own 50d-MA).
     Defensive triple-confirmation filter.

V25  Portfolio DD circuit breaker
     After combined equity drops ≥ 20% from ATH, go FLAT and stay flat
     for ≥ 4 weeks OR until equity recovers to 90% of ATH.

V26  Dynamic leverage (vol-scaled)
     leverage_t = target_sigma / realised_sigma_28d (clip 0.5-2.0).
     Automatically reduces exposure in chop / vol spikes.

V27  Long-short hedged XSM
     Long top-K, short bottom-K, equal-weight.  Net beta near zero.

V28  Per-position stop-loss
     Hard 15% stop-loss per held coin.  Exits early if a winner flips.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab import portfolio_audit as pa

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","ADAUSDT","XRPUSDT",
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
BARS_PER_DAY = 6
OUT = Path(__file__).resolve().parent / "results"


def load_all() -> dict[str, pd.DataFrame]:
    return {sym: pa.load_ohlcv(sym, STARTS[sym], END) for sym in COINS}


def build_panel(data):
    idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    close = pd.DataFrame({s: df["close"].reindex(idx).ffill() for s, df in data.items()})
    open_ = pd.DataFrame({s: df["open"].reindex(idx).ffill() for s, df in data.items()})
    return close, open_, idx


def low_dd_xsm(
    data: dict,
    mode: str = "baseline",              # baseline, vol_target, multi_filter, dd_breaker,
                                         # dyn_lev, long_short, sl_per_pos, combined
    lookback_days: int = 14,
    top_k: int = 4,
    bottom_k: int = 0,
    rebal_days: int = 7,
    leverage: float = 1.0,
    btc_ma_days: int = 100,
    # V23 target-vol params
    target_ann_vol: float = 0.50,
    vol_lookback_bars: int = 168,        # 28 days
    vol_weight_clip: tuple = (0.25, 1.5),
    # V24 multi-filter
    mf_breadth_min: int = 5,
    mf_btc_ma_fast: int = 50,
    # V25 DD breaker
    dd_halt_thresh: float = 0.20,
    dd_halt_bars: int = 168,             # 4 wks
    dd_recover_pct: float = 0.90,
    # V26 dynamic leverage
    dyn_target_vol: float = 0.50,
    dyn_vol_lookback: int = 168,
    dyn_lev_clip: tuple = (0.5, 2.0),
    # V28 per-position SL
    per_pos_sl_pct: float = 0.15,
) -> tuple[pd.Series, int, dict]:

    close, open_, idx = build_panel(data)
    n = len(idx)
    rets_panel = close.pct_change(fill_method=None)
    equity = np.empty(n); equity[0] = INIT
    cash = INIT
    positions = {s: 0.0 for s in close}
    entry_prices = {s: 0.0 for s in close}
    trade_legs = 0
    step = rebal_days * BARS_PER_DAY
    lookback_bars = lookback_days * BARS_PER_DAY
    init_bars = max(lookback_bars, vol_lookback_bars, btc_ma_days * BARS_PER_DAY)
    if mode in ("multi_filter", "combined"):
        init_bars = max(init_bars, mf_btc_ma_fast * BARS_PER_DAY)

    btc_ma = close["BTCUSDT"].rolling(btc_ma_days * BARS_PER_DAY).mean()
    btc_ma_fast = close["BTCUSDT"].rolling(mf_btc_ma_fast * BARS_PER_DAY).mean()
    per_coin_ma50 = {s: close[s].rolling(50 * BARS_PER_DAY).mean() for s in close}

    equity_peak = INIT
    halted_until_bar = -1
    ann_factor = np.sqrt(365.25 * 24 / 4)
    stats = {"halt_events": 0, "trade_legs": 0}

    for i in range(n):
        # MTM
        mv = 0.0
        for s, sh in positions.items():
            px_now = close.iloc[i][s]
            if sh != 0 and not np.isnan(px_now):
                mv += sh * px_now
        eq = cash + mv
        equity_peak = max(equity_peak, eq)
        equity[i] = eq

        # V28 / combined: per-position stop-loss check every bar (not just rebalance)
        if mode in ("sl_per_pos", "combined"):
            for s in list(positions):
                if positions[s] > 0 and entry_prices[s] > 0:
                    px_now = close.iloc[i][s]
                    if not np.isnan(px_now) and px_now <= entry_prices[s] * (1 - per_pos_sl_pct):
                        gross = positions[s] * px_now
                        fee = abs(gross) * FEE
                        cash += gross - fee
                        trade_legs += 1
                        positions[s] = 0.0; entry_prices[s] = 0.0

        # DD circuit breaker
        if mode in ("dd_breaker", "combined"):
            dd_now = (eq / equity_peak) - 1
            if dd_now <= -dd_halt_thresh:
                # Flatten and halt
                if any(positions.values()):
                    for s in list(positions):
                        if positions[s] != 0:
                            px = open_.iloc[min(i+1, n-1)][s]
                            if np.isnan(px): continue
                            gross = positions[s] * px
                            fee = abs(gross) * FEE
                            cash += gross - fee
                            trade_legs += 1
                            positions[s] = 0.0; entry_prices[s] = 0.0
                halted_until_bar = i + dd_halt_bars
                stats["halt_events"] += 1

            if i < halted_until_bar:
                # Stay flat unless recovered
                if eq >= equity_peak * dd_recover_pct:
                    halted_until_bar = -1

        # Rebalance bar?
        if i < init_bars or (i - init_bars) % step != 0:
            continue
        if i < halted_until_bar:
            continue

        # ---------- BTC bear filter ----------
        btc_bear = False
        if not np.isnan(btc_ma.iloc[i]) and close["BTCUSDT"].iloc[i] < btc_ma.iloc[i]:
            btc_bear = True

        # ---------- V24 / combined: multi-filter ----------
        if mode in ("multi_filter", "combined") and not btc_bear:
            # Triple confirmation
            if not np.isnan(btc_ma_fast.iloc[i]):
                # BTC 50d MA rising?
                if i >= mf_btc_ma_fast * BARS_PER_DAY + 24:
                    if btc_ma_fast.iloc[i] < btc_ma_fast.iloc[i - 24]:  # 1-day flat/down
                        btc_bear = True
            # Market breadth — 5 of 9 coins above own 50d-MA
            breadth = 0
            for s in close:
                if idx[i] < pd.Timestamp(STARTS[s], tz="UTC"): continue
                ma = per_coin_ma50[s].iloc[i]
                if not np.isnan(ma) and close.iloc[i][s] > ma:
                    breadth += 1
            if breadth < mf_breadth_min:
                btc_bear = True

        if btc_bear:
            for s in list(positions):
                if positions[s] != 0:
                    px = open_.iloc[min(i+1, n-1)][s]
                    if np.isnan(px): continue
                    gross = positions[s] * px
                    fee = abs(gross) * FEE
                    cash += gross - fee
                    trade_legs += 1
                    positions[s] = 0.0; entry_prices[s] = 0.0
            continue

        # ---------- Rank by momentum ----------
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
        longs = sorted_sym[:top_k]
        shorts = sorted_sym[-bottom_k:] if bottom_k > 0 else []

        # ---------- V26 / combined: dynamic leverage ----------
        lev_t = leverage
        if mode in ("dyn_lev", "combined"):
            # portfolio realised vol on prior winners
            win_rets = rets_panel[longs].iloc[max(0, i - dyn_vol_lookback):i]
            port_ret = win_rets.mean(axis=1).dropna()
            if len(port_ret) > 20:
                realised = port_ret.std() * ann_factor
                if realised > 1e-6:
                    lev_t = dyn_target_vol / realised
                    lev_t = float(np.clip(lev_t, *dyn_lev_clip)) * leverage

        # ---------- Target weights ----------
        targets = {s: 0.0 for s in close}
        if mode in ("vol_target", "combined") and longs:
            # Inverse-vol sizing
            inv_vols = {}
            for s in longs + shorts:
                r_hist = rets_panel[s].iloc[max(0, i - vol_lookback_bars):i].dropna()
                if len(r_hist) < 10:
                    inv_vols[s] = 1.0
                else:
                    v = r_hist.std() * ann_factor
                    # Scale: target_vol/realised_vol, clipped
                    w = target_ann_vol / max(v, 1e-6)
                    inv_vols[s] = float(np.clip(w, *vol_weight_clip))
            total = sum(inv_vols.get(s, 1) for s in longs) or 1
            for s in longs: targets[s] = +inv_vols[s] / total * lev_t
            total_s = sum(inv_vols.get(s, 1) for s in shorts) or 1
            for s in shorts: targets[s] = -inv_vols[s] / total_s * lev_t
        else:
            # Equal-weight
            if longs:
                w = lev_t / len(longs)
                for s in longs: targets[s] = +w
            if shorts:
                w = lev_t / len(shorts)
                for s in shorts: targets[s] = -w

        # Apply rebalance
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
            if target_shares > 0 and (entry_prices[s] == 0 or (target_shares - (positions[s]-diff)) > 0):
                entry_prices[s] = px

    stats["trade_legs"] = trade_legs
    return pd.Series(equity, index=idx, name="equity"), trade_legs, stats


def metrics(eq: pd.Series) -> dict:
    if len(eq) < 50 or eq.iloc[-1] <= 0:
        return {"cagr":0,"sharpe":0,"dd":0,"calmar":0,"final":0}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    bpy = 365.25 * 24 / 4
    sh = (rets.mean() * bpy) / (rets.std() * np.sqrt(bpy) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr":round(float(cagr),4),"sharpe":round(float(sh),3),
            "dd":round(dd,4),"calmar":round(cagr/abs(dd) if dd<0 else 0,3),
            "final":round(float(eq.iloc[-1]),0)}


def main():
    data = load_all()
    print(f"Loaded {len(data)} coins")

    base_kw = dict(lookback_days=14, top_k=4, rebal_days=7, btc_ma_days=100)
    configs = [
        # (label, mode, overrides)
        ("BASELINE 1.0×",                "baseline",    {"leverage":1.0}),
        ("BASELINE 1.5×",                "baseline",    {"leverage":1.5}),
        # V23 vol-target
        ("V23 vol-target  target=35%  L=1×", "vol_target", {"leverage":1.0,"target_ann_vol":0.35}),
        ("V23 vol-target  target=50%  L=1×", "vol_target", {"leverage":1.0,"target_ann_vol":0.50}),
        ("V23 vol-target  target=50%  L=1.5×","vol_target", {"leverage":1.5,"target_ann_vol":0.50}),
        ("V23 vol-target  target=70%  L=1.5×","vol_target", {"leverage":1.5,"target_ann_vol":0.70}),
        # V24 multi-filter
        ("V24 multi-filter  breadth=5  L=1×", "multi_filter", {"leverage":1.0,"mf_breadth_min":5}),
        ("V24 multi-filter  breadth=6  L=1×", "multi_filter", {"leverage":1.0,"mf_breadth_min":6}),
        ("V24 multi-filter  breadth=5  L=1.5×","multi_filter", {"leverage":1.5,"mf_breadth_min":5}),
        # V25 DD breaker
        ("V25 DD breaker   halt@20%  L=1×",   "dd_breaker", {"leverage":1.0,"dd_halt_thresh":0.20}),
        ("V25 DD breaker   halt@25%  L=1.5×", "dd_breaker", {"leverage":1.5,"dd_halt_thresh":0.25}),
        ("V25 DD breaker   halt@30%  L=1.5×", "dd_breaker", {"leverage":1.5,"dd_halt_thresh":0.30}),
        # V26 dyn leverage
        ("V26 dyn-lev  target=40%  L=1×",     "dyn_lev", {"leverage":1.0,"dyn_target_vol":0.40}),
        ("V26 dyn-lev  target=50%  L=1.5×",   "dyn_lev", {"leverage":1.5,"dyn_target_vol":0.50}),
        # V27 long-short
        ("V27 long-short   L2/S2  L=1×",      "baseline", {"leverage":1.0,"top_k":2,"bottom_k":2}),
        ("V27 long-short   L3/S3  L=1×",      "baseline", {"leverage":1.0,"top_k":3,"bottom_k":3}),
        ("V27 long-short   L4/S4  L=1×",      "baseline", {"leverage":1.0,"top_k":4,"bottom_k":4}),
        # V28 per-pos SL
        ("V28 per-pos SL 15%  L=1×",          "sl_per_pos", {"leverage":1.0,"per_pos_sl_pct":0.15}),
        ("V28 per-pos SL 10%  L=1.5×",        "sl_per_pos", {"leverage":1.5,"per_pos_sl_pct":0.10}),
        ("V28 per-pos SL 20%  L=1.5×",        "sl_per_pos", {"leverage":1.5,"per_pos_sl_pct":0.20}),
        # Combined
        ("COMBINED v23+v25  L=1×",            "combined",   {"leverage":1.0,"target_ann_vol":0.50,"dd_halt_thresh":0.25}),
        ("COMBINED v23+v25+v28  L=1.5×",      "combined",   {"leverage":1.5,"target_ann_vol":0.50,"dd_halt_thresh":0.25,"per_pos_sl_pct":0.15}),
    ]

    rows = []
    for label, mode, over in configs:
        kw = {**base_kw, **over}
        try:
            eq, legs, stats = low_dd_xsm(data, mode=mode, **kw)
        except Exception as e:
            print(f"  {label}: error {e}"); continue
        m = metrics(eq)
        # OOS
        oos_mask = eq.index >= pd.Timestamp("2022-01-01", tz="UTC")
        m_oos = metrics(eq[oos_mask])
        row = {"label": label, "mode": mode, "legs": legs, "halts": stats.get("halt_events", 0),
               **{f"full_{k}": v for k, v in m.items()},
               **{f"oos_{k}":  v for k, v in m_oos.items()}}
        rows.append(row)
        print(f"  {label:<42} CAGR {m['cagr']*100:+6.1f}% Sh {m['sharpe']:+.2f} "
              f"DD {m['dd']*100:+6.1f}% Calmar {m['calmar']:5.2f} "
              f"Final {_fmt(m['final'])}  |  OOS DD {m_oos['dd']*100:+6.1f}%",
              flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v23_low_dd.csv", index=False)

    print("\n=== RANKED BY |OOS DD| (smallest first, profitable only) ===")
    good = df[df["full_final"] > INIT].copy()
    good = good.sort_values("oos_dd", ascending=False)   # least negative first
    print(good[["label","full_cagr","full_sharpe","full_dd","full_calmar","oos_cagr","oos_sharpe","oos_dd","legs","halts"]]
          .to_string(index=False))


def _fmt(x):
    ax = abs(x)
    if ax >= 1e6: return f"${x/1e6:.1f}M"
    if ax >= 1e3: return f"${x/1e3:.0f}k"
    return f"${x:.0f}"


if __name__ == "__main__":
    main()
