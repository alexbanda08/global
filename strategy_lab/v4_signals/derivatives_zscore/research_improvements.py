"""Broad research sweep for v4 — test multiple regime filters × exit rules.

Hypotheses (each is a discrete experimental knob):
  Entry filters (on top of z_lsr<-1.5 base trigger):
    F0  none — pure base trigger (control)
    F1  ma200      — price > 200d MA (classic risk-on)
    F2  ma50_up    — 50d MA slope rising (medium-term uptrend)
    F3  low_vol    — realized 30d vol < median (mean-reversion easier in calm regimes)
    F4  funding_band — |z_fund| < 1.5 (skip funding extremes both ways)
    F5  n_of_m     — at least 3 of {z_lsr<-1.5, z_fund<-0.5, z_oi_silent>1, brigalS<-1, oilsr>0} fire
    F6  btc_confluence (alts only) — BTC also has z_lsr<-1.0 in same hour
    F7  top_trader — sum_toptrader_long_short_ratio z-score below -1 (institutional bearish too)
    F8  ma200_AND_lowvol  — F1 ∩ F3 (the most defensive combo)

  Exit rules (replace 24h-fixed):
    E0  24h_fixed  — control
    E1  48h_fixed  — longer hold for stronger signal
    E2  trail_5pct — trailing stop, lock in gains
    E3  tp_or_24h  — take-profit at +5% OR 24h timeout
    E4  zcross     — exit when z_lsr crosses back above -0.5
    E5  vol_scaled_hold — hold = 24h × clip(0.5/realized_vol, 0.5, 2.0)

Hyperliquid fees: 12bp RT.
Composite ranking: prefer (PF >= 1.20) AND (MaxDD >= -30%) AND (n_trades >= 30).
"""
from __future__ import annotations
from pathlib import Path
import argparse
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
REPORTS.mkdir(parents=True, exist_ok=True)

FEE_BPS_PER_SIDE = 6.0  # Hyperliquid 4.5 + slip 1.5


def load_h(symbol: str, btc_panel: pd.DataFrame | None = None) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet").resample("1h").last()
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")["close"].astype(float)
    p["price"] = spot.reindex(p.index, method="ffill")
    p["ma_200d"] = p["price"].rolling(200 * 24, min_periods=200 * 24).mean()
    p["ma_50d"] = p["price"].rolling(50 * 24, min_periods=50 * 24).mean()
    p["ma_50d_24h_ago"] = p["ma_50d"].shift(24)
    p["ret_1h"] = p["price"].pct_change()
    p["realized_vol_30d"] = p["ret_1h"].rolling(30 * 24).std() * np.sqrt(24 * 365)
    p["vol_median"] = p["realized_vol_30d"].rolling(90 * 24, min_periods=24 * 24).median()
    # top-trader LSR z-score
    p["z_top_lsr"] = ((p["sum_toptrader_long_short_ratio"]
                      - p["sum_toptrader_long_short_ratio"].rolling(21).mean())
                     / p["sum_toptrader_long_short_ratio"].rolling(21).std().replace(0, np.nan))
    # join BTC z_lsr for cross-asset confluence (alts only)
    if btc_panel is not None and symbol != "BTCUSDT":
        p["btc_z_lsr"] = btc_panel["z_lsr"].reindex(p.index, method="ffill")
    else:
        p["btc_z_lsr"] = np.nan
    return p.dropna(subset=["price", "z_lsr", "z_oi_silent"])


# ────────────────────────────────────────────────────────────
#  Entry filters — return True iff entry conditions met
# ────────────────────────────────────────────────────────────

def base_trigger(r) -> bool:
    """Common base: extreme bearish positioning."""
    return r.z_lsr < -1.5


def filter_F0(r) -> bool:
    return base_trigger(r)


def filter_F1(r) -> bool:
    if pd.isna(r.ma_200d):
        return False
    return base_trigger(r) and r.price > r.ma_200d


def filter_F2(r) -> bool:
    if pd.isna(r.ma_50d) or pd.isna(r.ma_50d_24h_ago):
        return False
    return base_trigger(r) and r.ma_50d > r.ma_50d_24h_ago


def filter_F3(r) -> bool:
    if pd.isna(r.realized_vol_30d) or pd.isna(r.vol_median):
        return False
    return base_trigger(r) and r.realized_vol_30d < r.vol_median


def filter_F4(r) -> bool:
    if pd.isna(r.z_fund):
        return False
    return base_trigger(r) and abs(r.z_fund) < 1.5


def filter_F5(r) -> bool:
    """n-of-m: at least 3 of 5 confirmations."""
    confs = [
        r.z_lsr < -1.5,
        not pd.isna(r.z_fund) and r.z_fund < -0.5,
        not pd.isna(r.z_oi_silent) and r.z_oi_silent > 1.0,
        not pd.isna(r.brigalS) and r.brigalS < -1.0,
        not pd.isna(r.oilsr) and r.oilsr > 0,
    ]
    return sum(confs) >= 3


