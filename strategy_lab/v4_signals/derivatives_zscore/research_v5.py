"""V5 research — test the next wave of ideas on top of v4's regime-filter winners.

New ideas tested (each is a discrete experimental knob):

  Exit rules (replacing fixed-hold):
    E_24h           — 24h fixed (control)
    E_volscaled     — vol-scaled hold (v4 winner for BTC/ETH)
    E_tp_3 / 5 / 7  — take-profit at +3% / +5% / +7% OR 24h timeout
    E_trail_3 / 5 / 7 — trailing stop -3% / -5% / -7% from peak (cap 96h)
    E_tp5_trail3    — combo: TP at +5% OR trail at -3%
    E_tp7_trail5    — combo: TP at +7% OR trail at -5%
    E_atr_stop      — exit if 2× ATR(20) below entry; cap 48h

  Position sizing (multiplier on notional):
    S_flat          — 1× always (control)
    S_volscale      — clip(0.5 / realized_vol_30d, 0.5, 1.5)  (v4 winner)
    S_zmag          — clip(|z_lsr| / 1.5, 1.0, 2.5)   (deeper signal = bigger size)
    S_zmag_cap2     — clip(|z_lsr| / 1.5, 1.0, 2.0)
    S_combo         — vol_scale × z_mag (joint Kelly-ish)
    S_cb_boost      — BTC only: 1.5× if z_cb_premium>+0.5, else 1×

  Cross-asset confluence (alts only):
    X_none          — control
    X_btc_extreme   — only enter alt when BTC z_lsr<-1.5 also fires same hour
    X_btc_band      — BTC z_lsr in [-2.0, -0.3] (stress but not panic)

  Equity-curve / risk-management:
    R_none          — control
    R_3loss_pause   — pause new entries after 3 consecutive losses; resume after 1 win
    R_dd_pause      — pause if running DD < -10% from peak; resume when peak retaken

We start from each symbol's v4-tested entry filter (the regime detector that won)
and product the new knobs. Output ranked by composite (PF, MDD, Sharpe, n_trades).
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

FEE_BPS_PER_SIDE = 6.0


# ───────────────── Data load ─────────────────

def load_h(symbol: str, btc_panel: pd.DataFrame | None = None) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet").resample("1h").last()
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")["close"].astype(float)
    p["price"] = spot.reindex(p.index, method="ffill")
    p["ma_200d"] = p["price"].rolling(200 * 24, min_periods=200 * 24).mean()
    p["ret_1h"] = p["price"].pct_change()
    p["realized_vol_30d"] = p["ret_1h"].rolling(30 * 24, min_periods=30 * 24).std() * np.sqrt(24 * 365)
    p["vol_median"] = p["realized_vol_30d"].rolling(90 * 24, min_periods=24 * 24).median()
    # ATR for atr-stop
    h = p["price"]
    p["atr_20"] = (h.diff().abs().rolling(20).mean())
    if btc_panel is not None and symbol != "BTCUSDT":
        p["btc_z_lsr"] = btc_panel["z_lsr"].reindex(p.index, method="ffill")
    else:
        p["btc_z_lsr"] = np.nan
    # Coinbase premium z (only meaningful on BTC, NaN elsewhere)
    if "z_cb_premium" not in p.columns:
        p["z_cb_premium"] = np.nan
    return p.dropna(subset=["price", "z_lsr", "realized_vol_30d", "vol_median"])


# ───────────────── Entry filter (v4 winners as base) ─────────────────

def entry_v4_lowvol(r) -> bool:
    if pd.isna(r.realized_vol_30d) or pd.isna(r.vol_median):
        return False
    return r.z_lsr < -1.5 and r.realized_vol_30d < r.vol_median


def entry_v4_ma200_lowvol(r) -> bool:
    if pd.isna(r.ma_200d) or pd.isna(r.realized_vol_30d) or pd.isna(r.vol_median):
        return False
    return (r.z_lsr < -1.5 and r.price > r.ma_200d
            and r.realized_vol_30d < r.vol_median)


# ───────────────── Cross-asset confluence wrappers ─────────────────

def x_none(r) -> bool:
    return True


def x_btc_extreme(r) -> bool:
    if pd.isna(r.btc_z_lsr):
        return True  # for BTC itself, always passes
    return r.btc_z_lsr < -1.5


def x_btc_band(r) -> bool:
    if pd.isna(r.btc_z_lsr):
        return True
    return -2.0 < r.btc_z_lsr < -0.3


CROSS_ASSET = {"X_none": x_none, "X_btc_extreme": x_btc_extreme, "X_btc_band": x_btc_band}


# ───────────────── Position sizing ─────────────────

def size_flat(r):
    return 1.0


def size_volscale(r):
    rv = r.realized_vol_30d
    if pd.isna(rv) or rv <= 0:
        return 1.0
    return float(np.clip(0.5 / rv, 0.5, 1.5))


def size_zmag(r, cap=2.5):
    z = abs(r.z_lsr)
    return float(np.clip(z / 1.5, 1.0, cap))


def size_zmag_cap2(r):
    return size_zmag(r, cap=2.0)


def size_combo(r):
    return size_volscale(r) * size_zmag(r)


def size_cb_boost(r):
    if not pd.isna(r.z_cb_premium) and r.z_cb_premium > 0.5:
        return 1.5
    return 1.0


SIZINGS = {
    "S_flat":       size_flat,
    "S_volscale":   size_volscale,
    "S_zmag":       size_zmag,
    "S_zmag_cap2":  size_zmag_cap2,
    "S_combo":      size_combo,
    "S_cb_boost":   size_cb_boost,
}


# ───────────────── Exit rules ─────────────────
#   each returns True if should exit, given current row r and ctx dict
#   ctx keys: bars_held, mark_eq, entry_eq, high_water, entry_px

def exit_24h(r, ctx):
    return ctx["bars_held"] >= 24


def exit_volscaled(r, ctx):
    h = ctx.get("scheduled_hold", 24)
    return ctx["bars_held"] >= h


def _exit_tp_or_24h(r, ctx, tp):
    pl = ctx["mark_eq"] / ctx["entry_eq"] - 1
    return pl >= tp or ctx["bars_held"] >= 24


def exit_tp_3(r, ctx): return _exit_tp_or_24h(r, ctx, 0.03)
def exit_tp_5(r, ctx): return _exit_tp_or_24h(r, ctx, 0.05)
def exit_tp_7(r, ctx): return _exit_tp_or_24h(r, ctx, 0.07)


def _exit_trail(r, ctx, trail):
    if ctx["mark_eq"] > ctx["high_water"]:
        ctx["high_water"] = ctx["mark_eq"]
    dd = ctx["mark_eq"] / ctx["high_water"] - 1
    return dd <= -trail or ctx["bars_held"] >= 96


def exit_trail_3(r, ctx): return _exit_trail(r, ctx, 0.03)
def exit_trail_5(r, ctx): return _exit_trail(r, ctx, 0.05)
def exit_trail_7(r, ctx): return _exit_trail(r, ctx, 0.07)


def _exit_tp_trail(r, ctx, tp, trail):
    pl = ctx["mark_eq"] / ctx["entry_eq"] - 1
    if pl >= tp:
        return True
    if ctx["mark_eq"] > ctx["high_water"]:
        ctx["high_water"] = ctx["mark_eq"]
    dd = ctx["mark_eq"] / ctx["high_water"] - 1
    return dd <= -trail or ctx["bars_held"] >= 96


def exit_tp5_trail3(r, ctx): return _exit_tp_trail(r, ctx, 0.05, 0.03)
def exit_tp7_trail5(r, ctx): return _exit_tp_trail(r, ctx, 0.07, 0.05)


def exit_atr_stop(r, ctx):
    """Exit if drop > 2× ATR(20) from entry, else 48h cap."""
    atr_pct_at_entry = ctx.get("atr_pct_at_entry")
    if atr_pct_at_entry is None:
        return ctx["bars_held"] >= 48
    pl = ctx["mark_eq"] / ctx["entry_eq"] - 1
    return pl <= -2 * atr_pct_at_entry or ctx["bars_held"] >= 48


EXITS = {
    "E_24h":            exit_24h,
    "E_volscaled":      exit_volscaled,
    "E_tp_3":           exit_tp_3,
    "E_tp_5":           exit_tp_5,
    "E_tp_7":           exit_tp_7,
    "E_trail_3":        exit_trail_3,
    "E_trail_5":        exit_trail_5,
    "E_trail_7":        exit_trail_7,
    "E_tp5_trail3":     exit_tp5_trail3,
    "E_tp7_trail5":     exit_tp7_trail5,
    "E_atr_stop":       exit_atr_stop,
}


# ───────────────── Risk management ─────────────────

def rm_apply(rm: str, recent_trades: list, current_dd_from_peak: float) -> bool:
    """Returns True iff new entries are ALLOWED."""
    if rm == "R_none":
        return True
    if rm == "R_3loss_pause":
        # paused if last 3 trades were losses; unpause once any next-attempted entry wins
        # We approximate: if last 3 are all losses, block new entries until a winning trade lands.
        # Implementation note: caller must respect this — we don't add new losses while blocked.
        if len(recent_trades) >= 3 and all(t["ret"] < 0 for t in recent_trades[-3:]):
            return False
        return True
    if rm == "R_dd_pause":
        return current_dd_from_peak > -0.10
    return True


# ───────────────── Engine ─────────────────

def run_combo(df, entry_fn, cross_fn, sizing_fn, exit_name, exit_fn, rm: str = "R_none",
              fee_bps_per_side=FEE_BPS_PER_SIDE):
    fee = fee_bps_per_side / 1e4
    pos = 0
    cash = 1.0
    eq_log = np.empty(len(df), dtype=float)
    rows = list(df.itertuples(index=True))
    trades = []
    ctx = {}
    peak = cash

    for i, r in enumerate(rows):
        ts, px = r.Index, r.price

        if pos == 1:
            ret_open = (px / ctx["entry_px"] - 1) * ctx["pos_size"]
            mkt_eq = ctx["entry_eq"] * (1 + ret_open)
            ctx["mark_eq"] = mkt_eq
            ctx["bars_held"] = i - ctx["entry_idx"]
            eq_log[i] = mkt_eq
        else:
            eq_log[i] = cash

        peak = max(peak, eq_log[i])
        cur_dd = eq_log[i] / peak - 1

        # exit
        if pos == 1:
            try:
                should_exit = exit_fn(r, ctx)
            except Exception:
                should_exit = ctx["bars_held"] >= 96
            if should_exit:
                ret = (px / ctx["entry_px"] - 1) * ctx["pos_size"] - 2 * fee * ctx["pos_size"]
                cash = ctx["entry_eq"] * (1 + ret)
                trades.append(dict(entry_t=ctx["entry_t"], exit_t=ts, ret=float(ret),
                                   pos_size=float(ctx["pos_size"]),
                                   hours=float((ts - ctx["entry_t"]).total_seconds() / 3600)))
                pos = 0
                ctx = {}

        # entry
        if pos == 0:
            try:
                base_ok = entry_fn(r)
                cross_ok = cross_fn(r)
                rm_ok = rm_apply(rm, trades, cur_dd)
            except Exception:
                base_ok = cross_ok = rm_ok = False
            if base_ok and cross_ok and rm_ok:
                size = sizing_fn(r)
                pos = 1
                # vol-scaled hold (E_volscaled needs scheduled_hold)
                hold = 24
                if exit_name == "E_volscaled":
                    rv = r.realized_vol_30d
                    if not pd.isna(rv) and rv > 0:
                        hold = int(np.clip(24 * (0.50 / rv), 12, 96))
                # ATR snapshot at entry
                atr_pct = None
                if not pd.isna(r.atr_20) and r.atr_20 > 0:
                    atr_pct = float(2 * r.atr_20 / px)  # 2-ATR fraction of price
                ctx = {
                    "entry_t": ts, "entry_px": float(px), "entry_eq": cash,
                    "entry_idx": i, "bars_held": 0,
                    "mark_eq": cash, "high_water": cash,
                    "scheduled_hold": hold, "pos_size": float(size),
                    "atr_pct_at_entry": atr_pct,
                }

    eq = pd.Series(eq_log, index=df.index, name="equity")
    return eq, trades


def stats(name, sym, df, eq, trades):
    bh = float(df["price"].iloc[-1] / df["price"].iloc[0])
    if not trades:
        return {"combo": name, "symbol": sym, "n_trades": 0, "buy_hold_x": bh,
                "final_eq_x": float(eq.iloc[-1]), "outperform": float(eq.iloc[-1] / bh),
                "win_rate": 0.0, "expectancy": 0.0, "profit_factor": 0.0,
                "sharpe": 0.0, "max_dd": 0.0, "median_hold_h": 0.0, "calmar": 0.0}
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
    return {"combo": name, "symbol": sym, "n_trades": len(trades),
            "win_rate": float(wins.mean()),
            "expectancy": float(rets.mean()),
            "profit_factor": pf,
            "sharpe": float(sharpe),
            "max_dd": float(dd.min()),
            "buy_hold_x": bh, "final_eq_x": float(eq.iloc[-1]),
            "outperform": float(eq.iloc[-1] / bh),
            "median_hold_h": float(np.median([t["hours"] for t in trades])),
            "calmar": float(cal)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["SOLUSDT", "ETHUSDT", "BTCUSDT"])
    args = ap.parse_args()

    btc_panel = pd.read_parquet(PANELS / "BTCUSDT_zscore.parquet").resample("1h").last()

    all_rows = []
    for sym in args.symbols:
        df = load_h(sym, btc_panel=btc_panel)
        bh = df["price"].iloc[-1] / df["price"].iloc[0]
        print(f"\n══════ {sym}  bars={len(df):,}  buy-hold={bh:.2f}× ══════")

        # entry filter per symbol (v4 winner)
        entry_fn = entry_v4_lowvol if sym == "BTCUSDT" else entry_v4_ma200_lowvol

        # Cross-asset only on alts; on BTC, only X_none
        cross_keys = ["X_none"] if sym == "BTCUSDT" else list(CROSS_ASSET.keys())
        # CB-boost sizing only meaningful on BTC
        sizing_keys = list(SIZINGS.keys()) if sym == "BTCUSDT" else [k for k in SIZINGS.keys() if k != "S_cb_boost"]

        for cross_name in cross_keys:
            cfn = CROSS_ASSET[cross_name]
            for size_name in sizing_keys:
                sfn = SIZINGS[size_name]
                for exit_name, efn in EXITS.items():
                    for rm in ["R_none", "R_3loss_pause", "R_dd_pause"]:
                        eq, trades = run_combo(df, entry_fn, cfn, sfn, exit_name, efn, rm=rm)
                        combo = f"{cross_name}__{size_name}__{exit_name}__{rm}"
                        all_rows.append(stats(combo, sym, df, eq, trades))

    out = pd.DataFrame(all_rows)
    out.to_csv(REPORTS / "v5_research_results.csv", index=False)

    # Top per symbol with PF≥1.30, MDD≥-30%, n≥30
    print("\n══════════════ TOP 15 PER SYMBOL  (PF ≥ 1.30, MDD ≥ -30%, n ≥ 30) ══════════════")
    for sym in args.symbols:
        sub = out[out["symbol"] == sym].copy()
        elig = sub[(sub["profit_factor"] >= 1.30) & (sub["max_dd"] >= -0.30) & (sub["n_trades"] >= 30)]
        # sort by composite: outperform × Sharpe (positive both)
        elig = elig.sort_values(["outperform", "sharpe"], ascending=False).head(15)
        print(f"\n{sym}:  {len(elig)} eligible (out of {len(sub)} tested)")
        if len(elig) == 0:
            tops = sub.sort_values("outperform", ascending=False).head(8)
            print(f"  (none clear all 3 filters; top 8 by outperform vs B&H:)")
            for _, r in tops.iterrows():
                print(f"    {r['combo'][:60]:<60} n={r['n_trades']:>3}  WR={r['win_rate']*100:>4.1f}%  "
                      f"PF={r['profit_factor']:.2f}  Sh={r['sharpe']:+.2f}  MDD={r['max_dd']*100:+.1f}%  "
                      f"eq={r['final_eq_x']:.2f}× ({r['outperform']:.2f}× B&H)")
        else:
            for _, r in elig.iterrows():
                print(f"    {r['combo'][:60]:<60} n={r['n_trades']:>3}  WR={r['win_rate']*100:>4.1f}%  "
                      f"PF={r['profit_factor']:.2f}  Sh={r['sharpe']:+.2f}  MDD={r['max_dd']*100:+.1f}%  "
                      f"eq={r['final_eq_x']:.2f}× ({r['outperform']:.2f}× B&H)")

    print(f"\nFull results: {REPORTS/'v5_research_results.csv'} ({len(out)} rows)")


if __name__ == "__main__":
    main()
