"""28-day backtest with F7 + Markov + F7+Markov gates (momo only).

Uses canonical live-mimic per_trade.csv (Apr 25 - May 15, real fees + L25 walk
fills + chainlink outcomes). Applies gates with CORRECT ws_s anchor.

Walk-forward: splits 21-day window into 3 weeks (train/test) to check gate
lift is consistent across windows.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "strategy_lab/markov_filter")
from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, BEAR, BULL,
)

PER_TRADE = "data/v4/canonical/_results/full_universe_live_mimic_2026_05_16/per_trade.csv"
FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
OUT_DIR = Path("strategy_lab/markov_filter/_results/backtest_28d_with_gates")
OUT_DIR.mkdir(parents=True, exist_ok=True)

REP_VARIANT = "SELL_5bp"  # any of the 14 fire-equivalent variants works

MARKOV_VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
}


def wilder_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Causal Wilder RSI(14). Returns NaN for first `period` bars."""
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    diffs = np.diff(closes)
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)
    avg_g = gains[:period].mean()
    avg_l = losses[:period].mean()
    for i in range(period, n - 1):
        rsi[i + 1] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    return rsi


def build_rsi_cache():
    print("[1] RSI cache...")
    kdf = pd.read_csv(FRESH_KLINES)
    cache = {}
    for asset in ("BTC", "ETH", "SOL"):
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = kdf[kdf["symbol_id"] == sym].drop_duplicates("time_period_start_us") \
                                            .sort_values("time_period_start_us")
        closes = sub["price_close"].values.astype("float64")
        end_us = sub["time_period_start_us"].values.astype("int64") + 60_000_000
        rsi = wilder_rsi(closes, period=14)
        cache[asset] = (end_us, rsi)
        print(f"   {asset}: bars={len(closes)}, RSI finite={np.isfinite(rsi).sum()}")
    return cache


def rsi_asof(end_us, rsi, target_us):
    i = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if i < 0 or i >= len(rsi):
        return float("nan")
    return float(rsi[i])


def load_fires():
    print("[2] Loading per_trade.csv...")
    df = pd.read_csv(PER_TRADE)
    f = df[(df["variant"] == REP_VARIANT) & df["fired"]].copy().reset_index(drop=True)
    print(f"   {len(f)} fires under variant={REP_VARIANT}")

    # CORRECT anchor: ws = slot_start, ws_s = slot_start - window_s
    f["slot_start_s"] = f["ws"].astype("int64")
    f["window_s"] = f["tf"].map({"5m": 300, "15m": 900})
    f["ws_s"] = f["slot_start_s"] - f["window_s"]
    f["ws_us"] = f["ws_s"] * 1_000_000
    f["fire_us"] = (f["slot_start_s"] + f["fire_offset_s"].astype("int64")) * 1_000_000
    f["won"] = ((f["signal"] == "UP") & (f["outcome"] == "Up")) | \
              ((f["signal"] == "DOWN") & (f["outcome"] == "Down"))
    # HOLD-to-settlement pnl
    f["pnl"] = np.where(f["won"],
                        f["shares_e"] - f["usd_e"] - f["fee_in"],
                        -f["usd_e"] - f["fee_in"])
    f["sleeve"] = f["asset"].str.lower() + "_" + f["tf"] + "_" + f["version"]
    f["date"]   = pd.to_datetime(f["day"]).dt.date
    return f


def add_gates(f, rsi_cache, markov_cache):
    print(f"[3] RSI(14) at ws_s for {len(f)} fires...")
    rsis = []
    for _, r in f.iterrows():
        end_us, rsi = rsi_cache[r["asset"]]
        rsis.append(rsi_asof(end_us, rsi, int(r["ws_us"])))
    f["rsi_14"] = rsis
    f["f7_pass"] = ((f["signal"] == "UP") & (f["rsi_14"] > 50)) | \
                   ((f["signal"] == "DOWN") & (f["rsi_14"] < 50))
    print(f"   RSI finite: {f.rsi_14.notna().sum()}/{len(f)}  F7 pass: {f.f7_pass.sum()}")

    print(f"[4] Markov regime per fire...")
    for vname, _ in MARKOV_VARIANTS:
        regs = []
        for _, r in f.iterrows():
            end_us, labels = markov_cache[(vname, r["asset"])]
            regs.append(regime_at_us(end_us, labels, int(r["fire_us"])))
        f[f"regime_{vname}"] = regs
        f[f"markov_pass_{vname}"] = ((f["signal"] == "UP") & (f[f"regime_{vname}"] == BULL)) | \
                                     ((f["signal"] == "DOWN") & (f[f"regime_{vname}"] == BEAR))
    return f


def build_markov_cache():
    print("[Pre] Markov label cache...")
    cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ("BTC", "ETH", "SOL"):
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"],
                      fresh_klines_csv=FRESH_KLINES)
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            cache[(vname, asset)] = (end_us, labels)
    return cache