def filter_F6(r) -> bool:
    if pd.isna(r.btc_z_lsr):
        return False
    return base_trigger(r) and r.btc_z_lsr < -1.0


def filter_F7(r) -> bool:
    if pd.isna(r.z_top_lsr):
        return False
    return base_trigger(r) and r.z_top_lsr < -1.0


def filter_F8(r) -> bool:
    if pd.isna(r.ma_200d) or pd.isna(r.realized_vol_30d) or pd.isna(r.vol_median):
        return False
    return base_trigger(r) and r.price > r.ma_200d and r.realized_vol_30d < r.vol_median


ENTRY_FILTERS = {
    "F0_none":              filter_F0,
    "F1_ma200":             filter_F1,
    "F2_ma50_up":           filter_F2,
    "F3_low_vol":           filter_F3,
    "F4_funding_band":      filter_F4,
    "F5_n_of_m":            filter_F5,
    "F6_btc_confluence":    filter_F6,
    "F7_top_trader":        filter_F7,
    "F8_ma200_lowvol":      filter_F8,
}


# ────────────────────────────────────────────────────────────
#  Exit rules — return True iff should exit
# ────────────────────────────────────────────────────────────

def exit_24h_fixed(r, ctx) -> bool:
    return ctx["bars_held"] >= 24


def exit_48h_fixed(r, ctx) -> bool:
    return ctx["bars_held"] >= 48


def exit_trail_5pct(r, ctx) -> bool:
    """Trailing stop: exit if drops 5% from highest mark since entry."""
    if ctx["bars_held"] < 1:
        return False
    if ctx["mark_eq"] > ctx["high_water"]:
        ctx["high_water"] = ctx["mark_eq"]
    drawdown_from_peak = (ctx["mark_eq"] / ctx["high_water"]) - 1
    return drawdown_from_peak <= -0.05 or ctx["bars_held"] >= 96  # 4-day cap


def exit_tp_or_24h(r, ctx) -> bool:
    """Take-profit at +5% OR 24h timeout."""
    pl = (ctx["mark_eq"] / ctx["entry_eq"]) - 1
    return pl >= 0.05 or ctx["bars_held"] >= 24


def exit_zcross(r, ctx) -> bool:
    """Exit when z_lsr crosses back above -0.5."""
    return r.z_lsr > -0.5 or ctx["bars_held"] >= 96


def exit_vol_scaled_hold(r, ctx) -> bool:
    """Hold-period inversely proportional to realized vol."""
    hold = ctx.get("scheduled_hold")
    if hold is None:
        return False
    return ctx["bars_held"] >= hold


EXIT_RULES = {
    "E0_24h_fixed":     exit_24h_fixed,
    "E1_48h_fixed":     exit_48h_fixed,
    "E2_trail_5pct":    exit_trail_5pct,
    "E3_tp_or_24h":     exit_tp_or_24h,
    "E4_zcross":        exit_zcross,
    "E5_vol_scaled":    exit_vol_scaled_hold,
}


# ────────────────────────────────────────────────────────────
#  Engine
# ────────────────────────────────────────────────────────────

def run_combo(df: pd.DataFrame, entry_fn, exit_fn, exit_name: str,
              fee_bps_per_side: float = FEE_BPS_PER_SIDE):
    fee = fee_bps_per_side / 1e4
    pos = 0
    cash = 1.0
    eq_log = np.empty(len(df), dtype=float)
    rows = list(df.itertuples(index=True))
    trades = []
    ctx = {}

    for i, r in enumerate(rows):
        ts, px = r.Index, r.price
        # mark
        if pos == 1:
            mkt_eq = ctx["entry_eq"] * (px / ctx["entry_px"])
            ctx["mark_eq"] = mkt_eq
            ctx["bars_held"] = i - ctx["entry_idx"]
            eq_log[i] = mkt_eq
        else:
            eq_log[i] = cash

        # exit
        if pos == 1:
            if exit_fn(r, ctx):
                ret = (px / ctx["entry_px"] - 1) - 2 * fee
                cash = ctx["entry_eq"] * (1 + (px / ctx["entry_px"] - 1)) * (1 - 2 * fee)
                trades.append(dict(entry_t=ctx["entry_t"], exit_t=ts, side="long",
                                   entry_px=float(ctx["entry_px"]), exit_px=float(px),
                                   ret=float(ret),
                                   hours=float((ts - ctx["entry_t"]).total_seconds() / 3600)))
                pos = 0
                ctx = {}

        # entry
        if pos == 0:
            try:
                trigger = entry_fn(r)
            except Exception:
                trigger = False
            if trigger:
                pos = 1
                hold = None
                if exit_name == "E5_vol_scaled":
                    rv = r.realized_vol_30d
                    if not pd.isna(rv) and rv > 0:
                        hold = int(np.clip(24 * (0.50 / rv), 12, 96))
                    else:
                        hold = 24
                ctx = {
                    "entry_t": ts, "entry_px": float(px), "entry_eq": cash,
                    "entry_idx": i, "bars_held": 0,
                    "mark_eq": cash, "high_water": cash,
                    "scheduled_hold": hold,
                }

    eq = pd.Series(eq_log, index=df.index, name="equity")
    return eq, trades


def stats(name_combo: str, sym: str, df: pd.DataFrame, eq: pd.Series, trades: list) -> dict:
    bh = float(df["price"].iloc[-1] / df["price"].iloc[0])
    out = {"combo": name_combo, "symbol": sym, "n_trades": len(trades),
           "buy_hold_x": bh, "final_eq_x": float(eq.iloc[-1])}
    if not trades:
        out.update({"win_rate": 0.0, "expectancy": 0.0, "profit_factor": 0.0,
                    "sharpe": 0.0, "max_dd": 0.0, "outperform": float(eq.iloc[-1] / bh),
                    "median_hold_h": 0.0, "calmar": 0.0})
        return out
    rets = np.array([t["ret"] for t in trades])
    wins = rets > 0
    pf = float(rets[wins].sum() / -rets[~wins].sum()) if (~wins).any() and wins.any() else 0.0
    daily = eq.resample("1D").last().dropna()
    drets = daily.pct_change().dropna()
    sharpe = drets.mean() / drets.std() * np.sqrt(365) if drets.std() > 0 else 0.0
    peak = eq.cummax()
    dd = (eq - peak) / peak
    years = len(eq) / (24 * 365)
    cagr = (eq.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0.0
    cal = cagr / abs(dd.min()) if dd.min() < 0 else 0.0
    out.update({
        "win_rate": float(wins.mean()),
        "expectancy": float(rets.mean()),
        "profit_factor": pf,
        "sharpe": float(sharpe),
        "max_dd": float(dd.min()),
        "outperform": float(eq.iloc[-1] / bh),
        "median_hold_h": float(np.median([t["hours"] for t in trades])),
        "calmar": float(cal),
        "cagr": float(cagr),
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["SOLUSDT", "BTCUSDT", "ETHUSDT"])
    args = ap.parse_args()

    # Load BTC first so we can pass it for cross-asset confluence
    btc_panel = pd.read_parquet(PANELS / "BTCUSDT_zscore.parquet").resample("1h").last()

    rows_all = []
    for sym in args.symbols:
        df = load_h(sym, btc_panel=btc_panel)
        bh = df["price"].iloc[-1] / df["price"].iloc[0]
        print(f"\n══════ {sym}  bars={len(df):,}  buy-hold={bh:.2f}× ══════")

        for fname, ffn in ENTRY_FILTERS.items():
            # Skip BTC confluence on BTC itself
            if fname == "F6_btc_confluence" and sym == "BTCUSDT":
                continue
            for ename, efn in EXIT_RULES.items():
                eq, trades = run_combo(df, ffn, efn, ename)
                s = stats(f"{fname}__{ename}", sym, df, eq, trades)
                rows_all.append(s)

    out = pd.DataFrame(rows_all)
    out.to_csv(REPORTS / "v4_research_results.csv", index=False)

    # Top 10 per symbol by composite filter
    print("\n══════════════ TOP 10 PER SYMBOL (PF ≥ 1.20, MDD ≥ -30%, n ≥ 30) ══════════════")
    for sym in args.symbols:
        sub = out[out["symbol"] == sym].copy()
        elig = sub[(sub["profit_factor"] >= 1.20) & (sub["max_dd"] >= -0.30) & (sub["n_trades"] >= 30)]
        elig = elig.sort_values("sharpe", ascending=False).head(10)
        print(f"\n{sym}:  {len(elig)} eligible variants (out of {len(sub)} tested)")
        if len(elig) == 0:
            # fall back: show top 5 by sharpe regardless
            tops = sub.sort_values("sharpe", ascending=False).head(5)
            print(f"  (no variant clears all 3 filters; top 5 by Sharpe:)")
            for _, r in tops.iterrows():
                print(f"    {r['combo']:<35} n={r['n_trades']:>3}  WR={r['win_rate']*100:>4.1f}%  "
                      f"PF={r['profit_factor']:.2f}  Sh={r['sharpe']:+.2f}  MDD={r['max_dd']*100:+.1f}%  "
                      f"eq={r['final_eq_x']:.2f}× ({r['outperform']:.2f}× B&H)")
        else:
            for _, r in elig.iterrows():
                print(f"    {r['combo']:<35} n={r['n_trades']:>3}  WR={r['win_rate']*100:>4.1f}%  "
                      f"PF={r['profit_factor']:.2f}  Sh={r['sharpe']:+.2f}  MDD={r['max_dd']*100:+.1f}%  "
                      f"eq={r['final_eq_x']:.2f}× ({r['outperform']:.2f}× B&H)")

    print(f"\nFull results: {REPORTS/'v4_research_results.csv'} ({len(out)} rows)")


if __name__ == "__main__":
    main()