def summarize(g, label):
    n = len(g)
    if n == 0:
        return {"filter": label, "n": 0, "wr": 0.0, "avg": 0.0, "sum": 0.0}
    return {"filter": label, "n": n,
            "wr": round(g["won"].mean() * 100, 2),
            "avg": round(g["pnl"].mean(), 3),
            "sum": round(g["pnl"].sum(), 2)}


def per_sleeve_table(f):
    sleeves = sorted(f["sleeve"].unique())
    rows = []
    for sleeve in sleeves:
        sub = f[f["sleeve"] == sleeve]
        if len(sub) < 5:
            continue
        sleeve_rows = [summarize(sub, "NO_FILTER")]
        sleeve_rows.append(summarize(sub[sub.f7_pass], "F7_only"))
        for vname, _ in MARKOV_VARIANTS:
            mk = f"markov_pass_{vname}"
            sleeve_rows.append(summarize(sub[sub[mk]], f"MARKOV:{vname}"))
            sleeve_rows.append(summarize(sub[sub.f7_pass & sub[mk]], f"F7+MARKOV:{vname}"))
        for r in sleeve_rows:
            r["sleeve"] = sleeve
            rows.append(r)
    out = pd.DataFrame(rows)[["sleeve","filter","n","wr","avg","sum"]]
    return out


def walk_forward(f):
    """Split into 3 weekly windows. Apply gates per window."""
    f["week"] = pd.to_datetime(f["date"]).dt.isocalendar().week
    weeks = sorted(f["week"].unique())
    print(f"\n=== Walk-forward across {len(weeks)} weeks ===")
    summaries = []
    for w in weeks:
        wf = f[f["week"] == w]
        rows = [summarize(wf, "NO_FILTER")]
        rows.append(summarize(wf[wf.f7_pass], "F7_only"))
        for vname, _ in MARKOV_VARIANTS:
            mk = f"markov_pass_{vname}"
            rows.append(summarize(wf[wf[mk]], f"MARKOV:{vname}"))
            rows.append(summarize(wf[wf.f7_pass & wf[mk]], f"F7+MARKOV:{vname}"))
        df_w = pd.DataFrame(rows)
        df_w["week"] = w
        df_w["date_min"] = wf["date"].min()
        df_w["date_max"] = wf["date"].max()
        summaries.append(df_w)
        print(f"\n--- Week {w} ({wf['date'].min()} → {wf['date'].max()}, n={len(wf)}) ---")
        print(df_w[["filter","n","wr","avg","sum"]].to_string(index=False))
    return pd.concat(summaries, ignore_index=True)


def main():
    rsi_cache = build_rsi_cache()
    mk_cache  = build_markov_cache()
    f = load_fires()
    f = add_gates(f, rsi_cache, mk_cache)
    f.to_csv(OUT_DIR / "fires_with_gates.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'fires_with_gates.csv'}")

    print("\n=== OVERALL ===")
    overall = [summarize(f, "NO_FILTER")]
    overall.append(summarize(f[f.f7_pass], "F7_only"))
    for vname, _ in MARKOV_VARIANTS:
        mk = f"markov_pass_{vname}"
        overall.append(summarize(f[f[mk]], f"MARKOV:{vname}"))
        overall.append(summarize(f[f.f7_pass & f[mk]], f"F7+MARKOV:{vname}"))
    od = pd.DataFrame(overall)
    od.to_csv(OUT_DIR / "summary_overall.csv", index=False)
    print(od.to_string(index=False))

    sleeve_tbl = per_sleeve_table(f)
    sleeve_tbl.to_csv(OUT_DIR / "per_sleeve_full.csv", index=False)

    # Compact per-sleeve view (n>=10)
    print("\n=== Per-sleeve (n>=10 filter rows) — top filter per sleeve ===")
    rows = []
    for sleeve in sleeve_tbl["sleeve"].unique():
        sub = sleeve_tbl[sleeve_tbl["sleeve"] == sleeve]
        base = sub[sub["filter"] == "NO_FILTER"].iloc[0]
        if base["n"] < 10:
            continue
        cands = sub[(sub["filter"] != "NO_FILTER") & (sub["n"] >= 10)]
        if cands.empty: continue
        best = cands.loc[cands["sum"].idxmax()]
        rows.append({
            "sleeve": sleeve,
            "n_base": int(base["n"]), "wr_base": base["wr"], "avg_base": base["avg"], "sum_base": base["sum"],
            "best_filter": best["filter"],
            "n_best": int(best["n"]), "wr_best": best["wr"], "avg_best": best["avg"], "sum_best": best["sum"],
            "lift_avg": round(best["avg"] - base["avg"], 3),
        })
    sc = pd.DataFrame(rows).sort_values("sum_best", ascending=False)
    sc.to_csv(OUT_DIR / "scorecard.csv", index=False)
    print(sc.to_string(index=False))

    wf = walk_forward(f)
    wf.to_csv(OUT_DIR / "walk_forward.csv", index=False)


if __name__ == "__main__":
    main()
